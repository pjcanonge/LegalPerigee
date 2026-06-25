# Real-time alerts setup

Turn on push-delivered docket alerts so matching federal filings land in your
library within seconds — no waiting for the next sync. Three pieces: a
CourtListener token, the webhook receiver, and a public tunnel to reach it.

> Don't need sub-minute latency? You can skip the tunnel entirely. With just a
> `COURTLISTENER_API_TOKEN` and the "⚡ Real-time alerts" toggle in the app's
> Alerts tab, CourtListener will **email** you the moment a match is filed. The
> tunnel + receiver below are only for ingesting those hits straight into the DB.

## 1. Get a CourtListener API token (free)

1. Sign in at <https://www.courtlistener.com/> (create an account if needed).
2. Open <https://www.courtlistener.com/help/api/> → copy your API token.
3. Add it to `.env` in the project root:
   ```
   COURTLISTENER_API_TOKEN=your-token-here
   ```

That alone raises rate limits and unlocks real-time email alerts.

## 2. Start the webhook receiver

```bash
# from the project folder, with the venv active
python3 -m aggregator.webhook_receiver        # listens on http://localhost:8787
```

It ingests pushed docket activity into the case DB. It's guarded by
`LP_WEBHOOK_TOKEN` (the setup helper in step 4 generates one for you).

## 3. Expose it with a public HTTPS URL

CourtListener has to reach your machine, so a laptop needs a tunnel. Pick one:

```bash
# Option A — cloudflared (no account needed for a quick tunnel)
cloudflared tunnel --url http://localhost:8787
#  → prints  https://something.trycloudflare.com

# Option B — ngrok
ngrok http 8787
#  → prints  https://something.ngrok-free.app
```

Keep this running. Copy the `https://…` URL it prints.

## 4. Register the webhook (automated)

```bash
python3 scripts/setup_realtime.py --write-env \
    --url https://something.trycloudflare.com \
    --alert "AI lending discrimination"      # optional: also create an rt alert
```

This will:
- generate + save a strong `LP_WEBHOOK_TOKEN` to `.env`,
- register `https://…/webhooks/courtlistener?token=…` with CourtListener,
- (optionally) create a real-time docket search alert.

If you started **ngrok**, you can omit `--url` — the helper auto-detects the
tunnel from ngrok's local API.

Verify the receiver is reachable:
```bash
curl https://something.trycloudflare.com/health
# {"status":"ok","service":"legalperigee-webhook"}
```

## Notes

- **The tunnel URL changes** each time you restart a free cloudflared/ngrok
  tunnel — re-run step 4 with the new URL (a paid/static tunnel or a real host
  avoids this). For an always-on setup, run the receiver + a named tunnel on a
  small server instead of your laptop.
- **Security:** requests without the matching `?token=` are rejected (401), so
  keep `LP_WEBHOOK_TOKEN` secret. `.env` is git-ignored.
- **Per-rule control:** the app's Alerts tab has an "⚡ Real-time alerts" toggle
  to choose real-time vs daily-digest when you create each rule.
