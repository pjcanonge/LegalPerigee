#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# LegalPerigee — install BOTH background launchd agents in one go:
#   • scheduled incremental sync (every 20 min)
#   • real-time webhook receiver (always-on)
#
#   bash installers/macos/install_services.sh            # install + start both
#   bash installers/macos/install_services.sh --uninstall
# ─────────────────────────────────────────────────────────────────────────────
set -e
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

ARG="$1"
echo "▶︎ Scheduled sync"
bash "$HERE/install_scheduled_sync.sh" $ARG
echo ""
echo "▶︎ Webhook receiver"
bash "$HERE/install_webhook_receiver.sh" $ARG
echo ""
if [ "$ARG" = "--uninstall" ]; then
    echo "✅  Both services removed."
else
    echo "✅  Both services installed and started (and on every login)."
fi
