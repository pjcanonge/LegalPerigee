#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# LegalPerigee — install/uninstall the scheduled background sync (launchd agent)
#
#   bash installers/macos/install_scheduled_sync.sh            # install + start
#   bash installers/macos/install_scheduled_sync.sh --uninstall
#
# Keeps the case database fresh every 20 minutes even when the app is closed.
# ─────────────────────────────────────────────────────────────────────────────
set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
LABEL="com.legalperigee.sync"
TEMPLATE="$PROJECT_DIR/installers/macos/com.legalperigee.sync.plist"
AGENTS_DIR="$HOME/Library/LaunchAgents"
PLIST="$AGENTS_DIR/$LABEL.plist"
PYTHON="$PROJECT_DIR/.venv/bin/python3"
SYNC_SCRIPT="$PROJECT_DIR/scripts/scheduled_sync.py"

uninstall() {
    echo "⏏️  Removing scheduled sync…"
    launchctl unload "$PLIST" 2>/dev/null || true
    rm -f "$PLIST"
    echo "✅  Scheduled sync removed."
    exit 0
}

[ "$1" = "--uninstall" ] && uninstall

if [ ! -x "$PYTHON" ]; then
    echo "❌  Project venv not found at $PYTHON"
    echo "    Run:  bash setup.sh"
    exit 1
fi

mkdir -p "$AGENTS_DIR"

# Fill the template placeholders with the real, absolute paths.
sed -e "s|__PYTHON__|$PYTHON|g" \
    -e "s|__SYNC_SCRIPT__|$SYNC_SCRIPT|g" \
    -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
    "$TEMPLATE" > "$PLIST"

# Reload (unload first so re-running picks up changes).
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo "✅  Scheduled sync installed → $PLIST"
echo "    Runs every 20 min (and once now). Logs:"
echo "      ~/Library/Logs/LegalPerigee_sync.log"
echo "      $PROJECT_DIR/data/scheduled_sync.{out,err}.log"
echo "    Uninstall:  bash installers/macos/install_scheduled_sync.sh --uninstall"
