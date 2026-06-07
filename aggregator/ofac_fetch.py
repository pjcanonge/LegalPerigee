"""
OFAC (Office of Foreign Assets Control) sanctions aggregator.
Source: U.S. Treasury — free, no API key required.

Downloads the Consolidated Sanctions List (CSV) and indexes sanctioned
entities so investigators can quickly check if defendants appear on
Treasury's watchlist.
"""

import csv
import io
import json
import time
from typing import Callable, Optional

import httpx

from database.db import log_sync_finish, log_sync_start, upsert_case

SOURCE = "ofac_sanctions"
HEADERS = {"User-Agent": "LegalPerigee/1.0 (legal research; contact admin@legalperigee.ai)"}

# Consolidated Sanctions List — includes SDN, non-SDN, and other lists
CONSOLIDATED_CSV = "https://www.treasury.gov/ofac/downloads/consolidated/cons_prim.csv"
SDN_CSV          = "https://www.treasury.gov/ofac/downloads/sdn.csv"

ENTITY_TYPES = {
    "Individual": "Sanctioned Individual",
    "Entity":     "Sanctioned Entity",
    "Vessel":     "Sanctioned Vessel",
    "Aircraft":   "Sanctioned Aircraft",
}


def _sdn_row(record: dict) -> dict:
    ent_type   = ENTITY_TYPES.get(record.get("SDN_Type",""), "Sanctioned Party")
    name       = record.get("SDN_Name", "").title()
    nationality= record.get("Nationality_Country", "")
    dob        = record.get("DOB", "")
    remarks    = record.get("Remarks", "")[:300]
    programs   = record.get("PROGRAMS", "")

    return {
        "id": f"ofac_{record.get('ent_num','').strip()}",
        "source": SOURCE,
        "case_name": f"[SANCTIONED] {name}",
        "court": "U.S. Treasury / OFAC",
        "jurisdiction": nationality or "International",
        "filing_date": "",
        "case_type": ent_type,
        "status": f"Active — Programs: {programs}",
        "summary": remarks or f"Sanctioned by OFAC. Programs: {programs}",
        "defendants": name,
        "allegations": programs,
        "document_url": "https://sanctionssearch.ofac.treas.gov/",
        "raw_json": json.dumps({
            "name": name,
            "type": record.get("SDN_Type"),
            "programs": programs,
            "nationality": nationality,
            "dob": dob,
            "title": record.get("Title",""),
        }),
    }


def run_ofac_sync(
    progress_cb: Optional[Callable[[str], None]] = None,
) -> dict:
    """Download and index the OFAC SDN list."""
    sync_id = log_sync_start(SOURCE)
    total_a = total_u = 0

    if progress_cb: progress_cb("OFAC: downloading SDN list from Treasury…")

    try:
        r = httpx.get(SDN_CSV, headers=HEADERS, timeout=60, follow_redirects=True)
        r.raise_for_status()

        reader = csv.DictReader(
            io.StringIO(r.text),
            fieldnames=[
                "ent_num", "SDN_Name", "SDN_Type", "PROGRAMS", "Title",
                "Call_Sign", "Vess_type", "Tonnage", "GRT", "Vess_flag",
                "Vess_owner", "Remarks",
            ],
        )

        count = 0
        for record in reader:
            if not record.get("SDN_Name","").strip():
                continue
            row = _sdn_row(record)
            if upsert_case(row): total_a += 1
            else: total_u += 1
            count += 1
            if count % 1000 == 0 and progress_cb:
                progress_cb(f"OFAC: processed {count:,} records…")

        if progress_cb:
            progress_cb(f"OFAC SDN: +{total_a} new, {total_u} updated ({count:,} total records)")

    except Exception as e:
        if progress_cb: progress_cb(f"  ⚠️ OFAC error: {e}")
        log_sync_finish(sync_id, total_a, total_u, "error", str(e))
        return {"added": total_a, "updated": total_u, "status": "error", "error": str(e)}

    log_sync_finish(sync_id, total_a, total_u, "success")
    return {"added": total_a, "updated": total_u, "status": "success"}
