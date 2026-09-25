"""Background runs: `run --background`, `status` and `result`.

A run at high effort takes longer than most agent hosts let one command run, so
the run has to outlive the command that started it. These tests drive the real
CLI in a subprocess against a fake provider binary that waits until the test
lets it finish.
"""

import os
import pathlib
import signal
import subprocess
import sys
import time

import pytest

import groupwork
import provenance
import runner
from conftest import install_fake_cli

SCRIPT = pathlib.Path(runner.__file__).with_name("groupwork.py")

# A fake codex that says it has started, then waits for a release file before
# answering. So the test, not the clock, decides when the run finishes.
FAKE_CODEX_GATED = """#!/bin/bash
if [ "$1" = "--version" ]; then echo "codex-cli 0.0.0"; exit 0; fi
out=""
prev=""
for arg in "$@"; do
  if [ "$prev" = "-o" ]; then out="$arg"; fi
  prev="$arg"
done
cat > /dev/null
echo "$PPID" > "$GW_STARTED"
while [ ! -e "$GW_RELEASE" ]; do sleep 0.05; done
if [ -n "$GW_FAIL" ]; then echo "the model said no" >&2; exit 1; fi
printf '1. **minor** somewhere:1 - a slow finding\\n' > "$out"
"""


@pytest.fixture
def world(tmp_path, monkeypatch):
    """A fake codex on PATH, a private state directory, and the env to reach both."""
    install_fake_cli(tmp_path / "bin", "codex", FAKE_CODEX_GATED)
    home = tmp_path / "home"
    monkeypatch.setattr(runner, "STATE", home)
    monkeypatch.setattr(provenance, "LEDGER", home / "runs.jsonl")
    env = dict(
        os.environ,
        PATH=f"{tmp_path / 'bin'}:{os.environ['PATH']}",
        GROUPWORK_HOME=str(home),
        GW_STARTED=str(tmp_path / "started"),
        GW_RELEASE=str(tmp_path / "release"),
    )
    env.pop("GW_FAIL", None)
    yield tmp_path, env
    # Never leave a fake waiting, whatever the test did.
    (tmp_path / "release").touch()


def launch(tmp_path, env, *extra):
    started = time.monotonic()
    done = subprocess.run(
        [sys.executable, str(SCRIPT), "run", "second-opinion",
         "--subject", "a thing", "--no-prior-view", "--provider", "codex",
         "--timeout", "60", "--background", *extra],
        env=env, cwd=str(tmp_path), capture_output=True, text=True, timeout=30,
    )
    return done, time.monotonic() - started


def wait_for(path, seconds=15):
    deadline = time.monotonic() + seconds
    while not (path.exists() and path.read_text().strip()):
        assert time.monotonic() < deadline, f"{path.name} never appeared"
        time.sleep(0.05)
    return path.read_text().strip()


def wait_for_state(run_id, wanted, seconds=20):
    deadline = time.monotonic() + seconds
    while True:
        state = groupwork.background.state(run_id)[0]
        if state == wanted:
            return
        assert time.monotonic() < deadline, f"stuck at {state}, wanted {wanted}"
        time.sleep(0.05)


def test_background_returns_at_once_while_the_binary_is_still_running(world, capsys):
    tmp_path, env = world
    done, took = launch(tmp_path, env)
    assert done.returncode == 0, done.stderr
    run_id = done.stdout.strip()
    assert runner.valid_run_id(run_id), done.stdout
    # The fake cannot finish until the release file exists, and it does not
    # yet, so the command came back while the binary was still running.
    assert not (tmp_path / "release").exists()
    assert took < 1.0, f"run --background took {took:.1f}s, not under a second"

    wait_for(tmp_path / "started")
    assert groupwork.main(["status", run_id]) == 0
    assert "running" in capsys.readouterr().out
    assert groupwork.main(["result", run_id]) == 3
    assert "still running" in capsys.readouterr().err

    (tmp_path / "release").touch()
    wait_for_state(run_id, "done")
    assert groupwork.main(["status", run_id]) == 0
    assert "done" in capsys.readouterr().out
    assert groupwork.main(["result", run_id]) == 0
    out = capsys.readouterr().out
    assert "a slow finding" in out
    assert f"Run `{run_id}`" in out


def test_a_failed_background_run_says_so_and_why(world, capsys):
    tmp_path, env = world
    env["GW_FAIL"] = "1"
    done, _ = launch(tmp_path, env)
    run_id = done.stdout.strip()
    (tmp_path / "release").touch()
    wait_for_state(run_id, "failed")
    assert groupwork.main(["status", run_id]) == 0
    assert "exited 1" in capsys.readouterr().out
    assert groupwork.main(["result", run_id]) == 1
    assert "exited 1" in capsys.readouterr().err


def test_a_killed_background_run_reads_as_stopped_not_running(world, capsys):
    """The lock goes with the process, so a SIGKILL cannot leave it 'running'."""
    tmp_path, env = world
    done, _ = launch(tmp_path, env)
    run_id = done.stdout.strip()
    worker = int(wait_for(tmp_path / "started"))
    os.kill(worker, signal.SIGKILL)
    wait_for_state(run_id, "failed")
    groupwork.main(["status", run_id])
    assert "stopped before it finished" in capsys.readouterr().out


def test_a_refused_brief_is_refused_at_once_not_in_the_background(world):
    tmp_path, env = world
    done = subprocess.run(
        [sys.executable, str(SCRIPT), "run", "second-opinion",
         "--subject", "a thing", "--provider", "codex", "--background"],
        env=env, cwd=str(tmp_path), capture_output=True, text=True, timeout=30,
    )
    assert done.returncode == 2
    assert "--no-prior-view" in done.stderr
    assert not (runner.STATE / "runs").exists() or not list(
        (runner.STATE / "runs").glob("*.lock")
    )


def test_status_of_an_unknown_run_is_an_error(world, capsys):
    assert groupwork.main(["status", "20260101T000000Z-abcdef"]) == 1
    assert groupwork.main(["result", "20260101T000000Z-abcdef"]) == 1


def test_a_run_id_that_is_not_one_is_never_used_as_a_path(world, capsys):
    assert groupwork.main(["status", "../../etc/passwd"]) == 1
    with pytest.raises(runner.RunFailed, match="not a run id"):
        runner.run("verify", "a brief", provider_name="codex", run_id="../x")


def test_a_foreground_run_in_progress_reads_as_running(world, capsys):
    """It has a "started" line and nothing after, so only its lock says it is alive."""
    tmp_path, env = world
    proc = subprocess.Popen(
        [sys.executable, str(SCRIPT), "run", "second-opinion", "--subject", "a thing",
         "--no-prior-view", "--provider", "codex", "--timeout", "60"],
        env=env, cwd=str(tmp_path), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        wait_for(tmp_path / "started")
        (row,) = provenance.runs()
        assert row["status"] == "started"
        assert groupwork.main(["status", row["id"]]) == 0
        assert "running" in capsys.readouterr().out
        assert groupwork.main(["history"]) == 0
        assert "[running]" in capsys.readouterr().out
        (tmp_path / "release").touch()
        assert proc.wait(timeout=20) == 0
        assert groupwork.main(["status", row["id"]]) == 0
        assert "done" in capsys.readouterr().out
    finally:
        if proc.poll() is None:
            proc.kill()
