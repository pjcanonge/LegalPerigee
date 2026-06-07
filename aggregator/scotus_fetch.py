"""
SCOTUS aggregator: Oyez API (structured JSON) + SCOTUSblog (RSS feed).
Oyez: api.oyez.org — free, no key needed.
SCOTUSblog: RSS feed used instead of scraping to avoid 403 blocks.
"""

import json
import re
import time
from typing import Callable, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from database.db import log_sync_finish, log_sync_start, upsert_case
from utils.http_utils import safe_get_json, safe_get_soup

OYEZ_BASE = "https://api.oyez.org"


def _oyez_row(case: dict) -> dict:
    term = case.get("term", "")
    docket = case.get("docket_number", "")
    decided = case.get("decided_date") or case.get("argument_date") or ""
    if isinstance(decided, int):
        decided = str(decided)

    facts = ""
    if isinstance(case.get("facts_of_the_case"), str):
        facts = case["facts_of_the_case"][:500]

    conclusion = ""
    if isinstance(case.get("conclusion"), str):
        conclusion = case["conclusion"][:500]

    href = case.get("href", "")
    frontend = f"https://www.oyez.org/cases/{term}/{docket}" if term and docket else href

    return {
        "id": f"oyez_{case.get('ID', '')}",
        "source": "oyez_scotus",
        "case_name": case.get("name", ""),
        "court": "U.S. Supreme Court",
        "jurisdiction": "Federal",
        "docket_number": docket,
        "filing_date": str(decided)[:10] if decided else "",
        "case_type": "SCOTUS Opinion",
        "status": "Decided" if case.get("decided_date") else "Argued",
        "summary": facts,
        "allegations": conclusion,
        "document_url": frontend,
        "raw_json": json.dumps({k: v for k, v in case.items()
                                if k not in ("oral_argument_audio", "written_opinion")}),
    }


def fetch_oyez(
    terms: Optional[list] = None,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> tuple[int, int]:
    """Fetch SCOTUS cases from Oyez for given terms (years)."""
    import datetime
    if terms is None:
        current = datetime.date.today().year
        terms = list(range(2018, current + 1))

    added = updated = 0
    sync_id = log_sync_start("oyez_scotus")

    for term in terms:
        if progress_cb:
            progress_cb(f"Oyez SCOTUS: term {term}")
        data = safe_get_json(
            f"{OYEZ_BASE}/cases?per_page=100&filter=term:{term}",
            source_label="oyez_scotus",
            progress_cb=progress_cb,
        )
        if not data:
            continue
        cases = data if isinstance(data, list) else data.get("results", [])

        for case in cases:
            row = _oyez_row(case)
            if upsert_case(row):
                added += 1
            else:
                updated += 1

        time.sleep(0.3)

    log_sync_finish(sync_id, added, updated, "success")
    if progress_cb:
        progress_cb(f"Oyez SCOTUS: +{added} new")
    return added, updated


def fetch_scotusblog(progress_cb=None) -> tuple[int, int]:
    """Fetch SCOTUSblog via RSS feed (avoids 403 scraping blocks)."""
    added = updated = 0
    SOURCE = "scotusblog"
    sync_id = log_sync_start(SOURCE)

    rss_feeds = [
        "https://www.scotusblog.com/feed/",
        "https://www.scotusblog.com/category/cases/feed/",
    ]

    try:
        import feedparser
        for feed_url in rss_feeds:
            if progress_cb:
                progress_cb(f"SCOTUSblog (RSS): {feed_url}")
            feed = feedparser.parse(feed_url)
            for entry in feed.entries[:50]:
                title = entry.get("title", "").strip()
                href = entry.get("link", "")
                date = entry.get("published", "")
                summary = BeautifulSoup(
                    entry.get("summary", ""), "html.parser"
                ).get_text(strip=True)[:400]
                row = {
                    "id": f"scotusblog_{re.sub(r'[^a-z0-9]', '_', title.lower())[:60]}",
                    "source": SOURCE,
                    "case_name": title,
                    "court": "U.S. Supreme Court",
                    "jurisdiction": "Federal",
                    "filing_date": date,
                    "case_type": "SCOTUS",
                    "status": "Active",
                    "summary": summary,
                    "document_url": href,
                    "raw_json": json.dumps({"title": title, "url": href}),
                }
                if upsert_case(row):
                    added += 1
                else:
                    updated += 1
            time.sleep(0.5)

    except ImportError:
        # feedparser not available — fall back to safe scraping
        base = "https://www.scotusblog.com"
        for path in ["/case-files/terms/2024/", "/category/cases/"]:
            if progress_cb:
                progress_cb(f"SCOTUSblog: {path}")
            soup = safe_get_soup(
                base + path, source_label="scotusblog", progress_cb=progress_cb
            )
            if not soup:
                continue
            for item in soup.select("article, .case-item, .entry")[:30]:
                a = item.select_one("h2 a, h3 a, a.case-name")
                if not a:
                    continue
                title = a.get_text(strip=True)
                href = urljoin(base, a.get("href", ""))
                date_el = item.select_one("time, .date, .entry-date")
                date = date_el.get_text(strip=True) if date_el else ""
                summary_el = item.select_one("p, .excerpt")
                summary = summary_el.get_text(strip=True)[:400] if summary_el else ""
                row = {
                    "id": f"scotusblog_{re.sub(r'[^a-z0-9]', '_', title.lower())[:60]}",
                    "source": SOURCE,
                    "case_name": title,
                    "court": "U.S. Supreme Court",
                    "jurisdiction": "Federal",
                    "filing_date": date,
                    "case_type": "SCOTUS",
                    "status": "Active",
                    "summary": summary,
                    "document_url": href,
                    "raw_json": json.dumps({"title": title, "url": href}),
                }
                if upsert_case(row):
                    added += 1
                else:
                    updated += 1
            time.sleep(0.5)

    log_sync_finish(sync_id, added, updated, "success")
    if progress_cb:
        progress_cb(f"SCOTUSblog: +{added} new")
    return added, updated


def run_scotus_sync(progress_cb=None) -> dict:
    a1, u1 = fetch_oyez(progress_cb=progress_cb)
    a2, u2 = fetch_scotusblog(progress_cb=progress_cb)
    return {"added": a1 + a2, "updated": u1 + u2, "status": "success"}
