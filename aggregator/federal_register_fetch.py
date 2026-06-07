"""
Federal Register + Regulations.gov aggregator.
Free APIs — no key needed.
"""

import json
import time
from typing import Callable, Optional

import httpx

from database.db import log_sync_finish, log_sync_start, upsert_case

FR_BASE   = "https://www.federalregister.gov/api/v1"
REGS_BASE = "https://api.regulations.gov/v4"

# All major regulatory topics — no AI-only restriction
REG_TERMS = [
    # Consumer protection
    "consumer fraud", "unfair deceptive practices", "consumer protection",
    # Civil rights
    "civil rights", "discrimination", "equal opportunity",
    # Financial
    "financial fraud", "securities regulation", "banking enforcement",
    "fair lending", "predatory lending",
    # Privacy & tech
    "privacy data protection", "artificial intelligence", "algorithmic",
    "cybersecurity", "data breach",
    # Environmental & health
    "environmental enforcement", "public health safety",
    # Labor
    "labor employment", "workplace safety",
]
AI_TERMS = REG_TERMS  # backward compat

HEADERS = {"User-Agent": "LegalPerigee/1.0 (legal research)"}


def _fr_row(doc: dict) -> dict:
    agencies = ", ".join(a.get("name", "") for a in doc.get("agencies", []))
    return {
        "id": f"fr_{doc.get('document_number', doc.get('id',''))}",
        "source": "federal_register",
        "case_name": doc.get("title", ""),
        "court": agencies or "Federal Register",
        "jurisdiction": "Federal",
        "filing_date": (doc.get("publication_date") or "")[:10],
        "case_type": doc.get("type", "Rule"),
        "status": doc.get("action", "Published"),
        "summary": (doc.get("abstract") or doc.get("description") or "")[:500],
        "defendants": agencies,
        "document_url": doc.get("html_url", ""),
        "raw_json": json.dumps({k: v for k, v in doc.items()
                                if k not in ("full_text_xml_url", "body_html_url")}),
    }


def fetch_federal_register(
    terms: Optional[list[str]] = None,
    max_per_term: int = 20,
    start_date: str = "2018-01-01",
    progress_cb: Optional[Callable[[str], None]] = None,
) -> tuple[int, int]:
    added = updated = 0
    SOURCE = "federal_register"
    sync_id = log_sync_start(SOURCE)
    terms = terms or AI_TERMS

    for term in terms:
        if progress_cb: progress_cb(f"Federal Register: {term}")
        try:
            r = httpx.get(f"{FR_BASE}/documents.json", headers=HEADERS, timeout=20, params={
                "conditions[term]": term,
                "conditions[publication_date][gte]": start_date,
                "conditions[type][]": ["RULE", "PROPOSED_RULE", "NOTICE"],
                "per_page": max_per_term,
                "order": "newest",
                "fields[]": ["document_number", "title", "publication_date", "type",
                             "action", "abstract", "agencies", "html_url", "docket_id"],
            })
            r.raise_for_status()
            for doc in r.json().get("results", []):
                row = _fr_row(doc)
                if upsert_case(row): added += 1
                else: updated += 1
        except Exception as e:
            if progress_cb: progress_cb(f"  ⚠️ FR error: {e}")
        time.sleep(0.2)

    log_sync_finish(sync_id, added, updated, "success")
    if progress_cb: progress_cb(f"Federal Register: +{added} new")
    return added, updated


def run_federal_register_sync(progress_cb=None) -> dict:
    a, u = fetch_federal_register(progress_cb=progress_cb)
    return {"added": a, "updated": u, "status": "success"}
