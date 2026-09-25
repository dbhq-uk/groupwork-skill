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


def _trigger(phrase):
    """A phrase as a whole-word pattern, any spaces or hyphens between words."""
    words = [re.escape(word) for word in re.split(r"[\s-]+", phrase.strip()) if word]
    return re.compile(r"\b" + r"[\s-]+".join(words) + r"\b", re.IGNORECASE)


def find_triggers(text):
    """Return every trigger phrase present in the text, as whole words.

    A substring match refused "counterparts" for "counterpart" and would refuse
    "groupworking" for "groupwork". Only the phrase itself counts.
    """
    return [phrase for phrase in patterns.TRIGGER_PHRASES
            if _trigger(phrase).search(text)]


#: How many consecutive words two texts must share before it counts as a leak.
#: Six is long enough that ordinary shared phrasing ("the rest of the code")
#: does not trip it, and short enough that a view reworded in one or two
#: places still leaves a run of six untouched somewhere.
SHINGLE = 6


def _words(text):
    """Lower-case words with punctuation and markdown taken out.

    A comma, `**bold**` or a line break changes nothing a reader sees in the
    argument, so none of them should change whether a leak is found.
    """
    return re.findall(r"[^\W_]+", text.lower())


def leaks(text, our_view):
    """Does this text carry our conclusion?

    `build()` refuses `our_view` outright for a blind pattern, which handles the
    caller who passes it in the right field. This catches the caller who pastes
    their view into `context` instead, which the type system cannot see.

    Both sides are reduced to plain lower-case words, then every run of six
    consecutive words in the view is looked for in the text, across sentence
    boundaries. That catches a view with a comma added, a word in bold or one
    word swapped, as long as the view is long enough to keep one run of six
    intact. A view of fewer than six words cannot be checked this way, and
    `build()` refuses one rather than report a check that did not happen.

    Returns each matching run of words, longest runs merged, or [] if none.
    """
    if not our_view:
        return []
    view = _words(our_view)
    if len(view) < SHINGLE:
        return []
    hay = _words(text)
    seen = {tuple(hay[i:i + SHINGLE]) for i in range(len(hay) - SHINGLE + 1)}
    runs = []
    for i in range(len(view) - SHINGLE + 1):
        if tuple(view[i:i + SHINGLE]) not in seen:
            continue
        if runs and i <= runs[-1][1]:
            runs[-1][1] = i + SHINGLE
        else:
            runs.append([i, i + SHINGLE])
    return [" ".join(view[start:end]) for start, end in runs]


class Brief(str):
    """The brief text, carrying the result of the leak check that built it.

    The runner copies `leak_check` into the ledger and the citation. It travels
    with the text so that nobody downstream is in a position to type it: a brief
    that did not come out of `build()` is a plain string, and reads as not-run.

    `answers_shown` is how many earlier answers went into it, for a panel
    critique. The runner reads it to pick what the citation says was withheld,
    for the same reason: only the code that inserted them can say so.
    """

    leak_check = "not-run"
    no_prior_view = False
    answers_shown = 0


#: Stands in for the earlier answers while the brief is checked. The answers
#: are models' own words, put in only after every check has run.
_ANSWERS = "\x00answers\x00"


def answer_block(answers):
    """The earlier answers, labelled A, B, C in the order given."""
    parts = []
    for index, text in enumerate(answers):
        parts.append(f"### Answer {chr(ord('A') + index)}\n\n{text.strip()}")
    return "\n\n".join(parts)


def build(pattern_name, subject, context="", question="", our_view=None,
          constraints="", assert_withholds=None, no_prior_view=False,
          answers=None):
    """Build the brief for a pattern, or raise saying why it would be unsound.

    `our_view` is accepted so that passing it is an error rather than a
    silently ignored argument. Every pattern is blind, so none takes it. A
    caller who thinks it was included and a brief that dropped it are the two
    halves of a provenance claim that is not true.

    `assert_withholds` is the other half of that guard, and the one that catches
    the honest mistake. Pass your draft conclusion here when running a blind
    pattern; nothing is added to the brief, but if that text has found its way
    in through `subject`, `context`, `question` or `constraints`, the build fails
    instead of producing a review you would have cited as independent.

    A blind pattern needs one of `assert_withholds` or `no_prior_view`. Without
    either, nothing could be said in the citation about whether our view was
    kept out, so the build is refused rather than left to imply that it was.

    `answers` are the first answers of a panel, for its critique round. They
    go in after the trigger check and the leak check, and neither looks at
    them. They are models' own words: an answer that happens to use one of
    groupwork's trigger phrases must not refuse a round that has already been
    paid for, and an answer that reaches our conclusion alone is not a leak.

    Returns a `Brief`, which is the text plus the leak-check result.
    """
    spec = patterns.get(pattern_name)

    if spec["blind"] and our_view:
        raise BriefError(
            f"'{pattern_name}' withholds {spec['withholds']}. It cannot be given "
            f"our view - that is the whole of what makes its answer worth citing. "
            f"To think it through with a peer who sees your view, use a "
            f"persistent advisor session instead."
        )

    if assert_withholds and no_prior_view:
        raise BriefError(
            "pass --assert-withholds or --no-prior-view, not both: one says there "
            "is a view to keep out and the other says there is none"
        )
    if spec["blind"] and not assert_withholds and not no_prior_view:
        raise BriefError(
            f"'{pattern_name}' is blind, so the citation has to say whether our "
            f"view was kept out of the brief. Pass --assert-withholds with the "
            f"draft conclusion to check for it, or --no-prior-view if no view has "
            f"been formed yet."
        )
    if spec.get("needs_constraints") and not constraints.strip():
        raise BriefError(
            f"'{pattern_name}' rules on work against stated constraints, and "
            f"none were given, so it would have nothing to rule on. Pass "
            f"--constraints with what the work has to meet: the acceptance "
            f"criteria, the spec, the rules it must not break."
        )
    if assert_withholds and len(_words(assert_withholds)) < SHINGLE:
        raise BriefError(
            f"--assert-withholds is too short to check: give the draft conclusion "
            f"in at least {SHINGLE} words, or pass --no-prior-view if there is none"
        )

    if answers is not None:
        if not spec.get("critique_template"):
            raise BriefError(f"'{pattern_name}' has no critique round")
        if len(answers) < 2:
            raise BriefError("a critique round needs at least two answers to compare")
        body = load_template(spec["critique_template"])
    else:
        body = load_template(spec["template"])
    text = body.format(
        subject=subject.strip(),
        context=context.strip() or "(none supplied)",
        question=question.strip() or spec.get("default_question") or spec["purpose"],
        constraints=constraints.strip() or "(none stated)",
        answers=_ANSWERS,
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

    # Only what the caller supplied is searched. The template is the same for
    # every run and cannot carry anybody's view, so matching against it could
    # only ever produce a false positive.
    supplied = "\n".join([subject, context, question, constraints])
    leaked = leaks(supplied, assert_withholds)
    if leaked:
        raise BriefError(
            f"'{pattern_name}' withholds {spec['withholds']}, but our view reached "
            f"the brief anyway: \"{leaked[0][:120]}\". Take it out of the subject "
            f"and context, or the answer is not independent and must not be cited "
            f"as though it were."
        )

    if answers is not None:
        text = text.replace(_ANSWERS, answer_block(answers))

    result = Brief(text)
    result.leak_check = "passed" if assert_withholds else "not-run"
    result.no_prior_view = bool(no_prior_view)
    result.answers_shown = len(answers) if answers is not None else 0
    return result
