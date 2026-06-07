"""
Citation verifier — checks case citations against CourtListener API.

After the documentor generates a report, this post-pass performs a quick
existence check on each court-filing source to flag citations that cannot
be verified. This is a key safeguard against AI hallucination of case names.

Why this matters
----------------
*Mata v. Avianca* (S.D.N.Y. 2023): attorneys were sanctioned $5,000 each
for filing AI-hallucinated citations. A pre-submission verification pass
catches these before they leave the app.

Verification logic
------------------
For each CaseFinding that has at least one source with source_type == "court_filing":
  - Search CourtListener /api/rest/v4/search/ for the case name (quoted exact phrase)
  - If count > 0: mark verified
  - If count == 0: mark unverified (case name not found in CourtListener)
  - If no court_filing source at all: mark skipped (can't verify non-court sources)

Notes
-----
- Requires COURTLISTENER_API_TOKEN in environment (loaded from Keychain at startup).
  Without a token, all cases are soft-skipped with a warning.
- CourtListener covers all federal courts + many state courts. A case being
  "unverified" means it wasn't found there — it may exist in a state database
  not indexed by CourtListener. Always review before citing.
- Rate limit: CourtListener free tier = 5,000 requests/day. This verifier
  makes 1 request per finding, so a 20-finding report uses 20 requests.
"""

from __future__ import annotations

import os
import time
from typing import Optional

import httpx

from models.case_report import CaseIntelReport

_CL_BASE = "https://www.courtlistener.com/api/rest/v4"
_TIMEOUT = 8.0   # seconds per HTTP request
_RETRY_PAUSE = 0.3  # seconds between consecutive requests (be a good citizen)


def _cl_token() -> Optional[str]:
    """Return the CourtListener API token from the environment, or None."""
    tok = os.environ.get("COURTLISTENER_API_TOKEN", "").strip()
    return tok if tok else None


def _search_case_exists(case_name: str, token: Optional[str]) -> bool:
    """
    Return True if CourtListener has at least one opinion matching *case_name*.

    Uses a quoted phrase search so 'Smith v. Jones' finds that exact case,
    not every document containing 'Smith' or 'Jones'.
    """
    headers: dict[str, str] = {}
    if token:
        headers["Authorization"] = f"Token {token}"

    # Strip trailing citation decorations like ", 123 F.3d 456 (2d Cir. 2001)"
    # so we search on the plain case name only.
    clean_name = case_name.split(",")[0].strip()

    try:
        resp = httpx.get(
            f"{_CL_BASE}/search/",
            params={
                "q": f'"{clean_name}"',
                "type": "o",          # opinions
                "stat_Precedential": "on",
            },
            headers=headers,
            timeout=_TIMEOUT,
            follow_redirects=True,
        )
        if resp.status_code == 200:
            data = resp.json()
            return int(data.get("count", 0)) > 0
        if resp.status_code == 429:
            # Rate limited — treat as "cannot verify" rather than crash
            return False
    except (httpx.TimeoutException, httpx.RequestError):
        pass
    return False


def verify_report_citations(report: CaseIntelReport) -> dict:
    """
    Verify citations in a CaseIntelReport against CourtListener.

    Parameters
    ----------
    report : CaseIntelReport
        The completed investigation report from the documentor.

    Returns
    -------
    dict with keys:
        verified   : list[str]  — case names confirmed in CourtListener
        unverified : list[str]  — case names NOT found (potential hallucinations)
        skipped    : int        — findings with no court_filing source (can't verify)
        total_checked : int
        note       : str        — human-readable summary
    """
    token = _cl_token()
    verified: list[str]   = []
    unverified: list[str] = []
    skipped = 0

    if not token:
        skipped = len(report.findings)
        return {
            "verified": verified,
            "unverified": unverified,
            "skipped": skipped,
            "total_checked": 0,
            "note": (
                "CourtListener API token not configured — citation verification skipped. "
                "Add COURTLISTENER_API_TOKEN to Keychain for automatic verification."
            ),
        }

    for finding in report.findings:
        # Only verify findings that have a court_filing source
        has_court_source = any(
            s.source_type == "court_filing" for s in finding.sources
        )
        if not has_court_source:
            skipped += 1
            continue

        found = _search_case_exists(finding.case_name, token)
        if found:
            verified.append(finding.case_name)
        else:
            unverified.append(finding.case_name)

        time.sleep(_RETRY_PAUSE)   # respect rate limits

    total_checked = len(verified) + len(unverified)

    if total_checked == 0:
        note = (
            "No court-filing sources found in this report — citation verification "
            "is only performed for findings with a court_filing source type."
        )
    elif unverified:
        note = (
            f"{len(verified)}/{total_checked} citations verified in CourtListener. "
            f"⚠️ {len(unverified)} citation(s) could not be found: "
            f"{', '.join(unverified[:5])}{'…' if len(unverified) > 5 else ''}. "
            "Review unverified citations before filing — they may be in state databases "
            "not indexed by CourtListener, or may be AI-hallucinated."
        )
    else:
        note = (
            f"All {total_checked} citation(s) verified in CourtListener. "
            "Safe to cite."
        )

    return {
        "verified": verified,
        "unverified": unverified,
        "skipped": skipped,
        "total_checked": total_checked,
        "note": note,
    }
