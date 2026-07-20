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

[[ -f "$HERE/claude/skills/orchestrate/SKILL.md" && -d "$HERE/dashboard" && \
   -f "$HERE/scripts/orchestrate.sh" && -f "$HERE/scripts/claude_review.py" ]] || {
  echo "  ✗ incomplete orchestrate package" >&2
  exit 1
}

if [[ -e "$DEST" ]]; then
  backup="$DEST.bak-$(date +%Y%m%d%H%M%S)"
  mv "$DEST" "$backup"
  echo "  ↩ existing install backed up -> $backup"
fi
mkdir -p "$DEST/references"
cp "$HERE/claude/skills/orchestrate/SKILL.md" "$DEST/SKILL.md"
cp "$HERE/claude/skills/orchestrate/references/"*.md "$DEST/references/"
cp -R "$HERE/dashboard" "$DEST/dashboard"
chmod +x "$HERE/scripts/orchestrate.sh"
for tool in orchestrate-dashboard orchestrate-status orchestrate-watchdog orchestrate-codex-sidecar; do
  chmod +x "$DEST/dashboard/$tool"
done
echo "  ✓ skill + dashboard installed -> $DEST"
echo "  ✓ driver ready -> $HERE/scripts/orchestrate.sh"

# Optional Codex-side skill (the executor's view of the same loop).
CODEX_DEST="${CODEX_SKILLS_DIR:-$HOME/.codex/skills}"
CODEX_AGENTS_DEST="${CODEX_AGENTS_DIR:-$HOME/.codex/agents}"
if [[ -d "$HERE/codex/skills/orchestrate" ]]; then
  mkdir -p "$CODEX_DEST"
  if [[ -e "$CODEX_DEST/orchestrate" ]]; then
    mv "$CODEX_DEST/orchestrate" "$CODEX_DEST/orchestrate.bak-$(date +%Y%m%d%H%M%S)"
  fi
  cp -R "$HERE/codex/skills/orchestrate" "$CODEX_DEST/orchestrate"
  echo "  ✓ codex skill installed -> $CODEX_DEST/orchestrate"
  if [[ -d "$HERE/codex/agents" ]]; then
    mkdir -p "$CODEX_AGENTS_DEST"
    cp "$HERE/codex/agents/"orchestrate_*.toml "$CODEX_AGENTS_DEST/"
    echo "  ✓ codex agent profiles installed -> $CODEX_AGENTS_DEST"
  fi
else
  echo "  · codex skill skipped (package does not contain a Codex projection)"
fi

link_tools() {
  mkdir -p "$BIN_DEST"
  ln -sfn "$HERE/scripts/orchestrate.sh" "$BIN_DEST/orchestrate-driver"
  for tool in orchestrate-dashboard orchestrate-status orchestrate-watchdog orchestrate-codex-sidecar; do
    ln -sfn "$DEST/dashboard/$tool" "$BIN_DEST/$tool"
  done
  echo "  ✓ PATH tools linked -> $BIN_DEST"
}
[[ "$link_bin" != "1" ]] || link_tools

# --- Optional layers (interactive; every answer defaults to No) -------------
# The skill alone is the product. These add live status on top — see README
# "What do you actually need?". Skipped entirely when not run from a terminal.
if [[ -t 0 && -t 1 ]]; then
  echo
  echo "== Optional layers (all default to No; Enter skips) =="
  if [[ "$link_bin" != "1" ]]; then
    read -r -p "  Link driver + dashboard tools into $BIN_DEST? [y/N] " ans
    if [[ "$ans" == [yY]* ]]; then link_tools; fi
  fi
  read -r -p "  Start the localhost:4600 status dashboard now? [y/N] " ans
  if [[ "$ans" == [yY]* ]]; then
    mkdir -p "$HOME/.orchestrate/logs"
    nohup "$DEST/dashboard/orchestrate-dashboard" >"$HOME/.orchestrate/logs/dashboard.log" 2>&1 &
    sleep 1
    curl -s -o /dev/null -w "  ✓ dashboard -> http://localhost:4600 (%{http_code})\n" localhost:4600 || true
  fi
  if [[ "$(uname)" == "Darwin" && -x "$DEST/dashboard/launchd/install-launchd.sh" ]]; then
    read -r -p "  Install macOS launchd agents so dashboard+watchdog stay on across reboots? [y/N] " ans
    if [[ "$ans" == [yY]* ]]; then bash "$DEST/dashboard/launchd/install-launchd.sh"; fi
  fi
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

Optional layers (any time later — see README "What do you actually need?"):
  Dashboard:        "$DEST/dashboard/orchestrate-dashboard"     # localhost:4600
  Watchdog:         "$DEST/dashboard/orchestrate-watchdog"      # flags dead/stalled runs
  Always-on (mac):  bash "$DEST/dashboard/launchd/install-launchd.sh"
EOF

[[ "$missing" == "0" ]] || { echo; echo "NOTE: install the missing CLI(s) above before running the loop."; }
echo
echo "Done."
