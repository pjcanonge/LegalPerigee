"""
All 50 State AG offices aggregator.
Uses a config-driven approach — each state defines its news URL and CSS selectors.
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
         "data broker", "biometric", "surveillance", "chatbot", "privacy",
         "fintech", "lending", "credit", "employment", "housing"]

# ── State AG configuration ────────────────────────────────────────────────────
# Format: (source_id, state_name, news_url, item_sel, title_sel)
STATE_CONFIGS = [
    # Already in state_courts_fetch.py:
    ("ny_ag",  "New York",       "https://ag.ny.gov/press-releases",                      "article,.views-row",  "h3 a,h2 a"),
    ("ca_ag",  "California",     "https://oag.ca.gov/news/press-releases",                 "article,.views-row",  "h3 a,h2 a"),
    ("tx_ag",  "Texas",          "https://www.texasattorneygeneral.gov/news/releases",      ".views-row,article",  "h3 a,h2 a"),
    ("fl_ag",  "Florida",        "https://www.myfloridalegal.com/news",                    "article,.news-list-item", "h3 a,h2 a"),
    ("wa_ag",  "Washington",     "https://www.atg.wa.gov/news/news-releases",              "article,.views-row",  "h3 a,h2 a"),
    ("il_ag",  "Illinois",       "https://illinoisattorneygeneral.gov/news/",              "li,article",          "a[href*='/news/']"),
    # New states:
    ("ma_ag",  "Massachusetts",  "https://www.mass.gov/orgs/office-of-the-attorney-general/news", "article,.ma__rich-text__li", "h3 a,h2 a,a.ma__rich-text__link"),
    ("co_ag",  "Colorado",       "https://coag.gov/press-releases/",                      "article,.entry",      "h2 a,h3 a"),
    ("ct_ag",  "Connecticut",    "https://portal.ct.gov/AG/Press-Releases",               "article,.list-item",  "h3 a,h2 a,a.list-item__title"),
    ("nj_ag",  "New Jersey",     "https://www.njoag.gov/news/",                           "article,.post",       "h2 a,h3 a"),
    ("pa_ag",  "Pennsylvania",   "https://www.attorneygeneral.gov/taking-action/press-releases/", "article,.press-release", "h2 a,h3 a"),
    ("oh_ag",  "Ohio",           "https://www.ohioattorneygeneral.gov/Media/News-Releases", "article,.item",      "h3 a,h2 a"),
    ("mi_ag",  "Michigan",       "https://www.michigan.gov/ag/news/press-releases",        "article,.item",       "h3 a,h2 a"),
    ("mn_ag",  "Minnesota",      "https://www.ag.state.mn.us/Office/Communications/PressReleases/", "li,tr", "a"),
    ("or_ag",  "Oregon",         "https://www.doj.state.or.us/media-home/news-media-releases/", "article,li", "h3 a,h2 a,a"),
    ("az_ag",  "Arizona",        "https://www.azag.gov/press-releases",                   "article,.views-row",  "h3 a,h2 a"),
    ("nc_ag",  "North Carolina", "https://ncdoj.gov/news/",                               "article,.post",       "h2 a,h3 a"),
    ("ga_ag",  "Georgia",        "https://law.georgia.gov/press-releases",                "article,.views-row",  "h3 a,h2 a"),
    ("nv_ag",  "Nevada",         "https://ag.nv.gov/News/Press_Releases/",                "article,li",          "h3 a,h2 a,a"),
    ("md_ag",  "Maryland",       "https://www.marylandattorneygeneral.gov/Pages/media/pressrel.aspx", "li,.press-item", "a"),
    ("va_ag",  "Virginia",       "https://www.oag.state.va.us/media-center/news-releases", "article,.item",      "h3 a,h2 a"),
    ("wi_ag",  "Wisconsin",      "https://www.doj.state.wi.us/news-releases",             "article,.item",       "h3 a,h2 a"),
    ("mo_ag",  "Missouri",       "https://ago.mo.gov/home/news-releases",                 "article,.views-row",  "h3 a,h2 a"),
    ("in_ag",  "Indiana",        "https://www.in.gov/attorneygeneral/about-the-office/news-and-media/", "article,.post", "h2 a,h3 a"),
    ("tn_ag",  "Tennessee",      "https://www.tn.gov/attorneygeneral/news.html",          "article,.item",       "h3 a,h2 a"),
    ("ky_ag",  "Kentucky",       "https://ag.ky.gov/Media-Center/Pages/Press-Releases.aspx", "li,.item",        "a"),
    ("sc_ag",  "South Carolina", "https://www.scag.gov/office-news-releases/",            "article,.post",       "h2 a,h3 a"),
    ("al_ag",  "Alabama",        "https://www.alabamaag.gov/news/",                       "article,.post",       "h2 a,h3 a"),
    ("ms_ag",  "Mississippi",    "https://www.ago.state.ms.us/index.php/in-the-news/",   "article,.post",       "h2 a,h3 a"),
    ("ar_ag",  "Arkansas",       "https://arkansasag.gov/media/news-releases/",           "article,.post",       "h2 a,h3 a"),
    ("la_ag",  "Louisiana",      "https://ag.louisiana.gov/news",                         "article,.post",       "h2 a,h3 a"),
    ("ok_ag",  "Oklahoma",       "https://www.oag.ok.gov/news",                           "article,.post",       "h2 a,h3 a"),
    ("ks_ag",  "Kansas",         "https://ag.ks.gov/media-center/news-releases",          "article,.item",       "h3 a,h2 a"),
    ("ne_ag",  "Nebraska",       "https://ago.nebraska.gov/press-releases",               "article,.item",       "h3 a,h2 a"),
    ("ia_ag",  "Iowa",           "https://www.iowaattorneygeneral.gov/news",              "article,.post",       "h2 a,h3 a"),
    ("sd_ag",  "South Dakota",   "https://atg.sd.gov/news/",                              "article,.post",       "h2 a,h3 a"),
    ("nd_ag",  "North Dakota",   "https://attorneygeneral.nd.gov/media/news-releases",    "article,.item",       "h3 a,h2 a"),
    ("mt_ag",  "Montana",        "https://dojmt.gov/news/",                               "article,.post",       "h2 a,h3 a"),
    ("wy_ag",  "Wyoming",        "https://ag.wyo.gov/media/news-releases",                "article,.item",       "h3 a,h2 a"),
    ("id_ag",  "Idaho",          "https://www.ag.idaho.gov/resources/press-releases/",   "article,.post",       "h2 a,h3 a"),
    ("nm_ag",  "New Mexico",     "https://www.nmag.gov/news/",                            "article,.post",       "h2 a,h3 a"),
    ("ut_ag",  "Utah",           "https://agutah.gov/news/",                              "article,.post",       "h2 a,h3 a"),
    ("hi_ag",  "Hawaii",         "https://ag.hawaii.gov/news/",                           "article,.post",       "h2 a,h3 a"),
    ("ak_ag",  "Alaska",         "https://www.law.alaska.gov/press/index.html",           "li,tr",               "a"),
    ("me_ag",  "Maine",          "https://www.maine.gov/ag/news/",                        "article,.post",       "h2 a,h3 a"),
    ("nh_ag",  "New Hampshire",  "https://www.doj.nh.gov/media/news/",                    "article,.post",       "h2 a,h3 a"),
    ("vt_ag",  "Vermont",        "https://ago.vermont.gov/news/",                         "article,.post",       "h2 a,h3 a"),
    ("ri_ag",  "Rhode Island",   "https://www.riag.ri.gov/media/news/",                   "article,.post",       "h2 a,h3 a"),
    ("de_ag",  "Delaware",       "https://ago.delaware.gov/news/",                        "article,.post",       "h2 a,h3 a"),
    ("wv_ag",  "West Virginia",  "https://ago.wv.gov/pressroom/Pages/default.aspx",       "li,.item",            "a"),
    ("dc_ag",  "DC",             "https://oag.dc.gov/release",                            "article,.views-row",  "h3 a,h2 a"),
]


def _fetch_state(source_id: str, state: str, url: str,
                 item_sel: str, title_sel: str,
                 progress_cb: Optional[Callable[[str], None]] = None) -> tuple[int, int]:
    added = updated = 0
    try:
        r = httpx.get(url, headers=HEADERS, timeout=20, follow_redirects=True)
        soup = BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        if progress_cb: progress_cb(f"  ⚠️ {state}: {e}")
        return 0, 0

    base = "/".join(url.split("/")[:3])
    for selector in item_sel.split(","):
        for item in soup.select(selector.strip())[:30]:
            for t_sel in title_sel.split(","):
                a = item.select_one(t_sel.strip())
                if a: break
            if not a: continue
            title = a.get_text(strip=True)
            if not title or len(title) < 5: continue
            href = urljoin(base, a.get("href", ""))
            date_el = item.select_one("time,.date,.field-date")
            date = date_el.get_text(strip=True) if date_el else ""
            summary_el = item.select_one("p,.field-body,.summary")
            summary = summary_el.get_text(strip=True)[:400] if summary_el else ""
            # No topic filter — all cases are indexed
            row = {
                "id": f"{source_id}_{re.sub(r'[^a-z0-9]','_',title.lower())[:60]}",
                "source": source_id,
                "case_name": title,
                "court": f"{state} Attorney General",
                "jurisdiction": state,
                "filing_date": date,
                "case_type": "State AG Enforcement",
                "status": "Enforcement",
                "summary": summary,
                "document_url": href,
                "raw_json": json.dumps({"title": title, "url": href, "state": state}),
            }
            if upsert_case(row): added += 1
            else: updated += 1
    return added, updated


def run_all_states_sync(
    states: Optional[list[str]] = None,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> dict:
    configs = [c for c in STATE_CONFIGS if states is None or c[1] in states]
    total_added = total_updated = 0
    errors = []
    sync_id = log_sync_start("all_states")

    for i, (src_id, state, url, item_sel, title_sel) in enumerate(configs, 1):
        if progress_cb:
            progress_cb(f"[{i}/{len(configs)}] {state} AG…")
        try:
            a, u = _fetch_state(src_id, state, url, item_sel, title_sel, progress_cb)
            total_added += a
            total_updated += u
        except Exception as e:
            errors.append(f"{state}: {e}")
        time.sleep(0.3)

    log_sync_finish(sync_id, total_added, total_updated,
                    "success" if not errors else "partial")
    if progress_cb:
        progress_cb(f"All States: +{total_added} new, {len(errors)} errors")
    return {"added": total_added, "updated": total_updated,
            "status": "success", "errors": errors,
            "states_covered": len(configs)}
