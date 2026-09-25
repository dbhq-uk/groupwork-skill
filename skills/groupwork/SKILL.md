---
name: groupwork
description: >-
  Put a second agent on the work - as an adversary or as a partner - and get
  back a result you can cite. Five named patterns: red-team attacks an idea
  without being shown your evidence, second-opinion judges your material
  without being shown your conclusion, verify rules on finished work against
  stated constraints, collaborate is a peer conversation, and panel puts one
  hard question to several models at once, each answering alone. Runs on Codex
  or opencode behind one
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
| `panel` | A hard call where the trade-off is the answer | Your view, and each other's answers |

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

**Always pass `--background`, then poll.** A run at `high` effort can take more
than ten minutes, and one at `max` more than twenty. That is longer than most
hosts let one command run: the Claude Code Bash tool stops a command after two
minutes by default and ten at most. A host that stops a foreground run loses
it.

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/groupwork.py run second-opinion --background \
  --subject "the Terraform tool research in docs/research/..." \
  --context "$(gh pr view 12 --json title,body -q '.body')" \
  --question "does the recommendation survive its own evidence?" \
  --assert-withholds "$MY_DRAFT_CONCLUSION"
```

It builds the brief, starts the run detached and prints the run id at once. A
brief that would be refused is refused there and then, before anything starts.
Then check on it, a minute or two apart, each check a short command of its own:

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/groupwork.py status 20260925T101500Z-a1b2c3
python3 ${CLAUDE_SKILL_DIR}/scripts/groupwork.py result 20260925T101500Z-a1b2c3
```

`status` says `running`, `done` or `failed`, with the reason for a failure.
`result` prints the answer and the citation once the run is done. It exits 3
while the run is still going, and 1 if it failed. Carry on with other work
between checks rather than sleeping through the whole run in one command.

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

Runs are slow. The time limit follows the effort: 20 minutes at `high`, 30 at
`max`. `--timeout N` sets a different limit, in seconds, for one run. A run
that hits its limit is stopped completely, including every process the CLI
started, and nothing is salvaged, because Codex writes its answer only at the
end.

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

## Panel

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/groupwork.py panel --background \
  --subject "queue or cron for the nightly reconcile" \
  --no-prior-view
```

A panel puts the same brief to at least two members at once: one per ready
provider, or two on the only one that is ready. Each answers alone, in its own
session, without sight of the others. Every answer is kept, and each member is
an ordinary run with its own citation. A panel of two is two runs at `high`
effort, so it costs twice what one run does.

Answers from different model families are worth more than two from one. Name
the members as `provider` or `provider:model` when opencode has another family
signed in: `--members codex,opencode:google/gemini-3-pro`.

`status` and `result` take the panel id as they take a run id. `result` prints
every answer, labelled A, B and so on, then a citation for each.

Then reconcile them yourself, and tell the user: what every answer agrees on,
which can be relied on; where they differ, which is the real trade-off and the
user's to settle; and what only one of them raised, which needs checking before
you believe it. If every answer came from one model family, `result` says so,
and agreement then counts for less.

`--critique` adds one more round. Each member, in a fresh session, is shown
every first answer, unlabelled and in no particular order, and asked to attack
the reasoning. That doubles the cost again. Most of the gain comes from
comparing answers reached alone, so use it only when the first answers
disagree and you cannot tell why.

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

A run that fails, times out or is stopped is in the ledger too: one line when
it starts and one when it ends, so `history` marks it `[failed]`,
`[timed out]` or `[stopped]`. `show` on one of those prints what went wrong and
where its log is, and no citation, because there is no finding to cite.

## Providers

`codex` by default. `opencode` carries other model families behind one adapter.

Two differences worth stating rather than papering over:

**Sandboxing is not the same guarantee everywhere.** Codex takes
`--sandbox read-only` and the kernel enforces it. That blocks writes, not reads,
so a `red-team` run without the repository uses a Codex permission profile
instead: it can read only the platform's runtime paths and an empty directory,
with no network, and it is started in that directory. Where Codex cannot start
its sandbox on the machine, the session fails before it begins and groupwork
says so; `--repo-access` is the deliberate alternative, and the citation then
says the repository was open to it. opencode has no sandbox, and
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
