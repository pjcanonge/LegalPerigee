"""
GovInfo aggregator — U.S. federal bills via GPO's BILLSTATUS bulk data.

Replaces the dead GovTrack API (GovTrack shut down its API in 2017). GovInfo
BILLSTATUS bulk data is published by the Government Publishing Office, refreshed
every ~4 hours for the current Congress, and requires NO API key.

Docs: https://github.com/usgpo/bill-status  ·  https://www.govinfo.gov/bulkdata/BILLSTATUS

Design: the network calls (`_list_billstatus`, `_fetch_xml`) are thin; the
parsing/mapping/filtering are pure functions (`parse_billstatus_xml`,
`bill_matches`, `bill_to_row`) so they can be unit-tested without a network.
"""

import json
import re
import time
import xml.etree.ElementTree as ET
from typing import Callable, Optional

import httpx

from database.db import log_sync_finish, log_sync_start, upsert_case

SOURCE = "govinfo"
BASE = "https://www.govinfo.gov/bulkdata"
HEADERS = {
    "User-Agent": "LegalPerigee/1.5 (legal research; contact admin@legalperigee.ai)",
    "Accept": "application/json",
}

# Bill types worth tracking (House/Senate bills + joint resolutions).
BILL_TYPES = ["hr", "s", "hjres", "sjres"]

# Civil-rights / consumer-protection keyword filter applied locally to each
# bill's title, summary, policy area, and subjects.
KEYWORDS = [
    "civil rights", "discrimination", "voting", "police", "housing",
    "consumer protection", "fraud", "privacy", "surveillance", "immigration",
    "healthcare", "environmental justice", "disability", "labor", "education",
    "artificial intelligence", "algorithm", "facial recognition", "predatory",
    "data privacy", "reproductive", "lgbt", "hate crime", "criminal justice",
]

_HTML_TAG = re.compile(r"<[^>]+>")


def _strip_html(text: str) -> str:
    return _HTML_TAG.sub(" ", text or "").replace("&nbsp;", " ").strip()


def _txt(el: Optional[ET.Element]) -> str:
    return (el.text or "").strip() if el is not None and el.text else ""


def _first(parent: ET.Element, *paths: str) -> str:
    """Return the text of the first matching element across candidate paths.

    Tries direct children first (exact path), then any descendant (`.//path`),
    so it tolerates both the current and older BILLSTATUS schema variants.
    """
    for path in paths:
        el = parent.find(path)
        if el is None:
            el = parent.find(f".//{path}")
        if el is not None and (el.text or "").strip():
            return el.text.strip()
    return ""


def parse_billstatus_xml(xml_text) -> Optional[dict]:
    """Parse a BILLSTATUS XML document into a normalized dict (pure function)."""
    if isinstance(xml_text, bytes):
        xml_text = xml_text.decode("utf-8", "replace")
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return None

    bill = root.find(".//bill")
    if bill is None:
        bill = root

    number = _first(bill, "number", "billNumber")
    btype = _first(bill, "type", "billType")
    congress = _first(bill, "congress")
    if not (number and btype):
        return None

    sponsor = _first(bill, "sponsors/item/fullName", "sponsors/item/lastName")

    # Summaries: prefer the most recent (last) summary's text.
    summary_text = ""
    summaries = bill.findall(".//summaries//text")
    if summaries:
        summary_text = _strip_html(summaries[-1].text or "")

    subjects = [
        (i.text or "").strip()
        for i in bill.findall(".//subjects//name")
        if (i.text or "").strip()
    ]

    policy_area = _first(bill, "policyArea/name")

    return {
        "number": number,
        "type": btype.upper(),
        "congress": congress,
        "title": _first(bill, "title"),
        "introduced_date": _first(bill, "introducedDate"),
        "sponsor": sponsor,
        "latest_action_text": _first(bill, "latestAction/text"),
        "latest_action_date": _first(bill, "latestAction/actionDate"),
        "policy_area": policy_area,
        "subjects": subjects,
        "summary": summary_text,
    }


def bill_matches(parsed: dict, keywords=KEYWORDS) -> bool:
    """True if any keyword appears in the bill's text (pure function)."""
    haystack = " ".join([
        parsed.get("title", ""),
        parsed.get("summary", ""),
        parsed.get("policy_area", ""),
        " ".join(parsed.get("subjects", [])),
    ]).lower()
    return any(k in haystack for k in keywords)


def bill_to_row(parsed: dict) -> dict:
    """Map a parsed bill into a cases-table row (pure function)."""
    congress = parsed.get("congress", "")
    btype = parsed.get("type", "")
    number = parsed.get("number", "")
    chamber = "Senate" if btype.lower().startswith("s") else "House"
    display = f"{btype} {number}"
    summary = parsed.get("summary") or parsed.get("title", "")

    return {
        "id": f"govinfo_{congress}_{btype.lower()}{number}",
        "source": SOURCE,
        "case_name": f"{display} — {parsed.get('title','')}"[:300],
        "court": f"U.S. Congress — {chamber}",
        "jurisdiction": "Federal",
        "docket_number": display,
        "filing_date": parsed.get("introduced_date", ""),
        "case_type": "Federal Legislation",
        "status": (parsed.get("latest_action_text") or "Introduced")[:200],
        "summary": summary[:1000],
        "allegations": ", ".join(parsed.get("subjects", [])[:10]),
        "plaintiffs": parsed.get("sponsor", ""),
        "document_url": f"https://www.congress.gov/bill/{congress}th-congress/"
                        f"{'senate' if chamber=='Senate' else 'house'}-bill/{number}",
        "raw_json": json.dumps({
            "congress": congress, "type": btype, "number": number,
            "policy_area": parsed.get("policy_area", ""),
            "latest_action_date": parsed.get("latest_action_date", ""),
        }),
    }


def _billnum(filename: str) -> int:
    """Extract the numeric bill number from a BILLSTATUS filename for sorting.

    'BILLSTATUS-119hr1234.xml' -> 1234. Higher numbers were introduced later,
    so sorting desc surfaces the most recent bills without relying on the
    listing's (alphabetical) order or an undocumented timestamp format.
    """
    m = re.search(r"[a-z]+(\d+)\.xml$", filename or "", re.I)
    return int(m.group(1)) if m else 0


def _list_billstatus(congress: int, bill_type: str, timeout: int = 25) -> list[dict]:
    """List BILLSTATUS files for a congress + bill type. Returns [{url, name}]."""
    url = f"{BASE}/json/BILLSTATUS/{congress}/{bill_type}"
    r = httpx.get(url, headers=HEADERS, timeout=timeout)
    r.raise_for_status()
    out = []
    for item in r.json().get("files", []):
        name = item.get("justFileName") or item.get("name", "")
        if not name.lower().endswith(".xml"):
            continue
        link = item.get("link") or f"{BASE}/BILLSTATUS/{congress}/{bill_type}/{name}"
        out.append({"url": link, "name": name})
    return out


def _fetch_xml(url: str, timeout: int = 25) -> str:
    r = httpx.get(url, headers={"User-Agent": HEADERS["User-Agent"]}, timeout=timeout)
    r.raise_for_status()
    return r.text


def fetch_govinfo_bills(
    congress: int = 119,
    bill_types: Optional[list[str]] = None,
    max_bills: int = 120,
    keywords=KEYWORDS,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> tuple[int, int]:
    """Fetch recent federal bills from GovInfo, keyword-filter, and upsert."""
    bill_types = bill_types or BILL_TYPES
    per_type = max(1, max_bills // len(bill_types))
    added = updated = 0

    for bt in bill_types:
        try:
            files = _list_billstatus(congress, bt)
        except Exception as e:  # noqa: BLE001
            if progress_cb:
                progress_cb(f"  ⚠️ GovInfo list {bt}: {e}")
            continue

        # Most recent bills first (highest number), capped per type.
        files.sort(key=lambda f: _billnum(f["name"]), reverse=True)
        for f in files[:per_type]:
            try:
                parsed = parse_billstatus_xml(_fetch_xml(f["url"]))
            except Exception as e:  # noqa: BLE001
                if progress_cb:
                    progress_cb(f"  ⚠️ GovInfo {f['name']}: {e}")
                continue
            if not parsed or not bill_matches(parsed, keywords):
                continue
            if upsert_case(bill_to_row(parsed)):
                added += 1
            else:
                updated += 1
            time.sleep(0.1)

        if progress_cb:
            progress_cb(f"GovInfo {bt.upper()}: scanned {min(len(files), per_type)} bills")

    return added, updated


def run_govinfo_sync(
    congress: int = 119,
    progress_cb: Optional[Callable[[str], None]] = None,
) -> dict:
    sync_id = log_sync_start(SOURCE)
    try:
        a, u = fetch_govinfo_bills(congress=congress, progress_cb=progress_cb)
        log_sync_finish(sync_id, a, u, "success")
        if progress_cb:
            progress_cb(f"GovInfo: +{a} new, {u} updated")
        return {"added": a, "updated": u, "status": "success"}
    except Exception as e:  # noqa: BLE001
        log_sync_finish(sync_id, 0, 0, "error", str(e))
        return {"added": 0, "updated": 0, "status": "error", "error": str(e)}
