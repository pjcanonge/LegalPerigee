#!/usr/bin/env python3
"""
LegalPerigee — real-time alerts setup helper.

Automates the two fiddly parts of turning on push-delivered alerts:
  1. Makes sure COURTLISTENER_API_TOKEN and a strong LP_WEBHOOK_TOKEN are in .env
     (generating the webhook secret for you, optionally persisting both).
  2. Registers your public webhook URL with CourtListener (token appended) and,
     optionally, creates a real-time ('rt') search alert.

It cannot fetch your CourtListener token (that needs your login) or open the
tunnel for you, but it will auto-detect a running ngrok tunnel if you don't pass
a URL explicitly.

Examples
--------
    # Generate + persist a webhook secret, then register an ngrok tunnel it finds:
    python3 scripts/setup_realtime.py --write-env

    # Be explicit about the public base URL (cloudflared, ngrok, a real host…):
    python3 scripts/setup_realtime.py --url https://abc-123.trycloudflare.com

    # Also create a real-time docket search alert:
    python3 scripts/setup_realtime.py --url https://abc-123.trycloudflare.com \\
        --alert "AI lending discrimination"
"""

import argparse
import os
import secrets
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))
ENV_PATH = PROJECT_DIR / ".env"

WEBHOOK_PATH = "/webhooks/courtlistener"


def _load_env() -> None:
    if ENV_PATH.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(dotenv_path=str(ENV_PATH), override=False)
        except Exception:
            pass


def _set_env_var(key: str, value: str) -> None:
    """Insert or replace `key=value` in .env, preserving everything else."""
    lines = ENV_PATH.read_text().splitlines() if ENV_PATH.exists() else []
    out, found = [], False
    for line in lines:
        stripped = line.strip()
        # Match KEY= and a commented "# KEY=" placeholder.
        bare = stripped[1:].strip() if stripped.startswith("#") else stripped
        if bare.startswith(f"{key}="):
            out.append(f"{key}={value}")
            found = True
        else:
            out.append(line)
    if not found:
        out.append(f"{key}={value}")
    ENV_PATH.write_text("\n".join(out) + "\n")
    # Keep secrets owner-only.
    try:
        os.chmod(ENV_PATH, 0o600)
    except OSError:
        pass


def _detect_ngrok_url() -> str | None:
    """Return the public https URL of a running ngrok tunnel, if any."""
    try:
        import httpx
        r = httpx.get("http://127.0.0.1:4040/api/tunnels", timeout=3)
        r.raise_for_status()
        for t in r.json().get("tunnels", []):
            url = t.get("public_url", "")
            if url.startswith("https://"):
                return url
    except Exception:
        return None
    return None


def main() -> int:
    p = argparse.ArgumentParser(description="Set up LegalPerigee real-time alerts")
    p.add_argument("--url", help="Public base URL of your tunnel/host (https://…).")
    p.add_argument("--alert", help="Also create a real-time docket search alert for this query.")
    p.add_argument("--write-env", action="store_true",
                   help="Persist a generated LP_WEBHOOK_TOKEN (and any --cl-token) to .env.")
    p.add_argument("--cl-token", help="CourtListener API token (else read from env/.env).")
    args = p.parse_args()

    _load_env()

    # ── 1. CourtListener token ────────────────────────────────────────────────
    cl_token = args.cl_token or os.getenv("COURTLISTENER_API_TOKEN", "")
    if not cl_token:
        print("❌ No CourtListener API token.")
        print("   Get one (free): https://www.courtlistener.com/help/api/")
        print("   Then add it to .env as COURTLISTENER_API_TOKEN=… or pass --cl-token.")
        return 1
    os.environ["COURTLISTENER_API_TOKEN"] = cl_token
    if args.cl_token and args.write_env:
        _set_env_var("COURTLISTENER_API_TOKEN", cl_token)
        print("✅ Saved COURTLISTENER_API_TOKEN to .env")

    # ── 2. Webhook secret ─────────────────────────────────────────────────────
    wh_token = os.getenv("LP_WEBHOOK_TOKEN", "")
    if not wh_token:
        wh_token = secrets.token_urlsafe(32)
        os.environ["LP_WEBHOOK_TOKEN"] = wh_token
        print(f"🔑 Generated LP_WEBHOOK_TOKEN: {wh_token}")
        if args.write_env:
            _set_env_var("LP_WEBHOOK_TOKEN", wh_token)
            print("✅ Saved LP_WEBHOOK_TOKEN to .env")
        else:
            print("   (re-run with --write-env to persist it, or add it to .env yourself)")

    # ── 3. Public URL ─────────────────────────────────────────────────────────
    base = (args.url or _detect_ngrok_url() or "").rstrip("/")
    if not base:
        print("\nℹ️  No --url given and no ngrok tunnel detected.")
        print("   Start the receiver and a tunnel first, e.g.:")
        port = os.getenv("LP_WEBHOOK_PORT", "8787")
        print(f"     python3 -m aggregator.webhook_receiver        # listens on :{port}")
        print(f"     cloudflared tunnel --url http://localhost:{port}")
        print("   then re-run this with --url <the https URL it prints>.")
        return 1
    if not base.startswith("https://"):
        print(f"❌ Public URL must be https:// (got {base}). CourtListener requires TLS.")
        return 1

    endpoint = f"{base}{WEBHOOK_PATH}?token={wh_token}"

    # ── 4. Register the webhook ───────────────────────────────────────────────
    from aggregator.courtlistener_alerts import register_webhook, create_cl_search_alert

    print(f"\n📡 Registering webhook → {base}{WEBHOOK_PATH}?token=…")
    res = register_webhook(endpoint, event_type=1)  # 1 = docket alert
    if res.get("status") == "registered":
        print(f"✅ Webhook registered (id {res.get('id')}).")
    else:
        print(f"❌ Webhook registration: {res.get('error') or res.get('message')}")
        return 1

    # ── 5. Optional real-time search alert ────────────────────────────────────
    if args.alert:
        print(f"🔔 Creating real-time docket alert for: {args.alert!r}")
        a = create_cl_search_alert(
            name=f"LegalPerigee RT: {args.alert}",
            query=args.alert,
            rate="rt",
            alert_type="d",
        )
        if a.get("status") == "created":
            print(f"✅ Real-time alert created (id {a.get('id')}).")
        else:
            print(f"⚠️ Alert: {a.get('error') or a.get('message')}")

    print("\n🎉 Done. Keep the receiver and the tunnel running to receive pushes.")
    print(f"   Health check: curl {base}/health")
    return 0


if __name__ == "__main__":
    sys.exit(main())
