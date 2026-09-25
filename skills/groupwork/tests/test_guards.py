"""The four hard rules. If one of these fails, groupwork is lying about something.

Each test names the rule it holds. They are the reason AGENTS.md says to read it
before changing anything in scripts/.
"""

import pathlib
import re

import pytest

import brief
import patterns

SKILL_MD = pathlib.Path(__file__).resolve().parent.parent / "SKILL.md"
TEMPLATES = pathlib.Path(__file__).resolve().parent.parent / "templates"

DRAFT_VIEW = (
    "We should ship the thing because the incumbent is weak and the market "
    "is clearly wide open for a tool like ours."
)


def needs(pattern):
    """What a pattern must be given beyond a subject to build at all."""
    if patterns.PATTERNS[pattern].get("needs_constraints"):
        return {"constraints": "It must not change the public API."}
    return {}


# --- Rule 1: a blind pattern never carries our conclusion --------------------

@pytest.mark.parametrize("pattern", sorted(patterns.BLIND))
def test_blind_patterns_refuse_our_view(pattern):
    """Passing our conclusion to a blind pattern is an error, not an ignored kwarg.

    Silently dropping it would be worse than either alternative: the caller
    believes the counterpart saw their reasoning, the counterpart did not, and
    nobody finds out until the provenance line is already in a document.
    """
    with pytest.raises(brief.BriefError, match="withholds"):
        brief.build(pattern, subject="a thing", our_view=DRAFT_VIEW)


@pytest.mark.parametrize("pattern", sorted(patterns.BLIND))
def test_blind_patterns_catch_a_leak_through_context(pattern):
    """The honest mistake: the view goes in via `context` instead."""
    with pytest.raises(brief.BriefError, match="not independent"):
        brief.build(
            pattern,
            subject="a thing",
            context=f"Background. {DRAFT_VIEW} Some more background.",
            assert_withholds=DRAFT_VIEW,
            **needs(pattern),
        )


def test_a_clean_blind_brief_builds():
    """The guard must not be so eager that the normal case fails."""
    text = brief.build(
        "second-opinion",
        subject="the plan in docs/plan.md",
        context="It was written last week.",
        assert_withholds=DRAFT_VIEW,
    )
    assert "independent" in text.lower()


def test_short_phrases_are_not_treated_as_leaks():
    """A shared short phrase is coincidence, not anchoring."""
    assert brief.leaks("we should ship the thing", "we should ship the thing") == []


# The three rewordings that got past the old whole-sentence match. Each one
# leaves the argument exactly as a reader would take it, so each one has to be
# caught.
REWORDED = {
    "comma": (
        "We should ship the thing, because the incumbent is weak and the market "
        "is clearly wide open for a tool like ours."
    ),
    "bold": (
        "We should ship the thing because the **incumbent is weak** and the "
        "market is clearly wide open for a tool like ours."
    ),
    "one word swapped": (
        "We should ship the thing because the incumbent is feeble and the market "
        "is clearly wide open for a tool like ours."
    ),
    "two short sentences": "We should use the queue. Cron is wrong.",
}


@pytest.mark.parametrize("case", sorted(REWORDED))
def test_a_reworded_view_is_still_caught(case):
    view = DRAFT_VIEW if case != "two short sentences" else REWORDED[case]
    with pytest.raises(brief.BriefError, match="not independent"):
        brief.build(
            "second-opinion",
            subject="a thing",
            context=f"Background.\n\n{REWORDED[case]}\n\nSome more background.",
            assert_withholds=view,
        )


@pytest.mark.parametrize("template", sorted(p.name for p in TEMPLATES.glob("*.md")))
def test_no_template_is_mistaken_for_a_leak(template):
    """The template is the same in every run, so it can never carry our view.

    Given the whole of a template as the view to withhold, a clean brief must
    still build. Anything else is a false positive that would refuse runs for
    sharing a phrase with groupwork's own wording.
    """
    view = (TEMPLATES / template).read_text(encoding="utf-8")
    for pattern in sorted(patterns.BLIND):
        brief.build(pattern, subject="the plan in docs/plan.md",
                    context="It was written last week.", assert_withholds=view,
                    **needs(pattern))
    brief.build("red-team", subject="x", context="y",
                assert_withholds=brief.SOLE_REVIEWER + brief.OUTPUT_CONTRACT)


@pytest.mark.parametrize("pattern", sorted(patterns.BLIND))
def test_a_blind_pattern_needs_a_declaration_about_our_view(pattern):
    """Without one, the citation could say nothing true about what was kept out."""
    with pytest.raises(brief.BriefError, match="--no-prior-view"):
        brief.build(pattern, subject="a thing", context="some context")


def test_no_prior_view_is_enough_on_its_own():
    text = brief.build("second-opinion", subject="a thing", no_prior_view=True)
    assert text.leak_check == "not-run"
    assert text.no_prior_view is True


def test_a_checked_brief_records_that_the_check_passed():
    text = brief.build("second-opinion", subject="a thing",
                       assert_withholds=DRAFT_VIEW)
    assert text.leak_check == "passed"
    assert text.no_prior_view is False


def test_a_view_too_short_to_check_is_refused_rather_than_passed():
    """A view of five words has no run of six to look for, so nothing was checked."""
    with pytest.raises(brief.BriefError, match="too short"):
        brief.build("second-opinion", subject="a thing", assert_withholds="use the queue")


def test_both_declarations_at_once_are_refused():
    with pytest.raises(brief.BriefError, match="not both"):
        brief.build("second-opinion", subject="a thing",
                    assert_withholds=DRAFT_VIEW, no_prior_view=True)


def test_a_panel_answer_that_reaches_our_view_is_not_a_leak():
    """The first answers are the members' own work. Agreeing is not a leak."""
    text = brief.build(
        "panel", subject="queue or cron", assert_withholds=DRAFT_VIEW,
        answers=[DRAFT_VIEW, "Use cron, it is simpler."],
    )
    assert "incumbent is weak" in text
    assert text.leak_check == "passed"
    assert text.answers_shown == 2


def test_verify_without_constraints_is_refused():
    """It rules on work against constraints. With none it has nothing to rule on."""
    for constraints in ("", "   \n"):
        with pytest.raises(brief.BriefError, match="--constraints"):
            brief.build("verify", subject="the diff on this branch",
                        no_prior_view=True, constraints=constraints)


def test_verify_with_constraints_carries_them():
    text = brief.build("verify", subject="the diff", no_prior_view=True,
                       constraints="No new dependencies.")
    assert "No new dependencies." in text
    assert "(none stated)" not in text


# --- Rule 3: no brief contains groupwork's own trigger phrases ----------------

@pytest.mark.parametrize("template", sorted(p.name for p in TEMPLATES.glob("*.md")))
def test_templates_contain_no_trigger_phrases(template):
    """A template that says "second opinion" makes the far end delegate.

    The counterpart very likely has this skill installed. Its copy fires, tries
    to hand the work to a third agent, fails on auth or the read-only sandbox,
    and returns an apology where the review should be.
    """
    text = (TEMPLATES / template).read_text(encoding="utf-8")
    assert brief.find_triggers(text) == [], (
        f"{template} contains trigger phrases that will re-trigger groupwork "
        f"at the far end"
    )


def test_build_rejects_a_trigger_phrase_in_the_subject():
    with pytest.raises(brief.BriefError, match="re-trigger"):
        brief.build("verify", subject="give me a second opinion on the diff",
                    no_prior_view=True, **needs("verify"))


def test_a_critique_is_never_refused_for_words_in_an_earlier_answer():
    """The first round has been paid for by then. Its words are not a brief.

    debate ran the trigger check over the previous round's answer, so a model
    that wrote "counterpart" or "second opinion" got the next round refused.
    The check now runs on the brief before any answer goes in.
    """
    answers = [
        "My counterpart argued for cron. A second opinion would help.",
        "Use a red team on the queue design before anything ships.",
    ]
    text = brief.build("panel", subject="queue or cron", no_prior_view=True,
                       answers=answers)
    assert "### Answer A" in text and "### Answer B" in text
    for answer in answers:
        assert answer in text


def test_a_critique_still_refuses_a_trigger_phrase_from_the_caller():
    with pytest.raises(brief.BriefError, match="re-trigger"):
        brief.build("panel", subject="a second opinion on queue or cron",
                    no_prior_view=True, answers=["one", "two"])


def test_a_critique_needs_two_answers_to_compare():
    with pytest.raises(brief.BriefError, match="at least two"):
        brief.build("panel", subject="queue or cron", no_prior_view=True,
                    answers=["only one"])


def test_the_trigger_list_is_exactly_the_phrases_in_the_skill_frontmatter():
    """The list and SKILL.md's own triggers must not drift apart, either way.

    A trigger in the description and not here lets a brief quoting it sail
    through, and the far end delegates. A phrase here and not in the
    description is not a trigger at all, and only refuses ordinary subjects.
    """
    frontmatter = re.match(r"^---\n(.*?)\n---", SKILL_MD.read_text(encoding="utf-8"), re.S)
    assert frontmatter, "SKILL.md has no frontmatter"
    quoted = {q.lower() for q in re.findall(r'"([^"]+)"', frontmatter.group(1))}
    known = {p.lower() for p in patterns.TRIGGER_PHRASES}
    assert quoted - known == set(), f"in SKILL.md but not in TRIGGER_PHRASES: {quoted - known}"
    assert known - quoted == set(), f"in TRIGGER_PHRASES but not in SKILL.md: {known - quoted}"


@pytest.mark.parametrize("subject", [
    "our exposure to the counterpart bank",
    "counterparties and counterparts in the swap book",
    "the blind review stage of the hiring policy",
    "the red teams in the league table",
    "a groupworking session for the new starters",
])
def test_an_ordinary_subject_is_not_mistaken_for_a_trigger(subject):
    """Only groupwork's own phrases, and only as whole words."""
    brief.build("second-opinion", subject=subject, no_prior_view=True)


@pytest.mark.parametrize("subject", [
    "Red-Team this plan",
    "a SECOND-OPINION on the diff",
    "a second\nopinion on the diff",
    "what does  Codex think of it",
    "the groupwork-skill repository",
])
def test_a_trigger_is_caught_however_it_is_spaced(subject):
    with pytest.raises(brief.BriefError, match="re-trigger"):
        brief.build("second-opinion", subject=subject, no_prior_view=True)


# --- Rule 4: no write sandbox without an explicit per-run decision -----------

def test_no_pattern_asks_for_a_write_sandbox():
    for name, spec in patterns.PATTERNS.items():
        assert spec["sandbox"] == "read-only", f"{name} defaults to a write sandbox"


def test_no_template_asks_the_counterpart_to_change_anything():
    """A read-only sandbox that is asked to edit produces a stalled run, not a refusal."""
    banned = re.compile(
        r"\b(edit the|modify the|apply the (fix|change)|commit |push |write the file)\b",
        re.I,
    )
    for template in TEMPLATES.glob("*.md"):
        hit = banned.search(template.read_text(encoding="utf-8"))
        assert not hit, f"{template.name} asks for a write: {hit.group(0)!r}"


# --- The pattern definitions themselves --------------------------------------

def test_red_team_withholds_the_repository():
    """The sharpest default in the skill, and the one worth a test of its own."""
    assert patterns.PATTERNS["red-team"]["repo_access"] is False


def test_adversarial_patterns_use_the_frontier_model():
    for name in ("red-team", "second-opinion", "verify", "panel"):
        assert patterns.PATTERNS[name]["model"] == "gpt-6-astra"
        assert patterns.PATTERNS[name]["effort"] == "high"


def test_every_pattern_is_blind():
    """collaborate was the one pattern that took our view, and it is gone.

    It withheld nothing, so its citation showed nothing a reader could rely on,
    and nothing could resume the session it claimed to be.
    """
    assert "collaborate" not in patterns.PATTERNS
    assert not (TEMPLATES / "collaborate.md").exists()
    assert patterns.BLIND == set(patterns.PATTERNS)


def test_a_view_passed_in_points_at_an_advisor_not_a_pattern():
    with pytest.raises(brief.BriefError, match="persistent advisor"):
        brief.build("second-opinion", subject="a thing", our_view=DRAFT_VIEW)


def test_every_pattern_has_a_template_that_exists():
    for name, spec in patterns.PATTERNS.items():
        assert (TEMPLATES / spec["template"]).exists(), f"{name} has no template"
        if spec.get("critique_template"):
            assert (TEMPLATES / spec["critique_template"]).exists(), name


def test_debate_is_gone_and_nothing_claims_two_parties():
    """debate told one model that two parties had answered independently.

    The only templates that say other people are answering are panel's, and a
    panel always starts at least two members.
    """
    assert "debate" not in patterns.PATTERNS
    assert not (TEMPLATES / "debate.md").exists()
    claims = re.compile(r"two parties|other people|put to several people", re.I)
    for template in TEMPLATES.glob("*.md"):
        if claims.search(template.read_text(encoding="utf-8")):
            assert template.name.startswith("panel"), template.name


def test_every_pattern_builds():
    """Every template's placeholders are ones build() actually supplies."""
    for name in patterns.PATTERNS:
        text = brief.build(name, subject="a subject", context="some context",
                           no_prior_view=name in patterns.BLIND, **needs(name))
        assert text.strip()
        assert "{" not in text.replace("{subject}", ""), f"{name} left a placeholder"
