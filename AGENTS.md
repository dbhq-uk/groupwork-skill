# Working on pairwork

Read this before changing anything in `skills/pairwork/scripts/`.

## The thing that makes this skill worth having

Not the CLI wrapping. Anyone can shell out to `codex exec`, and OpenAI ship a
better-plumbed version of that themselves.

What pairwork has is a **withholding rule per pattern, enforced in code, and
recorded at the moment of the run**. A red-team citation says the counterpart
was starved of the material because it demonstrably was - it ran in an empty
directory, and the field saying so was copied from the pattern definition rather
than typed by anybody.

Every change has to leave that true. If a change makes it easier to produce a
citation that overstates what was withheld, it is the wrong change however
convenient.

## The four rules

Each has tests in `skills/pairwork/tests/`. Do not weaken one to make something
else easier.

### 1. A blind pattern's brief never carries our conclusion

`brief.build()` raises if `our_view` is passed to `red-team`, `second-opinion`,
`verify` or `debate`. It also raises if `assert_withholds` text is found in the
assembled brief, which catches the honest mistake of pasting a conclusion into
`--context`.

Do not make this a warning. A caller who believes the counterpart saw their
reasoning, and a counterpart that did not, are the two halves of a provenance
line that is false.

### 2. Empty output is a failure, never a clean review

The single most dangerous failure this skill has. Codex writes `-o` only at
completion, so a run killed at a timeout leaves a zero-byte file and an exit
status that looks survivable. Copilot has an open bug where it exits 0 having
written nothing at all ([#1181](https://github.com/github/copilot-cli/issues/1181)).

Read either as success and you report "the reviewer found no issues" about a
review that never happened. `runner.run()` raises instead.

### 3. No brief contains pairwork's own trigger phrases

The far end very likely has this skill installed. A brief containing "second
opinion" fires its copy of the protocol, which tries to delegate to a third
agent, fails on auth or the read-only sandbox, and returns an apology where the
review should be. You pay for the run and get a polite note.

`patterns.TRIGGER_PHRASES` is the list; `brief.build()` refuses any brief
containing one. A test asserts the list covers every phrase quoted in `SKILL.md`
frontmatter, so adding a trigger there without adding it here fails CI.

### 4. No write sandbox without a decision in that run

All five patterns are `read-only`. `--allow-write` is not sticky, is not read
from config, and requires the caller to have asked the user in that run.

## Adding a provider

A new provider is one file in `scripts/providers/` and one line in
`REGISTRY`. Nothing else should need to change - if it does, something
vendor-specific has leaked out of the provider package, and that is the bug.

Implement three things:

- `probe()` - return the version if installed **and authenticated**, else raise
  `ProviderError` with a reason a human can act on. Auth is the real barrier;
  every one of these CLIs installs in a second and then refuses to run.
- `capabilities()` - what it can actually do. Be honest here. `opencode.py` is
  the worked example: it declares only `read-only` because it has no sandbox to
  enforce anything stronger, and its docstring says so plainly rather than
  claiming the guarantee Codex gives.
- `run()` - brief in from a file on stdin, answer out to a file, raise on
  failure.

Never claim a capability the CLI does not have. The runner passes capabilities
straight into the provenance record, so an overstated `capabilities()` becomes
an overstated citation.

## Changing a pattern

`patterns.py` is the product. A change there is a change to what a pairwork
citation means, so:

- Changing `withholds` changes what every past citation of that pattern claimed.
  Think about whether it is really the same pattern.
- Changing `repo_access` on `red-team` removes the sharpest thing in the skill.
  It is `False` for a reason, with a precedent, and there is a test.
- Changing a model or effort changes what runs cost. `ADVERSARIAL` is
  `gpt-6-astra` at `high` deliberately, and `collaborate` is deliberately not.

## Templates

Prose, in `skills/pairwork/templates/`. Two constraints beyond taste:

- No trigger phrases (rule 3, tested per template).
- Never ask the counterpart to change anything. A read-only sandbox asked to
  edit produces a stalled run and a timeout, not a clean refusal. Tested.

## Tests

```bash
python3 -m pytest skills/pairwork/tests -q
```

Standard library plus pytest. Everything runs against a stub provider, so no
CLI, no credentials and no network are needed.

## House style

British English. Plain hyphens, never em or en dashes. No trailing full stop on
a heading. `pairwork` is lowercase everywhere, including at the start of a
sentence - but the products it talks to keep their own capitalisation: Codex,
GitHub Copilot, opencode as its own project styles it.
