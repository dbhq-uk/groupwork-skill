"""GitHub Copilot CLI.

Two of its documented bugs shape this adapter:

1. `-p` puts the whole prompt on the command line, which hits ARG_MAX on any
   real diff (github/copilot-cli#3398). The brief therefore goes in on stdin,
   which is the workaround its own maintainers recommend until `--prompt-file`
   lands.

2. It can exit 0 having written nothing at all (github/copilot-cli#1181). The
   runner's empty-output-is-a-failure rule exists partly for this: a silent
   success here would otherwise be reported as "the reviewer found no issues",
   which is the worst possible way to be wrong.

Auth is the one easy part. It reads COPILOT_GITHUB_TOKEN, GH_TOKEN or
GITHUB_TOKEN in that order, so a machine with a working `gh` is already set up.
"""

import os
import subprocess

from .base import Provider, ProviderError


class Copilot(Provider):
    name = "copilot"

    # Copilot selects the model itself unless told; these are what it exposes.
    models = ["default", "claude-opus-5", "claude-sonnet-5", "gpt-5.6-sol", "gemini-3-pro"]
    # It has no reasoning-effort dial, so a pattern asking for `high` is served
    # at its only level and the record says so rather than claiming high.
    efforts = ["default"]
    sandboxes = ["read-only", "workspace-write"]
    can_resume = False
    can_withhold_repo = True

    # This adapter has never been run against the real CLI. It is written from
    # Copilot's own documentation and issue tracker, which means the two bugs
    # above are coded around without either having been seen to fire, and the
    # flag shapes below are documented rather than observed. Use codex or
    # opencode where the answer matters; report what breaks here.
    experimental = True

    def install_hint(self):
        return (
            "Install with 'gh copilot' (it downloads on first use), then "
            "authenticate with 'copilot login' or export GITHUB_TOKEN."
        )

    def probe(self):
        self._which("copilot")
        version = self._version(["copilot", "--version"])
        if not any(
            os.environ.get(v)
            for v in ("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN")
        ):
            # Not fatal - an interactive `copilot login` also works - but worth
            # saying, because the failure mode otherwise is a silent empty run.
            raise ProviderError(
                "copilot: no COPILOT_GITHUB_TOKEN, GH_TOKEN or GITHUB_TOKEN set, "
                "and headless runs need one. Run 'copilot login' or export a token."
            )
        return version

    def argv(self, brief_path, out_path, model, effort, sandbox, cwd, repo_access=True):
        argv = [
            "copilot",
            "-p",
            "-",  # read the prompt from stdin; see ARG_MAX above
            "-s",  # suppress stats and decoration, so stdout is only the answer
            "--no-ask-user",  # nothing is watching to answer a clarifying question
        ]
        if sandbox == "read-only":
            # Narrow permissions by name rather than --allow-all. A reviewer
            # needs to read the tree and the history, and nothing else.
            argv += ["--allow-tool", "shell(git:*)"]
        if model and model != "default":
            argv += ["--model", model]
        return argv

    def run(self, brief_path, out_path, model, effort, sandbox, cwd,
            repo_access=True, log_path=None, timeout=600):
        argv = self.argv(
            brief_path, out_path, model, effort, sandbox, cwd, repo_access
        )
        with open(brief_path, "rb") as stdin, open(out_path, "wb") as out:
            log = open(log_path, "wb") if log_path else subprocess.DEVNULL
            try:
                done = subprocess.run(
                    argv, stdin=stdin, stdout=out, stderr=log,
                    cwd=cwd, timeout=timeout,
                )
            except subprocess.TimeoutExpired:
                raise ProviderError(
                    f"copilot: timed out after {timeout}s"
                ) from None
            finally:
                if log is not subprocess.DEVNULL:
                    log.close()
        if done.returncode != 0:
            raise ProviderError(f"copilot: exited {done.returncode}; see the log")
        return done.returncode
