"""opencode. The provider that proves the layer is real.

It earns its place twice over. It is a second CLI, so the contract in base.py
was written against two implementations rather than one - which is the only way
to find out whether an interface is a contract or just Codex's flags renamed.
And it is itself a multi-model front end, so Gemini, Grok, Qwen and anything
running locally arrive behind this one file rather than one adapter each.

It is also the provider with the honest gap, and the gap is instructive.
opencode has no sandbox flag. Codex takes `--sandbox read-only` and the kernel
enforces it; opencode has a permission prompt instead, and in a headless run
there is nobody to answer it. So read-only here means "do not pass --auto, and
let a write attempt stall until the timeout kills it" - real, but enforced by
absence rather than by a sandbox. capabilities() says so, the runner passes it
on, and the provenance record names the provider, so a reader can weigh the
difference. What it must never do is claim the same guarantee Codex gives.
"""

import subprocess

from .base import Provider, ProviderError


class Opencode(Provider):
    name = "opencode"

    # Written provider/model, which is the point of this adapter: one file,
    # many model families. The list is what groupwork's patterns can ask for;
    # opencode itself accepts anything its config knows about.
    models = [
        "anthropic/claude-opus-5",
        "anthropic/claude-sonnet-5",
        "openai/gpt-6-astra",
        "openai/gpt-5.6-sol",
        "google/gemini-3-pro",
        "xai/grok-5",
    ]
    # --variant carries provider-specific reasoning effort.
    efforts = ["minimal", "low", "medium", "high", "max"]
    # Deliberately only one. See the module docstring: offering
    # "workspace-write" would imply a boundary this CLI does not enforce.
    sandboxes = ["read-only"]
    can_resume = True
    can_withhold_repo = True

    def install_hint(self):
        return "Install opencode and authenticate a model provider with 'opencode auth login'."

    def probe(self):
        self._which("opencode")
        return "opencode " + self._version(["opencode", "--version"])

    def argv(self, brief_path, out_path, model, effort, sandbox, cwd, repo_access=True):
        if sandbox != "read-only":
            raise ProviderError(
                "opencode: only read-only is offered, because it has no sandbox "
                "to enforce anything stronger"
            )
        argv = ["opencode", "run", "--dir", cwd, "--format", "default"]
        if model:
            argv += ["-m", model]
        if effort and effort != "default":
            argv += ["--variant", effort]
        # No --auto. That is the whole of the read-only enforcement, and the
        # docstring is explicit that it is weaker than a sandbox.
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
                    f"opencode: timed out after {timeout}s. If the brief asked it "
                    f"to change something, it is waiting on a permission prompt "
                    f"nobody can answer."
                ) from None
            finally:
                if log is not subprocess.DEVNULL:
                    log.close()
        if done.returncode != 0:
            raise ProviderError(f"opencode: exited {done.returncode}; see the log")
        return done.returncode

    def resume(self, brief_path, out_path, cwd, log_path=None, timeout=600):
        argv = ["opencode", "run", "--dir", cwd, "--continue"]
        with open(brief_path, "rb") as stdin, open(out_path, "wb") as out:
            done = subprocess.run(
                argv, stdin=stdin, stdout=out, stderr=subprocess.DEVNULL,
                cwd=cwd, timeout=timeout,
            )
        if done.returncode != 0:
            raise ProviderError(f"opencode: resume exited {done.returncode}")
        return done.returncode
