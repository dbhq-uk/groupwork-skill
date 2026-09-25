---
name: groupwork
description: >-
  Put a second agent on the work - as an adversary or as a partner - and get
  back a result you can cite. Five named patterns: red-team attacks an idea
  without being shown your evidence, second-opinion judges your material
  without being shown your conclusion, verify rules on finished work against
  stated constraints, collaborate is a peer conversation, and debate runs blind
  proposals into adversarial rounds. Runs on Codex or opencode behind one
  provider layer. Use when the user says "groupwork", "second opinion",
  "red team", "adversarial review", "cross-check this", "what does codex think",
  "what does claude think", or wants independent eyes before something ships.
license: MIT
---

# groupwork

A second agent on the work. The patterns are the product; the CLI underneath is
swappable.

The reason this is not a wrapper around `codex exec` is the **withholding
rule**. A second opinion that has already been told your conclusion is not a
second opinion, it is agreement with extra steps. Three of the five patterns
therefore refuse to carry your view at all, and the refusal is enforced in code.

## Pick the pattern first

| Pattern | Use it when | It is not told |
|---|---|---|
| `red-team` | You want the idea killed if it deserves killing | Your evidence, and by default the repository itself |
| `second-opinion` | You have a view and want one reached without it | Your conclusion, draft or findings |
| `verify` | Work is finished and about to ship | Whether anyone thinks it passes |
| `collaborate` | You are thinking out loud and want a peer | Nothing - it gets the full picture |
| `debate` | A hard call where the trade-off is the answer | The other side, in round 0 |

Two that look alike and are not: `red-team` is handed a claim and told to break
it, deliberately starved of the material so its attack cannot inherit your blind
spots. `second-opinion` is handed the material and asked to reach its own
judgement. Use `red-team` on an idea, `second-opinion` on a document.

Do not burn a run on something cheap. Naming, style, "what does this code do" -
read it yourself. These calls are slow and they cost money.

## Check what is available

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/groupwork.py providers
```

Installed is not the same as authenticated, and every one of these CLIs installs
in a second and then refuses to run. The command distinguishes the two.

## Run one

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/groupwork.py run second-opinion \
  --subject "the Terraform tool research in docs/research/..." \
  --context "$(gh pr view 12 --json title,body -q '.body')" \
  --question "does the recommendation survive its own evidence?" \
  --assert-withholds "$MY_DRAFT_CONCLUSION"
```

**A blind pattern needs `--assert-withholds` or `--no-prior-view`, and is
refused without one.** Give `--assert-withholds` your draft conclusion, in at
least six words. Nothing is added to the brief - it is checked for absence. Any
run of six words from it that turns up in `--subject`, `--context`,
`--question` or `--constraints` refuses the run before it costs anything, so a
comma, a word in bold or one changed word does not get it past.

Pass `--no-prior-view` only when you have not formed a view yet. The citation
then says the leak check did not run and that you declared no view, rather
than implying a check that never happened.

Use `--dry-run` to read the brief before spending on it.

### Before you run

The counterpart is sandboxed with no network and no access to this
conversation. **Anything from outside the repository has to be fetched by you
now and put in `--context`**: PR bodies, issue text, acceptance criteria that
exist only in this session, the page you read earlier. It cannot go and look.

### Resolving the subject

First match wins:

1. What the user named explicitly.
2. What this session has been working on.
3. The branch's work: `git log --oneline main..HEAD` plus `git status --short`.
4. Nothing found - ask, and stop.

## Debate

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/groupwork.py debate \
  --subject "queue or cron for the nightly reconcile" --rounds 2 \
  --no-prior-view
```

Round 0 is blind. Each later round shows the previous position and asks for an
attack on its reasoning. Every round is a **fresh session** - a reviewer that
already argued a position defends it rather than re-examining it, and a resumed
session produces entrenchment while looking like convergence.

The output is not a winner. It is: where the rounds agreed, which you can rely
on, and where they diverged, which is the real trade-off and yours to settle.

## Reading the result

Treat the counterpart as a colleague, not an authority.

- **Trust your own knowledge when you are confident.** If it says something you
  know is wrong, push back rather than deferring.
- **Check disagreements** against documentation or the web before accepting a
  claim, particularly about model names, recent releases and API changes, where
  its cutoff bites.
- **Disagreement is the signal.** Where the two of you differ is where the risk
  lives. Say so to the user and give both readings rather than silently picking.
- **An empty result is a failed run, never a clean review.** The skill enforces
  this, but if you ever see a zero-byte output reported as success, that is a
  bug worth reporting.

## Citing it

Every run appends to `~/.dbhq/groupwork/runs.jsonl` and keeps the exact brief
it was sent and its raw output in `~/.dbhq/groupwork/runs/`. The command prints
a citation line built from what actually happened - model, provider, CLI
version, sandbox, what the brief withheld, whether the leak check ran, and the
sha256 of the stored brief. Paste that line into whatever document the finding
lands in.

The `withheld` field is copied from the pattern definition, not typed by anyone,
so a `red-team` citation cannot claim an independence the run did not have. A
`red-team` run given `--repo-access` says the repository was open to it rather
than claiming the evidence was withheld.

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/groupwork.py history --limit 10
python3 ${CLAUDE_SKILL_DIR}/scripts/groupwork.py show 20260917T143000Z-a1b2c3
```

## Providers

`codex` by default. `opencode` carries other model families behind one adapter.

Two differences worth stating rather than papering over:

**Sandboxing is not the same guarantee everywhere.** Codex takes
`--sandbox read-only` and the kernel enforces it. opencode has no sandbox, and
most of its tools are allowed by default. groupwork passes it deny rules for
file edits, bash (apart from read-only `git`), web fetch and search, sub-agents,
skills and directories outside the working one. opencode enforces those itself,
which is weaker than a kernel sandbox. The citation names the provider.

**There is no `copilot` provider for now.** An adapter exists in the source,
but it has never been run against the real CLI and could not complete a run, so
it is not registered. It comes back once it has been verified.

## What this will not do

- **Delegate work.** There is no "go and build this" mode. Sandbox mistakes cost
  real money there, and OpenAI's own plugin already does it well.
- **Write findings into the repo.** It records the run and hands you a citation.
  Where a finding belongs is your call, not a guess.
- **Merge, commit or change anything.** Read-only is the default for all five
  patterns, and a write sandbox needs a decision from the user in that run.
