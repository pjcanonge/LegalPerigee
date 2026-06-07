"""
CourtListener real-time alert manager.

Uses the CourtListener MCP (already connected) to create and manage
real-time search alerts and docket subscriptions.

When a user creates a LegalPerigee alert rule, this module ALSO registers
a CourtListener email alert so they're notified the moment a matching
federal case is filed — before the next sync.

Alert rates: rt (real-time), dly (daily), wly (weekly), mly (monthly)
"""

import json
import os
from typing import Optional

# CourtListener API (direct REST — for managing alerts without MCP in background)
import httpx

CL_BASE = "https://www.courtlistener.com/api/rest/v4"


def _cl_headers() -> dict:
    """
    M-2: Build headers lazily so Keychain tokens loaded after import are included.
    Always call this function at request time — never cache the result.
    """
    token = os.getenv("COURTLISTENER_API_TOKEN", "")
    h = {"User-Agent": "LegalPerigee/1.2 (legal research)"}
    if token:
        h["Authorization"] = f"Token {token}"
    return h


def create_cl_search_alert(
    name: str,
    query: str,
    rate: str = "dly",
    alert_type: str = "d",
) -> dict:
    """
    Create a CourtListener search alert via direct API.
    Requires COURTLISTENER_API_TOKEN in .env (free at courtlistener.com/help/api/).

    Args:
        name:       Human-readable alert name
        query:      Search query string (e.g. "fraud consumer class action")
        rate:       rt | dly | wly | mly (real-time, daily, weekly, monthly)
        alert_type: o (opinion) | d (docket) | r (recap)

    Returns:
        dict with 'id', 'status', and optionally 'error'
    """
    if not os.getenv("COURTLISTENER_API_TOKEN", ""):
        return {
            "status": "skipped",
            "message": "No CourtListener API token — add COURTLISTENER_API_TOKEN to .env (free at courtlistener.com/help/api/)",
        }

    try:
        r = httpx.post(
            f"{CL_BASE}/alerts/",
            headers=_cl_headers(),
            timeout=20,
            json={
                "name":  name,
                "query": f"q={query}&type={alert_type}",
                "rate":  rate,
            },
        )
        r.raise_for_status()
        data = r.json()
        return {"status": "created", "id": data.get("id"), "url": data.get("absolute_url", "")}
    except httpx.HTTPStatusError as e:
        return {"status": "error", "error": f"HTTP {e.response.status_code}: {e.response.text[:200]}"}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def subscribe_docket_alert(docket_id: int) -> dict:
    """Subscribe to real-time alerts for a specific docket."""
    if not os.getenv("COURTLISTENER_API_TOKEN", ""):
        return {"status": "skipped", "message": "No CourtListener API token"}
    try:
        r = httpx.post(
            f"{CL_BASE}/docket-alerts/",
            headers=_cl_headers(),
            timeout=20,
            json={"docket": docket_id},
        )
        r.raise_for_status()
        return {"status": "subscribed", "docket_id": docket_id}
    except httpx.HTTPStatusError as e:
        if e.response.status_code == 409:
            return {"status": "already_subscribed", "docket_id": docket_id}
        return {"status": "error", "error": str(e)}
    except Exception as e:
        return {"status": "error", "error": str(e)}


def list_cl_alerts() -> list[dict]:
    """List all active CourtListener alerts for this account."""
    if not os.getenv("COURTLISTENER_API_TOKEN", ""):
        return []
    try:
        r = httpx.get(f"{CL_BASE}/alerts/", headers=CL_HEADERS, timeout=15)
        r.raise_for_status()
        return r.json().get("results", [])
    except Exception:
        return []


def delete_cl_alert(alert_id: int) -> bool:
    """Delete a CourtListener alert by ID."""
    if not os.getenv("COURTLISTENER_API_TOKEN", ""):
        return False
    try:
        r = httpx.delete(f"{CL_BASE}/alerts/{alert_id}/", headers=CL_HEADERS, timeout=15)
        return r.status_code in (200, 204)
    except Exception:
        return False


def sync_alert_to_courtlistener(rule: dict) -> dict:
    """
    Given a LegalPerigee alert rule dict, create the equivalent CourtListener alert.
    Called automatically when a new alert rule is saved.

    Returns a status dict that is stored in the alert rule's metadata.
    """
    keywords = rule.get("keywords", "")
    name     = rule.get("name", "LegalPerigee Alert")
    courts   = rule.get("courts", "")
    states   = rule.get("states", "")

    # Build CourtListener query
    query_parts = [keywords] if keywords else []
    if courts:
        for court in [c.strip() for c in courts.split(",") if c.strip()]:
            query_parts.append(f"court:{court.lower()}")

    query = " ".join(query_parts) or name

    result = create_cl_search_alert(
        name=f"LegalPerigee: {name}",
        query=query,
        rate="dly",   # daily digest by default
        alert_type="d",  # docket alerts
    )
    return result
