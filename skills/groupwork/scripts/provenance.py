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

import json
import pathlib

from runner import STATE

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
    existing document and a groupwork-generated one read the same.
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
