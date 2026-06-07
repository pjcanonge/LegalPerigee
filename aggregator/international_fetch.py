"""
International legal sources aggregator.

Covers:
  EUR-Lex    — EU AI Act, GDPR, Digital Services Act enforcement
  UK ICO     — UK data protection & AI enforcement (RSS feed)
  Canada OPC — Canadian privacy & AI enforcement
  OECD       — International AI policy tracker

All free, no API keys required.
"""

import json
import re
import time
import xml.etree.ElementTree as ET
from typing import Callable, Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from database.db import log_sync_finish, log_sync_start, upsert_case

HEADERS = {"User-Agent": "LegalPerigee/1.0 (legal research; contact admin@legalperigee.ai)"}


def _get(url: str) -> Optional[BeautifulSoup]:
    try:
        r = httpx.get(url, headers=HEADERS, timeout=20, follow_redirects=True)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception:
        return None


def _get_text(url: str) -> Optional[str]:
    try:
        r = httpx.get(url, headers=HEADERS, timeout=20, follow_redirects=True)
        r.raise_for_status()
        return r.text
    except Exception:
        return None


def _safe_id(src: str, title: str) -> str:
    return f"{src}_{re.sub(r'[^a-z0-9]','_',title.lower())[:65]}"


# ── EUR-Lex (EU Court of Justice + AI Act enforcement) ────────────────────────

def fetch_eurlex(progress_cb=None) -> tuple[int, int]:
    """Fetch EU Court of Justice judgments and AI-related legal acts from EUR-Lex."""
    added = updated = 0
    SOURCE = "eurlex"
    sync_id = log_sync_start(SOURCE)
    base = "https://eur-lex.europa.eu"

    search_urls = [
        f"{base}/search.html?scope=EURLEX&text=artificial+intelligence+enforcement&lang=en&type=quick&qid=1",
        f"{base}/search.html?scope=EURLEX&text=GDPR+enforcement+violation&lang=en&type=quick",
        f"{base}/search.html?scope=EURLEX&text=digital+services+act+enforcement&lang=en&type=quick",
        f"{base}/search.html?scope=EURLEX&text=consumer+fraud+judgment&lang=en&type=quick",
        f"{base}/search.html?scope=EURLEX&text=discrimination+civil+rights&lang=en&type=quick",
    ]

    if progress_cb: progress_cb("EUR-Lex: fetching EU enforcement actions…")
    for url in search_urls:
        soup = _get(url)
        if not soup: continue
        for item in soup.select(".SearchResult, .result-item, article.result")[:20]:
            a = item.select_one("a.title, h2 a, h3 a, .ResultTitle a")
            if not a: continue
            title = a.get_text(strip=True)
            href = urljoin(base, a.get("href",""))
            date_el = item.select_one("time, .date, .ResultDate")
            date = date_el.get_text(strip=True) if date_el else ""
            summary_el = item.select_one("p, .excerpt, .ResultDescription")
            summary = summary_el.get_text(strip=True)[:400] if summary_el else ""
            row = {
                "id": _safe_id(SOURCE, title),
                "source": SOURCE,
                "case_name": title,
                "court": "EU Court of Justice / EUR-Lex",
                "jurisdiction": "European Union",
                "filing_date": date,
                "case_type": "EU Legal Act / Judgment",
                "status": "Published",
                "summary": summary,
                "document_url": href,
                "raw_json": json.dumps({"title": title, "url": href, "date": date}),
            }
            if upsert_case(row): added += 1
            else: updated += 1
        time.sleep(0.5)

    log_sync_finish(sync_id, added, updated, "success")
    if progress_cb: progress_cb(f"EUR-Lex: +{added} new")
    return added, updated


# ── UK ICO (RSS feed) ─────────────────────────────────────────────────────────

def fetch_uk_ico(progress_cb=None) -> tuple[int, int]:
    """Fetch UK ICO enforcement actions via RSS and scraping."""
    added = updated = 0
    SOURCE = "uk_ico"
    sync_id = log_sync_start(SOURCE)
    base = "https://ico.org.uk"

    if progress_cb: progress_cb("UK ICO: fetching enforcement actions…")

    # Try RSS feed first
    rss_text = _get_text(f"{base}/feed/enforcement/")
    if rss_text:
        try:
            root = ET.fromstring(rss_text)
            ns = {"atom": "http://www.w3.org/2005/Atom"}
            for item in root.findall(".//item") or root.findall(".//atom:entry", ns):
                title_el = item.find("title") or item.find("atom:title", ns)
                link_el  = item.find("link")  or item.find("atom:link", ns)
                date_el  = item.find("pubDate") or item.find("atom:updated", ns)
                desc_el  = item.find("description") or item.find("atom:summary", ns)

                title   = title_el.text.strip() if title_el is not None and title_el.text else ""
                href    = (link_el.text or link_el.get("href","")).strip() if link_el is not None else ""
                date    = (date_el.text or "")[:20] if date_el is not None else ""
                summary = BeautifulSoup(desc_el.text or "", "html.parser").get_text()[:400] if desc_el is not None else ""

                if not title: continue
                row = {
                    "id": _safe_id(SOURCE, title),
                    "source": SOURCE,
                    "case_name": title,
                    "court": "UK Information Commissioner's Office",
                    "jurisdiction": "United Kingdom",
                    "filing_date": date[:10],
                    "case_type": "UK Data Protection Enforcement",
                    "status": "Enforcement",
                    "summary": summary,
                    "document_url": href,
                    "raw_json": json.dumps({"title": title, "url": href}),
                }
                if upsert_case(row): added += 1
                else: updated += 1
        except Exception as e:
            if progress_cb: progress_cb(f"  ⚠️ ICO RSS: {e}")

    # Also scrape enforcement pages
    for path in ["/action-weve-taken/enforcement/", "/action-weve-taken/audits-and-advisory-visits/"]:
        soup = _get(base + path)
        if not soup: continue
        for item in soup.select("article, .views-row, .enforcement-item")[:30]:
            a = item.select_one("h3 a, h2 a, .field-title a")
            if not a: continue
            title = a.get_text(strip=True)
            href  = urljoin(base, a.get("href",""))
            date_el = item.select_one("time, .date")
            date = date_el.get_text(strip=True) if date_el else ""
            summary_el = item.select_one("p, .field-body")
            summary = summary_el.get_text(strip=True)[:300] if summary_el else ""
            row = {
                "id": _safe_id(SOURCE, title),
                "source": SOURCE,
                "case_name": title,
                "court": "UK ICO",
                "jurisdiction": "United Kingdom",
                "filing_date": date,
                "case_type": "UK Enforcement",
                "status": "Enforcement",
                "summary": summary,
                "document_url": href,
                "raw_json": json.dumps({"title": title, "url": href}),
            }
            if upsert_case(row): added += 1
            else: updated += 1
        time.sleep(0.4)

    log_sync_finish(sync_id, added, updated, "success")
    if progress_cb: progress_cb(f"UK ICO: +{added} new")
    return added, updated


# ── Canada OPC ────────────────────────────────────────────────────────────────

def fetch_canada_opc(progress_cb=None) -> tuple[int, int]:
    """Fetch Canadian OPC privacy and AI enforcement actions."""
    added = updated = 0
    SOURCE = "canada_opc"
    sync_id = log_sync_start(SOURCE)
    base = "https://www.priv.gc.ca"

    if progress_cb: progress_cb("Canada OPC: fetching privacy enforcement…")

    for path in [
        "/en/opc-actions-and-decisions/investigations/",
        "/en/opc-actions-and-decisions/pipeda-compliance-summaries/",
        "/en/opc-actions-and-decisions/enforcement-reports/",
    ]:
        soup = _get(base + path)
        if not soup: continue
        for item in soup.select("article, li.views-row, .case-item, tr")[:30]:
            a = item.select_one("h3 a, h2 a, td a, a.title")
            if not a: continue
            title = a.get_text(strip=True)
            if len(title) < 5: continue
            href  = urljoin(base, a.get("href",""))
            date_el = item.select_one("time, .date, td:nth-child(2)")
            date = date_el.get_text(strip=True) if date_el else ""
            summary_el = item.select_one("p, .excerpt")
            summary = summary_el.get_text(strip=True)[:300] if summary_el else ""
            row = {
                "id": _safe_id(SOURCE, title),
                "source": SOURCE,
                "case_name": title,
                "court": "Office of the Privacy Commissioner of Canada",
                "jurisdiction": "Canada",
                "filing_date": date,
                "case_type": "Canadian Privacy Enforcement",
                "status": "Enforcement",
                "summary": summary,
                "document_url": href,
                "raw_json": json.dumps({"title": title, "url": href}),
            }
            if upsert_case(row): added += 1
            else: updated += 1
        time.sleep(0.4)

    log_sync_finish(sync_id, added, updated, "success")
    if progress_cb: progress_cb(f"Canada OPC: +{added} new")
    return added, updated


# ── Master international sync ─────────────────────────────────────────────────

def run_international_sync(progress_cb=None) -> dict:
    total_a = total_u = 0
    for fn in [fetch_eurlex, fetch_uk_ico, fetch_canada_opc]:
        try:
            a, u = fn(progress_cb=progress_cb)
            total_a += a; total_u += u
        except Exception as e:
            if progress_cb: progress_cb(f"  ⚠️ {fn.__name__}: {e}")
        time.sleep(0.5)
    return {"added": total_a, "updated": total_u, "status": "success"}
