"""Record what happened, and hand back a line that can be cited.

This is the part that separates pairwork from a wrapper round a CLI.

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

import json
import pathlib

from runner import STATE

LEDGER = STATE / "runs.jsonl"

#: Written to the ledger. Everything here is either measured or copied from the
#: pattern - none of it is supplied by the caller except the subject.
FIELDS = [
    "id", "pattern", "provider", "cli_version", "model", "effort",
    "effort_requested", "effort_downgraded", "sandbox", "repo_access",
    "experimental_adapter", "started_utc", "ended_utc", "duration_s",
    "subject", "withheld", "output_path",
]


def record(run):
    """Append one line to the ledger and return what was written."""
    entry = {field: run.get(field) for field in FIELDS}
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def citation(run):
    """The line to paste into the document the finding ends up in.

    Deliberately the shape already used in the DBHQ research folder, so an
    existing document and a pairwork-generated one read the same.
    """
    label = {
        "red-team": "Red team",
        "second-opinion": "Second opinion",
        "verify": "Verification pass",
        "collaborate": "Worked through with",
        "debate": "Debated with",
    }.get(run["pattern"], run["pattern"])

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

    detail = f"withheld: {run['withheld']}"
    if run.get("experimental_adapter"):
        detail += (
            f". Ran through pairwork's experimental {run['provider']} adapter, "
            f"which has not been verified against the real CLI"
        )
    if run["effort_downgraded"]:
        detail += (
            f". Ran at {run['effort']} effort, not the {run['effort_requested']} "
            f"this pattern asks for - {run['provider']} cannot reach it"
        )
    return f"{line}. Run `{run['id']}`, {detail}."


def read_ledger(limit=None):
    """Past runs, newest last. Returns [] if nothing has been run yet."""
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


def find(run_id):
    """One past run by id, with its output re-read from disk."""
    for row in read_ledger():
        if row.get("id") == run_id:
            path = pathlib.Path(row.get("output_path", ""))
            row["output"] = path.read_text(encoding="utf-8") if path.exists() else ""
            return row
    return None
