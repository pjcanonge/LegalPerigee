"""
CourtListener aggregator — fetches published opinions and federal dockets
across all U.S. courts and stores them in the local SQLite database.
"""

import json
import time
from datetime import datetime, timedelta
from typing import Callable, Optional

import httpx

from database.db import log_sync_finish, log_sync_start, upsert_case
from tools.court_tools import _cl_headers, _CL_BASE, _CL_TIMEOUT

SOURCE = "courtlistener"

# Broad AI-related search terms to seed the library
DEFAULT_QUERIES = [
    "artificial intelligence fraud",
    "AI discrimination",
    "algorithmic bias",
    "automated decision making discrimination",
    "deepfake fraud",
    "chatbot deception",
    "machine learning discrimination",
    "AI lending discrimination",
    "facial recognition discrimination",
    "predictive policing discrimination",
]


def _cl_get_raw(path: str, params: dict) -> dict:
    url = f"{_CL_BASE}{path}"
    with httpx.Client(timeout=_CL_TIMEOUT, headers=_cl_headers()) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


def _opinion_to_row(hit: dict) -> dict:
    """Map a CourtListener opinion search result to a cases table row."""
    case_id = f"cl_opinion_{hit.get('id') or hit.get('cluster_id', '')}"
    absolute_url = hit.get("absolute_url", "")
    doc_url = f"https://www.courtlistener.com{absolute_url}" if absolute_url else None

    return {
        "id": case_id,
        "source": SOURCE,
        "case_name": hit.get("caseName") or hit.get("case_name", ""),
        "court": hit.get("court", ""),
        "jurisdiction": hit.get("court", ""),
        "docket_number": hit.get("docketNumber") or hit.get("docket_number", ""),
        "filing_date": hit.get("dateFiled") or hit.get("date_filed", ""),
        "decision_date": hit.get("dateArgued") or hit.get("date_argued", ""),
        "case_type": "opinion",
        "status": hit.get("status", "Published"),
        "summary": hit.get("snippet", ""),
        "allegations": "",
        "harm_types": json.dumps([]),
        "citation": json.dumps(hit.get("citation", [])),
        "document_url": doc_url,
        "raw_json": json.dumps(hit),
    }


def _docket_to_row(hit: dict) -> dict:
    """Map a CourtListener docket search result to a cases table row."""
    case_id = f"cl_docket_{hit.get('docket_id') or hit.get('id', '')}"
    absolute_url = hit.get("absolute_url", "")
    doc_url = f"https://www.courtlistener.com{absolute_url}" if absolute_url else None

    parties = hit.get("party", [])
    plaintiffs_raw = hit.get("plaintiff", "") or (parties[0] if parties else "")
    defendants_raw = hit.get("defendant", "") or (parties[1] if len(parties) > 1 else "")

    return {
        "id": case_id,
        "source": SOURCE,
        "case_name": hit.get("caseName") or hit.get("case_name", ""),
        "court": hit.get("court", ""),
        "jurisdiction": hit.get("court", ""),
        "docket_number": hit.get("docketNumber") or hit.get("docket_number", ""),
        "filing_date": hit.get("dateFiled") or hit.get("date_filed", ""),
        "case_type": hit.get("suitNature") or hit.get("nature_of_suit", "docket"),
        "status": "active",
        "summary": "",
        "allegations": hit.get("cause", ""),
        "harm_types": json.dumps([]),
        "plaintiffs": str(plaintiffs_raw),
        "defendants": str(defendants_raw),
        "judge": hit.get("assignedTo") or hit.get("assigned_to", ""),
        "document_url": doc_url,
        "raw_json": json.dumps(hit),
    }


def fetch_opinions(
    query: str,
    max_results: int = 100,
    filed_after: Optional[str] = None,
    court: Optional[str] = None,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> tuple[int, int]:
    """Fetch opinions matching query. Returns (added, updated)."""
    added = updated = 0
    page = 1
    fetched = 0

    while fetched < max_results:
        params: dict = {
            "q": query,
            "type": "o",
            "order_by": "dateFiled desc",
            "format": "json",
            "page": page,
        }
        if filed_after:
            params["filed_after"] = filed_after
        if court:
            params["court"] = court

        try:
            data = _cl_get_raw("/search/", params)
        except Exception as e:
            if progress_cb:
                progress_cb(f"CourtListener opinions error: {e}")
            break

        results = data.get("results", [])
        if not results:
            break

        for hit in results:
            row = _opinion_to_row(hit)
            if upsert_case(row):
                added += 1
            else:
                updated += 1
            fetched += 1
            if fetched >= max_results:
                break

        if not data.get("next"):
            break
        page += 1
        time.sleep(0.3)  # be polite to CourtListener

    if progress_cb:
        progress_cb(f"Opinions: +{added} new, {updated} updated")
    return added, updated


def fetch_dockets(
    query: str,
    max_results: int = 100,
    filed_after: Optional[str] = None,
    court: Optional[str] = None,
    nature_of_suit: Optional[str] = None,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> tuple[int, int]:
    """Fetch dockets matching query. Returns (added, updated)."""
    added = updated = 0
    page = 1
    fetched = 0

    while fetched < max_results:
        params: dict = {
            "q": query,
            "type": "d",
            "order_by": "dateFiled desc",
            "format": "json",
            "page": page,
        }
        if filed_after:
            params["filed_after"] = filed_after
        if court:
            params["court"] = court
        if nature_of_suit:
            params["nature_of_suit"] = nature_of_suit

        try:
            data = _cl_get_raw("/search/", params)
        except Exception as e:
            if progress_cb:
                progress_cb(f"CourtListener dockets error: {e}")
            break

        results = data.get("results", [])
        if not results:
            break

        for hit in results:
            row = _docket_to_row(hit)
            if upsert_case(row):
                added += 1
            else:
                updated += 1
            fetched += 1
            if fetched >= max_results:
                break

        if not data.get("next"):
            break
        page += 1
        time.sleep(0.3)

    if progress_cb:
        progress_cb(f"Dockets: +{added} new, {updated} updated")
    return added, updated


def run_full_sync(
    queries: Optional[list[str]] = None,
    max_per_query: int = 50,
    filed_after: Optional[str] = None,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> dict:
    """
    Run a full CourtListener sync across all default queries.

    Args:
        queries: Search terms to use (defaults to DEFAULT_QUERIES)
        max_per_query: Max cases per query (opinions + dockets)
        filed_after: Only fetch cases filed after this date (YYYY-MM-DD)
        progress_cb: Optional callback for progress messages

    Returns:
        Summary dict with totals
    """
    if queries is None:
        queries = DEFAULT_QUERIES

    if filed_after is None:
        # Default: last 2 years
        filed_after = (datetime.now() - timedelta(days=730)).strftime("%Y-%m-%d")

    sync_id = log_sync_start(SOURCE)
    total_added = total_updated = 0

    try:
        for i, q in enumerate(queries, 1):
            if progress_cb:
                progress_cb(f"[{i}/{len(queries)}] Fetching: {q}")

            a, u = fetch_opinions(q, max_per_query, filed_after, progress_cb=progress_cb)
            total_added += a
            total_updated += u
            time.sleep(0.5)

            a, u = fetch_dockets(q, max_per_query, filed_after, progress_cb=progress_cb)
            total_added += a
            total_updated += u
            time.sleep(0.5)

        log_sync_finish(sync_id, total_added, total_updated, "success")
        return {"added": total_added, "updated": total_updated, "status": "success"}

    except Exception as e:
        log_sync_finish(sync_id, total_added, total_updated, "error", str(e))
        return {"added": total_added, "updated": total_updated, "status": "error", "error": str(e)}
