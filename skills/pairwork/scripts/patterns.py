"""The five patterns. This file is the product.

Everything else in pairwork is plumbing that exists to run one of these
faithfully and record what happened. A pattern is four things:

  - a model and effort, because an adversary is worth paying for and a
    conversation is not;
  - a sandbox, which is read-only for all five;
  - a **withholding rule**, which is the part that makes the result citable;
  - a brief template that says all of it to the counterpart.

The withholding rule is why this is not a wrapper. A second opinion that has
already been told your conclusion is not a second opinion, it is agreement with
extra steps. Three of the five patterns therefore refuse to carry your view at
all, and the refusal is enforced in code rather than requested in prose.
"""

# --- Model policy -----------------------------------------------------------
#
# Adversarial work gets the frontier model at high effort. That is a standing
# decision (Dan, 17 Sep 2026) and it is the reason this skill exists rather than
# a prompt: the request is made once, here, instead of per run.
#
# Collaboration does not get it. A resumable back-and-forth is many turns, and
# neither the cost nor the latency is earned when the job is thinking out loud
# with somebody.
ADVERSARIAL = ("gpt-6-astra", "high")
COLLABORATIVE = ("gpt-5.6-sol", "medium")


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
        "template": "verify.md",
    },
    "collaborate": {
        "purpose": "A resumable peer session where disagreement is a discussion",
        "model": COLLABORATIVE[0],
        "effort": COLLABORATIVE[1],
        "sandbox": "read-only",
        "repo_access": True,
        "blind": False,
        "withholds": "nothing - it is working with you, so it gets the full picture",
        "template": "collaborate.md",
    },
    "debate": {
        "purpose": (
            "Blind proposals, adversarial critique, early stop on convergence, "
            "then synthesis"
        ),
        "model": ADVERSARIAL[0],
        "effort": ADVERSARIAL[1],
        "sandbox": "read-only",
        "repo_access": True,
        "blind": True,
        "withholds": "each other, in round 0",
        "template": "debate.md",
    },
}

#: Patterns that must never carry our conclusion into the brief. Enforced by
#: brief.build(), not merely stated in the template.
BLIND = {name for name, spec in PATTERNS.items() if spec["blind"]}

#: How long to wait, by effort. Codex writes its output only at completion, so
#: a run killed early is not a partial result - it is nothing at all, silently.
TIMEOUTS = {
    "low": 150,
    "medium": 300,
    "high": 600,
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
#: tests/test_guards.py asserts this list covers every trigger phrase in
#: SKILL.md's own frontmatter, so the two cannot drift apart.
TRIGGER_PHRASES = [
    "pairwork",
    "second opinion",
    "red team",
    "red-team",
    "adversarial review",
    "cross-check this",
    "what does codex think",
    "what does claude think",
    "blind review",
    "counterpart",
]


def get(name):
    """Return a pattern by name, or raise with the list of real ones."""
    try:
        return PATTERNS[name]
    except KeyError:
        raise ValueError(
            f"Unknown pattern '{name}'. Available: {', '.join(sorted(PATTERNS))}"
        ) from None


def resolve_effort(wanted, supported):
    """Pick the highest effort a provider can actually reach.

    Returns (effort, downgraded). Silently running at a lower effort than the
    pattern asked for would make the provenance record a lie, so the caller is
    told and the record names what was really used.
    """
    if wanted in supported:
        return wanted, False
    ranked = [e for e in EFFORTS if e in supported]
    if not ranked:
        raise ValueError("provider supports no known effort level")
    ceiling = ranked[-1]
    return ceiling, True
