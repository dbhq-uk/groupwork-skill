"""opencode. The provider that proves the layer is real.

It earns its place twice over. It is a second CLI, so the contract in base.py
was written against two implementations rather than one - which is the only way
to find out whether an interface is a contract or just Codex's flags renamed.
And it is itself a multi-model front end, so Gemini, Grok, Qwen and anything
running locally arrive behind this one file rather than one adapter each.

It is also the provider with the honest gap, and the gap is instructive.
opencode has no sandbox. Codex takes `--sandbox read-only` and the kernel
enforces it. opencode governs its tools with permissions instead, and most of
them default to allow, so a headless run left to its defaults can edit files,
run bash and fetch from the web. Leaving out `--auto` changes nothing about
that: `--auto` only approves what would otherwise ask.

So every run passes an inline config in `OPENCODE_CONFIG_CONTENT` that denies
`edit`, `bash` (apart from read-only `git` subcommands), `webfetch`,
`websearch`, `task`, `skill` and `external_directory`. Inline config outranks
project and user config. The same rules are set on the `build` agent as well as
globally, because an agent's own permissions are applied after the global ones
and would otherwise win, and the run names `--agent build` so it is that agent
that runs.

That is a tool-permission deny enforced by opencode itself, not a sandbox. A
bug in opencode's permission checks, or an allowed `git` subcommand given a flag
that writes, is not contained the way the kernel contains Codex. capabilities()
offers only read-only, and the provenance record names the provider, so a
reader can weigh the difference. What it must never do is claim the same
guarantee Codex gives.
"""

import json
import os
import subprocess

from .base import Provider, ProviderError, RunTimedOut, spawn

#: What a read-only review may do, as opencode permission rules. Last match
#: wins, so the blanket bash deny comes first and the git reads after it.
READ_ONLY_PERMISSIONS = {
    "edit": "deny",
    "bash": {
        "*": "deny",
        "git status*": "allow",
        "git log*": "allow",
        "git diff*": "allow",
        "git show*": "allow",
        "git blame*": "allow",
        "git ls-files*": "allow",
        "git grep*": "allow",
    },
    "webfetch": "deny",
    "websearch": "deny",
    # The brief tells it not to hand the work to another agent or skill. These
    # two make that a rule rather than a request.
    "task": "deny",
    "skill": "deny",
    "external_directory": "deny",
}

#: The agent every run uses. Its permissions are set as well as the global
#: ones; see the module docstring.
AGENT = "build"


def read_only_env(base=None):
    """The child's environment, carrying the read-only permission config.

    Anything else already in a caller's own OPENCODE_CONFIG_CONTENT is kept. The
    permission rules, global and for the agent that runs, are always ours.
    """
    env = dict(os.environ if base is None else base)
    try:
        config = json.loads(env.get("OPENCODE_CONFIG_CONTENT") or "{}")
    except json.JSONDecodeError:
        config = {}
    if not isinstance(config, dict):
        config = {}
    config["permission"] = READ_ONLY_PERMISSIONS
    agents = config.get("agent") if isinstance(config.get("agent"), dict) else {}
    agent = agents.get(AGENT) if isinstance(agents.get(AGENT), dict) else {}
    agent["permission"] = READ_ONLY_PERMISSIONS
    agents[AGENT] = agent
    config["agent"] = agents
    env["OPENCODE_CONFIG_CONTENT"] = json.dumps(config)
    return env


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
    # "workspace-write" would imply a boundary this adapter does not set up.
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
        argv = ["opencode", "run", "--dir", cwd, "--format", "default",
                "--agent", AGENT]
        if model:
            argv += ["-m", model]
        if effort and effort != "default":
            argv += ["--variant", effort]
        # No --auto either, though it is not what enforces anything. The deny
        # rules travel in the environment; see read_only_env().
        return argv

    def run(self, brief_path, out_path, model, effort, sandbox, cwd,
            repo_access=True, log_path=None, timeout=600):
        argv = self.argv(
            brief_path, out_path, model, effort, sandbox, cwd, repo_access
        )
        with open(brief_path, "rb") as stdin, open(out_path, "wb") as out:
            log = open(log_path, "wb") if log_path else subprocess.DEVNULL
            try:
                returncode = spawn(
                    self.name, argv, stdin=stdin, stdout=out, stderr=log,
                    cwd=cwd, timeout=timeout, env=read_only_env(),
                )
            except RunTimedOut as exc:
                raise RunTimedOut(
                    f"{exc} A tool that still asks for permission, such as "
                    f"reading a .env file, waits on a prompt nobody can answer."
                ) from None
            finally:
                if log is not subprocess.DEVNULL:
                    log.close()
        if returncode != 0:
            raise ProviderError(f"opencode: exited {returncode}; see the log")
        return returncode

    def resume(self, brief_path, out_path, cwd, log_path=None, timeout=600):
        argv = ["opencode", "run", "--dir", cwd, "--agent", AGENT, "--continue"]
        with open(brief_path, "rb") as stdin, open(out_path, "wb") as out:
            returncode = spawn(
                self.name, argv, stdin=stdin, stdout=out,
                stderr=subprocess.DEVNULL, cwd=cwd, timeout=timeout,
                env=read_only_env(),
            )
        if returncode != 0:
            raise ProviderError(f"opencode: resume exited {returncode}")
        return returncode
