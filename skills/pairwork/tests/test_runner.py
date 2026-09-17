"""Rule 2, the provider contract, and honest fallback.

Everything here runs against a stub provider, so the suite needs no CLI
installed, no credentials and no network.
"""

import json
import pathlib

import pytest

import patterns
import provenance
import providers
import runner
from providers.base import Provider, ProviderError


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
        }
        pathlib.Path(out_path).write_text(Stub.payload, encoding="utf-8")
        return 0


@pytest.fixture(autouse=True)
def isolated_state(tmp_path, monkeypatch):
    """Keep every test out of the real ~/.dbhq/pairwork/."""
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
    for key in ("provider", "models", "efforts", "sandboxes", "can_resume",
                "can_withhold_repo"):
        assert key in caps, f"{name} capabilities missing {key}"
    assert caps["sandboxes"], f"{name} offers no sandbox at all"
    assert json.dumps(caps), f"{name} capabilities are not serialisable"


def test_a_provider_that_cannot_reach_the_sandbox_says_so():
    """Rule 4 from the other side: asking for write on a provider without it fails."""
    with pytest.raises(runner.RunFailed, match="does not offer a write sandbox"):
        go(allow_write=True)


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


def test_an_effort_the_provider_has_is_not_downgraded():
    effort, downgraded = patterns.resolve_effort("medium", Stub.efforts)
    assert (effort, downgraded) == ("medium", False)


# --- Withholding the repository ----------------------------------------------

def test_red_team_runs_somewhere_with_no_repository_in_it():
    """'Independent of our retrieval' has to be a fact, not an intention."""
    result = go("red-team")
    assert result["repo_access"] is False
    workdir = pathlib.Path(Stub.last_call["cwd"])
    assert workdir.exists()
    assert list(workdir.iterdir()) == [], "red-team was given a non-empty directory"


def test_red_team_can_be_given_the_repo_deliberately():
    result = go("red-team", repo_access=True, cwd=".")
    assert result["repo_access"] is True


def test_other_patterns_run_in_the_repo():
    result = go("verify", cwd=".")
    assert result["repo_access"] is True


# --- Timeouts ----------------------------------------------------------------

def test_each_effort_maps_to_the_documented_timeout():
    assert patterns.TIMEOUTS == {
        "low": 150, "medium": 300, "high": 600,
        "xhigh": 1200, "max": 1800, "ultra": 1800,
    }


def test_the_timeout_follows_the_effort_actually_used():
    go(effort="low")
    assert Stub.last_call["timeout"] == 150


# --- Provenance --------------------------------------------------------------

def test_every_ledger_field_is_present_and_populated():
    entry = provenance.record(go(subject="the diff on this branch"))
    for field in provenance.FIELDS:
        assert field in entry, f"ledger is missing {field}"
        assert entry[field] not in (None, ""), f"ledger field {field} is empty"


def test_withheld_is_copied_from_the_pattern_not_supplied_by_the_caller():
    """Nobody is in a position to type an independence claim that is not true."""
    entry = provenance.record(go("red-team"))
    assert entry["withheld"] == patterns.PATTERNS["red-team"]["withholds"]


def test_the_citation_names_the_model_provider_version_and_what_was_withheld():
    line = provenance.citation(go("red-team"))
    assert "gpt-6-astra" in line
    assert "stub 1.0" in line
    assert "no repository access" in line
    assert "withheld" in line


def test_an_unverified_adapter_says_so_in_its_own_citation():
    """An adapter written from documentation is a caveat on the finding itself.

    copilot's is, at v0.1.0. Burying that in a README would put the caveat
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


def test_copilot_is_the_experimental_one_at_this_version():
    assert providers.get("copilot").experimental is True
    assert providers.get("codex").experimental is False
    assert providers.get("opencode").experimental is False


def test_the_ledger_survives_a_half_written_line(tmp_path):
    provenance.LEDGER.write_text(
        json.dumps({"id": "good", "pattern": "verify"}) + "\n{\"id\": \"trunc",
        encoding="utf-8",
    )
    rows = provenance.read_ledger()
    assert [r["id"] for r in rows] == ["good"]


def test_history_is_empty_before_anything_runs():
    assert provenance.read_ledger() == []
