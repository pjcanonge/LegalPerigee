"""
OpenStates aggregator — all 50 state legislatures.
API: v3.openstates.org  (free API key at openstates.org/accounts/login)
Set OPENSTATES_API_KEY in .env

Covers: state bills, sponsors, committee assignments, latest legislative actions.
"""

import json
import os
import time
from typing import Callable, Optional

import httpx

from database.db import log_sync_finish, log_sync_start, upsert_case

SOURCE = "openstates"
BASE   = "https://v3.openstates.org"


def _os_headers() -> dict:
    """
    M-2: Build headers lazily so Keychain tokens loaded after import are included.
    """
    api_key = os.getenv("OPENSTATES_API_KEY", "")
    return {
        "User-Agent": "LegalPerigee/1.2 (legal research)",
        "X-API-KEY":  api_key,
    }

# All US state + territory jurisdictions
JURISDICTIONS = [
    "us","al","ak","az","ar","ca","co","ct","de","fl","ga","hi","id","il","in",
    "ia","ks","ky","la","me","md","ma","mi","mn","ms","mo","mt","ne","nv","nh",
    "nj","nm","ny","nc","nd","oh","ok","or","pa","ri","sc","sd","tn","tx","ut",
    "vt","va","wa","wv","wi","wy","dc","pr",
]

# Broad search terms covering all major legal categories
SEARCH_TERMS = [
    "fraud", "consumer protection", "civil rights", "discrimination",
    "housing", "employment", "criminal justice", "environmental",
    "healthcare", "financial", "privacy", "surveillance", "voting rights",
    "police", "immigration", "education", "labor", "child welfare",
]


def _bill_to_row(bill: dict) -> dict:
    sponsors = bill.get("sponsorships", [])
    sponsor_names = ", ".join(
        s.get("name", "") for s in sponsors[:3] if s.get("name")
    )
    actions = bill.get("actions", [])
    latest_action = actions[-1].get("description", "") if actions else ""
    latest_date   = actions[-1].get("date", "")[:10] if actions else ""

    return {
        "id": f"openstates_{bill.get('id', '')}",
        "source": SOURCE,
        "case_name": f"{bill.get('identifier','')} — {bill.get('title','')}",
        "court": f"{bill.get('jurisdiction',{}).get('name','')}"
                 f" {bill.get('chamber','').title()} Legislature",
        "jurisdiction": bill.get("jurisdiction", {}).get("name", ""),
        "filing_date": bill.get("first_action_date", "")[:10],
        "decision_date": latest_date,
        "case_type": "State Legislation",
        "status": latest_action[:200] if latest_action else bill.get("status", ""),
        "summary": bill.get("title", "")[:500],
        "allegations": ", ".join(bill.get("subject", [])),
        "plaintiffs": sponsor_names,
        "document_url": bill.get("openstates_url", ""),
        "raw_json": json.dumps({
            "id": bill.get("id"),
            "identifier": bill.get("identifier"),
            "session": bill.get("session"),
            "subjects": bill.get("subject", []),
            "url": bill.get("openstates_url", ""),
        }),
    }


def fetch_bills(
    term: str,
    jurisdictions: Optional[list[str]] = None,
    max_per_term: int = 50,
    since_date: str = "2020-01-01",
    progress_cb: Optional[Callable[[str], None]] = None,
    max_jurisdictions: Optional[int] = None,
) -> tuple[int, int]:
    """Fetch state bills matching a term across jurisdictions.

    Previously this silently capped at the first 10 jurisdictions, so every
    state after Florida was never queried. It now iterates ALL supplied
    jurisdictions (optionally capped via `max_jurisdictions`), throttled to stay
    within the OpenStates free-tier rate limit.
    """
    if not os.getenv("OPENSTATES_API_KEY", ""):
        if progress_cb:
            progress_cb("OpenStates: no API key — add OPENSTATES_API_KEY to .env (free at openstates.org)")
        return 0, 0

    added = updated = 0
    jurisdictions = jurisdictions or ["us"]   # default to just federal if none specified
    if max_jurisdictions:
        jurisdictions = jurisdictions[:max_jurisdictions]

    # Free-tier friendly throttle (OpenStates limits to a few requests/sec and a
    # daily cap). Override via OPENSTATES_RATE_DELAY if you have a higher tier.
    delay = float(os.getenv("OPENSTATES_RATE_DELAY", "1.0"))

    for jur in jurisdictions:
        params = {
            "q": term,
            "jurisdiction": jur,
            "sort": "updated_desc",
            "per_page": min(max_per_term, 20),
            "include": "sponsorships,actions",
            "updated_since": since_date,
        }
        try:
            r = httpx.get(f"{BASE}/bills", headers=_os_headers(), timeout=20, params=params)
            if r.status_code == 429:
                # Respect Retry-After, then try once more before giving up.
                wait = int(r.headers.get("Retry-After", "5") or "5")
                if progress_cb: progress_cb(f"  ⏳ OpenStates rate-limited on {jur}; waiting {wait}s")
                time.sleep(min(wait, 30))
                r = httpx.get(f"{BASE}/bills", headers=_os_headers(), timeout=20, params=params)
            r.raise_for_status()
            for bill in r.json().get("results", []):
                row = _bill_to_row(bill)
                if upsert_case(row): added += 1
                else: updated += 1
        except Exception as e:
            if progress_cb: progress_cb(f"  ⚠️ OpenStates {jur}: {e}")
        time.sleep(delay)

    return added, updated


def run_openstates_sync(
    terms: Optional[list[str]] = None,
    jurisdictions: Optional[list[str]] = None,
    max_per_term: int = 20,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> dict:
    """Sync state legislative bills. Uses all US state jurisdictions by default."""
    sync_id  = log_sync_start(SOURCE)
    terms    = terms or SEARCH_TERMS
    jurs     = jurisdictions or JURISDICTIONS
    total_a  = total_u = 0

    for i, term in enumerate(terms, 1):
        if progress_cb: progress_cb(f"[{i}/{len(terms)}] OpenStates: {term}")
        a, u = fetch_bills(term, jurs, max_per_term, progress_cb=progress_cb)
        total_a += a; total_u += u
        time.sleep(0.3)

    log_sync_finish(sync_id, total_a, total_u, "success")
    if progress_cb: progress_cb(f"OpenStates: +{total_a} new, {total_u} updated")
    return {"added": total_a, "updated": total_u, "status": "success"}
