"""panel: several blind answers in parallel, then an optional critique round.

It replaced debate, which was one model attacking its own previous answer
while its template claimed two independent parties. These tests drive the real
CLI, whose members are real background processes, against fake codex and
opencode binaries on PATH. Nothing is installed, authenticated or paid for.
"""

import json
import os
import pathlib
import subprocess
import sys
import time

import pytest

import groupwork
import panel
import provenance
import runner
from conftest import install_fake_cli

SCRIPT = pathlib.Path(runner.__file__).with_name("groupwork.py")

DRAFT_VIEW = (
    "We should ship the thing because the incumbent is weak and the market "
    "is clearly wide open for a tool like ours."
)

# A fake provider that says it has started, then waits for a release file. Its
# first answer uses words groupwork's trigger guard knows, to prove a critique
# round is never refused because of what a model said. A brief with answers in
# it gets a critique back instead. Codex writes to -o, opencode to stdout.
FAKE = """#!/bin/bash
if [ "$1" = "--version" ]; then echo "__NAME__ 1.0"; exit 0; fi
out=""
prev=""
for arg in "$@"; do
  if [ "$prev" = "-o" ]; then out="$arg"; fi
  prev="$arg"
done
brief=$(cat)
touch "$GW_DIR/started-__NAME__-$$"
while [ ! -e "$GW_DIR/release" ]; do sleep 0.05; done
if [ -n "$GW_FAIL_ONE" ] && [ "__NAME__" = "opencode" ]; then exit 1; fi
if printf '%s' "$brief" | grep -q '### Answer A'; then
  answer="__NAME__ critique: both answers rest on the load estimate"
else
  answer="__NAME__ says: my counterpart would pick cron, a second opinion agrees"
fi
if [ -n "$out" ]; then printf '%s\\n' "$answer" > "$out"; else printf '%s\\n' "$answer"; fi
"""


@pytest.fixture
def world(tmp_path, monkeypatch):
    for name in ("codex", "opencode"):
        install_fake_cli(tmp_path / "bin", name, FAKE.replace("__NAME__", name))
    home = tmp_path / "home"
    monkeypatch.setattr(runner, "STATE", home)
    monkeypatch.setattr(provenance, "LEDGER", home / "runs.jsonl")
    monkeypatch.setattr(panel, "POLL_S", 0.05)
    # Members are separate processes, so they find everything through the env.
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}:{os.environ['PATH']}")
    monkeypatch.setenv("GROUPWORK_HOME", str(home))
    monkeypatch.setenv("GW_DIR", str(tmp_path))
    monkeypatch.delenv("GW_FAIL_ONE", raising=False)
    monkeypatch.chdir(tmp_path)
    yield tmp_path
    (tmp_path / "release").touch()


def started(tmp_path):
    return sorted(p.name.split("-")[1] for p in tmp_path.glob("started-*"))


def wait_until(check, seconds=20):
    deadline = time.monotonic() + seconds
    while not check():
        assert time.monotonic() < deadline, "timed out waiting"
        time.sleep(0.05)


def launch_panel(tmp_path, *extra):
    done = subprocess.run(
        [sys.executable, str(SCRIPT), "panel", "--subject", "queue or cron",
         "--no-prior-view", "--timeout", "60", "--background", *extra],
        cwd=str(tmp_path), capture_output=True, text=True, timeout=30,
    )
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def test_the_members_answer_in_parallel_and_every_answer_is_kept(world, capsys):
    panel_id = launch_panel(world)
    # Both members are running at once, before either may finish.
    wait_until(lambda: started(world) == ["codex", "opencode"])
    assert groupwork.main(["status", panel_id]) == 0
    assert "running" in capsys.readouterr().out

    (world / "release").touch()
    wait_until(lambda: panel.state(panel_id)[0] == "done")

    record = json.loads((runner.STATE / "runs" / f"{panel_id}.panel.json").read_text())
    assert len(record["rounds"]) == 1
    rows = [provenance.find(run_id) for run_id in record["rounds"][0]]
    assert sorted(row["provider"] for row in rows) == ["codex", "opencode"]
    for row in rows:
        assert row["pattern"] == "panel"
        assert row["panel_id"] == panel_id
        assert pathlib.Path(row["output_path"]).read_text().strip()
        assert "each answered alone" in row["withheld"]

    assert groupwork.main(["result", panel_id]) == 0
    out = capsys.readouterr().out
    assert "## Answer A" in out and "## Answer B" in out
    assert "codex says" in out and "opencode says" in out
    assert out.count("**Panel member:**") == 2
    assert "Reconcile them now" in out


def test_a_critique_round_is_not_refused_for_words_in_the_first_answers(world, capsys):
    """Every first answer says "counterpart" and "second opinion"."""
    (world / "release").touch()
    code = groupwork.main(["panel", "--subject", "queue or cron", "--no-prior-view",
                           "--timeout", "60", "--critique"])
    assert code == 0, capsys.readouterr().err
    out = capsys.readouterr().out
    assert out.count("critique: both answers rest on") == 2
    assert out.count("**Panel critique:**") == 2

    panel_id = sorted((runner.STATE / "runs").glob("*.panel.json"))[0].stem.split(".")[0]
    record = panel.load(panel_id)
    first, second = record["rounds"]
    for run_id in second:
        row = provenance.find(run_id)
        assert row["panel_round"] == 1
        assert "which member wrote which answer" in row["withheld"]
        shown = pathlib.Path(row["brief_path"]).read_text()
        # Every first answer, unlabelled: no provider name, no run id.
        assert "my counterpart would pick cron" in shown
        for first_id in first:
            assert first_id not in shown
        assert "### Answer A" in shown and "### Answer B" in shown


def test_the_critique_and_the_result_label_the_same_answer_a(world):
    (world / "release").touch()
    assert groupwork.main(["panel", "--subject", "queue or cron",
                           "--no-prior-view", "--critique"]) == 0
    panel_id = next((runner.STATE / "runs").glob("*.panel.json")).name.split(".")[0]
    answers = panel.first_answers(panel_id)
    shown = pathlib.Path(provenance.find(panel.load(panel_id)["rounds"][1][0])
                         ["brief_path"]).read_text()
    assert shown.index(answers[0].strip()) < shown.index(answers[1].strip())
    rendered = panel.render(panel_id)
    assert rendered.index(answers[0].strip()) < rendered.index(answers[1].strip())


def test_the_panel_takes_assert_withholds_and_refuses_a_leak(world, capsys):
    code = groupwork.main(["panel", "--subject", "queue or cron",
                           "--context", f"Background. {DRAFT_VIEW}",
                           "--assert-withholds", DRAFT_VIEW])
    assert code == 2
    assert "not independent" in capsys.readouterr().err
    assert started(world) == [], "a member started despite the leak"


def test_a_checked_panel_records_that_the_leak_check_passed(world):
    (world / "release").touch()
    assert groupwork.main(["panel", "--subject", "queue or cron",
                           "--assert-withholds", DRAFT_VIEW]) == 0
    panel_id = next((runner.STATE / "runs").glob("*.panel.json")).name.split(".")[0]
    for run_id in panel.load(panel_id)["rounds"][0]:
        assert provenance.find(run_id)["leak_check"] == "passed"


# An opencode that is on PATH but not ready. It shadows any real opencode on
# the machine, so no test can ever reach one.
BROKEN = """#!/bin/bash
echo "not signed in" >&2
exit 1
"""


def test_one_ready_provider_still_gives_two_answers_and_says_they_share_a_family(
        world, capsys):
    install_fake_cli(world / "bin", "opencode", BROKEN)
    (world / "release").touch()
    assert groupwork.main(["panel", "--subject", "queue or cron",
                           "--no-prior-view"]) == 0
    out = capsys.readouterr().out
    assert out.count("via codex") == 2
    assert "one model family (openai)" in out


def test_a_panel_of_one_is_refused(world, capsys):
    assert groupwork.main(["panel", "--subject", "queue or cron",
                           "--no-prior-view", "--members", "codex"]) == 2
    assert "at least 2 members" in capsys.readouterr().err


def test_named_members_are_used(world, capsys):
    (world / "release").touch()
    assert groupwork.main(["panel", "--subject", "queue or cron", "--no-prior-view",
                           "--members", "codex:gpt-5.6-sol,opencode:google/gemini-3-pro"]) == 0
    out = capsys.readouterr().out
    assert "`gpt-5.6-sol` via codex" in out
    assert "`google/gemini-3-pro` via opencode" in out
    assert "one model family" not in out


def test_fewer_than_two_answers_is_a_failed_panel(world, monkeypatch, capsys):
    monkeypatch.setenv("GW_FAIL_ONE", "1")
    (world / "release").touch()
    assert groupwork.main(["panel", "--subject", "queue or cron",
                           "--no-prior-view"]) == 1
    assert "only 1 of 2 members answered" in capsys.readouterr().err
    panel_id = next((runner.STATE / "runs").glob("*.panel.json")).name.split(".")[0]
    assert panel.state(panel_id)[0] == "failed"


def test_one_run_on_its_own_is_not_a_panel(world, capsys):
    assert groupwork.main(["run", "panel", "--subject", "queue or cron",
                           "--no-prior-view"]) == 2
    assert "groupwork.py panel" in capsys.readouterr().err


def test_an_old_debate_line_still_shows_and_cites(world, capsys):
    """debate is gone, but runs made with it are still in people's ledgers."""
    out_path = runner.STATE / "runs" / "20260920T100000Z-abc123.md"
    out_path.parent.mkdir(parents=True)
    out_path.write_text("an old debate answer", encoding="utf-8")
    old = {
        "id": "20260920T100000Z-abc123", "pattern": "debate", "provider": "codex",
        "cli_version": "codex-cli 0.150.0", "model": "gpt-6-astra",
        "effort": "high", "effort_requested": "high", "effort_downgraded": False,
        "sandbox": "read-only", "repo_access": True,
        "experimental_adapter": False, "started_utc": "2026-09-20T10:00:00Z",
        "ended_utc": "2026-09-20T10:10:00Z", "duration_s": 600.0,
        "subject": "queue or cron (round 0)", "withheld": "each other, in round 0",
        "output_path": str(out_path),
    }
    provenance.LEDGER.write_text(json.dumps(old) + "\n", encoding="utf-8")
    assert groupwork.main(["history"]) == 0
    assert "debate" in capsys.readouterr().out
    assert groupwork.main(["show", old["id"]]) == 0
    out = capsys.readouterr().out
    assert "an old debate answer" in out
    assert "**Debated with:**" in out
