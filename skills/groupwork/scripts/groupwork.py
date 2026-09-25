#!/usr/bin/env python3
"""groupwork - put a second agent on the work, as an adversary or as a partner.

    groupwork.py providers
    groupwork.py patterns
    groupwork.py run <pattern> --subject ... [--context ...] [--background]
    groupwork.py status <run-id>
    groupwork.py result <run-id>
    groupwork.py panel --subject ... [--members codex,opencode] [--critique]
    groupwork.py history [--limit 10]
    groupwork.py show <run-id>

Standard library only. Every provider authenticates itself, so there is nothing
to configure and no credential to store.
"""

import argparse
import contextlib
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import background  # noqa: E402
import brief  # noqa: E402
import panel  # noqa: E402
import patterns  # noqa: E402
import provenance  # noqa: E402
import providers  # noqa: E402
import runner  # noqa: E402


def cmd_providers(args):
    working, broken = providers.available()
    if working:
        print("Ready:")
        for name, version in sorted(working.items()):
            tags = []
            if name == providers.DEFAULT:
                tags.append("default")
            if providers.get(name).experimental:
                tags.append("experimental - adapter never run against the real CLI")
            suffix = f"  ({'; '.join(tags)})" if tags else ""
            print(f"  {name:<10} {version}{suffix}")
    if broken:
        print("\nNot ready:")
        for name, reason in sorted(broken.items()):
            print(f"  {name:<10} {reason}")
    if not working:
        print("\nNothing is ready, so nothing can be run. Install and "
              "authenticate at least one of the above.")
        return 1
    return 0


def cmd_patterns(args):
    for name, spec in patterns.PATTERNS.items():
        repo = "no repo access" if not spec["repo_access"] else "repo read-only"
        print(f"{name}")
        print(f"  {spec['purpose']}")
        print(f"  {spec['model']} at {spec['effort']}, {repo}")
        print(f"  withholds {spec['withholds']}")
        print()
    return 0


def _fail(args, message, code):
    """Say why the run stopped, and leave the reason where `status` finds it."""
    print(message, file=sys.stderr)
    if args.run_id:
        background.mark_failed(args.run_id, message)
    return code


def _warn_if_same_family(args, answering, flag):
    """Say so when the counterpart is the model family of the agent asking.

    Not a refusal: sometimes it is the only provider there is. But two models
    of one family tend to miss the same things, so the user should know.
    """
    host = providers.host()
    if host and host in answering and not args.run_id:
        print(f"Note: groupwork is running inside {host}, and {host} is "
              f"answering too. A model of the same family tends to miss the "
              f"same things, so this is a weaker second look. Use {flag} to "
              f"name another provider if one is ready.", file=sys.stderr)


def cmd_run(args):
    if args.pattern == "panel" and not (args.panel_id and args.run_id):
        return _fail(args, "Brief refused: a panel runs through `groupwork.py "
                     "panel`, which starts at least two members. One run on "
                     "its own is not a panel.", 2)
    try:
        answers = None
        if args.panel_critique:
            answers = panel.first_answers(args.panel_id)
        text = brief.build(
            args.pattern,
            subject=args.subject,
            context=args.context or "",
            question=args.question or "",
            constraints=args.constraints or "",
            assert_withholds=args.assert_withholds,
            no_prior_view=args.no_prior_view,
            answers=answers,
        )
    except (brief.BriefError, ValueError, OSError) as exc:
        return _fail(args, f"Brief refused: {exc}", 2)

    _warn_if_same_family(args, {args.provider or providers.DEFAULT}, "--provider")

    if args.dry_run:
        print(text)
        return 0

    # The brief is built above either way, so a refusal comes back at once
    # rather than turning up later as a failed background run. The detached
    # process builds it again from the same arguments: the leak-check result
    # travels with a brief built by brief.build(), never through a file.
    if args.background and not args.run_id:
        run_id = runner.new_run_id()
        background.launch(pathlib.Path(__file__).resolve(), args.argv, run_id)
        print(run_id)
        print(f"Running in the background. Check it with: groupwork.py status {run_id}",
              file=sys.stderr)
        return 0

    # A foreground run holds its own lock, so `status` from another shell says
    # running. A detached one was handed the lock when it was launched.
    run_id = args.run_id or runner.new_run_id()
    lock = background.hold(run_id) if not args.run_id else contextlib.nullcontext()
    try:
        with lock:
            result = runner.run(
                args.pattern,
                text,
                provider_name=args.provider,
                cwd=args.cwd,
                repo_access=(True if args.repo_access else None),
                model=args.model,
                effort=args.effort,
                allow_write=args.allow_write,
                subject=args.subject,
                timeout=args.timeout,
                run_id=run_id,
                panel_id=args.panel_id,
            )
    except (runner.RunFailed, providers.ProviderError, ValueError) as exc:
        return _fail(args, f"Run failed: {exc}", 1)

    # runner.run() has already written the ledger lines, the last one "done".
    print(result["output"])
    print()
    print("---")
    print(provenance.citation(result))
    return 0


def cmd_panel(args):
    """Several blind answers in parallel, for the host to reconcile.

    The brief is built here first, exactly as each member will build it, so a
    refusal comes back at once rather than as a panel of failed members.
    """
    try:
        brief.build(
            "panel",
            subject=args.subject,
            context=args.context or "",
            question=args.question or "",
            constraints=args.constraints or "",
            assert_withholds=args.assert_withholds,
            no_prior_view=args.no_prior_view,
        )
        answering = set(providers.REGISTRY)
        if args.members:
            answering = {m["provider"] for m in panel.parse_members(args.members)}
    except (brief.BriefError, ValueError) as exc:
        return _fail(args, f"Panel refused: {exc}", 2)
    _warn_if_same_family(args, answering, "--members")

    script = pathlib.Path(__file__).resolve()
    if args.background and not args.run_id:
        panel_id = runner.new_run_id()
        background.launch(script, args.argv, panel_id)
        print(panel_id)
        print(f"Panel running in the background. Check it with: groupwork.py "
              f"status {panel_id}", file=sys.stderr)
        return 0

    panel_id = args.run_id or runner.new_run_id()
    print(f"Panel {panel_id} started.", file=sys.stderr)
    lock = (background.hold(panel_id) if not args.run_id
            else contextlib.nullcontext())
    try:
        with lock:
            panel.coordinate(args, script, panel_id)
    except panel.PanelFailed as exc:
        return _fail(args, f"Panel failed: {exc}", 1)
    print(panel.render(panel_id))
    return 0


def _state(run_id):
    if panel.is_panel(run_id):
        return panel.state(run_id)
    return background.state(run_id)


def cmd_status(args):
    state, detail, _ = _state(args.run_id)
    if state == "unknown":
        print(f"No run '{args.run_id}'.", file=sys.stderr)
        return 1
    print(f"{args.run_id}  {state}")
    for line in detail.splitlines():
        print(f"    {line}")
    return 0


def cmd_result(args):
    state, detail, row = _state(args.run_id)
    if state == "done" and panel.is_panel(args.run_id):
        print(panel.render(args.run_id))
        return 0
    if state == "done":
        print(row["output"])
        print()
        print("---")
        print(provenance.citation(row))
        return 0
    if state == "running":
        print(f"{args.run_id} is still running ({detail}). Check again with "
              f"`status`.", file=sys.stderr)
        return 3
    if state == "failed":
        print(f"{args.run_id} failed: {detail}", file=sys.stderr)
        return 1
    print(f"No run '{args.run_id}'.", file=sys.stderr)
    return 1


#: How history and show name a run that did not finish cleanly.
_ENDED = {
    "failed": "failed",
    "timed-out": "timed out",
    "stopped": "stopped",
    "unrecorded": "no result recorded",
}


def _ended(row):
    """Empty for a run that is done, else how it ended, in words."""
    status = provenance.status(row)
    if status == "done":
        return ""
    if status == "started":
        return "running" if background.running(row["id"]) else "stopped"
    return _ENDED.get(status, status)


def cmd_history(args):
    rows = provenance.runs(limit=args.limit)
    if not rows:
        print("Nothing has been run yet.")
        return 0
    for row in rows:
        repo = "" if row.get("repo_access") else ", no repo"
        duration = row.get("duration_s")
        took = f"{duration}s" if duration is not None else "-"
        ended = _ended(row)
        mark = f"  [{ended}]" if ended else ""
        print(f"{row['id']}  {row.get('pattern', '?'):<15} "
              f"{row.get('provider', '?'):<9} {row.get('model') or '?':<14} "
              f"{took}{repo}{mark}")
        print(f"    {(row.get('subject') or '')[:100]}")
        if row.get("error") and ended:
            print(f"    {row['error'][:200]}")
    return 0


def cmd_show(args):
    row = provenance.find(args.run_id)
    if not row:
        print(f"No run '{args.run_id}'.", file=sys.stderr)
        return 1
    ended = _ended(row)
    if ended:
        # No answer to cite. Say what happened and where the evidence is.
        print(f"Run {args.run_id}: {ended}.")
        if row.get("error"):
            print(row["error"])
        output = pathlib.Path(row.get("output_path") or "")
        for label, path in (
            ("Brief", row.get("brief_path")),
            ("Log", row.get("log_path") or (str(output.with_suffix(".log"))
                                            if output.name else None)),
        ):
            if path and pathlib.Path(path).exists():
                print(f"{label}: {path}")
        if row.get("output", "").strip():
            print()
            print("Its output file holds this, but the run did not end cleanly, "
                  "so it has no citation:")
            print()
            print(row["output"])
        return 1
    print(row["output"])
    print()
    print("---")
    print(provenance.citation(row))
    return 0


def _seconds(value):
    seconds = int(value)
    if seconds <= 0:
        raise argparse.ArgumentTypeError("must be a whole number of seconds above 0")
    return seconds


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="groupwork",
        description="Put a second agent on the work - as an adversary or a partner.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("providers", help="which counterpart CLIs are ready").set_defaults(
        func=cmd_providers
    )
    sub.add_parser("patterns", help="the four patterns and what each withholds").set_defaults(
        func=cmd_patterns
    )

    run = sub.add_parser("run", help="run one pattern")
    run.add_argument("pattern", choices=sorted(patterns.PATTERNS))
    run.add_argument("--subject", required=True, help="what is being looked at")
    run.add_argument("--context", help="everything from outside the repo it will need")
    run.add_argument("--question", help="what specifically to answer")
    run.add_argument("--constraints", help="for verify: the constraints to rule on")
    run.add_argument("--assert-withholds", dest="assert_withholds",
                     help="our draft conclusion, checked for absence and not included")
    run.add_argument("--no-prior-view", dest="no_prior_view", action="store_true",
                     help="declare that no view has been formed yet; a blind "
                          "pattern needs this or --assert-withholds")
    run.add_argument("--provider", choices=sorted(providers.REGISTRY))
    run.add_argument("--model")
    run.add_argument("--effort", choices=patterns.EFFORTS)
    run.add_argument("--cwd", help="where to run (default: here)")
    run.add_argument("--repo-access", action="store_true",
                     help="give red-team the repository, against its default")
    run.add_argument("--allow-write", action="store_true",
                     help="permit a write sandbox; ask the user first, every time")
    run.add_argument("--dry-run", action="store_true",
                     help="print the brief and run nothing")
    run.add_argument("--timeout", type=_seconds,
                     help="seconds before the run is stopped (default: by effort)")
    run.add_argument("--background", action="store_true",
                     help="start the run detached, print its id and return at once")
    # Given to the detached process by --background, and to each member by a
    # panel. Not for use by hand.
    run.add_argument("--run-id", dest="run_id", help=argparse.SUPPRESS)
    run.add_argument("--panel-id", dest="panel_id", help=argparse.SUPPRESS)
    run.add_argument("--panel-critique", dest="panel_critique",
                     action="store_true", help=argparse.SUPPRESS)
    run.set_defaults(func=cmd_run)

    status = sub.add_parser("status", help="whether a run is running, done or failed")
    status.add_argument("run_id")
    status.set_defaults(func=cmd_status)

    result = sub.add_parser(
        "result", help="a finished run's answer and citation (exit 3 if still running)"
    )
    result.add_argument("run_id")
    result.set_defaults(func=cmd_result)

    pan = sub.add_parser(
        "panel", help="several blind answers in parallel, for you to reconcile"
    )
    pan.add_argument("--subject", required=True, help="the question")
    pan.add_argument("--context", help="everything from outside the repo it will need")
    pan.add_argument("--question", help="what specifically is being decided")
    pan.add_argument("--constraints", help="what binds any answer")
    pan.add_argument("--assert-withholds", dest="assert_withholds",
                     help="our draft conclusion, checked for absence and not included")
    pan.add_argument("--no-prior-view", dest="no_prior_view", action="store_true",
                     help="declare that no view has been formed yet")
    pan.add_argument("--members",
                     help="provider[:model], comma-separated, at least two "
                          "(default: one per ready provider)")
    pan.add_argument("--critique", action="store_true",
                     help="then one round where each member attacks every "
                          "first answer, unlabelled")
    pan.add_argument("--effort", choices=patterns.EFFORTS)
    pan.add_argument("--cwd", help="where to run (default: here)")
    pan.add_argument("--timeout", type=_seconds,
                     help="seconds before each member is stopped (default: by effort)")
    pan.add_argument("--background", action="store_true",
                     help="start the panel detached, print its id and return at once")
    pan.add_argument("--run-id", dest="run_id", help=argparse.SUPPRESS)
    pan.set_defaults(func=cmd_panel)

    history = sub.add_parser("history", help="past runs")
    history.add_argument("--limit", type=int, default=10)
    history.set_defaults(func=cmd_history)

    show = sub.add_parser("show", help="one past run in full")
    show.add_argument("run_id")
    show.set_defaults(func=cmd_show)

    argv = sys.argv[1:] if argv is None else list(argv)
    args = parser.parse_args(argv)
    args.argv = argv
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
