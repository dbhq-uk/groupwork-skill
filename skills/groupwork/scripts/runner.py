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
  - Every run is in the ledger, not only the ones that worked: a "started"
    line before the provider starts, then one saying done, failed, timed out
    or stopped.
"""

import hashlib
import json
import os
import pathlib
import re
import tempfile
import time
import uuid

import patterns
import providers
from providers.base import RunTimedOut

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
        subject="", timeout=None, run_id=None, panel_id=None):
    """Run one brief. Returns a record dict; raises RunFailed on anything else.

    `run_id` is given by a background launch, which has to print the id before
    the run starts. Otherwise a new one is made here. `panel_id` names the
    panel a member run belongs to, so its answers can be found together.
    """
    if run_id is not None and not valid_run_id(run_id):
        raise RunFailed(f"'{run_id}' is not a run id")
    spec = patterns.get(pattern_name)
    provider = providers.get(provider_name)
    version = provider.probe()  # raises ProviderError with the reason
    # After probe(), because what a provider can reach may depend on what it
    # is signed in to, and probe() is what finds that out.
    caps = provider.capabilities()

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
    used_model = model or model_override(provider.name) or _pick_model(
        provider.name, spec["model"], caps["models"], caps.get("default_model")
    )
    # Refused here, before the ledger line, so a run that could never have
    # started does not turn up in `history` as one that failed.
    blocked = caps.get("unreachable", {}).get(used_model)
    if blocked:
        raise RunFailed(blocked)

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

    critique = bool(getattr(brief_text, "answers_shown", 0))
    started = time.time()
    record = {
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
        "started_utc": _utc(started),
        "ended_utc": None,
        "duration_s": None,
        "subject": subject or "(unstated)",
        "withheld": patterns.withheld(pattern_name, repo_access, critique=critique),
        # Set by brief.build(), which is the only thing that ran the check. A
        # brief that did not come from there is a plain string and reads as
        # not-run, which is the truth about it.
        "leak_check": getattr(brief_text, "leak_check", "not-run"),
        "no_prior_view": bool(getattr(brief_text, "no_prior_view", False)),
        "brief_path": str(brief_path),
        "brief_sha256": brief_sha256,
        "output_path": str(out_path),
        "panel_id": panel_id,
        # 1 when the brief carried a panel's first answers. Read off the brief,
        # which only brief.build() can mark, not passed in by the caller.
        "panel_round": (1 if critique else 0) if panel_id else None,
        "status": "started",
        "error": None,
    }

    # A line before the provider starts and another when it ends, whatever the
    # end. A run that fails, times out or is stopped used to leave a log in
    # runs/ and nothing in the ledger, so `history` never showed it. If this
    # process is killed outright, the "started" line is what is left.
    import provenance  # here, not at the top: provenance reads STATE from here
    provenance.record(record)
    try:
        provider.run(
            str(brief_path), str(out_path), used_model, used_effort, sandbox,
            workdir, repo_access=repo_access, log_path=str(log_path),
            timeout=timeout,
        )
    except RunTimedOut as exc:
        _finish(provenance, record, started, "timed-out", str(exc))
        raise RunFailed(str(exc)) from None
    except providers.ProviderError as exc:
        # Named, because a model the account cannot use fails like any other
        # error, and "exited 1" alone sends the user to the wrong place.
        reason = f"{exc} The run asked for {used_model} at {used_effort} effort."
        _finish(provenance, record, started, "failed", reason)
        raise RunFailed(reason) from None
    except BaseException:
        _finish(provenance, record, started, "stopped",
                "groupwork was stopped while the run was in flight")
        raise

    text = out_path.read_text(encoding="utf-8") if out_path.exists() else ""
    if not text.strip():
        reason = (
            f"{provider.name} returned nothing. This is a failed run, not a "
            f"clean review - do not report it as 'no issues found'. The log is "
            f"at {log_path}."
        )
        _finish(provenance, record, started, "failed", reason)
        raise RunFailed(reason)

    _finish(provenance, record, started, "done")
    record["output"] = text
    return record


def _utc(seconds):
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(seconds))


def _finish(provenance, record, started, status, error=None):
    """Write the line that says how the run ended."""
    ended = time.time()
    record.update(
        ended_utc=_utc(ended),
        duration_s=round(ended - started, 1),
        status=status,
        error=error,
    )
    provenance.record(record)


def model_override(provider):
    """The model the user has chosen for this provider, or None.

    `GROUPWORK_<PROVIDER>_MODEL` in the environment, else `model.<provider>` in
    config.json in the state directory. `--model` beats both. Per provider,
    because a model name only means something to the CLI it is written for.

    A config file that cannot be read refuses the run. Ignoring it would run
    the pattern's model, which is very likely the one the user set this to get
    away from.
    """
    value = os.environ.get(f"GROUPWORK_{provider.upper()}_MODEL", "").strip()
    if value:
        return value
    path = STATE / "config.json"
    try:
        config = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as exc:
        raise RunFailed(f"{path} could not be read, so no run was started: {exc}") from None
    models = config.get("model") if isinstance(config, dict) else None
    value = models.get(provider) if isinstance(models, dict) else None
    return value.strip() if isinstance(value, str) and value.strip() else None


def _pick_model(provider, wanted, supported, default=None):
    """Use the pattern's model if the provider has it, else the provider's default.

    No cleverness here on purpose. A provider that does not carry `gpt-6-astra`
    is not going to have a near-equivalent that groupwork can identify reliably,
    and guessing one would put a model name in the record that nobody chose. The
    provider's own default was chosen by the user, in its configuration. Without
    one the run is refused and the user names a model.
    """
    if wanted in supported:
        return wanted
    for name in supported:
        if name.endswith("/" + wanted):
            return name
    if default:
        return default
    raise RunFailed(
        f"{provider} cannot reach {wanted} here and has no default model "
        f"configured. Pass --model with a model it can reach."
    )
