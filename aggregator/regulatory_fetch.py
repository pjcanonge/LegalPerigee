"""
Regulatory aggregator — scrapes FTC, SEC, and CFPB enforcement actions
involving AI, algorithmic systems, and consumer harm.
"""

import json
import re
import time
from typing import Callable, Optional

from bs4 import BeautifulSoup

from database.db import log_sync_finish, log_sync_start, upsert_case
from utils.http_utils import safe_get_soup


def _get(url: str, progress_cb=None) -> Optional[BeautifulSoup]:
    return safe_get_soup(url, source_label="regulatory", progress_cb=progress_cb)


# ── FTC ────────────────────────────────────────────────────────────────────────

FTC_ACTIONS_URL = "https://www.ftc.gov/legal-library/browse/cases-proceedings"
FTC_AI_SEARCH = "https://www.ftc.gov/legal-library/browse/cases-proceedings?title=AI&type=All"

def _ftc_row(item: dict) -> dict:
    return {
        "id": f"ftc_{item.get('id','')}",
        "source": "ftc",
        "case_name": item.get("title", ""),
        "court": "FTC",
        "jurisdiction": "Federal",
        "filing_date": item.get("date", ""),
        "case_type": item.get("type", "Enforcement Action"),
        "status": item.get("status", ""),
        "summary": item.get("summary", ""),
        "allegations": item.get("allegations", ""),
        "harm_types": json.dumps(item.get("harm_types", [])),
        "defendants": item.get("respondents", ""),
        "document_url": item.get("url", ""),
        "raw_json": json.dumps(item),
    }


def fetch_ftc(
    max_pages: int = 5,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> tuple[int, int]:
    """Scrape FTC enforcement actions related to AI/algorithms."""
    added = updated = 0
    SOURCE = "ftc"
    sync_id = log_sync_start(SOURCE)

    search_urls = [
        "https://www.ftc.gov/legal-library/browse/cases-proceedings?title=artificial+intelligence",
        "https://www.ftc.gov/legal-library/browse/cases-proceedings?title=algorithm",
        "https://www.ftc.gov/legal-library/browse/cases-proceedings?title=automated",
        "https://www.ftc.gov/legal-library/browse/cases-proceedings?title=data+broker",
        "https://www.ftc.gov/legal-library/browse/cases-proceedings?title=chatbot",
    ]

    for url in search_urls:
        if progress_cb:
            progress_cb(f"FTC: {url}")
        soup = _get(url, progress_cb=progress_cb)
        if not soup:
            continue

        for article in soup.select("article, .views-row, .case-item, li.views-row")[:20]:
            title_el = article.select_one("h3 a, h2 a, .field-title a, a.title")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            href = title_el.get("href", "")
            if href and not href.startswith("http"):
                href = "https://www.ftc.gov" + href

            date_el = article.select_one(".date-display-single, time, .field-date, .date")
            date_str = date_el.get_text(strip=True) if date_el else ""

            summary_el = article.select_one(".field-body, .summary, p")
            summary = summary_el.get_text(strip=True)[:500] if summary_el else ""

            case_id = re.sub(r"[^a-z0-9]", "_", title.lower())[:60]
            row = _ftc_row({
                "id": case_id,
                "title": title,
                "url": href,
                "date": date_str,
                "summary": summary,
                "type": "FTC Enforcement",
            })

            if upsert_case(row):
                added += 1
            else:
                updated += 1

        time.sleep(0.5)

    log_sync_finish(sync_id, added, updated, "success")
    if progress_cb:
        progress_cb(f"FTC: +{added} new, {updated} updated")
    return added, updated


# ── SEC ────────────────────────────────────────────────────────────────────────

def fetch_sec(
    progress_cb: Optional[Callable[[str], None]] = None,
) -> tuple[int, int]:
    """Fetch SEC enforcement actions involving AI/algorithmic trading/fraud."""
    added = updated = 0
    SOURCE = "sec"
    sync_id = log_sync_start(SOURCE)

    # SEC EDGAR full-text search API
    search_urls = [
        "https://efts.sec.gov/LATEST/search-index?q=%22artificial+intelligence%22&dateRange=custom&startdt=2020-01-01&forms=33-Act",
        "https://www.sec.gov/litigation/litreleases.htm",
    ]

    # SEC litigation releases page
    if progress_cb:
        progress_cb("SEC: fetching litigation releases…")

    soup = _get("https://www.sec.gov/divisions/enforce/enforcements-ai-related.htm", progress_cb=progress_cb)
    if not soup:
        soup = _get("https://www.sec.gov/litigation/litreleases.htm", progress_cb=progress_cb)

    if soup:
        for tr in soup.select("table tr")[1:51]:
            tds = tr.select("td")
            if len(tds) < 2:
                continue
            link_el = tds[1].select_one("a") if len(tds) > 1 else None
            if not link_el:
                continue

            title = link_el.get_text(strip=True)
            href = link_el.get("href", "")
            if href and not href.startswith("http"):
                href = "https://www.sec.gov" + href

            date_str = tds[0].get_text(strip=True) if tds else ""
            case_id = "sec_" + re.sub(r"[^a-z0-9]", "_", title.lower())[:60]

            row = {
                "id": case_id,
                "source": SOURCE,
                "case_name": title,
                "court": "SEC",
                "jurisdiction": "Federal",
                "filing_date": date_str,
                "case_type": "SEC Enforcement",
                "status": "Enforcement",
                "document_url": href,
                "raw_json": json.dumps({"title": title, "url": href, "date": date_str}),
            }
            if upsert_case(row):
                added += 1
            else:
                updated += 1

    log_sync_finish(sync_id, added, updated, "success")
    if progress_cb:
        progress_cb(f"SEC: +{added} new, {updated} updated")
    return added, updated


# ── CFPB ───────────────────────────────────────────────────────────────────────

def fetch_cfpb(
    progress_cb: Optional[Callable[[str], None]] = None,
) -> tuple[int, int]:
    """Fetch CFPB enforcement actions from their public action database."""
    added = updated = 0
    SOURCE = "cfpb"
    sync_id = log_sync_start(SOURCE)

    # CFPB has a public JSON API for enforcement actions
    api_url = "https://www.consumerfinance.gov/data-research/consumer-complaints/search/api/v1/"
    action_url = "https://www.consumerfinance.gov/enforcement/actions/"

    if progress_cb:
        progress_cb("CFPB: fetching enforcement actions…")

    soup = _get(action_url, progress_cb=progress_cb)
    if soup:
        for article in soup.select("article, .o-post-preview")[:50]:
            title_el = article.select_one("h3 a, h2 a, .o-post-preview__title a")
            if not title_el:
                continue

            title = title_el.get_text(strip=True)
            href = title_el.get("href", "")
            if href and not href.startswith("http"):
                href = "https://www.consumerfinance.gov" + href

            date_el = article.select_one("time, .date, .o-post-preview__date")
            date_str = date_el.get("datetime", date_el.get_text(strip=True)) if date_el else ""

            meta_el = article.select_one(".o-post-preview__description, p")
            summary = meta_el.get_text(strip=True)[:400] if meta_el else ""

            # Tag categories
            tags = [t.get_text(strip=True) for t in article.select(".a-tag, .tag")]
            harm_types = json.dumps(tags)

            case_id = "cfpb_" + re.sub(r"[^a-z0-9]", "_", title.lower())[:60]
            row = {
                "id": case_id,
                "source": SOURCE,
                "case_name": title,
                "court": "CFPB",
                "jurisdiction": "Federal",
                "filing_date": date_str,
                "case_type": "CFPB Enforcement",
                "status": "Enforcement",
                "summary": summary,
                "harm_types": harm_types,
                "document_url": href,
                "raw_json": json.dumps({"title": title, "url": href, "date": date_str}),
            }
            if upsert_case(row):
                added += 1
            else:
                updated += 1

    log_sync_finish(sync_id, added, updated, "success")
    if progress_cb:
        progress_cb(f"CFPB: +{added} new, {updated} updated")
    return added, updated


# ── Master sync ────────────────────────────────────────────────────────────────

def run_regulatory_sync(
    progress_cb: Optional[Callable[[str], None]] = None,
) -> dict:
    """Run FTC + SEC + CFPB sync. Returns totals."""
    total_added = total_updated = 0

    a, u = fetch_ftc(progress_cb=progress_cb)
    total_added += a
    total_updated += u
    time.sleep(1)

    a, u = fetch_sec(progress_cb=progress_cb)
    total_added += a
    total_updated += u
    time.sleep(1)

    a, u = fetch_cfpb(progress_cb=progress_cb)
    total_added += a
    total_updated += u

    return {"added": total_added, "updated": total_updated, "status": "success"}
