"""OpenAI Codex CLI. The default provider.

Three things about `codex exec` are not obvious and each one costs you a run:

1. It reads stdin and concatenates it with the positional prompt, even when the
   prompt is supplied in full as an argument. If stdin is neither a TTY nor
   closed - which is exactly the case in a background task or a hook - it blocks
   forever. Zero bytes out, no CPU, apparently hung. Hence the brief goes in on
   stdin deliberately, from a real file, so stdin always reaches EOF.

2. `-o` is written only at completion. A run killed at a harness timeout leaves
   an empty file and exit status that looks survivable. The runner treats an
   empty output as a failure for this reason.

3. Thinking tokens go to stderr and are voluminous. They are captured to the
   log rather than discarded, because when a run does fail the reason is in
   there, but they never reach the caller's context.

And one about withholding the repository. `--sandbox read-only` blocks writes,
not reads: the counterpart can still read almost anywhere on disk, including
the repository groupwork was run from. So a run without repository access uses
a Codex permission profile instead, which can read only the platform's minimal
runtime paths and the empty working directory, with no network. Codex refuses
a profile and `--sandbox` together, so it is one or the other. The process is
also started in the empty directory, not only pointed at it with `-C`.

A profile that restricts reads needs Codex's own sandbox helper to start. Where
the host blocks it - bwrap without user namespaces, typically - the session
fails before it starts. That is reported as such, with `--repo-access` as the
explicit alternative, rather than quietly running with the repository readable.
"""

import subprocess

from .base import Provider, ProviderError

#: The permission profile for a run that must not see the repository. Anything
#: not listed cannot be read. `:root` is deliberately not set to deny: deny
#: outranks read at every path, so it would take `:minimal` away too and no
#: command could run at all.
NO_REPO_PROFILE = "groupwork-norepo"


def no_repo_profile(access="read"):
    """The -c pair that selects and defines the no-repository profile."""
    return [
        "--config",
        f'default_permissions="{NO_REPO_PROFILE}"',
        "--config",
        (
            f"permissions.{NO_REPO_PROFILE}={{"
            f'filesystem={{":minimal"="read", ":workspace_roots"={{"."="{access}"}}}}, '
            f"network={{enabled=false}}}}"
        ),
    ]


#: What the log says when Codex could not start its sandbox on this host.
_SANDBOX_START_FAILURES = ("fs sandbox helper failed", "bwrap:")


class Codex(Provider):
    name = "codex"

    models = [
        "gpt-6-astra",
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
        "gpt-5.5",
        "gpt-5.4",
    ]
    efforts = ["low", "medium", "high", "xhigh", "max", "ultra"]
    sandboxes = ["read-only", "workspace-write", "danger-full-access"]
    can_resume = True
    can_withhold_repo = True

    def install_hint(self):
        return "Install the Codex CLI and run 'codex login'."

    def probe(self):
        self._which("codex")
        return self._version(["codex", "--version"])

    def argv(self, brief_path, out_path, model, effort, sandbox, cwd, repo_access=True):
        """The command, built but not run. Separated so tests can read it."""
        if repo_access:
            permissions = ["--sandbox", sandbox]
        elif sandbox in ("read-only", "workspace-write"):
            permissions = no_repo_profile(
                "write" if sandbox == "workspace-write" else "read"
            )
        else:
            raise ProviderError(
                f"codex: {sandbox} cannot be combined with withholding the "
                f"repository"
            )
        return [
            "codex",
            "exec",
            "--skip-git-repo-check",
            *permissions,
            "-C",
            cwd,
            "-m",
            model,
            "--config",
            f'model_reasoning_effort="{effort}"',
            "-o",
            out_path,
            "-",
        ]

    def run(self, brief_path, out_path, model, effort, sandbox, cwd,
            repo_access=True, log_path=None, timeout=600):
        argv = self.argv(
            brief_path, out_path, model, effort, sandbox, cwd, repo_access
        )
        try:
            return _spawn(argv, brief_path, log_path, timeout, self.name, cwd)
        except ProviderError:
            if not repo_access and _sandbox_failed_to_start(log_path):
                raise ProviderError(
                    "codex: could not start its sandbox on this machine, so the "
                    "session failed before it began and nothing was reviewed. "
                    "This pattern withholds the repository, and without the "
                    "sandbox that cannot be enforced. Re-run with --repo-access "
                    "to give it the repository deliberately; the citation will "
                    "say so. The log has Codex's own error."
                ) from None
            raise

    def resume(self, brief_path, out_path, cwd, log_path=None, timeout=600):
        # Deliberately no flags. A resumed session inherits the model, effort
        # and sandbox of the original, and passing them again is an error.
        argv = ["codex", "exec", "--skip-git-repo-check", "resume", "--last",
                "-o", out_path]
        return _spawn(argv, brief_path, log_path, timeout, self.name, cwd)


def _sandbox_failed_to_start(log_path):
    if not log_path:
        return False
    try:
        with open(log_path, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError:
        return False
    return any(marker in text for marker in _SANDBOX_START_FAILURES)


def _spawn(argv, brief_path, log_path, timeout, name, cwd):
    """Run it in cwd with the brief on stdin, everything noisy to the log.

    cwd is not a formality. `-C` only tells Codex where its workspace is; the
    process itself would otherwise start wherever groupwork was run, which for
    a run withholding the repository is the repository.
    """
    with open(brief_path, "rb") as stdin:
        log = open(log_path, "wb") if log_path else subprocess.DEVNULL
        try:
            done = subprocess.run(
                argv, stdin=stdin, stdout=log, stderr=log, timeout=timeout,
                cwd=cwd,
            )
        except subprocess.TimeoutExpired:
            raise ProviderError(
                f"{name}: timed out after {timeout}s. Output is written only at "
                f"completion, so nothing was salvaged."
            ) from None
        finally:
            if log is not subprocess.DEVNULL:
                log.close()
    if done.returncode != 0:
        raise ProviderError(f"{name}: exited {done.returncode}; see the log")
    return done.returncode
