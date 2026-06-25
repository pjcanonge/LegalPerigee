"""
LegalPerigee — CourtListener webhook receiver.

When you register a webhook (aggregator.courtlistener_alerts.register_webhook)
and use real-time ('rt') alerts, CourtListener POSTs matching docket activity
here the moment it's found. This receiver validates the request and upserts new
items straight into the local case database — so a matching filing can land in
your library within seconds of being docketed, with no polling delay.

Run it:
    uvicorn aggregator.webhook_receiver:app --host 0.0.0.0 --port 8787
    # or:  python -m aggregator.webhook_receiver

Exposing it publicly:
    CourtListener must be able to reach the URL, so for a laptop you need a
    tunnel (e.g. `cloudflared tunnel --url http://localhost:8787` or ngrok).
    Register the resulting https URL with register_webhook(url + "?token=...").

Security:
    Set LP_WEBHOOK_TOKEN in .env and append `?token=<that value>` to the URL you
    register. Requests without the matching token are rejected (401). This keeps
    the open endpoint from accepting forged payloads.
"""

import json
import os
import sys
from pathlib import Path

# Importable when launched directly (python -m aggregator.webhook_receiver).
PROJECT_DIR = Path(__file__).resolve().parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from fastapi import FastAPI, Request, Response, HTTPException

from database.db import init_db, upsert_case

SOURCE = "courtlistener_webhook"

app = FastAPI(title="LegalPerigee Webhook Receiver")


@app.on_event("startup")
def _startup() -> None:
    init_db()


def _check_token(request: Request) -> None:
    """Reject requests whose ?token= doesn't match LP_WEBHOOK_TOKEN (if set)."""
    expected = os.getenv("LP_WEBHOOK_TOKEN", "")
    if not expected:
        return  # no token configured — open endpoint (dev only)
    if request.query_params.get("token") != expected:
        raise HTTPException(status_code=401, detail="invalid or missing token")


def _result_to_row(item: dict) -> dict:
    """Map one CourtListener webhook result into a cases-table row.

    Webhook payloads vary by alert type; pull fields defensively so a schema
    tweak on their side never drops the whole batch.
    """
    docket_id = item.get("docket") or item.get("docket_id") or item.get("id")
    case_id = f"cl_webhook_{docket_id}" if docket_id else f"cl_webhook_{item.get('id', '')}"
    absolute_url = item.get("absolute_url", "")
    doc_url = f"https://www.courtlistener.com{absolute_url}" if absolute_url else None

    return {
        "id": case_id,
        "source": SOURCE,
        "case_name": item.get("caseName") or item.get("case_name", ""),
        "court": item.get("court") or item.get("court_id", ""),
        "jurisdiction": item.get("court") or item.get("court_id", ""),
        "docket_number": item.get("docketNumber") or item.get("docket_number", ""),
        "filing_date": item.get("dateFiled") or item.get("date_filed", ""),
        "case_type": "docket",
        "status": "Docket Alert",
        "summary": item.get("description") or item.get("snippet", ""),
        "document_url": doc_url,
        "raw_json": json.dumps(item)[:50000],
    }


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "legalperigee-webhook"}


@app.post("/webhooks/courtlistener")
async def courtlistener_webhook(request: Request) -> Response:
    _check_token(request)

    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="invalid JSON body")

    # CourtListener wraps results under payload.results; tolerate a few shapes.
    payload = body.get("payload", body)
    results = payload.get("results")
    if results is None and isinstance(payload, list):
        results = payload
    if not isinstance(results, list):
        results = []

    added = updated = 0
    for item in results:
        if not isinstance(item, dict):
            continue
        try:
            is_new = upsert_case(_result_to_row(item))
            added += int(is_new)
            updated += int(not is_new)
        except Exception:
            # One malformed item shouldn't fail the whole delivery, or
            # CourtListener will keep retrying the entire batch.
            continue

    # Always 200 on a processed delivery so CL doesn't retry indefinitely.
    return Response(
        content=json.dumps({"received": len(results), "added": added, "updated": updated}),
        media_type="application/json",
        status_code=200,
    )


def main() -> None:
    import uvicorn
    port = int(os.getenv("LP_WEBHOOK_PORT", "8787"))
    uvicorn.run(app, host="0.0.0.0", port=port)


if __name__ == "__main__":
    main()
