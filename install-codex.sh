#!/bin/bash
# Install the groupwork skill for Codex.
#
# Codex does not substitute ${CLAUDE_SKILL_DIR}, so SKILL.md is rewritten with
# the real installed path and the subdirectories are symlinked alongside it.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SKILLS_ROOT="${CODEX_SKILLS_DIR:-$HOME/.codex/skills}"

echo "=== groupwork skill installer (Codex) ==="
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "groupwork needs python3."
  exit 1
fi
if ! python3 -c 'import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)'; then
  echo "groupwork needs Python 3.9 or newer; found $(python3 -V 2>&1)."
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
  mkdir -p "$target"
  # Clear what a previous install symlinked, so a directory removed upstream
  # does not survive as a dangling link that still looks installed. Only
  # symlinks are removed, so a real SKILL.md is never at risk.
  find "$target" -mindepth 1 -maxdepth 1 -type l -exec rm -f {} +
  for sub in scripts references templates tests; do
    [ -d "$src/$sub" ] && ln -sfn "$src/$sub" "$target/$sub"
  done
  chmod +x "$src"/scripts/*.py 2>/dev/null || true
  sed "s#\${CLAUDE_SKILL_DIR}#$target#g" "$src/SKILL.md" > "$target/SKILL.md"
done

echo
echo "Installed for Codex."
echo
echo "Next: check which counterparts are ready:"
echo "  python3 $SKILLS_ROOT/groupwork/scripts/groupwork.py providers"
echo
echo "groupwork stores no credentials - each provider CLI authenticates"
echo "itself. You need at least one of codex or opencode"
echo "installed AND logged in."
echo
