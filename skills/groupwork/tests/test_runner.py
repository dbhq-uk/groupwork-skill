"""Rule 2, the provider contract, and honest fallback.

Everything here runs against a stub provider, so the suite needs no CLI
installed, no credentials and no network.
"""

import hashlib
import json
import os
import pathlib
import signal
import subprocess
import sys
import time

import pytest

import brief
import groupwork
import patterns
import provenance
import providers
import runner
from conftest import FAKE_CLI, install_fake_cli
from providers.base import Provider


DRAFT_VIEW = (
    "We should ship the thing because the incumbent is weak and the market "
    "is clearly wide open for a tool like ours."
)


class Stub(Provider):
    """A provider that does exactly what it is told to do, including nothing."""

    name = "stub"
    models = ["gpt-6-astra", "gpt-5.6-sol"]
    efforts = ["low", "medium", "high"]
    sandboxes = ["read-only"]

    #: What run() should write. Empty string means "exit 0 having written
    #: nothing", which is Copilot's real bug and Codex's killed-run signature.
    payload = "1. **major** somewhere:12 - the thing is wrong\n\nVerdict: fix it."
    last_call = {}

    def probe(self):
        return "stub 1.0"

    def run(self, brief_path, out_path, model, effort, sandbox, cwd,
            repo_access=True, log_path=None, timeout=600):
        Stub.last_call = {
            "model": model, "effort": effort, "sandbox": sandbox,
            "cwd": cwd, "repo_access": repo_access, "timeout": timeout,
            "brief": pathlib.Path(brief_path).read_text(encoding="utf-8"),
            "cwd_listing": sorted(os.listdir(cwd)) if os.path.isdir(cwd) else None,
        }
        pathlib.Path(out_path).write_text(Stub.payload, encoding="utf-8")
        return 0


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Keep every test out of the real ~/.dbhq/groupwork/."""
    monkeypatch.setattr(runner, "STATE", tmp_path)
    monkeypatch.setattr(provenance, "LEDGER", tmp_path / "runs.jsonl")
    monkeypatch.setitem(providers.REGISTRY, "stub", Stub)
    Stub.payload = "1. **major** somewhere:12 - the thing is wrong\n\nVerdict: fix it."
    yield


def go(pattern="second-opinion", **kwargs):
    kwargs.setdefault("provider_name", "stub")
    return runner.run(pattern, "a brief", **kwargs)


# --- Rule 2: empty output is a failure ---------------------------------------

def test_empty_output_is_a_failure_not_a_clean_review():
    """The single most dangerous failure mode this skill has.

    Codex writes its result only at completion, so a killed run leaves a
    zero-byte file and a survivable-looking exit. Copilot has a bug where it
    exits 0 having written nothing at all. Read either as success and you
    report "the reviewer found no issues" about a review that never happened.
    """
    Stub.payload = ""
    with pytest.raises(runner.RunFailed, match="no issues found"):
        go()


def test_whitespace_only_output_is_also_a_failure():
    Stub.payload = "\n   \n\t\n"
    with pytest.raises(runner.RunFailed):
        go()


# --- The provider contract ---------------------------------------------------

@pytest.mark.parametrize("name", sorted(providers.REGISTRY))
def test_every_provider_implements_the_contract(name):
    provider = providers.get(name)
    for verb in ("probe", "capabilities", "run"):
        assert callable(getattr(provider, verb)), f"{name} has no {verb}"


@pytest.mark.parametrize("name", sorted(providers.REGISTRY))
def test_capabilities_returns_every_required_key(name):
    caps = providers.get(name).capabilities()
    for key in ("provider", "models", "efforts", "sandboxes", "can_withhold_repo"):
        assert key in caps, f"{name} capabilities missing {key}"
    assert caps["sandboxes"], f"{name} offers no sandbox at all"
    assert json.dumps(caps), f"{name} capabilities are not serialisable"


@pytest.mark.parametrize("name", sorted(providers.REGISTRY) + ["copilot"])
def test_no_provider_can_resume_a_session(name):
    """Nothing called resume(), and Codex's picked the newest session on the machine."""
    if name == "copilot":
        from providers.copilot import Copilot as cls
    else:
        cls = providers.REGISTRY[name]
    assert not hasattr(cls, "resume"), f"{name} still defines resume()"
    assert "can_resume" not in cls().capabilities()


def test_patterns_does_not_list_collaborate(capsys):
    assert groupwork.main(["patterns"]) == 0
    out = capsys.readouterr().out
    assert "collaborate" not in out
    assert "panel" in out


def test_there_is_no_our_view_flag(capsys):
    with pytest.raises(SystemExit):
        groupwork.main(["run", "second-opinion", "--subject", "a thing",
                        "--our-view", DRAFT_VIEW, "--provider", "stub"])
    assert "--our-view" in capsys.readouterr().err


def test_a_provider_that_cannot_reach_the_sandbox_says_so():
    """Rule 4 from the other side: asking for write on a provider without it fails."""
    with pytest.raises(runner.RunFailed, match="does not offer a write sandbox"):
        go(allow_write=True)


@pytest.mark.parametrize("name", sorted(providers.REGISTRY))
def test_every_registered_provider_runs_every_pattern_against_a_fake_cli(
        name, tmp_path, monkeypatch):
    """A registered provider has to be able to run, not merely import.

    Drives the real adapter, with its real capabilities, against a fake binary
    of the same name on PATH. copilot was registered while every run through it
    failed on its own effort list, which a test like this catches at once.
    """
    install_fake_cli(tmp_path / "bin", name)
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:{os.environ['PATH']}")
    for pattern in patterns.PATTERNS:
        result = runner.run(pattern, "a brief", provider_name=name, cwd=str(tmp_path))
        assert "a canned finding" in result["output"], f"{name} {pattern}"


def test_copilot_is_not_registered_until_it_has_run_against_the_real_cli(
        capsys, tmp_path, monkeypatch):
    """Its adapter was written from documentation and could not complete a run."""
    assert "copilot" not in providers.REGISTRY
    for name in ("codex", "opencode", "copilot"):
        install_fake_cli(tmp_path / "bin", name)
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    groupwork.main(["providers"])
    assert "copilot" not in capsys.readouterr().out


# A fake opencode that answers with the config and argv it was given, so a test
# can read what the real adapter handed its child.
FAKE_OPENCODE_ECHO = """#!/bin/bash
if [ "$1" = "--version" ]; then echo "1.0.0"; exit 0; fi
cat > /dev/null
printf 'ARGV %s\\n' "$*"
printf 'CONFIG %s\\n' "$OPENCODE_CONFIG_CONTENT"
"""


def _opencode_child(tmp_path, monkeypatch, pattern="second-opinion"):
    install_fake_cli(tmp_path / "bin", "opencode", FAKE_OPENCODE_ECHO)
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:{os.environ['PATH']}")
    output = runner.run(pattern, "a brief", provider_name="opencode",
                        cwd=str(tmp_path))["output"]
    lines = dict(line.split(" ", 1) for line in output.splitlines() if " " in line)
    return lines["ARGV"], json.loads(lines["CONFIG"])


@pytest.mark.parametrize("pattern", sorted(patterns.PATTERNS))
def test_the_opencode_child_is_denied_edit_bash_and_the_web(
        pattern, tmp_path, monkeypatch):
    """Leaving out --auto enforces nothing: opencode defaults most tools to allow.

    Read-only has to arrive as explicit deny rules, globally and on the agent
    that runs, because an agent's own rules are applied after the global ones.
    """
    monkeypatch.delenv("OPENCODE_CONFIG_CONTENT", raising=False)
    argv, config = _opencode_child(tmp_path, monkeypatch, pattern)
    assert "--agent build" in argv
    assert "--auto" not in argv
    for rules in (config["permission"], config["agent"]["build"]["permission"]):
        for tool in ("edit", "webfetch", "websearch", "task", "skill",
                     "external_directory"):
            assert rules[tool] == "deny", tool
        bash = rules["bash"]
        assert list(bash)[0] == "*" and bash["*"] == "deny"
        allowed = [p for p, action in bash.items() if action == "allow"]
        assert allowed and all(p.startswith("git ") for p in allowed)


def test_the_opencode_deny_keeps_the_callers_other_config(tmp_path, monkeypatch):
    """A caller's own inline config survives, apart from the permission rules."""
    monkeypatch.setenv("OPENCODE_CONFIG_CONTENT", json.dumps({
        "theme": "mine",
        "permission": {"edit": "allow"},
        "agent": {"build": {"permission": {"edit": "allow"}, "temperature": 0.1}},
    }))
    _, config = _opencode_child(tmp_path, monkeypatch)
    assert config["theme"] == "mine"
    assert config["permission"]["edit"] == "deny"
    assert config["agent"]["build"]["permission"]["edit"] == "deny"
    assert config["agent"]["build"]["temperature"] == 0.1


# --- Signed in, not just installed -------------------------------------------

@pytest.mark.parametrize("name", sorted(providers.REGISTRY))
def test_a_signed_out_cli_is_listed_as_not_ready(name, capsys, tmp_path, monkeypatch):
    """Every one of these CLIs installs in a second and then refuses to run."""
    monkeypatch.delitem(providers.REGISTRY, "stub")
    for each in providers.REGISTRY:
        install_fake_cli(tmp_path / "bin", each)
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    monkeypatch.setenv("GW_FAKE_SIGNED_OUT", "1")
    for var in ("CODEX_API_KEY", "CODEX_ACCESS_TOKEN"):
        monkeypatch.delenv(var, raising=False)
    assert groupwork.main(["providers"]) == 1
    out = capsys.readouterr().out
    assert "Ready:" not in out
    ready, _, not_ready = out.partition("Not ready:")
    line = next(line for line in not_ready.splitlines() if line.strip().startswith(name))
    assert "not logged in" in line or "not signed in" in line, line
    with pytest.raises(providers.ProviderError, match="login"):
        providers.get(name).probe()


def test_a_codex_key_in_the_environment_counts_as_signed_in(tmp_path, monkeypatch):
    """`codex exec` takes CODEX_API_KEY, and `codex login status` does not see it."""
    install_fake_cli(tmp_path / "bin", "codex")
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    monkeypatch.setenv("GW_FAKE_SIGNED_OUT", "1")
    monkeypatch.setenv("CODEX_API_KEY", "sk-not-a-real-key")
    assert providers.get("codex").probe() == "fake-cli 1.0"


def test_an_opencode_auth_list_it_cannot_read_is_not_a_lockout():
    from providers import opencode
    assert opencode.signed_in("\x1b[90m└  0 credentials\n") is False
    assert opencode.signed_in(
        "└  0 credentials\n●  OpenAI OPENAI_API_KEY\n└  1 environment variable\n"
    ) is True
    assert opencode.signed_in("something opencode has never printed") is None


def test_opencode_signed_in_to_a_custom_provider_only_is_ready(tmp_path, monkeypatch):
    """A local model set up in opencode.json needs no credential."""
    install_fake_cli(tmp_path / "bin", "opencode")
    monkeypatch.setenv("PATH", str(tmp_path / "bin"))
    monkeypatch.setenv("GW_FAKE_SIGNED_OUT", "1")
    monkeypatch.setenv("GW_FAKE_CONFIG", json.dumps(
        {"provider": {"ollama": {}}, "model": "ollama/qwen3"}))
    assert providers.get("opencode").probe()


def _opencode_model(tmp_path, monkeypatch, models, config, **kwargs):
    install_fake_cli(tmp_path / "bin", "opencode", FAKE_OPENCODE_ECHO)
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:{os.environ['PATH']}")
    monkeypatch.setenv("GW_FAKE_MODELS", models)
    monkeypatch.setenv("GW_FAKE_CONFIG", json.dumps(config))
    result = runner.run("red-team", "a brief", provider_name="opencode",
                        cwd=str(tmp_path), **kwargs)
    argv = next(line for line in result["output"].splitlines()
                if line.startswith("ARGV "))
    return argv, result


def test_opencode_asks_for_the_patterns_model_when_it_can_reach_it(tmp_path, monkeypatch):
    argv, result = _opencode_model(
        tmp_path, monkeypatch, "openai/gpt-6-astra\nanthropic/claude-opus-5",
        {"model": "anthropic/claude-opus-5"})
    assert "-m openai/gpt-6-astra" in argv
    assert result["model"] == "openai/gpt-6-astra"


def test_opencode_without_openai_uses_its_own_default_not_an_openai_model(
        tmp_path, monkeypatch):
    argv, result = _opencode_model(
        tmp_path, monkeypatch, "anthropic/claude-opus-5\nanthropic/claude-sonnet-5",
        {"model": "anthropic/claude-sonnet-5"})
    assert "openai/" not in argv
    assert "-m anthropic/claude-sonnet-5" in argv
    assert result["model"] == "anthropic/claude-sonnet-5"
    assert provenance.runs()[-1]["model"] == "anthropic/claude-sonnet-5"


def test_opencode_without_openai_or_a_default_asks_for_a_model(tmp_path, monkeypatch):
    """Rather than run a model nobody chose, or one it has no credential for."""
    with pytest.raises(runner.RunFailed, match="--model"):
        _opencode_model(tmp_path, monkeypatch, "google/gemini-3-pro", {})
    assert provenance.runs() == [], "a refused run must not reach the ledger"


def test_a_model_named_with_model_is_used_as_given(tmp_path, monkeypatch):
    argv, result = _opencode_model(
        tmp_path, monkeypatch, "google/gemini-3-pro", {},
        model="google/gemini-3-pro")
    assert "-m google/gemini-3-pro" in argv


# --- The model: overridable, checked against the CLI, named on failure -------

def test_an_override_in_the_environment_changes_the_model_and_the_citation(monkeypatch):
    monkeypatch.setenv("GROUPWORK_STUB_MODEL", "gpt-5.6-sol")
    result = go()
    assert Stub.last_call["model"] == "gpt-5.6-sol"
    assert provenance.runs()[-1]["model"] == "gpt-5.6-sol"
    assert "`gpt-5.6-sol` via stub" in provenance.citation(result)


def test_an_override_in_the_config_file_changes_the_model(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"model": {"stub": "gpt-5.6-sol"}}))
    assert go()["model"] == "gpt-5.6-sol"
    assert Stub.last_call["model"] == "gpt-5.6-sol"


def test_the_environment_beats_the_file_and_model_beats_both(tmp_path, monkeypatch):
    (tmp_path / "config.json").write_text(json.dumps({"model": {"stub": "from-file"}}))
    monkeypatch.setenv("GROUPWORK_STUB_MODEL", "from-env")
    assert go()["model"] == "from-env"
    assert go(model="from-flag")["model"] == "from-flag"


def test_an_override_for_another_provider_changes_nothing(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({"model": {"codex": "gpt-5.6-sol"}}))
    assert go()["model"] == "gpt-6-astra"


def test_a_config_file_that_cannot_be_read_refuses_the_run(tmp_path):
    """Ignoring it would run the very model the user set it to avoid."""
    (tmp_path / "config.json").write_text("{not json")
    with pytest.raises(runner.RunFailed, match="config.json"):
        go()
    assert provenance.runs() == []


def _codex_at(tmp_path, monkeypatch, version, script=FAKE_CLI):
    script = script.replace('echo "fake-cli 1.0"', f'echo "{version}"')
    install_fake_cli(tmp_path / "bin", "codex", script)
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:{os.environ['PATH']}")


@pytest.mark.parametrize("named", [None, "gpt-6-astra"])
def test_astra_on_a_codex_below_the_floor_is_refused(named, tmp_path, monkeypatch):
    """Older CLIs cannot see the model, and the run failed with only "exited 1"."""
    _codex_at(tmp_path, monkeypatch, "codex-cli 0.152.9")
    with pytest.raises(runner.RunFailed) as caught:
        runner.run("red-team", "a brief", provider_name="codex",
                   cwd=str(tmp_path), model=named)
    assert "gpt-6-astra" in str(caught.value)
    assert "0.153.0" in str(caught.value)
    assert provenance.runs() == [], "a run that could not start is not in history"


def test_astra_on_a_codex_at_the_floor_runs(tmp_path, monkeypatch):
    _codex_at(tmp_path, monkeypatch, "codex-cli 0.153.0")
    result = runner.run("verify", "a brief", provider_name="codex", cwd=str(tmp_path))
    assert result["model"] == "gpt-6-astra"


def test_an_old_codex_runs_the_model_it_was_told_to_use(tmp_path, monkeypatch):
    _codex_at(tmp_path, monkeypatch, "codex-cli 0.140.0")
    monkeypatch.setenv("GROUPWORK_CODEX_MODEL", "gpt-5.6-sol")
    result = runner.run("verify", "a brief", provider_name="codex", cwd=str(tmp_path))
    assert result["model"] == "gpt-5.6-sol"


def test_a_failed_run_names_the_model_it_asked_for(tmp_path, monkeypatch):
    failing = FAKE_CLI.replace(
        "cat > /dev/null", 'cat > /dev/null\necho "no such model" >&2\nexit 1')
    _codex_at(tmp_path, monkeypatch, "codex-cli 0.154.0", failing)
    with pytest.raises(runner.RunFailed) as caught:
        runner.run("verify", "a brief", provider_name="codex", cwd=str(tmp_path))
    assert "exited 1" in str(caught.value)
    assert "gpt-6-astra" in str(caught.value)
    assert "gpt-6-astra" in provenance.runs()[-1]["error"]


def _dry_run(provider):
    return groupwork.main(["run", "second-opinion", "--subject", "a thing",
                           "--no-prior-view", "--provider", provider, "--dry-run"])


def test_running_inside_codex_says_the_counterpart_is_the_same_family(
        capsys, monkeypatch):
    monkeypatch.setenv("CODEX_THREAD_ID", "a-thread")
    assert providers.host() == "codex"
    assert _dry_run("codex") == 0
    assert "same family" in capsys.readouterr().err
    assert _dry_run("opencode") == 0
    assert "same family" not in capsys.readouterr().err


def test_outside_codex_there_is_no_family_note(capsys):
    assert providers.host() is None
    assert _dry_run("codex") == 0
    assert "same family" not in capsys.readouterr().err


# --- No groupwork inside a groupwork run -------------------------------------

@pytest.mark.parametrize("command", [
    ["run", "second-opinion", "--subject", "a thing", "--no-prior-view",
     "--provider", "stub"],
    ["panel", "--subject", "queue or cron", "--no-prior-view",
     "--members", "stub,stub"],
])
def test_run_and_panel_refuse_inside_a_groupwork_run(command, capsys, monkeypatch):
    monkeypatch.setenv("GROUPWORK_DEPTH", "1")
    Stub.last_call = {}
    assert groupwork.main(command) == 2
    assert "GROUPWORK_DEPTH" in capsys.readouterr().err
    assert Stub.last_call == {}, "a provider was called anyway"
    assert provenance.runs() == []


# A fake that reports the depth it was given, and what a groupwork started from
# inside it does, as a counterpart reaching for the skill would.
FAKE_NESTED = """#!/bin/bash
if [ "$1" = "--version" ]; then echo "codex-cli 0.154.0"; exit 0; fi
out=""
prev=""
for arg in "$@"; do
  if [ "$prev" = "-o" ]; then out="$arg"; fi
  prev="$arg"
done
cat > /dev/null
"$GW_PYTHON" "$GW_SCRIPT" run second-opinion --subject "a thing" \
  --no-prior-view --dry-run > /dev/null 2>&1
answer="DEPTH ${GROUPWORK_DEPTH:-unset} NESTED $?"
if [ -n "$out" ]; then printf '%s\n' "$answer" > "$out"; else printf '%s\n' "$answer"; fi
"""


@pytest.mark.parametrize("name", sorted(providers.REGISTRY))
def test_every_provider_child_refuses_to_start_another_run(name, tmp_path, monkeypatch):
    """The brief asks it not to. This makes it a rule rather than a request."""
    install_fake_cli(tmp_path / "bin", name, FAKE_NESTED)
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:{os.environ['PATH']}")
    monkeypatch.setenv("GW_PYTHON", sys.executable)
    monkeypatch.setenv("GROUPWORK_HOME", str(tmp_path / "nested-home"))
    monkeypatch.setenv("GW_SCRIPT", str(pathlib.Path(runner.__file__).with_name("groupwork.py")))
    result = runner.run("second-opinion", "a brief", provider_name=name, cwd=str(tmp_path))
    assert "DEPTH 1 NESTED 2" in result["output"], result["output"]


def test_the_codex_installer_links_every_directory_the_skill_reads(tmp_path):
    """templates was missing, and only worked because brief.py resolved a symlink."""
    repo = pathlib.Path(runner.__file__).resolve().parents[3]
    done = subprocess.run(
        ["bash", str(repo / "install-codex.sh")],
        env=dict(os.environ, CODEX_SKILLS_DIR=str(tmp_path)),
        capture_output=True, text=True, timeout=60,
    )
    assert done.returncode == 0, done.stderr
    installed = tmp_path / "groupwork"
    source = repo / "skills" / "groupwork"
    for sub in ("scripts", "templates", "tests"):
        assert (installed / sub).is_symlink(), f"{sub} is not linked"
        assert (installed / sub).resolve() == (source / sub).resolve()
    assert "${CLAUDE_SKILL_DIR}" not in (installed / "SKILL.md").read_text(encoding="utf-8")


def test_unknown_provider_names_the_real_ones():
    with pytest.raises(ValueError, match="Available"):
        providers.get("nonesuch")


# --- Honest fallback ---------------------------------------------------------

def test_an_effort_the_provider_cannot_reach_falls_back_and_says_so():
    """Running quietly at a lower effort would make the citation a lie."""
    effort, downgraded = patterns.resolve_effort("ultra", Stub.efforts)
    assert effort == "high"
    assert downgraded is True


def test_the_record_names_the_effort_actually_used():
    result = go(effort="ultra")
    assert result["effort"] == "high"
    assert result["effort_requested"] == "ultra"
    assert result["effort_downgraded"] is True
    assert "Ran at high effort, not the ultra" in provenance.citation(result)


def test_a_missing_effort_falls_to_the_nearest_level_below_not_the_ceiling():
    assert patterns.resolve_effort("xhigh", ["low", "medium", "high", "max"]) == ("high", True)


def test_a_missing_effort_with_nothing_below_goes_up_and_is_not_called_a_downgrade(
        monkeypatch):
    assert patterns.resolve_effort("low", ["medium", "high"]) == ("medium", False)
    monkeypatch.setattr(Stub, "efforts", ["medium", "high"])
    result = go(effort="low")
    assert result["effort"] == "medium"
    assert result["effort_downgraded"] is False
    assert "Ran at medium effort, not the low" in provenance.citation(result)


def test_an_effort_the_provider_has_is_not_downgraded():
    effort, downgraded = patterns.resolve_effort("medium", Stub.efforts)
    assert (effort, downgraded) == ("medium", False)


# --- Withholding the repository ----------------------------------------------

def test_red_team_runs_somewhere_with_no_repository_in_it():
    """'Independent of our retrieval' has to be a fact, not an intention."""
    result = go("red-team")
    assert result["repo_access"] is False
    assert Stub.last_call["cwd_listing"] == [], "red-team was given a non-empty directory"
    assert pathlib.Path(Stub.last_call["cwd"]).name.startswith("groupwork-norepo-")


@pytest.mark.parametrize("payload", ["an answer", ""])
def test_the_empty_directory_is_removed_however_the_run_ends(payload):
    """Every red-team run, and every test run, used to leave one behind."""
    Stub.payload = payload
    try:
        go("red-team")
    except runner.RunFailed:
        assert payload == ""
    workdir = pathlib.Path(Stub.last_call["cwd"])
    assert Stub.last_call["cwd_listing"] == []
    assert not workdir.exists(), f"{workdir} was left behind"


def test_red_team_can_be_given_the_repo_deliberately():
    result = go("red-team", repo_access=True, cwd=".")
    assert result["repo_access"] is True


def test_other_patterns_run_in_the_repo():
    result = go("verify", cwd=".")
    assert result["repo_access"] is True


# A fake codex that answers with where it was started and what it was given.
FAKE_CODEX_ECHO = """#!/bin/bash
if [ "$1" = "--version" ]; then echo "codex-cli 0.154.0"; exit 0; fi
out=""
prev=""
for arg in "$@"; do
  if [ "$prev" = "-o" ]; then out="$arg"; fi
  prev="$arg"
done
cat > /dev/null
{ printf 'PWD %s\\n' "$PWD"; printf 'ARGV %s\\n' "$*"; } > "$out"
"""


def _codex_child(tmp_path, monkeypatch, pattern, **kwargs):
    install_fake_cli(tmp_path / "bin", "codex", FAKE_CODEX_ECHO)
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:{os.environ['PATH']}")
    output = runner.run(pattern, "a brief", provider_name="codex", **kwargs)["output"]
    return dict(line.split(" ", 1) for line in output.splitlines())


def test_red_team_codex_runs_under_the_no_repo_profile_not_the_sandbox_flag(
        tmp_path, monkeypatch):
    """--sandbox read-only blocks writes, not reads. The profile blocks reads."""
    child = _codex_child(tmp_path, monkeypatch, "red-team", cwd=str(tmp_path))
    assert "--sandbox" not in child["ARGV"]
    assert 'default_permissions="groupwork-norepo"' in child["ARGV"]
    assert '":minimal"="read"' in child["ARGV"]
    assert '":workspace_roots"={"."="read"}' in child["ARGV"]
    assert "network={enabled=false}" in child["ARGV"]
    assert ":root" not in child["ARGV"], "deny on :root would deny :minimal too"


def test_red_team_codex_is_started_in_the_empty_directory(tmp_path, monkeypatch):
    """-C only names the workspace. The process must start there as well."""
    monkeypatch.chdir(tmp_path)
    child = _codex_child(tmp_path, monkeypatch, "red-team", cwd=str(tmp_path))
    started = pathlib.Path(child["PWD"])
    assert started != tmp_path
    assert started.name.startswith("groupwork-norepo-")
    assert f"-C {started}" in child["ARGV"]


def test_codex_with_the_repository_keeps_the_sandbox_flag(tmp_path, monkeypatch):
    child = _codex_child(tmp_path, monkeypatch, "verify", cwd=str(tmp_path))
    assert "--sandbox read-only" in child["ARGV"]
    assert "default_permissions" not in child["ARGV"]
    assert pathlib.Path(child["PWD"]) == tmp_path


def test_red_team_given_the_repo_uses_the_sandbox_flag(tmp_path, monkeypatch):
    child = _codex_child(tmp_path, monkeypatch, "red-team", cwd=str(tmp_path),
                         repo_access=True)
    assert "--sandbox read-only" in child["ARGV"]
    assert "default_permissions" not in child["ARGV"]


FAKE_CODEX_NO_SANDBOX = """#!/bin/bash
if [ "$1" = "--version" ]; then echo "codex-cli 0.154.0"; exit 0; fi
cat > /dev/null
echo "Error: Fatal error: Failed to initialize session: fs sandbox helper failed with status exit status: 1: bwrap: setting up uid map: Permission denied" >&2
exit 1
"""


def test_a_host_that_cannot_start_the_sandbox_is_told_so_not_left_guessing(
        tmp_path, monkeypatch):
    """Where Codex cannot restrict reads, red-team refuses rather than reading."""
    install_fake_cli(tmp_path / "bin", "codex", FAKE_CODEX_NO_SANDBOX)
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:{os.environ['PATH']}")
    with pytest.raises(runner.RunFailed, match="--repo-access"):
        runner.run("red-team", "a brief", provider_name="codex", cwd=str(tmp_path))
    # The same failure with the repository granted is an ordinary failure.
    with pytest.raises(runner.RunFailed, match="exited 1") as caught:
        runner.run("verify", "a brief", provider_name="codex", cwd=str(tmp_path))
    assert "--repo-access" not in str(caught.value)


# --- Timeouts ----------------------------------------------------------------

def test_each_effort_maps_to_the_documented_timeout():
    assert patterns.TIMEOUTS == {
        "low": 150, "medium": 300, "high": 1200,
        "xhigh": 1200, "max": 1800, "ultra": 1800,
    }


def test_the_timeout_follows_the_effort_actually_used():
    go(effort="low")
    assert Stub.last_call["timeout"] == 150


# A fake CLI that starts a long-lived grandchild, the way the Codex npm wrapper
# starts the native binary, records its pid and then waits on it.
FAKE_CLI_WITH_GRANDCHILD = """#!/bin/bash
if [ "$1" = "--version" ]; then echo "fake-cli 1.0"; exit 0; fi
cat > /dev/null
sleep 300 &
echo $! > "$GW_GRANDCHILD_PIDFILE"
wait
"""

# The same, with SIGTERM ignored by the wrapper and the grandchild alike.
FAKE_CLI_IGNORING_TERM = FAKE_CLI_WITH_GRANDCHILD.replace(
    "cat > /dev/null", "trap '' TERM\ncat > /dev/null"
)


def _alive(pid):
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    stat = pathlib.Path(f"/proc/{pid}/stat")
    try:
        return stat.read_text().split(") ", 1)[1][0] != "Z"
    except (OSError, IndexError):
        return True


def _wait_gone(pid, seconds=5.0):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not _alive(pid):
            return True
        time.sleep(0.05)
    return False


@pytest.mark.parametrize("name", sorted(providers.REGISTRY))
@pytest.mark.parametrize("script", ["grandchild", "ignores-term"])
def test_a_timeout_stops_the_grandchild_too(name, script, tmp_path, monkeypatch):
    """Killing only the direct child leaves the real CLI running, and billing.

    The Codex npm wrapper forwards SIGTERM to the native binary but cannot
    forward SIGKILL. So the whole process group gets SIGTERM, then SIGKILL for
    anything still there after a short grace period.
    """
    from providers import base
    monkeypatch.setattr(base, "GRACE_S", 0.5)
    body = FAKE_CLI_WITH_GRANDCHILD if script == "grandchild" else FAKE_CLI_IGNORING_TERM
    install_fake_cli(tmp_path / "bin", name, body)
    pidfile = tmp_path / "grandchild.pid"
    monkeypatch.setenv("GW_GRANDCHILD_PIDFILE", str(pidfile))
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:{os.environ['PATH']}")
    pid = None
    try:
        with pytest.raises(runner.RunFailed, match="timed out"):
            runner.run("verify", "a brief", provider_name=name,
                       cwd=str(tmp_path), timeout=1)
        pid = int(pidfile.read_text())
        assert _wait_gone(pid), "the grandchild outlived the timeout"
    finally:
        if pid is None and pidfile.exists():
            pid = int(pidfile.read_text())
        if pid is not None and _alive(pid):
            os.kill(pid, signal.SIGKILL)


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT])
def test_stopping_groupwork_stops_the_run_it_started(sig, tmp_path):
    """The child leads its own session, so a signal to groupwork must be passed on.

    Otherwise a host that stops groupwork would orphan the CLI it started, which
    is the same bill this change exists to stop.
    """
    install_fake_cli(tmp_path / "bin", "codex", FAKE_CLI_WITH_GRANDCHILD)
    pidfile = tmp_path / "grandchild.pid"
    env = dict(os.environ, PATH=f"{tmp_path / 'bin'}:{os.environ['PATH']}",
               GROUPWORK_HOME=str(tmp_path / "home"),
               GW_GRANDCHILD_PIDFILE=str(pidfile))
    script = pathlib.Path(runner.__file__).with_name("groupwork.py")
    proc = subprocess.Popen(
        [sys.executable, str(script), "run", "verify", "--subject", "a thing",
         "--constraints", "It builds.", "--no-prior-view", "--provider", "codex",
         "--timeout", "60"],
        env=env, cwd=str(tmp_path),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    pid = None
    try:
        deadline = time.monotonic() + 10
        while not (pidfile.exists() and pidfile.read_text().strip()):
            assert time.monotonic() < deadline, "the fake CLI never started"
            time.sleep(0.05)
        pid = int(pidfile.read_text())
        proc.send_signal(sig)
        proc.wait(timeout=20)
        assert _wait_gone(pid), "the grandchild outlived groupwork"
    finally:
        if proc.poll() is None:
            proc.kill()
        if pid is not None and _alive(pid):
            os.kill(pid, signal.SIGKILL)


FAKE_CODEX_SLOW_WITH_BWRAP_NOISE = """#!/bin/bash
if [ "$1" = "--version" ]; then echo "codex-cli 0.154.0"; exit 0; fi
cat > /dev/null
echo "bwrap: a sandboxed command failed partway through the run" >&2
sleep 300
"""


def test_a_red_team_timeout_is_reported_as_a_timeout(tmp_path, monkeypatch):
    """Sandbox noise in the log must not turn a timeout into a start failure."""
    from providers import base
    monkeypatch.setattr(base, "GRACE_S", 0.5)
    install_fake_cli(tmp_path / "bin", "codex", FAKE_CODEX_SLOW_WITH_BWRAP_NOISE)
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:{os.environ['PATH']}")
    with pytest.raises(runner.RunFailed) as caught:
        runner.run("red-team", "a brief", provider_name="codex",
                   cwd=str(tmp_path), timeout=1)
    assert "timed out" in str(caught.value)
    assert "--repo-access" not in str(caught.value)


def test_verify_without_constraints_is_refused_before_any_provider_is_called(capsys):
    Stub.last_call = {}
    code = groupwork.main(["run", "verify", "--subject", "the diff",
                           "--no-prior-view", "--provider", "stub"])
    assert code == 2
    assert "--constraints" in capsys.readouterr().err
    assert Stub.last_call == {}, "the provider was called anyway"
    assert provenance.runs() == [], "a refused brief must not reach the ledger"


def test_run_timeout_reaches_the_provider():
    code = groupwork.main(["run", "second-opinion", "--subject", "a thing",
                           "--no-prior-view", "--provider", "stub",
                           "--timeout", "42"])
    assert code == 0
    assert Stub.last_call["timeout"] == 42


def test_the_high_timeout_outlasts_a_real_high_effort_run():
    """Real high-effort runs have taken more than ten minutes."""
    assert patterns.TIMEOUTS["high"] >= 1200


# --- Provenance --------------------------------------------------------------

def test_every_ledger_field_is_present_and_populated():
    entry = provenance.record(go(subject="the diff on this branch"))
    for field in provenance.FIELDS:
        assert field in entry, f"ledger is missing {field}"
        if field in provenance.OPTIONAL_FIELDS:
            assert entry[field] is None, f"{field} set on a clean run outside a panel"
            continue
        assert entry[field] not in (None, ""), f"ledger field {field} is empty"


def test_withheld_is_copied_from_the_pattern_not_supplied_by_the_caller():
    """Nobody is in a position to type an independence claim that is not true."""
    entry = provenance.record(go("red-team"))
    assert entry["withheld"] == patterns.PATTERNS["red-team"]["withholds"]


def test_red_team_given_the_repo_does_not_claim_the_evidence_was_withheld():
    """With --repo-access, anything in the repository was open to it."""
    line = provenance.citation(go("red-team", repo_access=True, cwd="."))
    assert "our evidence and our retrieval" not in line
    assert "given the repository" in line


def test_every_run_keeps_its_brief_and_records_its_hash():
    """The brief is the only evidence of what the counterpart was told."""
    entry = provenance.record(go(subject="the diff"))
    stored = pathlib.Path(entry["brief_path"])
    assert stored.name == f"{entry['id']}.brief.md"
    assert stored.read_bytes() == b"a brief"
    assert entry["brief_sha256"] == hashlib.sha256(b"a brief").hexdigest()
    assert entry["brief_sha256"] in provenance.citation(entry)


def test_the_brief_is_kept_when_the_run_fails():
    Stub.payload = ""
    with pytest.raises(runner.RunFailed):
        go()
    assert list((runner.STATE / "runs").glob("*.brief.md"))


def test_the_citation_says_the_leak_check_passed():
    text = brief.build("second-opinion", subject="a thing",
                       assert_withholds=DRAFT_VIEW)
    result = runner.run("second-opinion", text, provider_name="stub")
    assert provenance.record(result)["leak_check"] == "passed"
    assert "Leak check passed" in provenance.citation(result)


def test_the_citation_says_the_leak_check_did_not_run():
    text = brief.build("second-opinion", subject="a thing", no_prior_view=True)
    result = runner.run("second-opinion", text, provider_name="stub")
    assert provenance.record(result)["leak_check"] == "not-run"
    assert "not run: the caller declared no prior view" in provenance.citation(result)


def test_a_plain_string_brief_never_reads_as_checked():
    """Only brief.build() runs the check, so only its output can say it passed."""
    assert go()["leak_check"] == "not-run"


def test_an_old_ledger_line_still_cites_without_claiming_a_check():
    """Lines written before these fields existed must still show, and not overclaim."""
    newer = {"leak_check", "no_prior_view", "brief_path", "brief_sha256"}
    old = {k: v for k, v in go().items() if k not in newer}
    line = provenance.citation(old)
    assert "Leak check not recorded" in line
    assert "sha256" not in line


def test_a_blind_run_with_no_declaration_is_refused_by_the_cli(capsys):
    code = groupwork.main(["run", "second-opinion", "--subject", "a thing",
                           "--provider", "stub"])
    assert code == 2
    assert "--no-prior-view" in capsys.readouterr().err


def test_the_citation_names_the_model_provider_version_and_what_was_withheld():
    line = provenance.citation(go("red-team"))
    assert "gpt-6-astra" in line
    assert "stub 1.0" in line
    assert "no repository access" in line
    assert "withheld" in line


def test_an_unverified_adapter_says_so_in_its_own_citation():
    """An adapter written from documentation is a caveat on the finding itself.

    copilot's is. Burying that in a README would put the caveat
    somewhere the person reading the review will never look.
    """
    Stub.experimental = True
    try:
        line = provenance.citation(go())
        assert "experimental" in line
        assert "not been verified against the real CLI" in line
    finally:
        Stub.experimental = False


def test_a_verified_adapter_adds_no_caveat():
    assert "experimental" not in provenance.citation(go())


def test_no_registered_provider_is_experimental_at_this_version():
    for name in providers.REGISTRY:
        assert providers.get(name).experimental is False, name


def test_the_pairwork_state_directory_is_migrated_once(tmp_path, monkeypatch):
    """The skill was pairwork for a few hours in public. Do not orphan those runs."""
    old = tmp_path / "pairwork"
    new = tmp_path / "groupwork"
    (old / "runs").mkdir(parents=True)
    (old / "runs" / "r1.md").write_text("a finding", encoding="utf-8")
    (old / "runs.jsonl").write_text(
        json.dumps({"id": "r1", "output_path": str(old / "runs" / "r1.md")}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(runner, "STATE", new)
    monkeypatch.setattr(runner, "_OLD_STATE", old)

    runner._migrate_from_pairwork()

    assert not old.exists()
    assert (new / "runs" / "r1.md").read_text(encoding="utf-8") == "a finding"
    # The absolute path in the ledger is rewritten, or `show` breaks for every
    # run made before the rename.
    row = json.loads((new / "runs.jsonl").read_text(encoding="utf-8").strip())
    assert row["output_path"] == str(new / "runs" / "r1.md")


def test_the_migration_never_overwrites_an_existing_directory(tmp_path, monkeypatch):
    old = tmp_path / "pairwork"
    new = tmp_path / "groupwork"
    old.mkdir()
    new.mkdir()
    (new / "runs.jsonl").write_text("mine\n", encoding="utf-8")
    monkeypatch.setattr(runner, "STATE", new)
    monkeypatch.setattr(runner, "_OLD_STATE", old)

    runner._migrate_from_pairwork()

    assert old.exists(), "the old directory was consumed despite a live new one"
    assert (new / "runs.jsonl").read_text(encoding="utf-8") == "mine\n"


def test_the_migration_is_a_no_op_for_a_fresh_install(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "STATE", tmp_path / "groupwork")
    monkeypatch.setattr(runner, "_OLD_STATE", tmp_path / "pairwork")
    runner._migrate_from_pairwork()
    assert not (tmp_path / "groupwork").exists()


def test_the_ledger_survives_a_half_written_line(tmp_path):
    provenance.LEDGER.write_text(
        json.dumps({"id": "good", "pattern": "verify"}) + "\n{\"id\": \"trunc",
        encoding="utf-8",
    )
    rows = provenance.read_ledger()
    assert [r["id"] for r in rows] == ["good"]


def test_history_is_empty_before_anything_runs():
    assert provenance.read_ledger() == []


# --- Every run is in the ledger, not only the ones that worked ---------------

FAKE_CODEX_EXIT_1 = """#!/bin/bash
if [ "$1" = "--version" ]; then echo "codex-cli 0.154.0"; exit 0; fi
cat > /dev/null
echo "the model refused" >&2
exit 1
"""


def _failed_codex_run(tmp_path, monkeypatch):
    install_fake_cli(tmp_path / "bin", "codex", FAKE_CODEX_EXIT_1)
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:{os.environ['PATH']}")
    with pytest.raises(runner.RunFailed, match="exited 1"):
        runner.run("verify", "a brief", provider_name="codex",
                   cwd=str(tmp_path), subject="the diff")
    return provenance.read_ledger()[-1]["id"]


def test_a_failed_run_has_a_ledger_line_saying_so(tmp_path, monkeypatch):
    """It used to leave a log in runs/ and nothing in the ledger."""
    run_id = _failed_codex_run(tmp_path, monkeypatch)
    lines = [line for line in provenance.read_ledger() if line["id"] == run_id]
    assert [line["status"] for line in lines] == ["started", "failed"]
    row = provenance.find(run_id)
    assert row["status"] == "failed"
    assert "exited 1" in row["error"]
    assert row["subject"] == "the diff"
    assert row["duration_s"] is not None


def test_history_lists_a_failed_run_marked_as_failed(tmp_path, monkeypatch, capsys):
    go(subject="a run that worked")
    run_id = _failed_codex_run(tmp_path, monkeypatch)
    assert groupwork.main(["history"]) == 0
    out = capsys.readouterr().out
    rows = [line for line in out.splitlines() if line.startswith("20")]
    assert len(rows) == 2, "one row per run, not one per ledger line"
    failed_line = next(line for line in out.splitlines() if line.startswith(run_id))
    assert "[failed]" in failed_line
    ok_line = next(line for line in out.splitlines()
                   if line.startswith("20") and not line.startswith(run_id))
    assert "[" not in ok_line


def test_show_works_for_a_run_with_a_log_but_no_output(tmp_path, monkeypatch, capsys):
    run_id = _failed_codex_run(tmp_path, monkeypatch)
    assert groupwork.main(["show", run_id]) == 1
    out = capsys.readouterr().out
    assert f"Run {run_id}: failed." in out
    assert "exited 1" in out
    assert f"{run_id}.log" in out
    assert "**Verification pass:**" not in out, "a failed run must not be cited"


def test_a_timed_out_run_is_recorded_as_timed_out(tmp_path, monkeypatch):
    from providers import base
    monkeypatch.setattr(base, "GRACE_S", 0.5)
    install_fake_cli(tmp_path / "bin", "codex", FAKE_CODEX_SLOW_WITH_BWRAP_NOISE)
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:{os.environ['PATH']}")
    with pytest.raises(runner.RunFailed, match="timed out"):
        runner.run("verify", "a brief", provider_name="codex",
                   cwd=str(tmp_path), timeout=1)
    (row,) = provenance.runs()
    assert row["status"] == "timed-out"


def test_an_empty_answer_is_recorded_as_failed():
    Stub.payload = ""
    with pytest.raises(runner.RunFailed):
        go()
    (row,) = provenance.runs()
    assert row["status"] == "failed"
    assert "returned nothing" in row["error"]


def test_a_killed_run_reads_as_stopped(capsys):
    """Killed outright, only the "started" line is left, and no lock is held."""
    go()
    started = dict(provenance.read_ledger()[0])
    started["id"] = "20260101T000000Z-abcdef"
    with provenance.LEDGER.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(started) + "\n")
    assert groupwork.main(["history"]) == 0
    assert "[stopped]" in capsys.readouterr().out
    assert groupwork.main(["status", started["id"]]) == 0
    assert "stopped before it finished" in capsys.readouterr().out


def test_a_run_from_before_failures_were_recorded_can_still_be_shown(capsys):
    """A log in runs/ and no ledger line at all is what older failures left."""
    runs = runner._state_dir()
    run_id = "20260920T112902Z-333cbb"
    (runs / f"{run_id}.log").write_text("codex: exited 1\n", encoding="utf-8")
    (runs / f"{run_id}.brief.md").write_text("a brief", encoding="utf-8")
    assert groupwork.main(["show", run_id]) == 1
    out = capsys.readouterr().out
    assert "no result recorded" in out
    assert f"{run_id}.log" in out


def test_a_ledger_line_from_before_status_existed_reads_as_done(capsys):
    """Older lines were only ever written for runs that worked."""
    row = {k: v for k, v in provenance.record(go()).items()
           if k not in ("status", "error")}
    provenance.LEDGER.write_text(json.dumps(row) + "\n", encoding="utf-8")
    assert provenance.status(provenance.find(row["id"])) == "done"
    assert groupwork.main(["history"]) == 0
    assert "[" not in capsys.readouterr().out
    assert groupwork.main(["show", row["id"]]) == 0


def test_an_old_collaborate_line_still_shows_and_cites(capsys):
    """collaborate is gone, but its runs are still in people's ledgers."""
    row = {k: v for k, v in provenance.record(go()).items()
           if k not in ("status", "error", "panel_id", "panel_round")}
    row.update(pattern="collaborate", withheld="nothing - it is working with you")
    provenance.LEDGER.write_text(json.dumps(row) + "\n", encoding="utf-8")
    assert groupwork.main(["show", row["id"]]) == 0
    assert "**Worked through with:**" in capsys.readouterr().out
