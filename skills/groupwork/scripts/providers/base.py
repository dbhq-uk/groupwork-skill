"""What a counterpart CLI has to be able to do.

groupwork ships with two providers. The interface exists so that adding a
third is a new file rather than a rewrite - but it is deliberately shaped
around what a *second opinion* needs, not around what any one vendor's CLI
happens to offer.

Three functions, and nothing else:

  probe()         - is it installed AND authenticated? Auth is the real barrier
                    to entry; every one of these CLIs installs in a second and
                    then refuses to run.
  capabilities()  - what can it actually do? This is what lets the runner fall
                    back honestly instead of pretending it ran at high effort.
  run()           - do it, write the answer to a file, raise on any failure.

Nothing vendor-specific belongs outside this package. If a flag name, an
environment variable or a quirk of one CLI leaks into the runner, the next
provider inherits it as though it were the contract.
"""

import contextlib
import os
import shutil
import signal
import subprocess
import threading
import time


class ProviderError(RuntimeError):
    """A provider could not do what was asked, and said why."""


class RunTimedOut(ProviderError):
    """The run hit its time limit and every process it started was stopped."""


#: How long a stopped run gets to exit after SIGTERM before it is SIGKILLed.
GRACE_S = 10


class _Terminated(SystemExit):
    """groupwork itself was told to stop while a run was in flight."""


def spawn(name, argv, *, stdin, stdout, stderr, cwd, timeout, env=None):
    """Run a provider CLI in its own process group, and stop all of it.

    `subprocess.run(timeout=)` SIGKILLs the direct child only. For Codex that is
    the npm wrapper, which forwards SIGINT, SIGTERM and SIGHUP to the native
    binary but cannot forward SIGKILL, so the real CLI kept running, and
    billing, after groupwork had reported the run dead.

    So the child leads a new session, and on a timeout, an interrupt or a
    SIGTERM or SIGHUP to groupwork, the whole group gets SIGTERM, then SIGKILL
    for anything still there after GRACE_S. Returns the exit status; raises
    ProviderError on a timeout.
    """
    proc = subprocess.Popen(
        argv, stdin=stdin, stdout=stdout, stderr=stderr, cwd=cwd, env=env,
        start_new_session=True,
    )
    try:
        with _stop_group_on_signal():
            return proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        stop_group(proc)
        raise RunTimedOut(
            f"{name}: timed out after {timeout}s, and every process it started "
            f"was stopped. Pass a longer --timeout if the run needs it."
        ) from None
    except BaseException:
        stop_group(proc)
        raise


def stop_group(proc, grace=None):
    """SIGTERM the process group, then SIGKILL whatever is left after grace."""
    grace = GRACE_S if grace is None else grace
    pgid = proc.pid
    _signal_group(pgid, signal.SIGTERM)
    deadline = time.monotonic() + grace
    while time.monotonic() < deadline:
        proc.poll()  # reap the leader, so a zombie does not count as alive
        if not _group_alive(pgid):
            return
        time.sleep(0.05)
    _signal_group(pgid, signal.SIGKILL)
    proc.wait()


def _signal_group(pgid, sig):
    try:
        os.killpg(pgid, sig)
    except ProcessLookupError:
        pass


def _group_alive(pgid):
    try:
        os.killpg(pgid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


@contextlib.contextmanager
def _stop_group_on_signal():
    """Turn SIGTERM and SIGHUP into an exception while a run is in flight.

    The child is in its own session, so a signal aimed at groupwork no longer
    reaches it. Raising lets spawn() stop the group on the way out. SIGINT
    already raises KeyboardInterrupt. Signal handlers can only be set from the
    main thread, so elsewhere this does nothing.
    """
    if threading.current_thread() is not threading.main_thread():
        yield
        return

    def raise_terminated(signum, frame):
        raise _Terminated(128 + signum)

    previous = {}
    for sig in (signal.SIGTERM, signal.SIGHUP):
        previous[sig] = signal.signal(sig, raise_terminated)
    try:
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


class Provider:
    name = "base"

    #: What this CLI can reach. The runner reads these rather than assuming.
    models: list = []
    efforts: list = []
    sandboxes: list = []

    #: Set by a provider that has no way to run without repository access.
    #: red-team defaults to withholding the repo entirely, so a provider that
    #: cannot honour that has to say so rather than quietly read it anyway.
    can_withhold_repo = True

    #: Set where the adapter has never been run against the real CLI - written
    #: from that CLI's documentation and issue tracker rather than from a
    #: working invocation. It surfaces in `groupwork providers` and in the
    #: provenance record, because "this ran through an unverified adapter" is
    #: exactly the sort of thing a citation should carry rather than bury.
    experimental = False

    def __init__(self, config=None):
        self.config = config or {}

    # --- contract -----------------------------------------------------------

    def probe(self):
        """Return the CLI version string, or raise ProviderError with the reason."""
        raise NotImplementedError

    def capabilities(self):
        """What it can do. Called after probe(), so it may use what that found.

        `default_model` is the model the CLI uses when none is named, where the
        provider can say which. The runner falls back to it, and to nothing
        else, when the pattern's model is not in `models`.
        """
        return {
            "provider": self.name,
            "models": list(self.models),
            "default_model": None,
            "efforts": list(self.efforts),
            "sandboxes": list(self.sandboxes),
            "can_withhold_repo": self.can_withhold_repo,
            "experimental": self.experimental,
        }

    def run(self, brief_path, out_path, model, effort, sandbox, cwd, repo_access=True):
        """Run the brief. Write the response to out_path. Raise on failure."""
        raise NotImplementedError

    # --- shared helpers -----------------------------------------------------

    def _which(self, binary):
        found = shutil.which(binary)
        if not found:
            raise ProviderError(
                f"{self.name}: '{binary}' is not on PATH. {self.install_hint()}"
            )
        return found

    def _call(self, argv, timeout=30):
        """Run a quick, free CLI command such as a version or login check.

        stdin is closed, so a CLI that would read it gets EOF rather than
        waiting on a terminal nobody is at. Returns the CompletedProcess.
        """
        try:
            return subprocess.run(
                argv, capture_output=True, text=True, timeout=timeout,
                stdin=subprocess.DEVNULL,
            )
        except subprocess.TimeoutExpired:
            raise ProviderError(
                f"{self.name}: '{' '.join(argv)}' hung for {timeout}s"
            ) from None

    def _version(self, argv, timeout=20):
        done = self._call(argv, timeout=timeout)
        if done.returncode != 0:
            raise ProviderError(
                f"{self.name}: '{' '.join(argv)}' exited {done.returncode}: "
                f"{(done.stderr or done.stdout).strip()[:300]}"
            )
        return (done.stdout or done.stderr).strip().splitlines()[0]

    def install_hint(self):
        return "See the provider's own install instructions."
