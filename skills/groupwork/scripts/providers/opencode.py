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

Signing in is per model provider, not per CLI. opencode with no credential at
all is not ready, and opencode signed in to Anthropic only cannot run
`openai/gpt-6-astra` however the pattern asks. So once probe() has passed,
capabilities() lists only the models opencode says it can reach, and names
opencode's own configured default. The runner uses the pattern's model if it is
listed, then that default, and otherwise asks for `--model`.
"""

import json
import os
import re
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


#: A line of `opencode models`: provider/model.
_MODEL = re.compile(r"^[\w.@-]+/\S+$")

#: Colour codes, which `opencode auth list` writes even to a pipe.
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def signed_in(listing):
    """Read `opencode auth list`: True, False, or None if the shape is unknown.

    It ends a section with "N credentials" and, when any provider key is set in
    the environment, another with "N environment variables". An output with
    neither count is a format this does not know, and reads as None, so a
    change on opencode's side does not lock everybody out. The run itself
    still fails loudly if nothing is signed in.
    """
    text = _ANSI.sub("", listing)
    counts = [int(n) for n in re.findall(
        r"(\d+)\s+(?:credentials?|environment variables?)\b", text)]
    if not counts:
        return None
    return sum(counts) > 0


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
    can_withhold_repo = True

    def __init__(self, config=None):
        super().__init__(config)
        self._probed = False
        self._reach = None
        self._resolved = None

    def install_hint(self):
        return "Install opencode and authenticate a model provider with 'opencode auth login'."

    def probe(self):
        """Installed, and signed in to at least one model provider.

        `opencode auth list` shows stored credentials and provider keys found
        in the environment. It makes no model call and costs nothing.
        """
        self._which("opencode")
        version = "opencode " + self._version(["opencode", "--version"])
        done = self._call(["opencode", "auth", "list"])
        if done.returncode != 0:
            raise ProviderError(
                f"opencode: 'opencode auth list' exited {done.returncode}: "
                f"{(done.stderr or done.stdout).strip()[:300]}"
            )
        if signed_in(done.stdout + done.stderr) is False and not self._config().get("provider"):
            raise ProviderError(
                f"opencode: installed ({version}) but not signed in to any model "
                f"provider: 'opencode auth list' shows no credential and no "
                f"provider key in the environment. Run 'opencode auth login'."
            )
        self._probed = True
        return version

    def capabilities(self):
        caps = super().capabilities()
        if self._probed:
            caps["models"], caps["default_model"] = self._reachable()
        return caps

    def _reachable(self):
        """Which of our models opencode can run here, and its own default.

        `opencode models` lists only the models of providers that are signed
        in. If it fails, nothing is assumed reachable, so the run falls back to
        the configured default or asks for --model rather than guess.
        """
        if self._reach is None:
            done = self._call(["opencode", "models"], timeout=90)
            listed = set()
            if done.returncode == 0:
                listed = {line.strip() for line in done.stdout.splitlines()
                          if _MODEL.match(line.strip())}
            default = self._config().get("model")
            self._reach = (
                [name for name in self.models if name in listed],
                default if isinstance(default, str) and default.strip() else None,
            )
        return self._reach

    def _config(self):
        """opencode's resolved configuration, or {} if it cannot be read."""
        if self._resolved is None:
            done = self._call(["opencode", "debug", "config"])
            try:
                config = json.loads(done.stdout) if done.returncode == 0 else {}
            except json.JSONDecodeError:
                config = {}
            self._resolved = config if isinstance(config, dict) else {}
        return self._resolved

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
