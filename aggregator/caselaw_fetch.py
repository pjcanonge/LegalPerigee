"""
Harvard Caselaw Access Project — 6.7 million U.S. cases, all 50 states + federal.
API: api.case.law  (free, no key needed for basic searches)
Register for a free key at case.law to get higher rate limits.
"""

import json
import os
import time
from typing import Callable, Optional

from database.db import log_sync_finish, log_sync_start, upsert_case
from utils.http_utils import safe_get_json

SOURCE = "harvard_cap"
BASE   = "https://api.case.law/v1"
TOKEN  = os.getenv("HARVARD_CAP_TOKEN", "")  # optional — add to .env for higher limits

AI_QUERIES = [
    "artificial intelligence fraud",
    "algorithmic discrimination",
    "deepfake",
    "automated decision making discrimination",
    "facial recognition wrongful",
    "machine learning bias employment",
    "AI lending discrimination",
    "chatbot deception consumer",
    "synthetic media fraud",
    "predictive policing civil rights",
]

HEADERS = {"User-Agent": "LegalPerigee/1.0 (legal research; contact admin@legalperigee.ai)"}
if TOKEN:
    HEADERS["Authorization"] = f"Token {TOKEN}"


def _get(path: str, params: dict, progress_cb=None) -> Optional[dict]:
    return safe_get_json(
        f"{BASE}{path}", headers=HEADERS, params=params,
        timeout=20, retries=3, progress_cb=progress_cb,
        source_label="harvard_cap",
    )


def _cap_to_row(case: dict) -> dict:
    court = case.get("court", {})
    jurisdiction = case.get("jurisdiction", {})
    citations = [c.get("cite", "") for c in case.get("citations", [])]
    url = case.get("url", "")
    frontend = case.get("frontend_url", url)

    return {
        "id": f"cap_{case.get('id', '')}",
        "source": SOURCE,
        "case_name": case.get("name_abbreviation") or case.get("name", ""),
        "court": court.get("name", ""),
        "jurisdiction": jurisdiction.get("name_long") or jurisdiction.get("name", ""),
        "docket_number": case.get("docket_number", ""),
        "filing_date": (case.get("decision_date") or "")[:10],
        "decision_date": (case.get("decision_date") or "")[:10],
        "case_type": "case_law",
        "status": "Decided",
        "citation": json.dumps(citations),
        "document_url": frontend,
        "raw_json": json.dumps({k: v for k, v in case.items() if k != "casebody"}),
    }


def fetch_by_query(
    query: str,
    jurisdiction: Optional[str] = None,
    max_results: int = 50,
    after_date: Optional[str] = None,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> tuple[int, int]:
    added = updated = 0
    params: dict = {
        "search": query,
        "page_size": min(max_results, 100),
        "ordering": "-decision_date",
    }
    if jurisdiction:
        params["jurisdiction"] = jurisdiction
    if after_date:
        params["decision_date_min"] = after_date

    data = _get("/cases/", params, progress_cb=progress_cb)
    if not data:
        return 0, 0

    for case in data.get("results", []):
        row = _cap_to_row(case)
        if upsert_case(row):
            added += 1
        else:
            updated += 1

    return added, updated


def run_cap_sync(
    queries: Optional[list[str]] = None,
    max_per_query: int = 30,
    after_date: str = "2018-01-01",
    progress_cb: Optional[Callable[[str], None]] = None,
) -> dict:
    queries = queries or AI_QUERIES
    sync_id = log_sync_start(SOURCE)
    total_added = total_updated = 0

    for i, q in enumerate(queries, 1):
        if progress_cb:
            progress_cb(f"[{i}/{len(queries)}] Harvard CAP: {q}")
        a, u = fetch_by_query(q, max_results=max_per_query,
                              after_date=after_date, progress_cb=progress_cb)
        total_added += a
        total_updated += u
        time.sleep(0.3)

    log_sync_finish(sync_id, total_added, total_updated, "success")
    if progress_cb:
        progress_cb(f"Harvard CAP: +{total_added} new, {total_updated} updated")
    return {"added": total_added, "updated": total_updated, "status": "success"}
