#!/bin/bash
# Install the pairwork skill into ~/.claude/skills/ as a live symlink install.
#
# SKILL.md references scripts via ${CLAUDE_SKILL_DIR}, which Claude Code
# substitutes to the skill's own directory. So this script symlinks the whole
# skill directory into ~/.claude/skills/ - every edit (scripts AND SKILL.md) is
# immediately live, with no per-file rewrite.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_ROOT="$HOME/.claude/skills"

echo "=== pairwork skill installer (Claude Code) ==="
echo

# --- Dependencies ---
# Standard library only. Python 3.9 is the floor, which is what ships on
# macOS Monterey and Ubuntu 20.04.
if ! command -v python3 >/dev/null 2>&1; then
  echo "pairwork needs python3."
  echo "  macOS:  brew install python3"
  echo "  Ubuntu: sudo apt install python3"
  exit 1
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then
  echo "pairwork needs Python 3.9 or newer; found $(python3 -V 2>&1)."
  exit 1
fi
echo "Dependencies OK ($(python3 -V 2>&1), standard library only)."
echo

mkdir -p "$SKILLS_ROOT"
for src in "$SCRIPT_DIR"/skills/*/; do
  src="${src%/}"
  name="$(basename "$src")"
  target="$SKILLS_ROOT/$name"
  echo "Installing '$name' -> $target"
  rm -rf "$target"
  ln -sfn "$src" "$target"
  chmod +x "$src"/scripts/*.py 2>/dev/null || true
done

echo
echo "Installed as a directory symlink - all edits are live."
echo
echo "Next: check which counterparts are ready:"
echo "  python3 $SKILLS_ROOT/pairwork/scripts/pairwork.py providers"
echo
echo "pairwork stores no credentials - each provider CLI authenticates"
echo "itself. You need at least one of codex, opencode or copilot"
echo "installed AND logged in."
echo
