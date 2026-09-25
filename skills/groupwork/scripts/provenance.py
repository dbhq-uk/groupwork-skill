"""Record what happened, and hand back a line that can be cited.

This is the part that separates groupwork from a wrapper round a CLI.

The research in the DBHQ repository carries lines like "given the keyword data
but none of the GitHub or community evidence, so its conclusions are independent
of the retrieval". A reader's only reason to trust a finding like that is the
claim that the counterpart really was starved of the material. Every one of
those lines was written afterwards, from memory, by whoever ran it.

So the record is written by the process that ran the command, at the moment it
ran, and `withheld` is copied from the pattern definition rather than typed by
anybody. A red-team run cannot claim an independence it did not have, because
nobody is in a position to type the claim.
"""

import fcntl
import json
import pathlib

from runner import STATE, valid_run_id

LEDGER = STATE / "runs.jsonl"

#: Written to the ledger. Everything here is either measured or copied from the
#: pattern - none of it is supplied by the caller except the subject and the
#: `no_prior_view` declaration, and the citation labels that one as declared.
#:
#: New fields are only ever appended. Existing readers of runs.jsonl look fields
#: up by name, and older lines simply lack the newer ones.
FIELDS = [
    "id", "pattern", "provider", "cli_version", "model", "effort",
    "effort_requested", "effort_downgraded", "sandbox", "repo_access",
    "experimental_adapter", "started_utc", "ended_utc", "duration_s",
    "subject", "withheld", "output_path",
    "leak_check", "no_prior_view", "brief_path", "brief_sha256",
    "panel_id", "panel_round", "status", "error",
]

#: Fields only a panel member has. Every other run leaves them empty.
PANEL_FIELDS = {"panel_id", "panel_round"}

#: Fields that are empty on a run that finished cleanly.
OPTIONAL_FIELDS = PANEL_FIELDS | {"error"}

#: How a run ended. A run is written twice: "started" before the provider
#: starts, then one of the others. A line from before this field existed was
#: only ever written for a run that worked, so it reads as done. A run found in
#: runs/ with no line at all reads as "unrecorded".
STATUSES = ("started", "done", "failed", "timed-out", "stopped")


def record(run):
    """Append one line to the ledger and return what was written."""
    entry = {field: run.get(field) for field in FIELDS}
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as handle:
        # Panel members finish at the same time in separate processes. The
        # lock keeps two of their lines from interleaving.
        fcntl.flock(handle, fcntl.LOCK_EX)
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        handle.flush()
    return entry


def citation(run):
    """The line to paste into the document the finding ends up in.

    Deliberately the shape already used in the DBHQ research folder, so an
    existing document and a groupwork-generated one read the same.
    """
    label = {
        "red-team": "Red team",
        "second-opinion": "Second opinion",
        "verify": "Verification pass",
        "collaborate": "Worked through with",
        "panel": "Panel member",
        # Retired, but its runs are still in older ledgers and still cite.
        "debate": "Debated with",
    }.get(run["pattern"], run["pattern"])
    if run["pattern"] == "panel" and run.get("panel_round"):
        label = "Panel critique"

    date = run["started_utc"][:10]
    # Parenthesised, because a version string usually carries the tool's own
    # name - "codex-cli 0.154.0" - and "via codex codex-cli 0.154.0" reads badly.
    bits = [
        f"**{label}:** `{run['model']}` via {run['provider']} ({run['cli_version']})",
        date,
        run["sandbox"],
    ]
    if not run["repo_access"]:
        bits.append("no repository access")
    line = ", ".join(bits)
    if run.get("panel_id"):
        line += f", panel `{run['panel_id']}`"

    detail = f"withheld: {run['withheld']}"
    detail += f". {_leak_check_line(run)}"
    if run.get("brief_sha256"):
        detail += f". Brief sha256 `{run['brief_sha256']}`"
    if run.get("experimental_adapter"):
        detail += (
            f". Ran through groupwork's experimental {run['provider']} adapter, "
            f"which has not been verified against the real CLI"
        )
    if run["effort_downgraded"]:
        detail += (
            f". Ran at {run['effort']} effort, not the {run['effort_requested']} "
            f"this pattern asks for - {run['provider']} cannot reach it"
        )
    return f"{line}. Run `{run['id']}`, {detail}."


def _leak_check_line(run):
    """Say whether our view was checked for in the brief, and nothing more.

    A ledger line written before the check was recorded has no `leak_check`
    field. Saying "not recorded" for it is true; saying nothing would let an
    old citation read as though it had passed.
    """
    status = run.get("leak_check")
    if status == "passed":
        return "Leak check passed: the draft conclusion was not found in the brief"
    if status == "not-run" and run.get("no_prior_view"):
        return "Leak check not run: the caller declared no prior view"
    if status == "not-run":
        return "Leak check not run"
    return "Leak check not recorded"


def status(row):
    """How a run ended, as far as the ledger says. Old lines read as done."""
    return row.get("status") or "done"


def read_ledger(limit=None):
    """Every line of the ledger, oldest first. Returns [] if nothing has run.

    A run has more than one line. `runs()` gives one row per run.
    """
    if not LEDGER.exists():
        return []
    rows = []
    for line in LEDGER.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            # A half-written line from a killed process. Skip it rather than
            # refusing to show the rest of the history.
            continue
    return rows[-limit:] if limit else rows


def runs(limit=None):
    """One row per run, oldest first, each the latest of its lines.

    The ledger is append-only, so how a run ended is a later line with the
    same id. Later values win field by field, and a field that only an older
    line carries is kept.
    """
    merged = {}
    for row in read_ledger():
        run_id = row.get("id")
        if not run_id:
            continue
        merged.setdefault(run_id, {}).update(row)
    rows = list(merged.values())
    return rows[-limit:] if limit else rows


def find(run_id):
    """One past run by id, with its output re-read from disk.

    A run with no line in the ledger, from before failures were recorded, is
    rebuilt from what it left in runs/, so `show` can still say what there is.
    """
    row = next((r for r in runs() if r.get("id") == run_id), None)
    if row is None:
        row = _from_files(run_id)
        if row is None:
            return None
    path = pathlib.Path(row.get("output_path") or "")
    row["output"] = (
        path.read_text(encoding="utf-8") if path.is_file() else ""
    )
    return row


def _from_files(run_id):
    """A bare row for a run that is in runs/ but not in the ledger."""
    runs_dir = LEDGER.parent / "runs"
    if not valid_run_id(run_id) or not runs_dir.is_dir():
        return None
    files = {
        "brief_path": runs_dir / f"{run_id}.brief.md",
        "output_path": runs_dir / f"{run_id}.md",
        "log_path": runs_dir / f"{run_id}.log",
    }
    if not any(path.exists() for path in files.values()):
        return None
    row = {"id": run_id, "status": "unrecorded"}
    for key, path in files.items():
        if path.exists():
            row[key] = str(path)
    return row
