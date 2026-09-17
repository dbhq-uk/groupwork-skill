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
"""

import subprocess

from .base import Provider, ProviderError


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
        return [
            "codex",
            "exec",
            "--skip-git-repo-check",
            "--sandbox",
            sandbox,
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
        return _spawn(argv, brief_path, log_path, timeout, self.name)

    def resume(self, brief_path, out_path, cwd, log_path=None, timeout=600):
        # Deliberately no flags. A resumed session inherits the model, effort
        # and sandbox of the original, and passing them again is an error.
        argv = ["codex", "exec", "--skip-git-repo-check", "resume", "--last",
                "-o", out_path]
        return _spawn(argv, brief_path, log_path, timeout, self.name)


def _spawn(argv, brief_path, log_path, timeout, name):
    """Run it with the brief on stdin, everything noisy to the log."""
    with open(brief_path, "rb") as stdin:
        log = open(log_path, "wb") if log_path else subprocess.DEVNULL
        try:
            done = subprocess.run(
                argv, stdin=stdin, stdout=log, stderr=log, timeout=timeout
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
