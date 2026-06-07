"""
SEC EDGAR aggregator — financial filings that precede court cases.
Uses the EDGAR full-text search API (free, no key required).

Key filing types:
  8-K  — Material events: fraud disclosures, regulatory actions, lawsuits
  10-K — Annual reports: risk factors, legal proceedings
  DEF 14A — Proxy statements with litigation disclosures
  SC 13D/G — Activist investor disclosures
"""

import json
import time
from typing import Callable, Optional

import httpx

from database.db import log_sync_finish, log_sync_start, upsert_case

SOURCE    = "sec_edgar"
EFTS_BASE = "https://efts.sec.gov/LATEST/search-index"
SEARCH_BASE = "https://efts.sec.gov/LATEST/search-index"
HEADERS   = {"User-Agent": "LegalPerigee/1.0 legal-research admin@legalperigee.ai"}

# Form types most relevant to fraud/litigation
FORM_TYPES = ["8-K", "10-K", "10-Q", "DEF 14A"]

SEARCH_TERMS = [
    "fraud", "securities fraud", "consumer fraud",
    "civil rights violation", "discrimination",
    "regulatory enforcement action",
    "class action lawsuit filed",
    "indicted charged criminal",
    "restatement financial misconduct",
    "whistleblower SEC investigation",
    "DOJ investigation subpoena",
    "FTC enforcement consent order",
    "data breach privacy violation",
    "FCPA foreign corrupt practices",
    "money laundering",
    "insider trading",
    "Ponzi scheme",
    "false statements material misrepresentation",
]


def _filing_to_row(hit: dict) -> dict:
    entity = hit.get("entity_name", "")
    form   = hit.get("file_type", "")
    filed  = (hit.get("period_of_report") or hit.get("file_date") or "")[:10]
    desc   = hit.get("description", "") or hit.get("display_date_filed", "")
    accession = hit.get("accession_no", "").replace("-", "")
    cik    = hit.get("entity_id", "")

    url = ""
    if cik and accession:
        url = f"https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&CIK={cik}&type={form}&dateb=&owner=include&count=10"
    elif hit.get("file_path"):
        url = f"https://www.sec.gov{hit['file_path']}"

    return {
        "id": f"edgar_{hit.get('accession_no','').replace('-','_')}",
        "source": SOURCE,
        "case_name": f"{form}: {entity} — {(hit.get('period_of_report') or filed)}",
        "court": "SEC EDGAR",
        "jurisdiction": "Federal",
        "filing_date": filed,
        "case_type": f"SEC Filing ({form})",
        "status": "Filed",
        "summary": (hit.get("file_description") or hit.get("description") or "")[:500],
        "defendants": entity,
        "document_url": url,
        "raw_json": json.dumps({
            "entity": entity,
            "form": form,
            "accession": hit.get("accession_no"),
            "cik": cik,
            "filed": filed,
        }),
    }


def search_edgar(
    query: str,
    forms: Optional[list[str]] = None,
    start_date: str = "2020-01-01",
    max_results: int = 40,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> tuple[int, int]:
    """Full-text search EDGAR filings."""
    added = updated = 0
    forms = forms or ["8-K", "10-K"]

    params = {
        "q": f'"{query}"',
        "dateRange": "custom",
        "startdt": start_date,
        "forms": ",".join(forms),
    }

    try:
        r = httpx.get(EFTS_BASE, headers=HEADERS, timeout=25, params=params)
        r.raise_for_status()
        data = r.json()
        hits = data.get("hits", {}).get("hits", [])
        for hit in hits[:max_results]:
            src = hit.get("_source", {})
            row = _filing_to_row(src)
            if upsert_case(row): added += 1
            else: updated += 1
    except Exception as e:
        if progress_cb: progress_cb(f"  ⚠️ EDGAR '{query}': {e}")

    return added, updated


def run_edgar_sync(
    terms: Optional[list[str]] = None,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> dict:
    sync_id = log_sync_start(SOURCE)
    terms   = terms or SEARCH_TERMS
    total_a = total_u = 0

    for i, term in enumerate(terms, 1):
        if progress_cb: progress_cb(f"[{i}/{len(terms)}] SEC EDGAR: {term}")
        a, u = search_edgar(term, progress_cb=progress_cb)
        total_a += a; total_u += u
        time.sleep(0.4)   # EDGAR rate limit: be polite

    log_sync_finish(sync_id, total_a, total_u, "success")
    if progress_cb: progress_cb(f"SEC EDGAR: +{total_a} new, {total_u} updated")
    return {"added": total_a, "updated": total_u, "status": "success"}
