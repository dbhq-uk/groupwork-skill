"""Run a brief through a provider, and be honest about what happened.

Every rule below is a failure someone has actually had, not a precaution.

  - The brief goes in from a file on stdin. Long text and shell quoting do not
    mix, and two of the three providers exceed ARG_MAX on a real diff.
  - Empty output is a failure. Codex writes its result only at completion, so a
    killed run leaves a zero-byte file and no error; Copilot has a bug where it
    exits 0 having written nothing. Both look like "the reviewer found no
    issues" unless something refuses to read them that way.
  - The effort actually used is recorded, not the effort asked for. A provider
    that cannot reach `high` runs at its ceiling and the record says so.
  - Nothing is retried automatically. A failed adversarial run costs money and
    a retry that silently changes the conditions makes the record meaningless.
"""

import hashlib
import os
import pathlib
import re
import tempfile
import time
import uuid

import patterns
import providers

STATE = pathlib.Path(os.environ.get("GROUPWORK_HOME", pathlib.Path.home() / ".dbhq" / "groupwork"))

#: This skill was called `pairwork` for its first hours in public, on
#: 17 Sep 2026. Anyone who installed it in that window has run records under the
#: old name, and a rename that silently orphans them would lose exactly the
#: thing the skill exists to keep.
_OLD_STATE = pathlib.Path.home() / ".dbhq" / "pairwork"


def _migrate_from_pairwork():
    """Move ~/.dbhq/pairwork/ to ~/.dbhq/groupwork/ once, on first run.

    Guarded on the new directory not existing, so it is a no-op for every
    install after the first and for every install that never saw the old name.

    The ledger stores absolute output paths, so they are rewritten as part of
    the move - otherwise `groupwork show <id>` would fail on every run made
    before the rename, which is the same as having lost them.
    """
    if STATE.exists() or not _OLD_STATE.exists():
        return
    try:
        STATE.parent.mkdir(parents=True, exist_ok=True)
        _OLD_STATE.rename(STATE)
    except OSError:
        return  # Not worth failing a run over; the new directory is made below.
    ledger = STATE / "runs.jsonl"
    if not ledger.exists():
        return
    try:
        ledger.write_text(
            ledger.read_text(encoding="utf-8").replace(
                str(_OLD_STATE), str(STATE)
            ),
            encoding="utf-8",
        )
    except OSError:
        pass


_migrate_from_pairwork()


class RunFailed(RuntimeError):
    """The run did not produce a usable answer, and the reason is in the message."""


#: What a run id looks like: the UTC start time and six hex digits. Anything
#: else is refused before it is used in a path under runs/.
RUN_ID = re.compile(r"^[0-9]{8}T[0-9]{6}Z-[0-9a-f]{6}$")


def new_run_id():
    return f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:6]}"


def valid_run_id(run_id):
    return bool(RUN_ID.match(run_id or ""))


def _state_dir():
    runs = STATE / "runs"
    runs.mkdir(parents=True, exist_ok=True)
    # 700 like every other ~/.dbhq/<skill>/, and the same on runs/ rather than
    # whatever umask gives. There are no credentials here - every provider
    # authenticates itself - but a brief can quote an unreleased document and
    # the output quotes it straight back.
    for path in (STATE, runs):
        try:
            path.chmod(0o700)
        except OSError:
            pass
    return runs


def _isolated_cwd():
    """A directory with nothing in it, for a pattern that withholds the repo.

    red-team runs here by default. Pointing the counterpart at an empty
    directory is what makes "its conclusions are independent of our retrieval"
    a statement of fact rather than a hope.
    """
    return tempfile.mkdtemp(prefix="groupwork-norepo-")


def run(pattern_name, brief_text, *, provider_name=None, cwd=None,
        repo_access=None, model=None, effort=None, allow_write=False,
        subject="", timeout=None, run_id=None):
    """Run one brief. Returns a record dict; raises RunFailed on anything else.

    `run_id` is given by a background launch, which has to print the id before
    the run starts. Otherwise a new one is made here.
    """
    if run_id is not None and not valid_run_id(run_id):
        raise RunFailed(f"'{run_id}' is not a run id")
    spec = patterns.get(pattern_name)
    provider = providers.get(provider_name)
    caps = provider.capabilities()

    version = provider.probe()  # raises ProviderError with the reason

    sandbox = spec["sandbox"]
    if allow_write:
        # Hard rule 4. Getting here requires the caller to have asked the user
        # in this run - the flag is not sticky and is not read from config.
        if "workspace-write" not in caps["sandboxes"]:
            raise RunFailed(
                f"{provider.name} does not offer a write sandbox"
            )
        sandbox = "workspace-write"
    elif sandbox not in caps["sandboxes"]:
        raise RunFailed(
            f"{provider.name} cannot run {sandbox}; it offers "
            f"{', '.join(caps['sandboxes'])}"
        )

    wanted_effort = effort or spec["effort"]
    used_effort, downgraded = patterns.resolve_effort(wanted_effort, caps["efforts"])
    used_model = model or _pick_model(spec["model"], caps["models"])

    if repo_access is None:
        repo_access = spec["repo_access"]
    workdir = cwd or os.getcwd()
    if not repo_access:
        workdir = _isolated_cwd()

    timeout = timeout or patterns.TIMEOUTS.get(used_effort, patterns.TIMEOUTS["high"])

    run_id = run_id or new_run_id()
    runs = _state_dir()
    out_path = runs / f"{run_id}.md"
    log_path = runs / f"{run_id}.log"

    # The brief is kept beside the output, not deleted after the run. It is the
    # only evidence of what the counterpart was actually told, and its hash goes
    # into the citation so the stored copy can be checked against it later.
    brief_path = runs / f"{run_id}.brief.md"
    if brief_path.exists() or out_path.exists():
        raise RunFailed(f"run {run_id} already exists; a run id is used once")
    brief_bytes = str(brief_text).encode("utf-8")
    brief_path.write_bytes(brief_bytes)
    brief_sha256 = hashlib.sha256(brief_bytes).hexdigest()

    started = time.time()
    try:
        provider.run(
            str(brief_path), str(out_path), used_model, used_effort, sandbox,
            workdir, repo_access=repo_access, log_path=str(log_path),
            timeout=timeout,
        )
    except providers.ProviderError as exc:
        raise RunFailed(str(exc)) from None
    finally:
        ended = time.time()

    text = out_path.read_text(encoding="utf-8") if out_path.exists() else ""
    if not text.strip():
        raise RunFailed(
            f"{provider.name} returned nothing. This is a failed run, not a "
            f"clean review - do not report it as 'no issues found'. The log is "
            f"at {log_path}."
        )

    return {
        "id": run_id,
        "pattern": pattern_name,
        "provider": provider.name,
        "cli_version": version,
        "model": used_model,
        "effort": used_effort,
        "effort_requested": wanted_effort,
        "effort_downgraded": downgraded,
        "sandbox": sandbox,
        "repo_access": bool(repo_access),
        "experimental_adapter": bool(caps.get("experimental")),
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started)),
        "ended_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ended)),
        "duration_s": round(ended - started, 1),
        "subject": subject or "(unstated)",
        "withheld": patterns.withheld(pattern_name, repo_access),
        # Set by brief.build(), which is the only thing that ran the check. A
        # brief that did not come from there is a plain string and reads as
        # not-run, which is the truth about it.
        "leak_check": getattr(brief_text, "leak_check", "not-run"),
        "no_prior_view": bool(getattr(brief_text, "no_prior_view", False)),
        "brief_path": str(brief_path),
        "brief_sha256": brief_sha256,
        "output_path": str(out_path),
        "output": text,
    }


def _pick_model(wanted, supported):
    """Use the pattern's model if the provider has it, else the provider's first.

    No cleverness here on purpose. A provider that does not carry `gpt-6-astra`
    is not going to have a near-equivalent that groupwork can identify reliably,
    and guessing one would put a model name in the record that nobody chose.
    """
    if not supported or wanted in supported:
        return wanted
    for name in supported:
        if name.endswith("/" + wanted) or name == wanted:
            return name
    return supported[0]
