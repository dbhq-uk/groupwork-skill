# Security

## Reporting

Email **dan@dbhq.uk**. Please do not open a public issue for a vulnerability.

Expect an acknowledgement within a few days. If the report is valid you will be
credited in the fix unless you would rather not be.

## What pairwork does with your data

- **Briefs go to a third-party AI provider.** Whatever you put in `--subject`
  and `--context` is sent to whichever CLI you selected, and from there to that
  vendor. Treat a brief the way you would treat a prompt: do not put anything in
  it you would not send to OpenAI, GitHub or whoever backs your opencode config.
- **Run records are kept locally**, in `~/.dbhq/pairwork/` at mode 700: the raw
  output of each run and one JSONL line per run. Nothing is uploaded anywhere by
  pairwork itself.
- **No credentials are stored.** Every provider authenticates itself through its
  own CLI. pairwork holds no token and writes no config.

## Sandboxing, honestly

All five patterns run read-only by default, and `--allow-write` requires an
explicit decision per run.

"Read-only" is not the same guarantee on every provider:

- **codex** passes `--sandbox read-only` and the kernel enforces it.
- **opencode** has no sandbox. Read-only there means `--auto` is not passed, so
  a write attempt waits on a permission prompt nobody can answer, and is killed
  by the timeout. That is weaker, it is recorded, and the citation names the
  provider so a reader can weigh it.
- **copilot** is given narrow tool permissions by name rather than `--allow-all`.

If you need a hard boundary, use codex.
