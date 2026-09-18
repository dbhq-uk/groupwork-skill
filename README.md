<div align="center">

<img src="assets/logo.svg" alt="groupwork - a second agent on the work, by DBHQ" width="560">

# groupwork

**A second agent on the work - as an adversary, or as a partner**

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Claude Code](https://img.shields.io/badge/Claude_Code-Plugin-blueviolet)](https://code.claude.com/docs/en/plugins)
[![Platform](https://img.shields.io/badge/Platform-Linux%20%7C%20macOS%20%7C%20WSL-lightgrey)]()

A free, open-source tool by [DBHQ](https://dbhq.uk) - documented at [skills.dbhq.uk](https://skills.dbhq.uk/groupwork/)

</div>

---

Put a second agent on the work - as an adversary or as a partner - and get back
a result you can cite.

## What makes it different

Five named patterns for using a second AI agent, running on Codex, opencode or
GitHub Copilot behind one provider layer.

The patterns are the product. The reason this is not a wrapper around
`codex exec` is the **withholding rule**: a second opinion that has already been
told your conclusion is not a second opinion, it is agreement with extra steps.
Three of the five patterns refuse to carry your view at all, and the refusal is
enforced in code rather than requested in prose.

| Pattern | Use it when | It is not told |
|---|---|---|
| `red-team` | You want the idea killed if it deserves killing | Your evidence, and by default the repository itself |
| `second-opinion` | You have a view and want one reached without it | Your conclusion, draft or findings |
| `verify` | Work is finished and about to ship | Whether anyone thinks it passes |
| `collaborate` | You are thinking out loud and want a peer | Nothing - it gets the full picture |
| `debate` | A hard call where the trade-off is the answer | The other side, in round 0 |

## Install

### As a Claude Code plugin (recommended)

```
/plugin marketplace add dbhq-uk/marketplace
/plugin install groupwork@dbhq
```

### Any agent (Cursor, Copilot, Windsurf, Gemini, Cline and more)

```bash
npx skills add dbhq-uk/groupwork-skill
```

The [skills.sh](https://skills.sh) CLI installs into whichever agent directories
it finds, so this works outside Claude Code and Codex too.

### Local install (Claude Code or Codex)

```bash
git clone https://github.com/dbhq-uk/groupwork-skill.git
cd groupwork-skill
./install.sh          # Claude Code: symlinks into ~/.claude/skills (edits are live)
./install-codex.sh    # Codex: installs into ~/.codex/skills
```

[`install.sh`](install.sh) and [`install-codex.sh`](install-codex.sh) are the
same install two ways: Claude Code substitutes `${CLAUDE_SKILL_DIR}`, so the
whole skill directory is symlinked untouched, while Codex does not, so its
`SKILL.md` is rewritten at install time. Re-run the Codex one after editing
`SKILL.md`.

## Requirements

Python 3.9 or newer, standard library only. At least one provider CLI installed
**and authenticated** - that is the real barrier to entry, not the install.

State lives in `~/.dbhq/groupwork/` (mode 700): raw output per run, and one JSONL
line each in `runs.jsonl`. No credentials are stored; every provider
authenticates itself.

## Why the withholding matters

Research write-ups routinely carry a line like *"given the keyword data but none
of the community evidence, so its conclusions are independent of the
retrieval"*. A reader's only reason to trust that finding is the claim that the
reviewer really was starved of the material - and that claim is almost always
written afterwards, from memory, by the person who ran it.

groupwork writes the record at the moment of the run, from the pattern
definition. Nobody types the independence claim, so nobody can type one that is
not true.

```
**Red team:** `gpt-6-astra` via codex (codex-cli 0.154.0), 2026-09-17,
read-only, no repository access. Run `20260917T165202Z-a037c3`, withheld: our
evidence and our retrieval - it is told the claim, not where we looked.
```

## Use

```bash
# which counterparts are installed AND authenticated - not the same thing
python3 scripts/groupwork.py providers

# attack an idea, without showing it where you looked
python3 scripts/groupwork.py run red-team \
  --subject "a CLI that posts physical letters, priced per letter" \
  --context "UK only. Signed For and Tracked. No subscription."

# an independent read of a document, with a guard against your own view leaking in
python3 scripts/groupwork.py run second-opinion \
  --subject "the recommendation in docs/research/foo.md" \
  --assert-withholds "$MY_DRAFT_CONCLUSION"

# blind proposals, then adversarial rounds, fresh session each time
python3 scripts/groupwork.py debate --subject "queue or cron" --rounds 2

python3 scripts/groupwork.py history
```

`--dry-run` prints the brief and runs nothing, so you can read what will be sent
before paying for it.

## Providers

| Provider | Notes |
|---|---|
| `codex` | The default. Real kernel-enforced `--sandbox read-only`. Verified |
| `opencode` | Multi-model, so Gemini, Grok, Qwen and local models arrive behind one adapter. Verified |
| `copilot` | No separate login where `gh` already works. **Experimental: the adapter has never been run against the real CLI** |

**The copilot adapter has never been run against the real CLI.** It is written
from Copilot's own documentation and issue tracker, so the two bugs it codes
around have not been seen to fire and the flag shapes are documented rather than
observed. `groupwork providers` labels it, and any citation from a run through it
carries the caveat - because a reader of the finding is the person who needs to
know, and a README is not where they will look. Use `codex` or `opencode` where
the answer matters, and please report what breaks.

One honest difference, stated rather than papered over: Codex takes
`--sandbox read-only` and the kernel enforces it. opencode has no sandbox -
read-only there means `--auto` is not passed, so a write attempt stalls instead
of being refused. Both are recorded and the citation names the provider.

`claude -p` is deliberately absent. Run from inside Claude Code the counterpart
would be the same model family as the host unless a different model is pinned,
and "two models fail differently" is the entire premise. It becomes worth
writing the day somebody runs groupwork from Codex.

## Four rules it will not break

Each has a test. `AGENTS.md` is the file to read before changing anything.

1. **A blind pattern's brief never carries your conclusion.** Passing it is an
   error, not a silently ignored argument.
2. **Empty output is a failure, never a clean review.** Codex writes its result
   only at completion, so a killed run leaves a zero-byte file; Copilot has a
   bug where it exits 0 having written nothing. Both otherwise read as "the
   reviewer found no issues".
3. **No brief contains groupwork's own trigger phrases.** The far end very likely
   has this skill installed; a brief saying "second opinion" trips its copy,
   which tries to delegate to a third agent and returns an apology instead of a
   review.
4. **No write sandbox without a decision in that run.** All five patterns are
   read-only by default.

## What it will not do

- **Delegate work.** There is no "go and build this" mode. OpenAI's own
  [codex-plugin-cc](https://github.com/openai/codex-plugin-cc) already does that
  well, and it is the mode where a sandbox mistake costs real money.
- **Write findings into your repo.** It records the run and hands you a
  citation. Where a finding belongs is your call.
- **Score or benchmark the counterpart.** It reports what the other agent said.

## Also from DBHQ

Sixteen free agent skills, all of them installable from the same marketplace and
all documented at **[skills.dbhq.uk](https://skills.dbhq.uk)**. The marketplace
itself is [dbhq-uk/marketplace](https://github.com/dbhq-uk/marketplace) - one
`/plugin marketplace add` and every one of them is available.

| Skill | What it does |
|---|---|
| [outlook](https://skills.dbhq.uk/outlook/) | Microsoft 365 mail and calendar, from the terminal |
| [trello](https://skills.dbhq.uk/trello/) | Your boards, run from your agent |
| [legwork](https://skills.dbhq.uk/legwork/) | Research that settles a decision, and says when it cannot |
| [dovetail](https://skills.dbhq.uk/dovetail/) | Checks whether your repository still agrees with itself |
| [verve](https://skills.dbhq.uk/verve/) | Strips AI tells from prose and puts a voice back |
| [vela](https://skills.dbhq.uk/vela/) | Compiler-exact code search, in any language you index |
| [garmin](https://skills.dbhq.uk/garmin/) | Your Garmin data, answered in the terminal |
| [imager](https://skills.dbhq.uk/imager/) | Images from GPT Image 2, costed before it spends |
| [gitview](https://skills.dbhq.uk/gitview/) | Which branches are finished, and safe to delete |
| [atlassian](https://skills.dbhq.uk/atlassian/) | Jira issues and Confluence pages |
| [pennyblack](https://skills.dbhq.uk/pennyblack/) | A physical letter, posted from the terminal |
| [buildwork](https://skills.dbhq.uk/buildwork/) | Your open issues, run as parallel agents |
| [deskwork](https://skills.dbhq.uk/deskwork/) | What an agent noticed, tracked as real work |

Plus [heliograph](https://skills.dbhq.uk/heliograph/), for a machine you cannot log into.

## Licence

MIT. Built by [DBHQ](https://dbhq.uk).
