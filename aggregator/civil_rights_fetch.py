"""
Civil rights agency aggregator: EEOC, HUD, DOJ Civil Rights, FCC, OCC, FDIC.
These agencies handle AI discrimination in employment, housing, banking, and telecom.
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
AI_KW = ["artificial intelligence", " ai ", "algorithm", "automated", "machine learning",
         "facial recognition", "predictive", "discriminat", "bias", "deepfake",
         "data broker", "biometric", "credit score", "hiring", "lending"]

def _get(url: str) -> Optional[BeautifulSoup]:
    try:
        r = httpx.get(url, headers=HEADERS, timeout=20, follow_redirects=True)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception:
        return None

def _matches(text: str) -> bool:
    return True  # No topic filter — accept all cases

def _safe_id(src: str, title: str) -> str:
    return f"{src}_" + re.sub(r"[^a-z0-9]", "_", title.lower())[:70]

def _row(source: str, title: str, url: str, date: str, summary: str,
         court: str, case_type: str = "Civil Rights Enforcement") -> dict:
    return {
        "id": _safe_id(source, title),
        "source": source,
        "case_name": title,
        "court": court,
        "jurisdiction": "Federal",
        "filing_date": date,
        "case_type": case_type,
        "status": "Enforcement",
        "summary": summary[:500],
        "document_url": url,
        "raw_json": json.dumps({"title": title, "url": url, "date": date}),
    }


# ── EEOC ──────────────────────────────────────────────────────────────────────
def fetch_eeoc(progress_cb=None) -> tuple[int, int]:
    added = updated = 0
    SOURCE = "eeoc"
    sync_id = log_sync_start(SOURCE)
    base = "https://www.eeoc.gov"

    for path in ["/newsroom/press-releases", "/newsroom/litigation"]:
        if progress_cb: progress_cb(f"EEOC: {base+path}")
        soup = _get(base + path)
        if not soup: continue
        for item in soup.select("article, .views-row, .news-item")[:40]:
            a = item.select_one("h3 a, h2 a, a.teaser-title, .field-title a")
            if not a: continue
            title = a.get_text(strip=True)
            href = urljoin(base, a.get("href", ""))
            date = (item.select_one("time, .date") or type('', (), {'get_text': lambda s, **k: ''})()).get_text(strip=True)
            summary_el = item.select_one("p, .field-body")
            summary = summary_el.get_text(strip=True)[:400] if summary_el else ""
            if not _matches(title + " " + summary): continue
            r = _row(SOURCE, title, href, date, summary, "EEOC", "Employment Discrimination")
            if upsert_case(r): added += 1
            else: updated += 1
        time.sleep(0.4)

    log_sync_finish(sync_id, added, updated, "success")
    if progress_cb: progress_cb(f"EEOC: +{added} new")
    return added, updated


# ── HUD ───────────────────────────────────────────────────────────────────────
def fetch_hud(progress_cb=None) -> tuple[int, int]:
    added = updated = 0
    SOURCE = "hud"
    sync_id = log_sync_start(SOURCE)
    base = "https://www.hud.gov"

    for path in ["/press/press_releases_media_advisories",
                 "/program_offices/fair_housing_equal_opp/enforcement"]:
        if progress_cb: progress_cb(f"HUD: {base+path}")
        soup = _get(base + path)
        if not soup: continue
        for item in soup.select("article, .views-row, li.item")[:40]:
            a = item.select_one("h3 a, h2 a, a.title")
            if not a: continue
            title = a.get_text(strip=True)
            href = urljoin(base, a.get("href", ""))
            date = (item.select_one("time, .date") or type('', (), {'get_text': lambda s, **k: ''})()).get_text(strip=True)
            summary_el = item.select_one("p, .field-body")
            summary = summary_el.get_text(strip=True)[:400] if summary_el else ""
            if not _matches(title + " " + summary): continue
            r = _row(SOURCE, title, href, date, summary, "HUD", "Housing Discrimination")
            if upsert_case(r): added += 1
            else: updated += 1
        time.sleep(0.4)

    log_sync_finish(sync_id, added, updated, "success")
    if progress_cb: progress_cb(f"HUD: +{added} new")
    return added, updated


# ── DOJ Civil Rights ──────────────────────────────────────────────────────────
def fetch_doj_civil_rights(progress_cb=None) -> tuple[int, int]:
    added = updated = 0
    SOURCE = "doj_civil_rights"
    sync_id = log_sync_start(SOURCE)
    base = "https://www.justice.gov"

    for path in ["/crt/press-releases", "/news", "/opa/blog"]:
        if progress_cb: progress_cb(f"DOJ CRT: {base+path}")
        soup = _get(base + path)
        if not soup: continue
        for item in soup.select("article, .views-row, .news-item")[:40]:
            a = item.select_one("h3 a, h2 a, .field-title a, a.news-title")
            if not a: continue
            title = a.get_text(strip=True)
            href = urljoin(base, a.get("href", ""))
            date = (item.select_one("time, .date, .field-date") or type('', (), {'get_text': lambda s, **k: ''})()).get_text(strip=True)
            summary_el = item.select_one("p, .field-body")
            summary = summary_el.get_text(strip=True)[:400] if summary_el else ""
            if not _matches(title + " " + summary): continue
            r = _row(SOURCE, title, href, date, summary, "DOJ Civil Rights", "Civil Rights Enforcement")
            if upsert_case(r): added += 1
            else: updated += 1
        time.sleep(0.4)

    log_sync_finish(sync_id, added, updated, "success")
    if progress_cb: progress_cb(f"DOJ Civil Rights: +{added} new")
    return added, updated


# ── FCC ───────────────────────────────────────────────────────────────────────
def fetch_fcc(progress_cb=None) -> tuple[int, int]:
    added = updated = 0
    SOURCE = "fcc"
    sync_id = log_sync_start(SOURCE)
    base = "https://www.fcc.gov"

    if progress_cb: progress_cb("FCC: news releases")
    soup = _get(base + "/news-events/press-releases")
    if soup:
        for item in soup.select("article, .views-row")[:40]:
            a = item.select_one("h3 a, h2 a, .field-title a")
            if not a: continue
            title = a.get_text(strip=True)
            href = urljoin(base, a.get("href", ""))
            date = (item.select_one("time, .date") or type('', (), {'get_text': lambda s, **k: ''})()).get_text(strip=True)
            if not _matches(title): continue
            r = _row(SOURCE, title, href, date, "", "FCC", "Telecom Enforcement")
            if upsert_case(r): added += 1
            else: updated += 1

    log_sync_finish(sync_id, added, updated, "success")
    if progress_cb: progress_cb(f"FCC: +{added} new")
    return added, updated


# ── OCC (banking AI) ──────────────────────────────────────────────────────────
def fetch_occ(progress_cb=None) -> tuple[int, int]:
    added = updated = 0
    SOURCE = "occ"
    sync_id = log_sync_start(SOURCE)
    base = "https://www.occ.gov"

    if progress_cb: progress_cb("OCC: enforcement actions")
    soup = _get(base + "/news-issuances/news-releases/index-news-releases.html")
    if soup:
        for a in soup.select("table a, .news-list a")[:60]:
            title = a.get_text(strip=True)
            href = urljoin(base, a.get("href", ""))
            if not title or not _matches(title): continue
            r = _row(SOURCE, title, href, "", "", "OCC", "Banking Enforcement")
            if upsert_case(r): added += 1
            else: updated += 1

    log_sync_finish(sync_id, added, updated, "success")
    if progress_cb: progress_cb(f"OCC: +{added} new")
    return added, updated


# ── Master civil rights sync ──────────────────────────────────────────────────
def run_civil_rights_sync(progress_cb=None) -> dict:
    total_added = total_updated = 0
    for fn in [fetch_eeoc, fetch_hud, fetch_doj_civil_rights, fetch_fcc, fetch_occ]:
        try:
            a, u = fn(progress_cb=progress_cb)
            total_added += a; total_updated += u
        except Exception as e:
            if progress_cb: progress_cb(f"  ⚠️ {fn.__name__}: {e}")
        time.sleep(0.5)
    return {"added": total_added, "updated": total_updated, "status": "success"}
