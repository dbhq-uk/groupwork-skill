#!/usr/bin/env python3
"""groupwork - put a second agent on the work, as an adversary or as a partner.

    groupwork.py providers
    groupwork.py patterns
    groupwork.py run <pattern> --subject ... [--context ...] [--background]
    groupwork.py status <run-id>
    groupwork.py result <run-id>
    groupwork.py debate --subject ... [--rounds 2]
    groupwork.py history [--limit 10]
    groupwork.py show <run-id>

Standard library only. Every provider authenticates itself, so there is nothing
to configure and no credential to store.
"""

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))

import background  # noqa: E402
import brief  # noqa: E402
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


def cmd_run(args):
    try:
        text = brief.build(
            args.pattern,
            subject=args.subject,
            context=args.context or "",
            question=args.question or "",
            constraints=args.constraints or "",
            our_view=args.our_view,
            assert_withholds=args.assert_withholds,
            no_prior_view=args.no_prior_view,
        )
    except (brief.BriefError, ValueError) as exc:
        return _fail(args, f"Brief refused: {exc}", 2)

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

    try:
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
            run_id=args.run_id,
        )
    except (runner.RunFailed, providers.ProviderError, ValueError) as exc:
        return _fail(args, f"Run failed: {exc}", 1)

    provenance.record(result)
    print(result["output"])
    print()
    print("---")
    print(provenance.citation(result))
    return 0


def cmd_debate(args):
    """Blind proposals, then adversarial critique, with a fresh session a round.

    The fresh session is not an implementation detail. A reviewer that already
    argued a position in round 1 defends it in round 2 rather than re-examining
    it, so a resumed session produces entrenchment and calls it convergence.
    """
    transcript = []
    for round_ in range(args.rounds + 1):
        try:
            text = brief.build(
                "debate",
                subject=args.subject,
                context=args.context or "",
                question=args.question or "",
                constraints=args.constraints or "",
                round_=round_,
                assert_withholds=args.assert_withholds,
                no_prior_view=args.no_prior_view,
                prior_round=transcript[-1]["output"] if transcript else "",
            )
        except (brief.BriefError, ValueError) as exc:
            print(f"Brief refused at round {round_}: {exc}", file=sys.stderr)
            return 2
        try:
            result = runner.run(
                "debate", text, provider_name=args.provider, cwd=args.cwd,
                model=args.model, subject=f"{args.subject} (round {round_})",
                timeout=args.timeout,
            )
        except (runner.RunFailed, providers.ProviderError, ValueError) as exc:
            print(f"Round {round_} failed: {exc}", file=sys.stderr)
            return 1
        provenance.record(result)
        transcript.append(result)
        print(f"## Round {round_}\n")
        print(result["output"])
        print()

    print("---")
    for result in transcript:
        print(provenance.citation(result))
    print()
    print("Where the rounds agree is the reliable part. Where they diverge is "
          "the real trade-off, and it is yours to settle.")
    return 0


def cmd_status(args):
    state, detail, _ = background.state(args.run_id)
    if state == "unknown":
        print(f"No run '{args.run_id}'.", file=sys.stderr)
        return 1
    print(f"{args.run_id}  {state}")
    print(f"    {detail}")
    return 0


def cmd_result(args):
    state, detail, row = background.state(args.run_id)
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


def cmd_history(args):
    rows = provenance.read_ledger(limit=args.limit)
    if not rows:
        print("Nothing has been run yet.")
        return 0
    for row in rows:
        repo = "" if row.get("repo_access") else ", no repo"
        print(f"{row['id']}  {row['pattern']:<15} {row['provider']:<9} "
              f"{row['model']:<14} {row['duration_s']}s{repo}")
        print(f"    {row['subject'][:100]}")
    return 0


def cmd_show(args):
    row = provenance.find(args.run_id)
    if not row:
        print(f"No run '{args.run_id}'.", file=sys.stderr)
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
    sub.add_parser("patterns", help="the five patterns and what each withholds").set_defaults(
        func=cmd_patterns
    )

    run = sub.add_parser("run", help="run one pattern")
    run.add_argument("pattern", choices=sorted(patterns.PATTERNS))
    run.add_argument("--subject", required=True, help="what is being looked at")
    run.add_argument("--context", help="everything from outside the repo it will need")
    run.add_argument("--question", help="what specifically to answer")
    run.add_argument("--constraints", help="for verify: the constraints to rule on")
    run.add_argument("--our-view", dest="our_view",
                     help="collaborate only; refused by the blind patterns")
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
    # Given to the detached process by --background. Not for use by hand.
    run.add_argument("--run-id", dest="run_id", help=argparse.SUPPRESS)
    run.set_defaults(func=cmd_run)

    status = sub.add_parser("status", help="whether a run is running, done or failed")
    status.add_argument("run_id")
    status.set_defaults(func=cmd_status)

    result = sub.add_parser(
        "result", help="a finished run's answer and citation (exit 3 if still running)"
    )
    result.add_argument("run_id")
    result.set_defaults(func=cmd_result)

    debate = sub.add_parser("debate", help="blind proposals, then adversarial rounds")
    debate.add_argument("--subject", required=True)
    debate.add_argument("--context")
    debate.add_argument("--question")
    debate.add_argument("--constraints")
    debate.add_argument("--rounds", type=int, default=2)
    debate.add_argument("--assert-withholds", dest="assert_withholds",
                        help="our draft conclusion, checked for absence and not included")
    debate.add_argument("--no-prior-view", dest="no_prior_view", action="store_true",
                        help="declare that no view has been formed yet")
    debate.add_argument("--provider", choices=sorted(providers.REGISTRY))
    debate.add_argument("--model")
    debate.add_argument("--cwd")
    debate.add_argument("--timeout", type=_seconds,
                        help="seconds before each round is stopped (default: by effort)")
    debate.set_defaults(func=cmd_debate)

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
