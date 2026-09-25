"""Provider registry.

To add a provider, write a module here that subclasses Provider and add it
below. Nothing else in groupwork changes: the patterns, the briefs, the
withholding rules and the provenance record are all provider-neutral, which is
the point of the layer.

`claude -p` is the obvious next one and is deliberately absent. Run from inside
Claude Code the counterpart would be the same model family as the host unless a
different model is pinned, and "two models fail differently" is the entire
premise. It becomes worth writing the day somebody runs groupwork from Codex.
"""

from .base import Provider, ProviderError  # noqa: F401  (re-exported)
from .codex import Codex
from .opencode import Opencode

#: Only providers that can complete a run. copilot.py is deliberately absent:
#: its adapter was written from documentation, has never run against the real
#: CLI, and failed every run on its own effort list. Its module docstring says
#: what it needs before it comes back.
REGISTRY = {
    Codex.name: Codex,
    Opencode.name: Opencode,
}

DEFAULT = Codex.name


def get(name=None, config=None):
    """Build a provider by name."""
    name = name or DEFAULT
    try:
        cls = REGISTRY[name]
    except KeyError:
        raise ValueError(
            f"Unknown provider '{name}'. Available: {', '.join(sorted(REGISTRY))}"
        ) from None
    return cls(config)


def host():
    """The registered provider whose CLI groupwork is running inside, or None."""
    for name, cls in REGISTRY.items():
        if cls.is_host():
            return name
    return None


def available(config=None):
    """Every provider that is installed and authenticated, with its version.

    Returns {name: version} for the ones that work and {name: reason} for the
    ones that do not, because "not installed" and "installed but logged out"
    need different answers from the user.
    """
    working, broken = {}, {}
    for name, cls in REGISTRY.items():
        try:
            working[name] = cls(config).probe()
        except ProviderError as exc:
            broken[name] = str(exc)
    return working, broken
