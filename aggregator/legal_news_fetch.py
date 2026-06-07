"""
Legal news aggregator: Reuters Legal (RSS), Above the Law, Justia, SSRN, Google Scholar.
Uses RSS feeds where available to avoid 403/429 scraper blocks.
"""

import json
import re
import time
from typing import Callable, Optional
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from database.db import log_sync_finish, log_sync_start, upsert_case
from utils.http_utils import safe_get_json, safe_get_soup


def _matches(text: str) -> bool:
    return True  # No topic filter — accept all cases


def _row(source: str, title: str, url: str, date: str, summary: str,
         court: str = "Legal News") -> dict:
    clean = re.sub(r"[^a-z0-9]", "_", title.lower())[:60]
    return {
        "id": f"{source}_{clean}",
        "source": source,
        "case_name": title,
        "court": court,
        "jurisdiction": "National",
        "filing_date": date,
        "case_type": "Legal News",
        "status": "Published",
        "summary": summary[:500],
        "document_url": url,
        "raw_json": json.dumps({"title": title, "url": url, "date": date}),
    }


# ── Reuters Legal (RSS — avoids 403) ─────────────────────────────────────────
def fetch_reuters_legal(progress_cb=None) -> tuple[int, int]:
    """Use Reuters RSS feeds to avoid scraper blocks."""
    added = updated = 0
    SOURCE = "reuters_legal"
    sync_id = log_sync_start(SOURCE)

    rss_feeds = [
        "https://feeds.reuters.com/reuters/legalNews",
        "https://feeds.reuters.com/reuters/businessNews",
    ]

    try:
        import feedparser
        for feed_url in rss_feeds:
            if progress_cb:
                progress_cb(f"Reuters Legal (RSS): {feed_url}")
            feed = feedparser.parse(feed_url)
            if feed.bozo and not feed.entries:
                if progress_cb:
                    progress_cb(f"  ⚠️ Reuters RSS: could not parse {feed_url}")
                continue
            for entry in feed.entries[:40]:
                title = entry.get("title", "").strip()
                href = entry.get("link", "")
                date = entry.get("published", "")
                summary = BeautifulSoup(
                    entry.get("summary", ""), "html.parser"
                ).get_text(strip=True)[:300]
                if not title or "legal" not in href.lower() and "law" not in title.lower():
                    continue
                r = _row(SOURCE, title, href, date, summary, "Reuters Legal")
                if upsert_case(r):
                    added += 1
                else:
                    updated += 1
            time.sleep(0.5)
    except ImportError:
        # feedparser not installed — fall back to direct scrape with safe_get
        if progress_cb:
            progress_cb("  ⚠️ feedparser not installed; trying direct Reuters scrape…")
        base = "https://www.reuters.com"
        for path in ["/legal/", "/legal/legalindustry/"]:
            soup = safe_get_soup(
                base + path, source_label="reuters_legal", progress_cb=progress_cb
            )
            if not soup:
                continue
            for item in soup.select("article, .article-card")[:30]:
                a = item.select_one("a[href*='/legal/']")
                if not a:
                    continue
                title = a.get_text(strip=True)
                href = urljoin(base, a.get("href", ""))
                date_el = item.select_one("time")
                date = date_el.get_text(strip=True) if date_el else ""
                r = _row(SOURCE, title, href, date, "", "Reuters Legal")
                if upsert_case(r):
                    added += 1
                else:
                    updated += 1
            time.sleep(1)

    log_sync_finish(sync_id, added, updated, "success")
    if progress_cb:
        progress_cb(f"Reuters Legal: +{added} new, {updated} updated")
    return added, updated


# ── Above the Law ─────────────────────────────────────────────────────────────
def fetch_above_the_law(progress_cb=None) -> tuple[int, int]:
    added = updated = 0
    SOURCE = "above_the_law"
    sync_id = log_sync_start(SOURCE)
    base = "https://abovethelaw.com"

    # ATL has RSS — use it
    try:
        import feedparser
        feed = feedparser.parse("https://abovethelaw.com/feed/")
        if progress_cb:
            progress_cb("Above the Law (RSS): fetching feed…")
        for entry in feed.entries[:40]:
            title = entry.get("title", "").strip()
            href = entry.get("link", "")
            date = entry.get("published", "")
            summary = BeautifulSoup(
                entry.get("summary", ""), "html.parser"
            ).get_text(strip=True)[:300]
            r = _row(SOURCE, title, href, date, summary, "Above the Law")
            if upsert_case(r):
                added += 1
            else:
                updated += 1
    except ImportError:
        for path in ["/", "/artificial-intelligence/", "/legal-tech/"]:
            if progress_cb:
                progress_cb(f"Above the Law: {path}")
            soup = safe_get_soup(
                base + path, source_label="above_the_law", progress_cb=progress_cb
            )
            if not soup:
                continue
            for item in soup.select("article, .post, .story")[:30]:
                a = item.select_one("h2 a, h3 a, .entry-title a")
                if not a:
                    continue
                title = a.get_text(strip=True)
                href = urljoin(base, a.get("href", ""))
                date_el = item.select_one("time, .entry-date")
                date = date_el.get_text(strip=True) if date_el else ""
                r = _row(SOURCE, title, href, date, "", "Above the Law")
                if upsert_case(r):
                    added += 1
                else:
                    updated += 1
            time.sleep(0.4)

    log_sync_finish(sync_id, added, updated, "success")
    if progress_cb:
        progress_cb(f"Above the Law: +{added} new, {updated} updated")
    return added, updated


# ── Justia Federal Cases ──────────────────────────────────────────────────────
_JUSTIA_DEFAULT_QUERIES = [
    "fraud consumer protection",
    "civil rights discrimination",
    "criminal sentencing",
    "housing discrimination",
    "employment discrimination",
    "environmental enforcement",
    "police misconduct",
    "voting rights",
]


def fetch_justia(queries=None, progress_cb=None) -> tuple[int, int]:
    """Justia free federal opinions via their search pages."""
    added = updated = 0
    SOURCE = "justia"
    sync_id = log_sync_start(SOURCE)
    base = "https://law.justia.com"
    terms = queries or _JUSTIA_DEFAULT_QUERIES

    for q in terms:
        url = f"{base}/federal/appellate-courts/?q={q.replace(' ', '+')}"
        if progress_cb:
            progress_cb(f"Justia: {q}")
        soup = safe_get_soup(
            url, source_label="justia", progress_cb=progress_cb
        )
        if not soup:
            continue
        for item in soup.select(".case-listing, article, .result")[:20]:
            a = item.select_one("h3 a, h2 a, a.case-name, .case-title a")
            if not a:
                continue
            title = a.get_text(strip=True)
            href = urljoin(base, a.get("href", ""))
            court_el = item.select_one(".court, .case-court, .meta")
            court = court_el.get_text(strip=True) if court_el else "Federal"
            date_el = item.select_one(".date, time, .case-date")
            date = date_el.get_text(strip=True) if date_el else ""
            row = {
                "id": f"justia_{re.sub(r'[^a-z0-9]', '_', title.lower())[:60]}",
                "source": SOURCE,
                "case_name": title,
                "court": court,
                "jurisdiction": "Federal",
                "filing_date": date,
                "case_type": "Opinion",
                "status": "Decided",
                "document_url": href,
                "raw_json": json.dumps({"title": title, "url": href, "court": court}),
            }
            if upsert_case(row):
                added += 1
            else:
                updated += 1
        time.sleep(0.4)

    log_sync_finish(sync_id, added, updated, "success")
    if progress_cb:
        progress_cb(f"Justia: +{added} new, {updated} updated")
    return added, updated


# ── SSRN legal papers ─────────────────────────────────────────────────────────
_SSRN_DEFAULT_QUERIES = [
    "consumer protection law",
    "civil rights litigation",
    "criminal justice reform",
    "housing discrimination law",
    "employment discrimination",
    "environmental justice law",
    "artificial intelligence law",
    "algorithmic accountability",
]


def fetch_ssrn(queries=None, progress_cb=None) -> tuple[int, int]:
    """SSRN academic legal papers."""
    added = updated = 0
    SOURCE = "ssrn"
    sync_id = log_sync_start(SOURCE)
    queries = queries or _SSRN_DEFAULT_QUERIES

    for q in queries:
        if progress_cb:
            progress_cb(f"SSRN: {q}")
        url = (
            f"https://ssrn.com/search?AnnouncementSearch=Search"
            f"&txtKeywords={q.replace(' ', '+')}&rdoSort=0"
        )
        soup = safe_get_soup(url, source_label="ssrn", progress_cb=progress_cb)
        if not soup:
            continue
        for item in soup.select(".title, .searchResult, article")[:15]:
            a = item.select_one("a[href*='/abstract/'], a.title")
            if not a:
                continue
            title = a.get_text(strip=True)
            href = a.get("href", "")
            if not href.startswith("http"):
                href = "https://papers.ssrn.com" + href
            author_el = item.select_one(".authors, .author")
            author = author_el.get_text(strip=True)[:100] if author_el else ""
            date_el = item.select_one(".date, .submitted")
            date = date_el.get_text(strip=True) if date_el else ""
            row = {
                "id": f"ssrn_{re.sub(r'[^a-z0-9]', '_', title.lower())[:60]}",
                "source": SOURCE,
                "case_name": title,
                "court": "SSRN",
                "jurisdiction": "Academic",
                "filing_date": date,
                "case_type": "Academic Paper",
                "status": "Published",
                "plaintiffs": author,
                "document_url": href,
                "raw_json": json.dumps({"title": title, "url": href, "author": author}),
            }
            if upsert_case(row):
                added += 1
            else:
                updated += 1
        time.sleep(1)  # SSRN rate limit — be conservative

    log_sync_finish(sync_id, added, updated, "success")
    if progress_cb:
        progress_cb(f"SSRN: +{added} new, {updated} updated")
    return added, updated


# ── Google Scholar case search ────────────────────────────────────────────────
def fetch_google_scholar(progress_cb=None) -> tuple[int, int]:
    """
    Google Scholar case law. Note: Google Scholar aggressively rate-limits
    automated requests. Results may be limited; errors are logged and skipped.
    """
    added = updated = 0
    SOURCE = "google_scholar"
    sync_id = log_sync_start(SOURCE)
    base = "https://scholar.google.com"

    queries = [
        "artificial intelligence fraud consumer",
        "algorithmic discrimination civil rights",
        "deepfake fraud criminal",
    ]
    for q in queries:
        if progress_cb:
            progress_cb(f"Google Scholar: {q}")
        url = f"{base}/scholar?q={q.replace(' ', '+')}&as_sdt=2006"
        soup = safe_get_soup(url, source_label="google_scholar", progress_cb=progress_cb)
        if not soup:
            # 403/429 logged by safe_get_soup — continue to next query
            time.sleep(5)
            continue
        for item in soup.select(".gs_r.gs_or.gs_scl, .gs_ri")[:15]:
            a = item.select_one("h3 a, .gs_rt a")
            if not a:
                continue
            title = a.get_text(strip=True)
            href = a.get("href", "")
            if not href.startswith("http"):
                href = base + href
            meta_el = item.select_one(".gs_a")
            meta = meta_el.get_text(strip=True) if meta_el else ""
            summary_el = item.select_one(".gs_rs")
            summary = summary_el.get_text(strip=True)[:300] if summary_el else ""
            row = {
                "id": f"scholar_{re.sub(r'[^a-z0-9]', '_', title.lower())[:60]}",
                "source": SOURCE,
                "case_name": title,
                "court": meta[:80],
                "jurisdiction": "Various",
                "case_type": "Case Law",
                "status": "Decided",
                "summary": summary,
                "document_url": href,
                "raw_json": json.dumps({"title": title, "url": href, "meta": meta}),
            }
            if upsert_case(row):
                added += 1
            else:
                updated += 1
        time.sleep(3)  # Conservative Google rate limit

    log_sync_finish(sync_id, added, updated, "success")
    if progress_cb:
        progress_cb(f"Google Scholar: +{added} new, {updated} updated")
    return added, updated


# ── Master legal news sync ────────────────────────────────────────────────────
def run_legal_news_sync(progress_cb=None) -> dict:
    total_added = total_updated = 0
    for fn in [fetch_reuters_legal, fetch_above_the_law,
               fetch_justia, fetch_ssrn, fetch_google_scholar]:
        try:
            a, u = fn(progress_cb=progress_cb)
            total_added += a
            total_updated += u
        except Exception as e:
            if progress_cb:
                progress_cb(f"  ⚠️ {fn.__name__}: {e}")
        time.sleep(0.5)
    return {"added": total_added, "updated": total_updated, "status": "success"}
