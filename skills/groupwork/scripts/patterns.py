"""The four patterns. This file is the product.

Everything else in groupwork is plumbing that exists to run one of these
faithfully and record what happened. A pattern is four things:

  - a model and effort, because an adversary is worth paying for;
  - a sandbox, which is read-only for all four;
  - a **withholding rule**, which is the part that makes the result citable;
  - a brief template that says all of it to the counterpart.

The withholding rule is why this is not a wrapper. A second opinion that has
already been told your conclusion is not a second opinion, it is agreement with
extra steps. So every pattern refuses to carry your view at all, and the
refusal is enforced in code rather than requested in prose.
"""

# --- Model policy -----------------------------------------------------------
#
# Adversarial work gets the frontier model at high effort. That is a standing
# decision (Dan, 17 Sep 2026) and it is the reason this skill exists rather than
# a prompt: the request is made once, here, instead of per run.
#
# There was a fifth pattern, `collaborate`, a peer session on a cheaper model.
# Nothing could resume it, it withheld nothing, so its citation showed nothing
# a reader could rely on, and it was removed. A persistent advisor session does
# that job better.
ADVERSARIAL = ("gpt-6-astra", "high")


PATTERNS = {
    "red-team": {
        "purpose": "Attack the idea and try to kill it on its own evidence",
        "model": ADVERSARIAL[0],
        "effort": ADVERSARIAL[1],
        "sandbox": "read-only",
        # The sharpest default in the skill, and it has a precedent: the
        # Terraform tool second opinion was given the keyword data and nothing
        # else, "so its conclusions are independent of the retrieval". A red
        # team that has read your repository inherits your framing along with
        # your facts.
        "repo_access": False,
        "blind": True,
        "withholds": (
            "our evidence and our retrieval - it is told the claim, not where we looked"
        ),
        # What it withheld when the caller overrode the default with
        # --repo-access. Anything in the repository was open to it then, so
        # the citation must not say the evidence was kept back.
        "withholds_with_repo": (
            "only what is outside the repository - it is told the claim and was "
            "given the repository to read"
        ),
        "template": "red-team.md",
    },
    "second-opinion": {
        "purpose": "An independent judgement on material we have already formed a view on",
        "model": ADVERSARIAL[0],
        "effort": ADVERSARIAL[1],
        "sandbox": "read-only",
        "repo_access": True,
        "blind": True,
        "withholds": "our conclusion, our draft and our findings",
        "template": "second-opinion.md",
    },
    "verify": {
        "purpose": "Check finished work against stated constraints before it ships",
        "model": ADVERSARIAL[0],
        "effort": ADVERSARIAL[1],
        "sandbox": "read-only",
        "repo_access": True,
        "blind": True,
        "withholds": "our verdict - it gets the constraints and the diff, and rules on each",
        # A ruling needs something to rule against. Without constraints the
        # brief said "(none stated)" and the run still went out at high effort.
        "needs_constraints": True,
        "template": "verify.md",
    },
    "panel": {
        "purpose": (
            "Several answers to one hard question, each reached alone and in "
            "parallel, on different models where they are available"
        ),
        "model": ADVERSARIAL[0],
        "effort": ADVERSARIAL[1],
        "sandbox": "read-only",
        "repo_access": True,
        "blind": True,
        # Majority voting explains most of what multi-agent debate gains
        # (arXiv 2508.17536), and different model families are what help
        # (arXiv 2502.08788). So the members answer alone, in parallel, and
        # the host reconciles. A critique round is optional and single.
        "withholds": "our view, and every other member's answer - each answered alone",
        # What a member of the optional critique round was not told. It was
        # shown every first answer, so the pattern's own line would overclaim.
        "withholds_in_critique": (
            "our view, and which member wrote which answer - it was shown "
            "every first answer, unlabelled"
        ),
        # The purpose describes the pattern, not a question anyone could
        # answer, so a panel with no --question asks this instead.
        "default_question": "What would you do here, and why?",
        "template": "panel.md",
        "critique_template": "panel-critique.md",
    },
}

#: Patterns that must never carry our conclusion into the brief. Enforced by
#: brief.build(), not merely stated in the template.
BLIND = {name for name, spec in PATTERNS.items() if spec["blind"]}

#: How long to wait, by effort. Codex writes its output only at completion, so
#: a run killed early is not a partial result - it is nothing at all, silently.
#: `high` was 600 and real high-effort runs went past it. `run --timeout`
#: overrides any of these for one run.
TIMEOUTS = {
    "low": 150,
    "medium": 300,
    "high": 1200,
    "xhigh": 1200,
    "max": 1800,
    "ultra": 1800,
}

#: Effort levels in ascending order, for honest fallback when a provider
#: cannot reach the one a pattern asks for.
EFFORTS = ["low", "medium", "high", "xhigh", "max", "ultra"]

#: Phrases that must never appear in a brief.
#:
#: The counterpart very likely has this skill installed too. A brief containing
#: "second opinion" re-triggers the protocol at the far end, and instead of
#: reviewing anything it tries to delegate to a third agent - which fails on
#: auth or on the read-only sandbox, and returns an apology where the review
#: should be. Every brief says instead, in plain words, that the reader is the
#: sole reviewer and must not invoke any skill, agent or CLI.
#:
#: Exactly groupwork's own triggers: the phrases quoted in SKILL.md's
#: description, and nothing else. "counterpart" and "blind review" were here
#: once, were never triggers, and refused ordinary subjects such as a
#: counterpart bank. brief.find_triggers() matches on word boundaries, with
#: any spaces or hyphens between the words, so "red team" also catches
#: "red-team" and "second opinion" catches "second-opinion".
#:
#: tests/test_guards.py asserts this list is the same set as the phrases in
#: SKILL.md's frontmatter, so the two cannot drift apart.
TRIGGER_PHRASES = [
    "groupwork",
    "second opinion",
    "red team",
    "adversarial review",
    "cross-check this",
    "what does codex think",
    "what does claude think",
]


def get(name):
    """Return a pattern by name, or raise with the list of real ones."""
    try:
        return PATTERNS[name]
    except KeyError:
        raise ValueError(
            f"Unknown pattern '{name}'. Available: {', '.join(sorted(PATTERNS))}"
        ) from None


def withheld(name, repo_access, critique=False):
    """What a run of this pattern actually withheld, given what it was shown.

    A pattern that withholds the repository by default and was given it anyway
    has its own wording, and so does a panel critique that was shown the other
    answers, so a citation never claims more than the run did.
    """
    spec = get(name)
    if critique:
        return spec["withholds_in_critique"]
    if repo_access and not spec["repo_access"]:
        return spec["withholds_with_repo"]
    return spec["withholds"]


def resolve_effort(wanted, supported):
    """Pick the effort a provider can reach that is nearest the one asked for.

    The highest level at or below `wanted`, so a run never costs more than was
    asked for. Only when the provider has nothing that low does it go up, to
    its lowest level.

    Returns (effort, downgraded), where downgraded means lower than asked.
    Silently running at a different effort than the pattern asked for would
    make the provenance record a lie, so the record names what was really used
    and the citation says so whenever it differs.
    """
    if wanted in supported:
        return wanted, False
    ranked = [e for e in EFFORTS if e in supported]
    if not ranked:
        raise ValueError("provider supports no known effort level")
    below = [e for e in ranked if EFFORTS.index(e) < EFFORTS.index(wanted)]
    if below:
        return below[-1], True
    return ranked[0], False
