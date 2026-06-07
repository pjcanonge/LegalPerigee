"""
Investigation orchestrator.

General-purpose legal case investigator — covers ALL civil and criminal cases:
fraud, consumer harm, civil rights, discrimination, criminal, regulatory, and more.
No topic restrictions.

v1.3 changes
------------
- Court researcher and web researcher now run in PARALLEL via ThreadPoolExecutor,
  cutting investigation wall-clock time roughly in half.
- The _INTER_AGENT_PAUSE between agents 1 and 2 has been removed (was only needed
  to separate sequential calls; parallel execution doesn't need it).
- The single pause before the documentor is retained at 0.5 s to give both
  futures time to flush before synthesis begins.
- Citation verification post-pass added via utils.citation_verifier.
"""

import concurrent.futures
import sys
import time
from typing import Callable, Optional

import anthropic

from agents.court_researcher import run_court_researcher
from agents.documentor import run_documentor
from agents.web_researcher import run_web_researcher
from models.case_report import CaseIntelReport, SearchFilters

# Brief pause before documentor — allows both parallel futures to flush logs.
_PRE_DOCUMENTOR_PAUSE = 0.5


def _build_court_query(query: str, filters: Optional[SearchFilters]) -> str:
    """Build a precise CourtListener query from the base query + active filters."""
    parts = [query]
    if filters:
        if filters.crime_types:
            parts.append(" ".join(filters.crime_types))
        if filters.protected_classes:
            parts.append(" ".join(filters.protected_classes))
        if filters.area:
            parts.append(filters.area)
    return " ".join(parts)


def _build_web_query(query: str, filters: Optional[SearchFilters]) -> str:
    """Build a web search query enriched with filter terms."""
    parts = [query]
    if filters:
        if filters.crime_types:
            parts.append(" ".join(filters.crime_types))
        if filters.protected_classes:
            parts.append(" ".join(filters.protected_classes))
        if filters.area:
            parts.append(filters.area)
        if filters.court_label:
            parts.append(filters.court_label)
    return " ".join(parts)


def run_investigation(
    query: str,
    filters: Optional[SearchFilters] = None,
    verbose: bool = False,
    client: Optional[anthropic.Anthropic] = None,
    log_cb: Optional[Callable[[str], None]] = None,
) -> CaseIntelReport:
    """
    Run a full investigation.

    1. Court researcher + Web researcher — run IN PARALLEL (ThreadPoolExecutor)
    2. Documentor                        — synthesizes both into a CaseIntelReport
    3. Citation verifier                 — verifies court citations against CourtListener

    Args:
        log_cb: optional callback(msg) called for each progress message.
                Thread-safe; used by the Streamlit fragment poller in gui.py.
    """
    if client is None:
        api_key = __import__("os").environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key or not api_key.startswith("sk-"):
            raise ValueError(
                "Anthropic API key not configured. "
                "Enter your key in the app sidebar (⚖️ LegalPerigee → sidebar → 🔑 Anthropic API Key)."
            )
        client = anthropic.Anthropic(api_key=api_key)

    def log(msg: str) -> None:
        if log_cb is not None:
            log_cb(msg)
        elif verbose:
            print(f"[investigation] {msg}", file=sys.stderr, flush=True)

    court_query = _build_court_query(query, filters)
    web_query   = _build_web_query(query, filters)

    # ── 1 & 2. Court + Web research — run concurrently ────────────────────────
    log("⚡ Launching court researcher and web researcher in parallel…")

    court_findings: dict = {}
    web_findings: dict   = {}

    with concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="lp-agent") as pool:
        court_future = pool.submit(
            run_court_researcher,
            query=court_query,
            court_code=filters.court_code if filters else None,
            date_from=filters.date_from if filters else None,
            date_to=filters.date_to if filters else None,
            client=client,
        )
        web_future = pool.submit(run_web_researcher, query=web_query, client=client)

        # Collect results as futures complete — log in arrival order
        for future in concurrent.futures.as_completed(
            {court_future: "court", web_future: "web"}
        ):
            label = {court_future: "Court researcher", web_future: "Web researcher"}[future]
            try:
                result = future.result()
                if future is court_future:
                    court_findings = result
                    n = result.get("total_found", len(result.get("cases", [])))
                    log(f"✅ Court researcher: {n} case(s) found")
                else:
                    web_findings = result
                    n = result.get("total_found", len(result.get("findings", [])))
                    log(f"✅ Web researcher: {n} finding(s)")
            except Exception as e:
                log(f"⚠️ {label} error: {e}")
                if future is court_future:
                    court_findings = {"cases": [], "total_found": 0, "error": str(e)}
                else:
                    web_findings = {"findings": [], "total_found": 0, "error": str(e)}

    log(f"Pausing {_PRE_DOCUMENTOR_PAUSE}s before synthesis…")
    time.sleep(_PRE_DOCUMENTOR_PAUSE)

    # ── 3. Synthesis ──────────────────────────────────────────────────────────
    log("📝 Documentor: synthesizing findings…")
    report = run_documentor(
        query=query,
        court_findings=court_findings,
        web_findings=web_findings,
        filters=filters,
        client=client,
        log_cb=log_cb,   # forward live streaming tokens to the UI log
    )
    log(f"✅ Synthesis: {report.total_cases_found} cases, {report.high_severity_count} high severity")

    # ── 4. Citation verification ──────────────────────────────────────────────
    try:
        from utils.citation_verifier import verify_report_citations
        log("🔍 Verifying citations against CourtListener…")
        cv = verify_report_citations(report)
        report.citation_verification = cv
        v_count = len(cv.get("verified", []))
        u_count = len(cv.get("unverified", []))
        if cv.get("total_checked", 0) > 0:
            log(f"✅ Citations: {v_count} verified, {u_count} unverified")
        else:
            log(f"ℹ️ Citations: {cv.get('note', 'skipped')}")
    except Exception as e:
        log(f"⚠️ Citation verification skipped: {e}")

    return report
