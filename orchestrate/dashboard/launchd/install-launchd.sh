#!/usr/bin/env bash
# Install always-on launchd agents for the orchestrate dashboard + watchdog.
# Run this YOURSELF (it installs persistence): bash install-launchd.sh
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
DASH_DIR="$(dirname "$HERE")"
AGENTS="$HOME/Library/LaunchAgents"
mkdir -p "$AGENTS" "$HOME/.orchestrate/logs"
# Stop any session-started instances so the agents can claim port 4600.
pkill -f "dashboard/orchestrate-dashboard" 2>/dev/null || true
pkill -f "dashboard/orchestrate-watchdog" 2>/dev/null || true
for name in com.orchestrate.dashboard com.orchestrate.watchdog; do
  sed -e "s|__DASHBOARD_DIR__|$DASH_DIR|g" -e "s|__HOME__|$HOME|g" \
    "$HERE/$name.plist" > "$AGENTS/$name.plist"
  launchctl bootout "gui/$(id -u)/$name" 2>/dev/null || true
  launchctl bootstrap "gui/$(id -u)" "$AGENTS/$name.plist"
  echo "loaded $name"
done
sleep 1
curl -s -o /dev/null -w "dashboard http_code=%{http_code}\n" localhost:4600 || true
echo "Uninstall: launchctl bootout gui/$(id -u)/com.orchestrate.{dashboard,watchdog}; rm $AGENTS/com.orchestrate.*.plist"
