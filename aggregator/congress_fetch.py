"""
Congress.gov aggregator — AI-related legislation and committee hearings.
Free API key required: register at api.congress.gov (instant, no cost).
Set CONGRESS_API_KEY in .env.
"""

import json
import os
import time
from typing import Callable, Optional

import httpx

from database.db import log_sync_finish, log_sync_start, upsert_case

BASE   = "https://api.congress.gov/v3"
SOURCE = "congress"


def _congress_headers() -> dict:
    """
    M-3: Build headers lazily with API key in header (not URL param) to avoid
    key appearing in server access logs and proxy caches.
    """
    token = os.getenv("CONGRESS_API_KEY", "")
    h = {"User-Agent": "LegalPerigee/1.2 (legal research)"}
    if token:
        h["X-Api-Key"] = token   # Congress.gov supports X-Api-Key header
    return h
BILL_QUERIES = [
    # Fraud & crime
    "consumer fraud", "wire fraud", "financial crime",
    "identity theft", "money laundering",
    # Civil rights
    "civil rights", "discrimination", "voting rights",
    "police reform", "equal opportunity",
    # Consumer & finance
    "consumer protection", "predatory lending", "data privacy",
    "financial regulation", "housing discrimination",
    # Emerging tech
    "artificial intelligence", "deepfake", "algorithmic accountability",
    "cybersecurity", "surveillance",
    # Health & environment
    "healthcare fraud", "environmental justice",
]
AI_QUERIES = BILL_QUERIES  # backward compat


def _bill_row(bill: dict) -> dict:
    sponsors = bill.get("sponsors", [])
    sponsor_name = sponsors[0].get("fullName", "") if sponsors else ""
    intro_date = bill.get("introducedDate", "")
    number = f"{bill.get('type','')} {bill.get('number','')}"
    congress_n = bill.get("congress", "")
    url = bill.get("url", "")
    title = bill.get("title", "") or bill.get("shortTitle", "")

    return {
        "id": f"congress_{congress_n}_{bill.get('type','')}{bill.get('number','')}",
        "source": SOURCE,
        "case_name": f"{number} — {title}",
        "court": "U.S. Congress",
        "jurisdiction": "Federal",
        "docket_number": number,
        "filing_date": intro_date,
        "case_type": "Legislation",
        "status": bill.get("latestAction", {}).get("text", "Introduced"),
        "summary": title,
        "plaintiffs": sponsor_name,
        "document_url": f"https://www.congress.gov/bill/{congress_n}th-congress/{bill.get('type','').lower()}-bill/{bill.get('number','')}",
        "raw_json": json.dumps(bill),
    }


# Local keyword filter — the Congress.gov /bill endpoint has NO full-text search
# parameter, so we pull recent bills and filter their titles ourselves.
KEYWORDS = [
    "civil rights", "discrimination", "voting", "police", "housing",
    "consumer protection", "fraud", "privacy", "surveillance", "immigration",
    "healthcare", "environmental justice", "disability", "labor", "education",
    "artificial intelligence", "algorithm", "facial recognition", "predatory",
    "data privacy", "reproductive", "hate crime", "criminal justice", "deepfake",
]


def title_matches(title: str, keywords=KEYWORDS) -> bool:
    """True if any keyword appears in the bill title (pure function)."""
    t = (title or "").lower()
    return any(k in t for k in keywords)


def fetch_congress_bills(
    bill_types: Optional[list[str]] = None,
    max_per_type: int = 250,
    congress: int = 119,
    keywords=KEYWORDS,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> tuple[int, int]:
    """Pull recent federal bills per type and keyword-filter locally.

    The previous implementation passed a `query=` param to `/bill`, but that
    endpoint ignores it (Congress.gov has no full-text bill search API), so every
    search term returned the same generic recent-bills list. We now request bills
    by congress + bill type, newest first, and filter titles against `keywords`.
    """
    added = updated = 0
    sync_id = log_sync_start(SOURCE)

    if not os.getenv("CONGRESS_API_KEY", ""):
        if progress_cb:
            progress_cb("Congress.gov: no API key — add CONGRESS_API_KEY to .env (free at api.congress.gov)")
        log_sync_finish(sync_id, 0, 0, "skipped", "No API key")
        return 0, 0

    bill_types = bill_types or ["hr", "s", "hjres", "sjres"]
    try:
        for bt in bill_types:
            if progress_cb: progress_cb(f"Congress: {bt.upper()} (newest {max_per_type})")
            try:
                # M-3: API key sent via header, not URL query parameter
                r = httpx.get(
                    f"{BASE}/bill/{congress}/{bt}",
                    headers=_congress_headers(), timeout=20,
                    params={"sort": "updateDate+desc", "limit": min(max_per_type, 250)},
                )
                r.raise_for_status()
                for bill in r.json().get("bills", []):
                    if not title_matches(bill.get("title", ""), keywords):
                        continue
                    row = _bill_row(bill)
                    if upsert_case(row): added += 1
                    else: updated += 1
            except Exception as e:
                if progress_cb: progress_cb(f"  ⚠️ Congress {bt}: {e}")
            time.sleep(0.2)

        log_sync_finish(sync_id, added, updated, "success")
        if progress_cb: progress_cb(f"Congress: +{added} new bills")
        return added, updated
    except Exception as e:
        log_sync_finish(sync_id, added, updated, "error", str(e))
        return added, updated


def run_congress_sync(progress_cb=None) -> dict:
    a, u = fetch_congress_bills(progress_cb=progress_cb)
    return {"added": a, "updated": u, "status": "success"}
