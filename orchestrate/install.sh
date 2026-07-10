#!/usr/bin/env bash
# Installer for the /orchestrate Claude Code skill and local dashboard tools.
set -euo pipefail

link_bin=0
[[ "${1:-}" != "--link-bin" ]] || { link_bin=1; shift; }
[[ "$#" -eq 0 ]] || { echo "usage: ./install.sh [--link-bin]" >&2; exit 2; }

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
DEST="${CLAUDE_SKILLS_DIR:-$HOME/.claude/skills}/orchestrate"
BIN_DEST="${XDG_BIN_HOME:-$HOME/.local/bin}"

echo "== Installing /orchestrate =="

missing=0
for command_name in codex gh git; do
  if command -v "$command_name" >/dev/null 2>&1; then
    echo "  ✓ $command_name found"
  else
    echo "  ✗ $command_name NOT found — install it before using the loop"
    missing=1
  fi
done

[[ -f "$HERE/skills/orchestrate/SKILL.md" && -d "$HERE/dashboard" && \
   -f "$HERE/scripts/orchestrate.sh" ]] || {
  echo "  ✗ incomplete orchestrate package" >&2
  exit 1
}

if [[ -e "$DEST" ]]; then
  backup="$DEST.bak-$(date +%Y%m%d%H%M%S)"
  mv "$DEST" "$backup"
  echo "  ↩ existing install backed up -> $backup"
fi
mkdir -p "$DEST/references"
cp "$HERE/skills/orchestrate/SKILL.md" "$DEST/SKILL.md"
cp "$HERE/skills/orchestrate/references/"*.md "$DEST/references/"
cp -R "$HERE/dashboard" "$DEST/dashboard"
chmod +x "$HERE/scripts/orchestrate.sh"
for tool in orchestrate-dashboard orchestrate-status orchestrate-watchdog; do
  chmod +x "$DEST/dashboard/$tool"
done
echo "  ✓ skill + dashboard installed -> $DEST"
echo "  ✓ driver ready -> $HERE/scripts/orchestrate.sh"

if [[ "$link_bin" == "1" ]]; then
  mkdir -p "$BIN_DEST"
  ln -sfn "$HERE/scripts/orchestrate.sh" "$BIN_DEST/orchestrate-driver"
  for tool in orchestrate-dashboard orchestrate-status orchestrate-watchdog; do
    ln -sfn "$DEST/dashboard/$tool" "$BIN_DEST/$tool"
  done
  echo "  ✓ PATH tools linked -> $BIN_DEST"
fi

cat <<EOF

Next (optional but recommended):
  1. Append the model-roles contract so sessions default to the split:
       cat "$HERE/contract/CLAUDE.snippet.md"  >> ~/.claude/CLAUDE.md
       cat "$HERE/contract/AGENTS.snippet.md"  >> ~/.codex/AGENTS.md
  2. Confirm Codex is logged in and set to gpt-5.6-sol:
       codex --version && codex login status
  3. Confirm gh auth: gh auth status
  4. Per repo you want to use it in:
       cp "$HERE/contract/orchestrate.toml.example" <repo>/.ai/orchestrate.toml
$([[ "$link_bin" == "1" ]] || echo "  5. Optional PATH links: ./install.sh --link-bin")

Use it:
  In Claude Code:   /orchestrate <topic>
  Headless leg:     "$HERE/scripts/orchestrate.sh" <topic> PLAN.md
  Dashboard:        "$DEST/dashboard/orchestrate-dashboard"
  Watchdog:         "$DEST/dashboard/orchestrate-watchdog"
EOF

[[ "$missing" == "0" ]] || { echo; echo "NOTE: install the missing CLI(s) above before running the loop."; }
echo
echo "Done."
