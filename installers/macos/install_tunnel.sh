#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# LegalPerigee — install a STABLE named cloudflared tunnel for the webhook
# receiver, as a launchd agent, and register the (now permanent) URL with
# CourtListener exactly once.
#
#   bash installers/macos/install_tunnel.sh webhook.yourdomain.com
#   bash installers/macos/install_tunnel.sh --uninstall
#
# Prerequisites (one-time, only you can do these):
#   1. brew install cloudflared
#   2. cloudflared tunnel login          # browser auth → ~/.cloudflared/cert.pem
#   3. A domain managed in that Cloudflare account (for the hostname you pass).
#
# After this, the hostname never changes, so the webhook URL never needs
# re-registering — the whole real-time path is hands-off across reboots.
# ─────────────────────────────────────────────────────────────────────────────
set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
TUNNEL_NAME="${LP_TUNNEL_NAME:-legalperigee}"
CF_DIR="$HOME/.cloudflared"
CONFIG="$CF_DIR/legalperigee-config.yml"
TEMPLATE="$PROJECT_DIR/installers/macos/cloudflared/config.template.yml"
PLIST_TEMPLATE="$PROJECT_DIR/installers/macos/com.legalperigee.tunnel.plist"
AGENTS_DIR="$HOME/Library/LaunchAgents"
LABEL="com.legalperigee.tunnel"
PLIST="$AGENTS_DIR/$LABEL.plist"
PYTHON="$PROJECT_DIR/.venv/bin/python3"

uninstall() {
    echo "⏏️  Removing tunnel service…"
    launchctl unload "$PLIST" 2>/dev/null || true
    rm -f "$PLIST"
    echo "✅  Tunnel launchd agent removed."
    echo "    (The named tunnel + DNS route still exist. To delete them fully:"
    echo "       cloudflared tunnel delete $TUNNEL_NAME )"
    exit 0
}

[ "$1" = "--uninstall" ] && uninstall

CLOUDFLARED="$(command -v cloudflared || true)"
[ -z "$CLOUDFLARED" ] && { echo "❌  cloudflared not found. Install:  brew install cloudflared"; exit 1; }
[ -f "$CF_DIR/cert.pem" ] || { echo "❌  Not logged in. Run:  cloudflared tunnel login"; exit 1; }

HOSTNAME="$1"
[ -z "$HOSTNAME" ] && { echo "❌  Usage: install_tunnel.sh <hostname>  (e.g. webhook.yourdomain.com)"; exit 1; }

PORT="$(grep -E '^LP_WEBHOOK_PORT=' "$PROJECT_DIR/.env" 2>/dev/null | cut -d= -f2)"
PORT="${PORT:-8787}"

# ── Reuse the tunnel if it exists, else create it; capture the UUID ───────────
UUID="$("$CLOUDFLARED" tunnel list -o json 2>/dev/null \
    | python3 -c "import sys,json; t=[x for x in json.load(sys.stdin) if x.get('name')=='$TUNNEL_NAME']; print(t[0]['id'] if t else '')" )"

if [ -z "$UUID" ]; then
    echo "🌀  Creating named tunnel '$TUNNEL_NAME'…"
    "$CLOUDFLARED" tunnel create "$TUNNEL_NAME"
    UUID="$("$CLOUDFLARED" tunnel list -o json \
        | python3 -c "import sys,json; print([x for x in json.load(sys.stdin) if x['name']=='$TUNNEL_NAME'][0]['id'])" )"
fi
echo "✅  Tunnel: $TUNNEL_NAME ($UUID)"

CRED_FILE="$CF_DIR/$UUID.json"
[ -f "$CRED_FILE" ] || { echo "❌  Credentials file missing: $CRED_FILE"; exit 1; }

# ── Route the hostname to this tunnel (idempotent) ────────────────────────────
echo "🔗  Routing $HOSTNAME → $TUNNEL_NAME…"
"$CLOUDFLARED" tunnel route dns "$UUID" "$HOSTNAME" 2>&1 | grep -vi "already" || true

# ── Write the cloudflared config from the template ────────────────────────────
mkdir -p "$CF_DIR"
sed -e "s|__TUNNEL_UUID__|$UUID|g" \
    -e "s|__CRED_FILE__|$CRED_FILE|g" \
    -e "s|__HOSTNAME__|$HOSTNAME|g" \
    -e "s|__PORT__|$PORT|g" \
    "$TEMPLATE" > "$CONFIG"
echo "✅  Wrote $CONFIG"

# ── Install the launchd agent ─────────────────────────────────────────────────
mkdir -p "$AGENTS_DIR"
sed -e "s|__CLOUDFLARED__|$CLOUDFLARED|g" \
    -e "s|__CONFIG__|$CONFIG|g" \
    -e "s|__TUNNEL_UUID__|$UUID|g" \
    -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
    "$PLIST_TEMPLATE" > "$PLIST"
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"
echo "✅  Tunnel launchd agent installed → $PLIST"

# ── Register the (permanent) webhook URL with CourtListener, once ─────────────
if [ -x "$PYTHON" ]; then
    echo "📡  Registering webhook for https://$HOSTNAME …"
    "$PYTHON" "$PROJECT_DIR/scripts/setup_realtime.py" --write-env --url "https://$HOSTNAME" || \
        echo "⚠️  Registration step failed — re-run scripts/setup_realtime.py once the token is set."
fi

echo ""
echo "🎉  Stable tunnel up. https://$HOSTNAME → localhost:$PORT, on every login."
echo "    Verify (give DNS a minute):  curl https://$HOSTNAME/health"
echo "    Logs: $PROJECT_DIR/data/tunnel.{out,err}.log"
