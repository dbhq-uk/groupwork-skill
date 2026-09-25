import pathlib
import sys

SCRIPTS = pathlib.Path(__file__).resolve().parent.parent / "scripts"
sys.path.insert(0, str(SCRIPTS))


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


def install_fake_cli(bin_dir, name, script=FAKE_CLI):
    """Write an executable fake `name` into bin_dir and return its path."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    path = bin_dir / name
    path.write_text(script, encoding="utf-8")
    path.chmod(0o755)
    return path
