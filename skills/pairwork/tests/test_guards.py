"""The four hard rules. If one of these fails, pairwork is lying about something.

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


# --- Rule 3: no brief contains pairwork's own trigger phrases ----------------

@pytest.mark.parametrize("template", sorted(p.name for p in TEMPLATES.glob("*.md")))
def test_templates_contain_no_trigger_phrases(template):
    """A template that says "second opinion" makes the far end delegate.

    The counterpart very likely has this skill installed. Its copy fires, tries
    to hand the work to a third agent, fails on auth or the read-only sandbox,
    and returns an apology where the review should be.
    """
    text = (TEMPLATES / template).read_text(encoding="utf-8")
    assert brief.find_triggers(text) == [], (
        f"{template} contains trigger phrases that will re-trigger pairwork "
        f"at the far end"
    )


def test_build_rejects_a_trigger_phrase_in_the_subject():
    with pytest.raises(brief.BriefError, match="re-trigger"):
        brief.build("verify", subject="give me a second opinion on the diff")


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
        text = brief.build(name, subject="a subject", context="some context")
        assert text.strip()
        assert "{" not in text.replace("{subject}", ""), f"{name} left a placeholder"
