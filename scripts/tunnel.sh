#!/usr/bin/env bash
# Persistent SSH tunnel to the Zetaris demo server (UI/API :3000, Thrift/JDBC :10000).
# Both ports stay bound to 127.0.0.1 on the server; nothing is opened in its firewall.
# usage: scripts/tunnel.sh start|stop|status|install|uninstall
#   install = launchd agent (macOS) that restarts the tunnel at login and if it drops.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
envval() { sed -n "s/^$1=//p" "$ROOT/.env" 2>/dev/null | tail -1 | tr -d '"'; }
HOST="${ZETARIS_SSH_HOST:-$(envval ZETARIS_SSH_HOST)}"
[ -n "$HOST" ] || { echo "set ZETARIS_SSH_HOST in .env (the Zetaris server)"; exit 2; }
USER_="${ZETARIS_SSH_USER:-root}"
KEY="${ZETARIS_SSH_KEY:-$HOME/.ssh/zetaris_mac}"
LABEL="uk.mnlabs.zetaris-tunnel"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
SSH_ARGS=(-N -i "$KEY" -o ExitOnForwardFailure=yes -o ServerAliveInterval=30 -o ServerAliveCountMax=3
  -o StrictHostKeyChecking=accept-new -L 127.0.0.1:3000:127.0.0.1:3000 -L 127.0.0.1:10000:127.0.0.1:10000 "$USER_@$HOST")

up() { curl -s -o /dev/null -m 5 -w '%{http_code}' http://127.0.0.1:3000/ | grep -qE '^[23]'; }
case "${1:-status}" in
  start)  up && { echo "tunnel already up"; exit 0; }; ssh -f "${SSH_ARGS[@]}"; sleep 2; up && echo "tunnel up: http://127.0.0.1:3000" ;;
  stop)   pkill -f "ssh.*-L 127.0.0.1:3000:127.0.0.1:3000.*$HOST" && echo stopped || echo "not running" ;;
  status) up && echo "up (Zetaris reachable on 127.0.0.1:3000)" || { echo down; exit 1; } ;;
  install)
    mkdir -p "$(dirname "$PLIST")"
    { echo '<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">'
      echo "<plist version=\"1.0\"><dict><key>Label</key><string>$LABEL</string><key>ProgramArguments</key><array><string>/usr/bin/ssh</string>"
      for a in "${SSH_ARGS[@]}"; do printf '<string>%s</string>' "$a"; done
      echo '</array><key>RunAtLoad</key><true/><key>KeepAlive</key><true/><key>ThrottleInterval</key><integer>15</integer>'
      echo "<key>StandardErrorPath</key><string>/tmp/$LABEL.log</string></dict></plist>"; } > "$PLIST"
    "$0" stop >/dev/null 2>&1 || true
    launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
    launchctl bootstrap "gui/$(id -u)" "$PLIST"; sleep 3; "$0" status ;;
  uninstall) launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true; rm -f "$PLIST"; echo removed ;;
  *) echo "usage: $0 start|stop|status|install|uninstall"; exit 2 ;;
esac
