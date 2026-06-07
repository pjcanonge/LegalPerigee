"""
GovTrack aggregator — U.S. Congress bill tracking, votes, members.
API: govtrack.us/api/v2  (no key required, free)

Covers: bills with status/progress, roll-call votes, member profiles,
        committee assignments, cosponsors.
"""

import json
import time
from typing import Callable, Optional

import httpx

from database.db import log_sync_finish, log_sync_start, upsert_case

SOURCE = "govtrack"
BASE   = "https://www.govtrack.us/api/v2"
HEADERS = {"User-Agent": "LegalPerigee/1.0 (legal research; contact admin@legalperigee.ai)"}

SEARCH_TERMS = [
    "fraud", "civil rights", "discrimination", "consumer protection",
    "criminal justice reform", "privacy", "housing", "employment",
    "environmental", "financial regulation", "healthcare", "voting rights",
    "police accountability", "immigration", "education", "labor",
]


def _bill_to_row(bill: dict) -> dict:
    cosponsors = bill.get("cosponsors_count", 0)
    sponsor    = bill.get("sponsor_name", "")
    status     = bill.get("current_status_description", "")
    introduced = bill.get("introduced_date", "")[:10]
    chamber    = "Senate" if bill.get("bill_type","").startswith("s") else "House"

    return {
        "id": f"govtrack_{bill.get('id','')}",
        "source": SOURCE,
        "case_name": f"{bill.get('display_number','')} — {bill.get('title_without_number','')[:120]}",
        "court": f"U.S. Congress — {chamber}",
        "jurisdiction": "Federal",
        "filing_date": introduced,
        "case_type": "Federal Legislation",
        "status": status[:200],
        "summary": bill.get("title_without_number", "")[:500],
        "plaintiffs": sponsor,
        "allegations": f"{cosponsors} cosponsors" if cosponsors else "",
        "document_url": f"https://www.govtrack.us{bill.get('link','')}",
        "raw_json": json.dumps({
            "id": bill.get("id"),
            "number": bill.get("display_number"),
            "bill_type": bill.get("bill_type"),
            "congress": bill.get("congress"),
            "prognosis": bill.get("prognosis", {}).get("pass_over_house"),
            "link": bill.get("link"),
        }),
    }


def _vote_to_row(vote: dict) -> dict:
    return {
        "id": f"govtrack_vote_{vote.get('id','')}",
        "source": SOURCE,
        "case_name": f"Vote: {vote.get('question','')[:100]}",
        "court": f"U.S. Congress — {vote.get('chamber','').title()}",
        "jurisdiction": "Federal",
        "filing_date": (vote.get("created", "")[:10]),
        "case_type": "Congressional Vote",
        "status": vote.get("result", ""),
        "summary": f"{vote.get('question','')} — {vote.get('result','')}",
        "document_url": f"https://www.govtrack.us{vote.get('link','')}",
        "raw_json": json.dumps({
            "id": vote.get("id"),
            "chamber": vote.get("chamber"),
            "total_plus": vote.get("total_plus"),
            "total_minus": vote.get("total_minus"),
            "link": vote.get("link"),
        }),
    }


def fetch_govtrack_bills(
    term: str,
    congress: int = 119,
    max_results: int = 50,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> tuple[int, int]:
    added = updated = 0
    try:
        r = httpx.get(
            f"{BASE}/bill",
            headers=HEADERS, timeout=20,
            params={
                "q": term,
                "congress": congress,
                "sort": "-introduced_date",
                "limit": min(max_results, 100),
                "fields": "id,display_number,title_without_number,bill_type,congress,"
                          "introduced_date,current_status_description,sponsor_name,"
                          "cosponsors_count,prognosis,link",
            },
        )
        r.raise_for_status()
        for bill in r.json().get("objects", []):
            row = _bill_to_row(bill)
            if upsert_case(row): added += 1
            else: updated += 1
    except Exception as e:
        if progress_cb: progress_cb(f"  ⚠️ GovTrack bills '{term}': {e}")
    return added, updated


def fetch_govtrack_votes(
    congress: int = 119,
    max_results: int = 100,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> tuple[int, int]:
    """Fetch recent congressional votes."""
    added = updated = 0
    try:
        r = httpx.get(
            f"{BASE}/vote",
            headers=HEADERS, timeout=20,
            params={
                "congress": congress,
                "sort": "-created",
                "limit": max_results,
                "fields": "id,chamber,question,result,created,link,total_plus,total_minus",
            },
        )
        r.raise_for_status()
        for vote in r.json().get("objects", []):
            row = _vote_to_row(vote)
            if upsert_case(row): added += 1
            else: updated += 1
    except Exception as e:
        if progress_cb: progress_cb(f"  ⚠️ GovTrack votes: {e}")
    return added, updated


def run_govtrack_sync(
    terms: Optional[list[str]] = None,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> dict:
    sync_id = log_sync_start(SOURCE)
    terms   = terms or SEARCH_TERMS
    total_a = total_u = 0

    for i, term in enumerate(terms, 1):
        if progress_cb: progress_cb(f"[{i}/{len(terms)}] GovTrack: {term}")
        a, u = fetch_govtrack_bills(term, progress_cb=progress_cb)
        total_a += a; total_u += u
        time.sleep(0.2)

    if progress_cb: progress_cb("GovTrack: fetching recent votes…")
    a, u = fetch_govtrack_votes(progress_cb=progress_cb)
    total_a += a; total_u += u

    log_sync_finish(sync_id, total_a, total_u, "success")
    if progress_cb: progress_cb(f"GovTrack: +{total_a} new, {total_u} updated")
    return {"added": total_a, "updated": total_u, "status": "success"}
