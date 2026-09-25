"""A panel: several answers to one hard question, each reached alone.

This replaced `debate`. That was one model: one proposal, then the same model
attacking its own previous answer each round, while its template told it two
parties had answered independently. The research on that shape is unkind.
Majority voting explains most of what multi-agent debate gains (arXiv
2508.17536), different model families are what help (arXiv 2502.08788), and
same-model debate loses to isolated self-correction (arXiv 2605.00914).

So a panel is at least two members answering the same brief alone and in
parallel, one per ready provider where more than one is ready. Every answer is
kept. The host reconciles them: where they agree, and where they differ. An
optional single critique round gives each member, in a fresh session, every
first answer, unlabelled and in no particular order.

Each member is an ordinary background run (`run panel ... --run-id`), so it is
recorded and cited like any other. The panel itself is one small file saying
which runs belong to it, `runs/<panel-id>.panel.json`, and its id has the same
shape as a run id, so `status` and `result` take either.
"""

import contextlib
import hashlib
import json
import os
import signal
import time

import background
import provenance
import providers
import runner
from providers import base

#: How often the panel looks at its members. Runs take minutes.
POLL_S = 1.0

#: Fewer than two answers is not a panel, it is a run.
MIN_MEMBERS = 2


class PanelFailed(RuntimeError):
    """The panel could not produce two answers to compare, and says why."""


# --- Members -----------------------------------------------------------------

def parse_members(spec):
    """'codex,opencode:google/gemini-3-pro' to a list of provider and model."""
    members = []
    for item in spec.split(","):
        item = item.strip()
        if not item:
            continue
        name, _, model = item.partition(":")
        if name not in providers.REGISTRY:
            raise ValueError(
                f"unknown provider '{name}' in --members. Available: "
                f"{', '.join(sorted(providers.REGISTRY))}"
            )
        members.append({"provider": name, "model": model or None})
    if len(members) < MIN_MEMBERS:
        raise ValueError(
            f"a panel needs at least {MIN_MEMBERS} members, and --members "
            f"named {len(members)}"
        )
    return members


def default_members():
    """One member per ready provider, or two on the only one that is ready.

    Two answers from the same model are still two answers reached alone, and
    comparing them is most of the gain. The result says when every answer came
    from one model family, because agreement then is weaker evidence.
    """
    working, broken = providers.available()
    names = [name for name in providers.REGISTRY if name in working]
    if not names:
        reasons = "; ".join(broken.values()) or "no provider is registered"
        raise PanelFailed(f"nothing is ready to answer: {reasons}")
    if len(names) == 1:
        names = names * MIN_MEMBERS
    return [{"provider": name, "model": None} for name in names]


def member_argv(args, member, panel_id, critique):
    """The `run panel` command line for one member.

    Every value goes as `--flag=value`, so a value that starts with a hyphen
    is never read as a flag.
    """
    argv = ["run", "panel", f"--subject={args.subject}"]
    for flag, value in (
        ("--context", args.context),
        ("--question", args.question),
        ("--constraints", args.constraints),
        ("--assert-withholds", args.assert_withholds),
        ("--effort", args.effort),
        ("--cwd", args.cwd),
        ("--timeout", args.timeout),
    ):
        if value:
            argv.append(f"{flag}={value}")
    if args.no_prior_view:
        argv.append("--no-prior-view")
    argv.append(f"--provider={member['provider']}")
    if member["model"]:
        argv.append(f"--model={member['model']}")
    argv.append(f"--panel-id={panel_id}")
    if critique:
        argv.append("--panel-critique")
    return argv


# --- The panel file ----------------------------------------------------------

def _path(panel_id):
    return runner.STATE / "runs" / f"{panel_id}.panel.json"


def is_panel(run_id):
    return runner.valid_run_id(run_id) and _path(run_id).exists()


def load(panel_id):
    return json.loads(_path(panel_id).read_text(encoding="utf-8"))


def _save(record):
    path = _path(record["id"])
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(record, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    os.replace(tmp, path)


# --- Answers -----------------------------------------------------------------

def ordered(rows):
    """Answers in an order that says nothing about who wrote them.

    Sorted by a hash of the text, so the order is the same every time it is
    asked for - the critique brief and the result label the same answer A -
    and has nothing to do with which provider was listed first.
    """
    return sorted(
        rows, key=lambda row: hashlib.sha256(row["output"].encode("utf-8")).hexdigest()
    )


def _rows(run_ids):
    return [row for row in (provenance.find(run_id) for run_id in run_ids) if row]


def first_answers(panel_id):
    """The first answers of a panel, in the order the critique shows them."""
    record = load(panel_id)
    rounds = record.get("rounds") or [[]]
    return [row["output"] for row in ordered(_rows(rounds[0]))]


def _family(row):
    """The model family an answer came from, as far as the record says."""
    if row.get("provider") == "codex":
        return "openai"
    model = row.get("model") or ""
    return model.split("/", 1)[0] if "/" in model else row.get("provider", "")


# --- Running it --------------------------------------------------------------

def coordinate(args, script, panel_id):
    """Run the panel to the end. Raises PanelFailed if it cannot."""
    record = {
        "id": panel_id,
        "subject": args.subject,
        "started_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "critique": bool(args.critique),
        "members": [],
        "rounds": [],
        "outcome": None,
    }
    _save(record)
    try:
        record["members"] = (
            parse_members(args.members) if args.members else default_members()
        )
        _save(record)
        first = _round(args, script, record, record["members"], critique=False)
        answered = [
            (member, run_id) for member, run_id in zip(record["members"], first)
            if provenance.find(run_id)
        ]
        if len(answered) < MIN_MEMBERS:
            raise PanelFailed(
                f"only {len(answered)} of {len(first)} members answered, and a "
                f"panel needs {MIN_MEMBERS} to compare. `status {panel_id}` "
                f"lists them."
            )
        if args.critique:
            _round(args, script, record, [m for m, _ in answered], critique=True)
    except (PanelFailed, ValueError) as exc:
        record["outcome"] = "failed"
        record["reason"] = str(exc)
        _save(record)
        raise PanelFailed(str(exc)) from None
    record["outcome"] = "done"
    _save(record)


def _round(args, script, record, members, critique):
    """Start one member per entry, all at once, and wait for every one."""
    run_ids = [runner.new_run_id() for _ in members]
    record["rounds"].append(run_ids)
    _save(record)
    started = []
    try:
        with base._stop_group_on_signal():
            for member, run_id in zip(members, run_ids):
                started.append(background.launch(
                    script, member_argv(args, member, record["id"], critique), run_id
                ))
            while any(background.running(run_id) for run_id in run_ids):
                time.sleep(POLL_S)
    except BaseException:
        # Stopping the panel stops its members, the same as stopping a run
        # stops the CLI it started. Each member passes the SIGTERM on to its
        # own provider process group.
        for proc in started:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.killpg(proc.pid, signal.SIGTERM)
        raise
    return run_ids


# --- Reading it --------------------------------------------------------------

def state(panel_id):
    """(state, detail) for a panel, in the shape background.state() uses."""
    record = load(panel_id)
    lines = []
    for index, run_ids in enumerate(record.get("rounds") or []):
        stage = "critique" if index else "first answers"
        for member, run_id in zip(_members_for(record, index), run_ids):
            member_state = background.state(run_id)[0]
            model = f" {member['model']}" if member.get("model") else ""
            lines.append(f"{run_id}  {member['provider']}{model}, {stage}: {member_state}")
    outcome = record.get("outcome")
    if outcome == "done":
        head = "finished; `result` prints every answer and the citations"
        return "done", "\n".join([head, *lines]), record
    if outcome == "failed":
        return "failed", "\n".join([record.get("reason", "failed"), *lines]), record
    if background.running(panel_id):
        size = len(record.get("members") or [])
        head = f"panel of {size}" if size else "choosing members"
        return "running", "\n".join([head, *lines]), record
    return "failed", "\n".join([
        "the panel stopped before it finished. Any member that answered is "
        "listed below, and `show <id>` prints it.", *lines
    ]), record


def _members_for(record, round_index):
    """The members that took part in a round, in launch order."""
    members = record.get("members") or []
    if round_index == 0:
        return members
    first = (record.get("rounds") or [[]])[0]
    return [m for m, run_id in zip(members, first) if provenance.find(run_id)]


def render(panel_id):
    """Every answer and critique, then the citations, then what to do with them."""
    record = load(panel_id)
    rounds = record.get("rounds") or []
    answers = ordered(_rows(rounds[0])) if rounds else []
    critiques = _rows(rounds[1]) if len(rounds) > 1 else []

    out = [f"# Panel `{panel_id}`: {record.get('subject', '')}", ""]
    for index, row in enumerate(answers):
        out += [f"## Answer {chr(ord('A') + index)}", "", row["output"].strip(), ""]
    for index, row in enumerate(critiques, start=1):
        out += [f"## Critique {index}", "", row["output"].strip(), ""]

    out += ["---", ""]
    for index, row in enumerate(answers):
        out += [f"Answer {chr(ord('A') + index)}: {provenance.citation(row)}", ""]
    for index, row in enumerate(critiques, start=1):
        out += [f"Critique {index}: {provenance.citation(row)}", ""]

    families = {_family(row) for row in answers}
    if len(families) == 1:
        out += [
            f"Every answer came from one model family ({families.pop()}). They "
            f"were still reached alone, but agreement between them is weaker "
            f"evidence than agreement across families.",
            "",
        ]
    out.append(
        "Reconcile them now: what every answer agrees on, which can be relied "
        "on; where they differ, which is the real trade-off and the user's to "
        "settle; and what only one of them raised, which needs checking before "
        "it is believed."
    )
    return "\n".join(out)
