# Working on groupwork

Read this before changing anything in `skills/groupwork/scripts/`.

## The thing that makes this skill worth having

Not the CLI wrapping. Anyone can shell out to `codex exec`, and OpenAI ship a
better-plumbed version of that themselves.

What groupwork has is a **withholding rule per pattern, enforced in code, and
recorded at the moment of the run**. A red-team citation says the counterpart
was starved of the material because it demonstrably was - it ran in an empty
directory, and the field saying so was copied from the pattern definition rather
than typed by anybody.

Every change has to leave that true. If a change makes it easier to produce a
citation that overstates what was withheld, it is the wrong change however
convenient.

## The four rules

Each has tests in `skills/groupwork/tests/`. Do not weaken one to make something
else easier.

### 1. A blind pattern's brief never carries our conclusion

`brief.build()` raises if `our_view` is passed at all, because every pattern
is blind: `red-team`, `second-opinion`, `verify` and `panel`. It also raises if any run of six words from
`assert_withholds` is found in what the caller supplied, after lower-casing and
stripping punctuation and markdown. That catches the honest mistake of pasting a
conclusion into `--context`, including with a comma added or a word changed.

A blind pattern also refuses to build without either `assert_withholds` or
`no_prior_view`. The result, `passed` or `not-run`, travels with the brief as a
`Brief` string and is copied into the ledger and the citation by the runner. The
brief itself is kept as `runs/<id>.brief.md`, and its sha256 goes in the
citation.

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

### 3. No brief contains groupwork's own trigger phrases

The far end very likely has this skill installed. A brief containing "second
opinion" fires its copy of the protocol, which tries to delegate to a third
agent, fails on auth or the read-only sandbox, and returns an apology where the
review should be. You pay for the run and get a polite note.

`patterns.TRIGGER_PHRASES` is the list, and it is exactly the phrases quoted in
the `SKILL.md` description. Nothing else goes in it: a word that is not a
trigger only refuses ordinary subjects, as "counterpart" once refused a brief
about a counterpart bank. `brief.build()` refuses any brief containing one as
whole words, with any spaces or hyphens between them, so "red team" also
catches "red-team". A test asserts the list and the quoted phrases are the same
set, so a trigger added in one place and not the other fails CI.

A panel's critique round is the one place a model's own words go into a brief.
They go in after the check, never before it. An answer that happens to use a
trigger phrase must not refuse a round when the first round has already been
paid for, and the caller cannot reword a model's answer.

The phrases are the first guard. The second does not depend on wording: every
provider child is started with `GROUPWORK_DEPTH` in its environment, by
`spawn()` in `providers/base.py`, and `groupwork.py` refuses `run` and `panel`
while it is set. A new provider gets this by using `spawn()`.

### 4. No write sandbox without a decision in that run

All four patterns are `read-only`. `--allow-write` is not sticky, is not read
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
  claiming the guarantee Codex gives. It is called after `probe()`, so it can
  list only the models this machine can reach and name the CLI's own
  `default_model`. The runner uses the pattern's model if it is listed, then
  that default, and otherwise refuses and asks for `--model`. It never picks a
  model nobody chose.
- `run()` - brief in from a file on stdin, answer out to a file, raise on
  failure.

Never claim a capability the CLI does not have. The runner passes capabilities
straight into the provenance record, so an overstated `capabilities()` becomes
an overstated citation.

## Changing a pattern

`patterns.py` is the product. A change there is a change to what a groupwork
citation means, so:

- Changing `withholds` changes what every past citation of that pattern claimed.
  Think about whether it is really the same pattern.
- Changing `repo_access` on `red-team` removes the sharpest thing in the skill.
  It is `False` for a reason, with a precedent, and there is a test.
- Changing a model or effort changes what runs cost. `ADVERSARIAL` is
  `gpt-6-astra` at `high` deliberately. A user without it sets
  `GROUPWORK_<PROVIDER>_MODEL` or `config.json` in the state directory, and the
  citation records the model that ran. A model a CLI version cannot run goes
  in that provider's `unreachable`, so the run is refused before it starts.
- Every pattern is blind. A pattern that takes our view withholds nothing, so
  its citation shows nothing a reader can rely on. That is why `collaborate`
  was removed.

## Templates

Prose, in `skills/groupwork/templates/`. Two constraints beyond taste:

- No trigger phrases (rule 3, tested per template).
- Never ask the counterpart to change anything. A read-only sandbox asked to
  edit produces a stalled run and a timeout, not a clean refusal. Tested.

## Tests

```bash
python3 -m pytest skills/groupwork/tests -q
```

Standard library plus pytest. Everything runs against a stub provider, so no
CLI, no credentials and no network are needed.

## House style

British English. Plain hyphens, never em or en dashes. No trailing full stop on
a heading. `groupwork` is lowercase everywhere, including at the start of a
sentence - but the products it talks to keep their own capitalisation: Codex,
GitHub Copilot, opencode as its own project styles it.
