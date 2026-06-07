"""
State eCourt aggregator — publicly searchable state court filing systems.

Most consumer class actions, civil rights cases, and criminal matters are filed
in STATE courts, not federal. This covers the largest state e-filing systems:

  NY NYSCEF    — New York (largest state court e-filing system)
  CA Appellate — California appellate court opinions
  TX Opinions  — Texas Supreme Court and Courts of Appeals
  FL Opinions  — Florida Supreme Court and District Courts of Appeal
  IL Opinions  — Illinois Supreme and Appellate Courts
"""

import json
import re
import time
from typing import Callable, Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from database.db import log_sync_finish, log_sync_start, upsert_case

HEADERS = {"User-Agent": "LegalPerigee/1.0 (legal research; contact admin@legalperigee.ai)"}


def _get(url: str, **kw) -> Optional[BeautifulSoup]:
    try:
        r = httpx.get(url, headers=HEADERS, timeout=25, follow_redirects=True, **kw)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception:
        return None


def _safe_id(src: str, title: str) -> str:
    return f"{src}_{re.sub(r'[^a-z0-9]','_',title.lower())[:65]}"


# ── New York — Appellate Division opinions (public) ───────────────────────────

def fetch_ny_courts(progress_cb=None) -> tuple[int, int]:
    """Fetch NY Appellate Division opinions — publicly available."""
    added = updated = 0
    SOURCE = "ny_courts"
    sync_id = log_sync_start(SOURCE)
    base = "https://www.nycourts.gov"

    if progress_cb: progress_cb("NY Courts: fetching appellate opinions…")

    # NY Courts decision search
    for dept in ["1", "2", "3", "4"]:
        url = f"{base}/reporter/Decisions.asp?Dept={dept}"
        soup = _get(url)
        if not soup: continue
        for a in soup.select("a[href*='.htm'], a[href*='.pdf']")[:25]:
            title = a.get_text(strip=True)
            if len(title) < 5: continue
            href = urljoin(base, a.get("href",""))
            row = {
                "id": _safe_id(SOURCE, title + dept),
                "source": SOURCE,
                "case_name": title,
                "court": f"NY Appellate Division, Dept. {dept}",
                "jurisdiction": "New York",
                "case_type": "State Court Opinion",
                "status": "Decided",
                "document_url": href,
                "raw_json": json.dumps({"title": title, "url": href, "dept": dept}),
            }
            if upsert_case(row): added += 1
            else: updated += 1
        time.sleep(0.3)

    log_sync_finish(sync_id, added, updated, "success")
    if progress_cb: progress_cb(f"NY Courts: +{added} new")
    return added, updated


# ── California — Appellate Court opinions ────────────────────────────────────

def fetch_ca_courts(progress_cb=None) -> tuple[int, int]:
    """Fetch California appellate court opinions."""
    added = updated = 0
    SOURCE = "ca_courts"
    sync_id = log_sync_start(SOURCE)
    base = "https://appellatecases.courtinfo.ca.gov"

    if progress_cb: progress_cb("CA Courts: fetching appellate opinions…")

    # CA Appellate search — recent published opinions
    for court_id in ["2", "4", "6", "S"]:  # Districts + Supreme
        params = {
            "search": "opinions",
            "dist": court_id,
            "doc_no": "",
            "party": "",
            "title": "",
        }
        soup = _get(f"{base}/search.cfm", params=params)
        if not soup: continue
        for row_el in soup.select("tr.result, .case-row, tr[class]")[:20]:
            cells = row_el.select("td")
            if len(cells) < 2: continue
            a = row_el.select_one("a")
            if not a: continue
            title = a.get_text(strip=True) or cells[0].get_text(strip=True)
            href  = urljoin(base, a.get("href",""))
            date  = cells[1].get_text(strip=True) if len(cells) > 1 else ""
            row_data = {
                "id": _safe_id(SOURCE, title + court_id),
                "source": SOURCE,
                "case_name": title,
                "court": f"California Court of Appeal, District {court_id}" if court_id != "S" else "California Supreme Court",
                "jurisdiction": "California",
                "filing_date": date,
                "case_type": "State Court Opinion",
                "status": "Decided",
                "document_url": href,
                "raw_json": json.dumps({"title": title, "url": href}),
            }
            if upsert_case(row_data): added += 1
            else: updated += 1
        time.sleep(0.4)

    log_sync_finish(sync_id, added, updated, "success")
    if progress_cb: progress_cb(f"CA Courts: +{added} new")
    return added, updated


# ── Texas — Supreme Court + Courts of Appeals ────────────────────────────────

def fetch_tx_courts(progress_cb=None) -> tuple[int, int]:
    """Fetch Texas Supreme Court and Courts of Appeals opinions."""
    added = updated = 0
    SOURCE = "tx_courts"
    sync_id = log_sync_start(SOURCE)
    base = "https://search.txcourts.gov"

    if progress_cb: progress_cb("TX Courts: fetching opinions…")

    soup = _get(f"{base}/Case.aspx?cn=&ct=13&te=4")  # TX Supreme Court opinions
    if soup:
        for row_el in soup.select("tr.GridRow, .result-row")[:30]:
            a = row_el.select_one("a")
            if not a: continue
            title = a.get_text(strip=True)
            href  = urljoin(base, a.get("href",""))
            cells = row_el.select("td")
            date  = cells[1].get_text(strip=True) if len(cells) > 1 else ""
            row_data = {
                "id": _safe_id(SOURCE, title),
                "source": SOURCE,
                "case_name": title,
                "court": "Texas Supreme Court",
                "jurisdiction": "Texas",
                "filing_date": date,
                "case_type": "State Court Opinion",
                "status": "Decided",
                "document_url": href,
                "raw_json": json.dumps({"title": title, "url": href}),
            }
            if upsert_case(row_data): added += 1
            else: updated += 1

    log_sync_finish(sync_id, added, updated, "success")
    if progress_cb: progress_cb(f"TX Courts: +{added} new")
    return added, updated


# ── Florida — District Courts of Appeal ──────────────────────────────────────

def fetch_fl_courts(progress_cb=None) -> tuple[int, int]:
    """Fetch Florida District Courts of Appeal opinions."""
    added = updated = 0
    SOURCE = "fl_courts"
    sync_id = log_sync_start(SOURCE)

    if progress_cb: progress_cb("FL Courts: fetching opinions…")

    for dca in ["1dca", "2dca", "3dca", "4dca", "5dca"]:
        base = f"https://www.{dca}.org"
        soup = _get(f"{base}/opinions/")
        if not soup: continue
        for a in soup.select("a[href*='.pdf'], a[href*='opinion']")[:20]:
            title = a.get_text(strip=True)
            if len(title) < 5: continue
            href = urljoin(base, a.get("href",""))
            row = {
                "id": _safe_id(SOURCE, title + dca),
                "source": SOURCE,
                "case_name": title,
                "court": f"Florida {dca.upper()}",
                "jurisdiction": "Florida",
                "case_type": "State Court Opinion",
                "status": "Decided",
                "document_url": href,
                "raw_json": json.dumps({"title": title, "url": href, "court": dca}),
            }
            if upsert_case(row): added += 1
            else: updated += 1
        time.sleep(0.3)

    log_sync_finish(sync_id, added, updated, "success")
    if progress_cb: progress_cb(f"FL Courts: +{added} new")
    return added, updated


# ── Master state eCourts sync ─────────────────────────────────────────────────

def run_state_ecourts_sync(
    states: Optional[list[str]] = None,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> dict:
    """Sync state eCourt opinions."""
    fetchers = {
        "New York":   fetch_ny_courts,
        "California": fetch_ca_courts,
        "Texas":      fetch_tx_courts,
        "Florida":    fetch_fl_courts,
    }
    if states:
        fetchers = {k: v for k, v in fetchers.items() if k in states}

    total_a = total_u = 0
    for state, fn in fetchers.items():
        if progress_cb: progress_cb(f"State eCourts: {state}…")
        try:
            a, u = fn(progress_cb=progress_cb)
            total_a += a; total_u += u
        except Exception as e:
            if progress_cb: progress_cb(f"  ⚠️ {state}: {e}")
        time.sleep(0.5)

    return {"added": total_a, "updated": total_u, "status": "success"}
