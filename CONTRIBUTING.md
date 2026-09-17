# Contributing

Issues and pull requests are welcome.

## Before you start

Read [`AGENTS.md`](AGENTS.md). It sets out the four rules pairwork does not
break and why each one exists. A change that weakens one will not be merged,
however convenient - they are the reason a pairwork citation means anything.

## Running the tests

```bash
python3 -m pytest skills/pairwork/tests -q
```

Python 3.9 or newer. Standard library plus pytest. Everything runs against a
stub provider, so you need no CLI installed, no credentials and no network.

## The most useful contribution

**A new provider.** One file in `skills/pairwork/scripts/providers/`, one line
in `REGISTRY`, three functions. `AGENTS.md` has the contract, and `opencode.py`
is the worked example of declaring a capability honestly rather than
generously.

If adding a provider requires touching anything outside that package, say so in
the pull request - it means something vendor-specific has leaked into the
runner, and that is worth fixing in the same change.

## Style

British English. Plain hyphens, never em or en dashes. No trailing full stop on
a heading. Comments explain why, not what - the code already says what.
