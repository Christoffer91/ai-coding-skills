#!/usr/bin/env bash
# Installer for the /orchestrate Claude Code skill.
# Copies the skill into ~/.claude/skills/orchestrate and marks the driver
# executable. Prints the remaining manual (optional) steps.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DEST="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}/orchestrate"

echo "== Installing /orchestrate =="

# 1) sanity: required CLIs
missing=0
for c in codex gh git; do
  if command -v "$c" >/dev/null 2>&1; then
    echo "  ✓ $c found"
  else
    echo "  ✗ $c NOT found — install it before using the loop"; missing=1
  fi
done

# 2) copy the skill (back up any existing install instead of clobbering it)
if [[ -e "$DEST" ]]; then
  BAK="$DEST.bak-$(date +%Y%m%d%H%M%S)"
  mv "$DEST" "$BAK"
  echo "  ↩ existing install backed up -> $BAK"
fi
mkdir -p "$DEST/references"
cp "$HERE/skills/orchestrate/SKILL.md" "$DEST/SKILL.md"
cp "$HERE/skills/orchestrate/references/"*.md "$DEST/references/"
echo "  ✓ skill installed -> $DEST"

# 3) make the driver executable (kept in this package; run it from here or copy onto PATH)
chmod +x "$HERE/scripts/orchestrate.sh"
echo "  ✓ driver ready -> $HERE/scripts/orchestrate.sh"

cat <<EOF

Next (optional but recommended):
  1. Append the model-roles contract so sessions default to the split:
       cat "$HERE/contract/CLAUDE.snippet.md"  >> ~/.claude/CLAUDE.md
       cat "$HERE/contract/AGENTS.snippet.md"  >> ~/.codex/AGENTS.md
  2. Confirm Codex is logged in and set to gpt-5.6-sol:
       codex --version && codex login status
       # ~/.codex/config.toml -> model = "gpt-5.6-sol"
  3. Confirm gh auth:  gh auth status   (needs repo + workflow scopes)
  4. Per repo you want to use it in:
       cp "$HERE/contract/orchestrate.toml.example" <repo>/.ai/orchestrate.toml

Use it:
  In Claude Code:   /orchestrate <topic>
  Headless leg:     "$HERE/scripts/orchestrate.sh" <topic> PLAN.md
  Dry run:          ORCH_DRYRUN=1 "$HERE/scripts/orchestrate.sh" <topic> PLAN.md
EOF

[[ "$missing" == "0" ]] || { echo; echo "NOTE: install the missing CLI(s) above before running the loop."; }
echo
echo "Done."
