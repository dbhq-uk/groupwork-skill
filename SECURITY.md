# Security

## Reporting

Email **dan@dbhq.uk**. Please do not open a public issue for a vulnerability.

Expect an acknowledgement within a few days. If the report is valid you will be
credited in the fix unless you would rather not be.

## What groupwork does with your data

- **Briefs go to a third-party AI provider.** Whatever you put in `--subject`
  and `--context` is sent to whichever CLI you selected, and from there to that
  vendor. Treat a brief the way you would treat a prompt: do not put anything in
  it you would not send to OpenAI or whoever backs your opencode config.
- **Run records are kept locally**, in `~/.dbhq/groupwork/` at mode 700: the
  brief each run was sent, its raw output and log, and a JSONL line when each
  run starts and another when it ends. Nothing is uploaded anywhere by
  groupwork itself.
- **No credentials are stored.** Every provider authenticates itself through its
  own CLI. groupwork holds no token and writes no config.

## Sandboxing, honestly

All four patterns run read-only by default, and `--allow-write` requires an
explicit decision per run.

"Read-only" is not the same guarantee on every provider:

- **codex** passes `--sandbox read-only` and the kernel enforces it. That
  blocks writes, not reads. A `red-team` run without the repository uses a
  Codex permission profile instead, readable only for the platform's runtime
  paths and an empty working directory, with no network, and is started in that
  directory. If Codex cannot start its sandbox on the host, the run fails before
  the session begins rather than running with the repository readable.
- **opencode** has no sandbox, and most of its tools are allowed by default.
  groupwork passes an inline config in `OPENCODE_CONFIG_CONTENT` that denies
  `edit`, `webfetch`, `websearch`, `task`, `skill` and `external_directory`,
  both globally and on the `build` agent the run uses. Out of `bash` it allows
  five exact commands and nothing else: `git status`, `git log`, `git diff`,
  `git show` and `git ls-files`, each with no argument, because a git flag is
  how a command gets out of the working directory. A pattern that withholds the
  repository gets no `bash` at all. Inline config outranks project and user
  config. This is a tool-permission deny enforced by opencode, not a sandbox: a
  bug in its permission checks is not contained. The citation names the provider
  so a reader can weigh it.

If you need a hard boundary, use codex.
