"""
Regulations.gov full docket aggregator.
API: api.regulations.gov/v4  (free key at api.regulations.gov)
Set REGULATIONS_GOV_KEY in .env

Pulls complete regulatory dockets including public comments — rich investigative
leads because commenters often name specific companies and document harms before
formal enforcement actions.
"""

import json
import os
import time
from typing import Callable, Optional

import httpx

from database.db import log_sync_finish, log_sync_start, upsert_case

SOURCE = "regulations_gov"
BASE   = "https://api.regulations.gov/v4"


def _regs_headers() -> dict:
    """
    M-3: Build headers lazily with API key in header, not URL param.
    Regulations.gov supports the X-Api-Key header.
    """
    api_key = os.getenv("REGULATIONS_GOV_KEY", "DEMO_KEY")  # DEMO_KEY has low rate limits
    return {
        "User-Agent": "LegalPerigee/1.2 (legal research; contact admin@legalperigee.ai)",
        "X-Api-Key":  api_key,
    }

SEARCH_TERMS = [
    "fraud consumer protection",
    "civil rights discrimination",
    "financial fraud predatory lending",
    "privacy data breach",
    "environmental enforcement",
    "healthcare fraud",
    "housing discrimination",
    "employment discrimination",
    "criminal justice",
    "voting rights",
    "artificial intelligence",
    "algorithmic decision",
    "surveillance biometric",
    "financial technology fintech",
]


def _doc_to_row(doc: dict) -> dict:
    attrs = doc.get("attributes", {})
    links = doc.get("links", {})
    return {
        "id": f"regs_{doc.get('id','')}",
        "source": SOURCE,
        "case_name": attrs.get("title", "")[:200],
        "court": attrs.get("agencyId", "Federal Agency"),
        "jurisdiction": "Federal",
        "filing_date": (attrs.get("postedDate") or attrs.get("receiveDate") or "")[:10],
        "case_type": attrs.get("documentType", "Regulatory Document"),
        "status": attrs.get("docketId", ""),
        "summary": attrs.get("summary", "")[:500] or attrs.get("title", "")[:200],
        "defendants": attrs.get("agencyId", ""),
        "document_url": (
            f"https://www.regulations.gov/document/{doc.get('id','')}"
            if doc.get("id") else links.get("self", "")
        ),
        "raw_json": json.dumps({
            "id": doc.get("id"),
            "type": attrs.get("documentType"),
            "docket": attrs.get("docketId"),
            "agency": attrs.get("agencyId"),
            "comment_count": attrs.get("numberOfCommentsReceived"),
        }),
    }


def _comment_to_row(comment: dict, docket_id: str) -> dict:
    attrs = comment.get("attributes", {})
    text  = attrs.get("comment", "")[:400]
    return {
        "id": f"regs_comment_{comment.get('id','')}",
        "source": SOURCE,
        "case_name": f"Public Comment on {docket_id}: {attrs.get('title','')[:80]}",
        "court": "Regulations.gov",
        "jurisdiction": "Federal",
        "filing_date": (attrs.get("postedDate") or "")[:10],
        "case_type": "Public Comment",
        "status": "Submitted",
        "summary": text,
        "plaintiffs": attrs.get("organization", "") or attrs.get("submitterRep", ""),
        "document_url": f"https://www.regulations.gov/comment/{comment.get('id','')}",
        "raw_json": json.dumps({
            "id": comment.get("id"),
            "docket": docket_id,
            "organization": attrs.get("organization"),
        }),
    }


def search_documents(
    term: str,
    max_results: int = 25,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> tuple[int, int]:
    added = updated = 0
    try:
        r = httpx.get(
            f"{BASE}/documents",
            headers=_regs_headers(), timeout=20,
            params={
                "filter[searchTerm]": term,
                "sort": "-postedDate",
                "page[size]": min(max_results, 25),
                # M-3: api_key moved to X-Api-Key header in _regs_headers()
            },
        )
        r.raise_for_status()
        for doc in r.json().get("data", []):
            row = _doc_to_row(doc)
            if upsert_case(row): added += 1
            else: updated += 1
    except Exception as e:
        if progress_cb: progress_cb(f"  ⚠️ Regulations.gov '{term}': {e}")
    return added, updated


def fetch_docket_comments(
    docket_id: str,
    max_comments: int = 20,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> tuple[int, int]:
    """Fetch public comments for a specific docket."""
    added = updated = 0
    try:
        r = httpx.get(
            f"{BASE}/comments",
            headers=_regs_headers(), timeout=20,
            params={
                "filter[docketId]": docket_id,
                "sort": "-postedDate",
                "page[size]": min(max_comments, 25),
                # M-3: api_key moved to X-Api-Key header in _regs_headers()
            },
        )
        r.raise_for_status()
        for comment in r.json().get("data", []):
            row = _comment_to_row(comment, docket_id)
            if upsert_case(row): added += 1
            else: updated += 1
    except Exception as e:
        if progress_cb: progress_cb(f"  ⚠️ Comments for {docket_id}: {e}")
    return added, updated


def run_regulations_sync(
    terms: Optional[list[str]] = None,
    fetch_comments: bool = True,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> dict:
    sync_id = log_sync_start(SOURCE)
    terms   = terms or SEARCH_TERMS
    total_a = total_u = 0

    if os.getenv("REGULATIONS_GOV_KEY", "DEMO_KEY") == "DEMO_KEY":
        if progress_cb:
            progress_cb("Regulations.gov: using DEMO_KEY (low rate limits). "
                        "Add REGULATIONS_GOV_KEY to .env for full access.")

    for i, term in enumerate(terms, 1):
        if progress_cb: progress_cb(f"[{i}/{len(terms)}] Regulations.gov: {term}")
        a, u = search_documents(term, progress_cb=progress_cb)
        total_a += a; total_u += u
        time.sleep(1.0 if os.getenv("REGULATIONS_GOV_KEY", "DEMO_KEY") == "DEMO_KEY" else 0.3)

    log_sync_finish(sync_id, total_a, total_u, "success")
    if progress_cb: progress_cb(f"Regulations.gov: +{total_a} new, {total_u} updated")
    return {"added": total_a, "updated": total_u, "status": "success"}
