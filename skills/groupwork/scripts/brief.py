"""Assemble a brief, and refuse to assemble a bad one.

Two of groupwork's four hard rules live here, and both are enforced rather than
requested. A rule written into a template is a suggestion to whoever edits the
template next; a rule that raises is a rule.

  Rule 1 - a blind pattern's brief must not carry our conclusion.
  Rule 3 - no brief may contain groupwork's own trigger phrases.

Rule 3 looks like fussiness and is not. The counterpart very likely has this
skill installed. A brief that says "give me a second opinion on this" trips its
copy of the protocol, which dutifully tries to delegate to a third agent, fails
on auth or on the read-only sandbox, and returns an apology. You get back a
polite note instead of a review, having paid for the run.
"""

import pathlib
import re

import patterns

TEMPLATES = pathlib.Path(__file__).resolve().parent.parent / "templates"


class BriefError(ValueError):
    """The brief would have been unsafe or useless, and was not built."""


#: Said in every brief, in place of the words we are not allowed to use.
SOLE_REVIEWER = """\
You are the only person looking at this. Do not run any skill, workflow, \
sub-agent or command-line tool to get another view - not `claude`, not `codex`, \
not anything else. Read the material and answer directly."""

#: The output contract. Same in every pattern, so findings from different
#: patterns can sit in the same document without being reformatted.
OUTPUT_CONTRACT = """\
Answer as a numbered list of findings. Give each one:

  - a severity: blocker, major, minor or nit
  - a location: file:line where there is one, otherwise where in the material
  - the reasoning, in enough detail that someone can check it

Then a short verdict, two or three sentences.

If you find nothing significant, say so plainly. Do not invent issues to fill \
the list - a short honest answer is worth more than a long invented one."""


def load_template(name):
    path = TEMPLATES / name
    if not path.exists():
        raise BriefError(f"no template at {path}")
    return path.read_text(encoding="utf-8")


def find_triggers(text):
    """Return every trigger phrase present in the text, case-insensitively."""
    lowered = text.lower()
    return [p for p in patterns.TRIGGER_PHRASES if p.lower() in lowered]


def leaks(text, our_view):
    """Does this text carry our conclusion?

    `build()` refuses `our_view` outright for a blind pattern, which handles the
    caller who passes it in the right field. This catches the caller who pastes
    their view into `context` instead, which the type system cannot see.

    Compares sentence by sentence rather than as one blob: a view reworded by a
    word or two has still anchored the counterpart. Anything of eight words or
    more appearing in both is treated as a leak.
    """
    if not our_view:
        return []
    haystack = re.sub(r"\s+", " ", text.lower())
    leaks = []
    for sentence in re.split(r"[.!?\n]+", our_view):
        words = sentence.split()
        if len(words) < 8:
            continue
        needle = re.sub(r"\s+", " ", sentence.strip().lower())
        if needle and needle in haystack:
            leaks.append(sentence.strip())
    return leaks


def build(pattern_name, subject, context="", question="", our_view=None,
          constraints="", assert_withholds=None, round_=0):
    """Build the brief for a pattern, or raise saying why it would be unsound.

    `our_view` is accepted for every pattern and permitted for one. Passing it
    to a blind pattern is an error rather than a silently ignored argument,
    because a caller who thinks it was included and a brief that dropped it are
    the two halves of a provenance claim that is not true.

    `assert_withholds` is the other half of that guard, and the one that catches
    the honest mistake. Pass your draft conclusion here when running a blind
    pattern; nothing is added to the brief, but if that text has found its way
    in through `context` or `subject`, the build fails instead of producing a
    review you would have cited as independent.
    """
    spec = patterns.get(pattern_name)

    if spec["blind"] and our_view:
        raise BriefError(
            f"'{pattern_name}' withholds {spec['withholds']}. It cannot be given "
            f"our view - that is the whole of what makes its answer worth citing. "
            f"Use 'collaborate' if you want to work through it together."
        )

    body = load_template(spec["template"])
    text = body.format(
        subject=subject.strip(),
        context=context.strip() or "(none supplied)",
        question=question.strip() or spec["purpose"],
        constraints=constraints.strip() or "(none stated)",
        our_view=(our_view or "").strip(),
        round=round_,
        sole_reviewer=SOLE_REVIEWER,
        output_contract=OUTPUT_CONTRACT,
    )

    found = find_triggers(text)
    if found:
        raise BriefError(
            "the brief contains phrases that will re-trigger groupwork at the far "
            f"end, so it would delegate instead of reviewing: {', '.join(sorted(set(found)))}. "
            "Reword the subject or context without them."
        )

    leaked = leaks(text, assert_withholds)
    if leaked:
        raise BriefError(
            f"'{pattern_name}' withholds {spec['withholds']}, but our view reached "
            f"the brief anyway: \"{leaked[0][:120]}\". Take it out of the subject "
            f"and context, or the answer is not independent and must not be cited "
            f"as though it were."
        )

    return text
