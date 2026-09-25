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
        )


def test_collaborate_accepts_our_view():
    """The one pattern that is meant to see it, does."""
    text = brief.build("collaborate", subject="a thing", our_view=DRAFT_VIEW)
    assert "incumbent is weak" in text


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
                    context="It was written last week.", assert_withholds=view)
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


def test_a_debate_round_is_not_checked_against_the_last_round_answer():
    """The earlier answer is the counterpart's own work. Agreeing is not a leak."""
    text = brief.build(
        "debate", subject="queue or cron", round_=1, assert_withholds=DRAFT_VIEW,
        prior_round=DRAFT_VIEW,
    )
    assert "incumbent is weak" in text
    assert text.leak_check == "passed"


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
                    no_prior_view=True)


def test_trigger_list_covers_every_phrase_in_the_skill_frontmatter():
    """The list and SKILL.md's own triggers must not drift apart.

    If a new trigger phrase is added to the description and not here, a brief
    quoting it sails through and the far end delegates.
    """
    frontmatter = re.match(r"^---\n(.*?)\n---", SKILL_MD.read_text(encoding="utf-8"), re.S)
    assert frontmatter, "SKILL.md has no frontmatter"
    quoted = re.findall(r'"([^"]+)"', frontmatter.group(1))
    known = {p.lower() for p in patterns.TRIGGER_PHRASES}
    missing = [q for q in quoted if q.lower() not in known]
    assert not missing, f"trigger phrases in SKILL.md but not in TRIGGER_PHRASES: {missing}"


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
    for name in ("red-team", "second-opinion", "verify", "debate"):
        assert patterns.PATTERNS[name]["model"] == "gpt-6-astra"
        assert patterns.PATTERNS[name]["effort"] == "high"


def test_collaborate_does_not():
    assert patterns.PATTERNS["collaborate"]["model"] == "gpt-5.6-sol"


def test_every_pattern_has_a_template_that_exists():
    for name, spec in patterns.PATTERNS.items():
        assert (TEMPLATES / spec["template"]).exists(), f"{name} has no template"


def test_every_pattern_builds():
    """Every template's placeholders are ones build() actually supplies."""
    for name in patterns.PATTERNS:
        text = brief.build(name, subject="a subject", context="some context",
                           no_prior_view=name in patterns.BLIND)
        assert text.strip()
        assert "{" not in text.replace("{subject}", ""), f"{name} left a placeholder"
