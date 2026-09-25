"""Run in the background, and say where a background run has got to.

A run at high effort takes ten to twenty minutes, and at max longer. Most agent
hosts stop a command well before that: the Claude Code Bash tool defaults to
two minutes and caps at ten. A host that stops a foreground run loses it, or
sits blocked until it ends.

So `run --background` builds the brief, starts the run as a detached process
and prints its id at once. `status <id>` and `result <id>` read where it has got
to. Nothing here decides anything about the run itself: the detached process is
the same `run` command, with the id handed to it, so a background run is
recorded and cited exactly as a foreground one is.

Three files beside the run's own, all in runs/:

  <id>.lock        held with flock by the detached process for as long as it
                   lives. The kernel drops the lock when the process ends, even
                   on SIGKILL, so a held lock means running and nothing else.
                   No pid is stored, so a reused pid cannot read as running.
  <id>.worker.log  what the detached process printed, including a traceback if
                   it crashed.
  <id>.failed      the reason, written when the run fails.
"""

import contextlib
import fcntl
import os
import subprocess
import sys
import time

import provenance
import runner


def _paths(run_id):
    runs = runner.STATE / "runs"
    return {
        "lock": runs / f"{run_id}.lock",
        "log": runs / f"{run_id}.worker.log",
        "failed": runs / f"{run_id}.failed",
        "brief": runs / f"{run_id}.brief.md",
    }


def launch(script, argv, run_id):
    """Start `script argv --run-id run_id` detached, and return without waiting.

    `argv` is the command line as the caller gave it, `--background` and all.
    The detached process sees `--run-id` and runs in the foreground, so a flag
    added to `run` later reaches it without anything here changing.

    The lock is taken here, before the process starts, and handed to it as an
    open file. So `status` says running from the moment this returns, not from
    whenever the new process gets round to taking the lock itself.

    The process leads its own session, so a host that stops the command that
    launched it, and everything in that command's process group, does not
    stop the run.
    """
    runner._state_dir()
    paths = _paths(run_id)
    fd = os.open(paths["lock"], os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        with open(paths["log"], "wb") as log:
            return subprocess.Popen(
                [sys.executable, str(script), *argv, "--run-id", run_id],
                stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                cwd=os.getcwd(), start_new_session=True, pass_fds=(fd,),
            )
    finally:
        # The child has its own copy of the descriptor, and a flock lock lasts
        # until every copy is closed, so closing ours does not release it.
        os.close(fd)


@contextlib.contextmanager
def hold(run_id):
    """Hold a run's lock for the life of this block, in this process.

    For work done in the foreground, so `status` from another shell says
    running rather than stopped. A process started by launch() already holds
    it and must not take it again.
    """
    runner._state_dir()
    fd = os.open(_paths(run_id)["lock"], os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def mark_failed(run_id, reason):
    """Record why a background run failed, for `status` and `result`."""
    if not runner.valid_run_id(run_id):
        return
    try:
        _paths(run_id)["failed"].write_text(reason.strip() + "\n", encoding="utf-8")
    except OSError:
        pass


def running(run_id):
    """Is the process doing this run still alive?"""
    return runner.valid_run_id(run_id) and _running(_paths(run_id)["lock"])


def _running(lock_path):
    try:
        fd = os.open(lock_path, os.O_RDONLY)
    except OSError:
        return False
    try:
        fcntl.flock(fd, fcntl.LOCK_SH | fcntl.LOCK_NB)
    except BlockingIOError:
        return True
    else:
        fcntl.flock(fd, fcntl.LOCK_UN)
        return False
    finally:
        os.close(fd)


def state(run_id):
    """Where a run has got to: (state, detail, row).

    state is "done", "running", "failed" or "unknown". detail is a sentence for
    a human. row is the ledger row, with its output, when the state is done.
    """
    if not runner.valid_run_id(run_id):
        return "unknown", f"'{run_id}' is not a run id", None
    row = provenance.find(run_id)
    if row:
        return "done", "finished; `result` prints the answer and the citation", row
    paths = _paths(run_id)
    if paths["failed"].exists():
        reason = paths["failed"].read_text(encoding="utf-8").strip()
        return "failed", reason, None
    if _running(paths["lock"]):
        started = paths["lock"].stat().st_mtime
        return "running", f"{_elapsed(time.time() - started)} so far", None
    if paths["lock"].exists():
        return "failed", (
            f"stopped before it finished, and nothing was recorded. The run "
            f"was killed or crashed; {paths['log']} has what it printed."
        ), None
    if paths["brief"].exists():
        return "failed", (
            f"did not finish, and no result was recorded. The provider's log is "
            f"at {runner.STATE / 'runs' / (run_id + '.log')}."
        ), None
    return "unknown", f"no run '{run_id}'", None


def _elapsed(seconds):
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    return f"{seconds // 60}m {seconds % 60:02d}s"
