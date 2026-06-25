#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# LegalPerigee — install/uninstall the real-time webhook receiver (launchd agent)
#
#   bash installers/macos/install_webhook_receiver.sh            # install + start
#   bash installers/macos/install_webhook_receiver.sh --uninstall
#
# Keeps aggregator/webhook_receiver.py running on login (KeepAlive) so pushed
# docket alerts are ingested in real time. NOTE: the receiver only receives
# pushes while a public tunnel points at it — see installers/REALTIME_SETUP.md.
# ─────────────────────────────────────────────────────────────────────────────
set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LABEL="com.legalperigee.webhook"
TEMPLATE="$PROJECT_DIR/installers/macos/com.legalperigee.webhook.plist"
AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST="$AGENTS_DIR/$LABEL.plist"
PYTHON="$PROJECT_DIR/.venv/bin/python3"

uninstall() {
    echo "⏏️  Removing webhook receiver service…"
    launchctl unload "$PLIST" 2>/dev/null || true
    rm -f "$PLIST"
    echo "✅  Webhook receiver service removed."
    exit 0
}

[ "$1" = "--uninstall" ] && uninstall

if [ ! -x "$PYTHON" ]; then
    echo "❌  Project venv not found at $PYTHON"
    echo "    Run:  bash setup.sh"
    exit 1
fi

# Warn (don't block) if the token guard isn't configured — an open endpoint is
# a dev-only convenience.
if ! grep -qE '^LP_WEBHOOK_TOKEN=.+' "$PROJECT_DIR/.env" 2>/dev/null; then
    echo "⚠️  LP_WEBHOOK_TOKEN is not set in .env — the endpoint will accept"
    echo "    unauthenticated POSTs. Run scripts/setup_realtime.py --write-env"
    echo "    to generate one before exposing the receiver publicly."
fi

mkdir -p "$AGENTS_DIR"

sed -e "s|__PYTHON__|$PYTHON|g" \
    -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
    "$TEMPLATE" > "$PLIST"

launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

PORT="$(grep -E '^LP_WEBHOOK_PORT=' "$PROJECT_DIR/.env" 2>/dev/null | cut -d= -f2)"
PORT="${PORT:-8787}"

echo "✅  Webhook receiver installed → $PLIST"
echo "    Starts on login, restarts if it exits. Listening on http://localhost:$PORT"
echo "    Health:  curl http://localhost:$PORT/health"
echo "    Logs:    $PROJECT_DIR/data/webhook_receiver.{out,err}.log"
echo ""
echo "    Still needed for pushes to arrive: a public tunnel to this port and a"
echo "    registered webhook URL. See installers/REALTIME_SETUP.md."
echo "    Uninstall:  bash installers/macos/install_webhook_receiver.sh --uninstall"
