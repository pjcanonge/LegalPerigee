"""
State Attorney General aggregator.

Scrapes AI/tech-related enforcement actions from the most active state AGs:
  New York, California, Texas, Florida, Illinois, Washington, Massachusetts,
  Colorado, Connecticut, Virginia.
"""

import json
import re
import time
from typing import Callable, Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from database.db import log_sync_finish, log_sync_start, upsert_case

HEADERS = {
    "User-Agent": (
        "LegalPerigee/1.0 (legal research aggregator; "
        "contact admin@legalperigee.ai)"
    )
}
TIMEOUT = 20

AI_KEYWORDS = [
    "artificial intelligence", " AI ", "algorithm", "automated decision",
    "machine learning", "deepfake", "chatbot", "facial recognition",
    "predictive", "data broker", "surveillance", "biometric",
    "discriminat", "redlining", "lending", "credit score",
]

def _matches_ai(text: str) -> bool:
    t = text.lower()
    return any(kw.lower() in t for kw in AI_KEYWORDS)

def _get(url: str) -> Optional[BeautifulSoup]:
    try:
        with httpx.Client(timeout=TIMEOUT, headers=HEADERS, follow_redirects=True) as c:
            r = c.get(url)
            r.raise_for_status()
            return BeautifulSoup(r.text, "html.parser")
    except Exception:
        return None

def _safe_id(source: str, title: str) -> str:
    return f"{source}_" + re.sub(r"[^a-z0-9]", "_", title.lower())[:70]

def _make_row(source_key: str, title: str, url: str, date: str,
              summary: str, state: str, case_type: str = "State AG Enforcement") -> dict:
    return {
        "id": _safe_id(source_key, title),
        "source": source_key,
        "case_name": title,
        "court": f"{state} Attorney General",
        "jurisdiction": state,
        "filing_date": date,
        "case_type": case_type,
        "status": "Enforcement",
        "summary": summary,
        "document_url": url,
        "raw_json": json.dumps({"title": title, "url": url, "date": date, "state": state}),
    }


# ── New York AG ───────────────────────────────────────────────────────────────
def fetch_ny_ag(progress_cb=None) -> tuple[int,int]:
    added = updated = 0
    SOURCE = "ny_ag"
    sync_id = log_sync_start(SOURCE)
    base = "https://ag.ny.gov"

    for path in ["/press-releases?field_issues_target_id=134",   # tech
                 "/press-releases?field_issues_target_id=18",    # consumer
                 "/press-releases"]:
        if progress_cb: progress_cb(f"NY AG: {base+path}")
        soup = _get(base + path)
        if not soup: continue
        for item in soup.select("article.views-row, .views-row, li.views-row")[:30]:
            a = item.select_one("h3 a, h2 a, a.title, .field-title a")
            if not a: continue
            title = a.get_text(strip=True)
            href = urljoin(base, a.get("href",""))
            date_el = item.select_one("time, .date, .field-date")
            date = date_el.get("datetime", date_el.get_text(strip=True)) if date_el else ""
            body_el = item.select_one("p, .field-body")
            summary = body_el.get_text(strip=True)[:400] if body_el else ""
            # No keyword filter — all cases accepted
            row = _make_row(SOURCE, title, href, date, summary, "New York")
            if upsert_case(row): added += 1
            else: updated += 1
        time.sleep(0.4)

    log_sync_finish(sync_id, added, updated, "success")
    if progress_cb: progress_cb(f"NY AG: +{added} new")
    return added, updated


# ── California AG ─────────────────────────────────────────────────────────────
def fetch_ca_ag(progress_cb=None) -> tuple[int,int]:
    added = updated = 0
    SOURCE = "ca_ag"
    sync_id = log_sync_start(SOURCE)
    base = "https://oag.ca.gov"

    for path in ["/news/press-releases", "/privacy/privacy-enforcement-and-case-summaries"]:
        if progress_cb: progress_cb(f"CA AG: {base+path}")
        soup = _get(base + path)
        if not soup: continue
        for item in soup.select("article, .views-row, li.views-row, .field-items .field-item")[:30]:
            a = item.select_one("h3 a, h2 a, a[href*='/news/'], a[href*='/privacy/']")
            if not a: continue
            title = a.get_text(strip=True)
            href = urljoin(base, a.get("href",""))
            date_el = item.select_one("time, .date-display-single, .field-date")
            date = date_el.get_text(strip=True) if date_el else ""
            body_el = item.select_one("p, .field-body, .views-field-body")
            summary = body_el.get_text(strip=True)[:400] if body_el else ""
            # No keyword filter — all cases accepted
            row = _make_row(SOURCE, title, href, date, summary, "California")
            if upsert_case(row): added += 1
            else: updated += 1
        time.sleep(0.4)

    log_sync_finish(sync_id, added, updated, "success")
    if progress_cb: progress_cb(f"CA AG: +{added} new")
    return added, updated


# ── Texas AG ──────────────────────────────────────────────────────────────────
def fetch_tx_ag(progress_cb=None) -> tuple[int,int]:
    added = updated = 0
    SOURCE = "tx_ag"
    sync_id = log_sync_start(SOURCE)
    base = "https://www.texasattorneygeneral.gov"

    soup = _get(base + "/news/releases")
    if soup:
        for item in soup.select(".news-item, article, .views-row")[:40]:
            a = item.select_one("h3 a, h2 a, a.news-title, .field-title a")
            if not a: continue
            title = a.get_text(strip=True)
            href = urljoin(base, a.get("href",""))
            date_el = item.select_one("time, .date, .news-date")
            date = date_el.get_text(strip=True) if date_el else ""
            body_el = item.select_one("p, .news-body, .field-body")
            summary = body_el.get_text(strip=True)[:400] if body_el else ""
            # No keyword filter — all cases accepted
            row = _make_row(SOURCE, title, href, date, summary, "Texas")
            if upsert_case(row): added += 1
            else: updated += 1

    log_sync_finish(sync_id, added, updated, "success")
    if progress_cb: progress_cb(f"TX AG: +{added} new")
    return added, updated


# ── Florida AG ────────────────────────────────────────────────────────────────
def fetch_fl_ag(progress_cb=None) -> tuple[int,int]:
    added = updated = 0
    SOURCE = "fl_ag"
    sync_id = log_sync_start(SOURCE)
    base = "https://www.myfloridalegal.com"

    soup = _get(base + "/news")
    if soup:
        for item in soup.select("article, .news-list-item, .views-row")[:30]:
            a = item.select_one("h3 a, h2 a, .field-title a")
            if not a: continue
            title = a.get_text(strip=True)
            href = urljoin(base, a.get("href",""))
            date_el = item.select_one("time, .date, .field-date")
            date = date_el.get_text(strip=True) if date_el else ""
            summary_el = item.select_one("p, .field-body")
            summary = summary_el.get_text(strip=True)[:400] if summary_el else ""
            # No keyword filter — all cases accepted
            row = _make_row(SOURCE, title, href, date, summary, "Florida")
            if upsert_case(row): added += 1
            else: updated += 1

    log_sync_finish(sync_id, added, updated, "success")
    if progress_cb: progress_cb(f"FL AG: +{added} new")
    return added, updated


# ── Washington AG ─────────────────────────────────────────────────────────────
def fetch_wa_ag(progress_cb=None) -> tuple[int,int]:
    added = updated = 0
    SOURCE = "wa_ag"
    sync_id = log_sync_start(SOURCE)
    base = "https://www.atg.wa.gov"

    soup = _get(base + "/news/news-releases")
    if soup:
        for item in soup.select("article, .views-row, li.views-row")[:30]:
            a = item.select_one("h3 a, h2 a, .field-title a")
            if not a: continue
            title = a.get_text(strip=True)
            href = urljoin(base, a.get("href",""))
            date_el = item.select_one("time, .date")
            date = date_el.get_text(strip=True) if date_el else ""
            body_el = item.select_one("p, .field-body")
            summary = body_el.get_text(strip=True)[:400] if body_el else ""
            # No keyword filter — all cases accepted
            row = _make_row(SOURCE, title, href, date, summary, "Washington")
            if upsert_case(row): added += 1
            else: updated += 1

    log_sync_finish(sync_id, added, updated, "success")
    if progress_cb: progress_cb(f"WA AG: +{added} new")
    return added, updated


# ── Illinois AG ───────────────────────────────────────────────────────────────
def fetch_il_ag(progress_cb=None) -> tuple[int,int]:
    added = updated = 0
    SOURCE = "il_ag"
    sync_id = log_sync_start(SOURCE)
    base = "https://illinoisattorneygeneral.gov"

    soup = _get(base + "/news/")
    if soup:
        for item in soup.select("article, .news-item, li")[:30]:
            a = item.select_one("a[href*='/news/']")
            if not a: continue
            title = a.get_text(strip=True)
            href = urljoin(base, a.get("href",""))
            if not _matches_ai(title): continue
            row = _make_row(SOURCE, title, href, "", "", "Illinois")
            if upsert_case(row): added += 1
            else: updated += 1

    log_sync_finish(sync_id, added, updated, "success")
    if progress_cb: progress_cb(f"IL AG: +{added} new")
    return added, updated


# ── Master state sync ─────────────────────────────────────────────────────────
STATE_FETCHERS = {
    "New York": fetch_ny_ag,
    "California": fetch_ca_ag,
    "Texas": fetch_tx_ag,
    "Florida": fetch_fl_ag,
    "Washington": fetch_wa_ag,
    "Illinois": fetch_il_ag,
}

def run_state_sync(
    states: Optional[list[str]] = None,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> dict:
    """Sync all (or selected) state AG offices. Returns totals."""
    fetchers = {k: v for k, v in STATE_FETCHERS.items()
                if states is None or k in states}
    total_added = total_updated = 0
    errors = []

    for state, fn in fetchers.items():
        try:
            a, u = fn(progress_cb=progress_cb)
            total_added += a
            total_updated += u
        except Exception as e:
            errors.append(f"{state}: {e}")
        time.sleep(0.5)

    return {
        "added": total_added,
        "updated": total_updated,
        "status": "success" if not errors else "partial",
        "errors": errors,
    }
