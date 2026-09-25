import os
import pathlib
import sys

import pytest

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))


@pytest.fixture(autouse=True)
def _no_outside_choices(monkeypatch):
    """A model override or a Codex host in the caller's shell must not leak in."""
    for name in list(os.environ):
        if name.startswith("GROUPWORK_") and name.endswith("_MODEL"):
            monkeypatch.delenv(name)
    for name in ("CODEX_THREAD_ID", "CODEX_SANDBOX", "CODEX_SANDBOX_NETWORK_DISABLED"):
        monkeypatch.delenv(name, raising=False)


# A stand-in for a provider CLI, so the real adapters can be driven end to end
# without installing, authenticating or paying for anything. It answers
# `--version`, reads the brief from stdin, and writes a canned finding to the
# `-o` path when there is one (Codex) or to stdout otherwise (opencode).
FAKE_CLI = """#!/bin/bash
if [ "$1" = "--version" ]; then echo "fake-cli 1.0"; exit 0; fi
out=""
prev=""
for arg in "$@"; do
  if [ "$prev" = "-o" ]; then out="$arg"; fi
  prev="$arg"
done
cat > /dev/null
answer='1. **minor** somewhere:1 - a canned finding'
if [ -n "$out" ]; then printf '%s\\n' "$answer" > "$out"; else printf '%s\\n' "$answer"; fi
"""


# How the real CLIs answer the free checks a probe makes: `codex login status`,
# and opencode's `auth list`, `models` and `debug config`. Signed in, with
# OpenAI reachable through opencode, unless the test sets:
#
#   GW_FAKE_SIGNED_OUT=1   codex is logged out; opencode has no credential
#   GW_FAKE_MODELS=...     what `opencode models` prints instead
#   GW_FAKE_CONFIG=...     what `opencode debug config` prints instead
#
# Every fake gets this ahead of its own body, so a fake written to act out a
# run is never mistaken for one by a probe.
FAKE_PROBES = r"""
if [ "$1 $2" = "login status" ]; then
  if [ -n "$GW_FAKE_SIGNED_OUT" ]; then echo "Not logged in" >&2; exit 1; fi
  echo "Logged in using ChatGPT" >&2; exit 0
fi
if [ "$1 $2" = "auth list" ]; then
  printf '\342\224\214  Credentials \033[90m~/.local/share/opencode/auth.json\n'
  if [ -n "$GW_FAKE_SIGNED_OUT" ]; then
    printf '\342\224\224  0 credentials\n'
  else
    printf '\342\227\217  OpenAI \033[90moauth\n\342\224\224  1 credentials\n'
  fi
  exit 0
fi
if [ "$1" = "models" ]; then
  models=$(printf 'openai/gpt-6-astra\nopenai/gpt-5.6-sol')
  printf '%s\n' "${GW_FAKE_MODELS-$models}"
  exit 0
fi
if [ "$1 $2" = "debug config" ]; then
  config='{"agent": {}}'
  printf '%s\n' "${GW_FAKE_CONFIG-$config}"
  exit 0
fi
"""


def install_fake_cli(bin_dir, name, script=FAKE_CLI):
    """Write an executable fake `name` into bin_dir and return its path."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    path = bin_dir / name
    shebang, _, body = script.partition("\n")
    path.write_text(shebang + "\n" + FAKE_PROBES + body, encoding="utf-8")
    path.chmod(0o755)
    return path
