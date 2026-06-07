"""
Investigation orchestrator.

General-purpose legal case investigator — covers ALL civil and criminal cases:
fraud, consumer harm, civil rights, discrimination, criminal, regulatory, and more.
No topic restrictions. Calls researchers directly in sequence.
"""

import sys
import time
from typing import Callable, Optional

import anthropic

from agents.court_researcher import run_court_researcher
from agents.documentor import run_documentor
from agents.web_researcher import run_web_researcher
from models.case_report import CaseIntelReport, SearchFilters

# Brief pause between agents — only needed to avoid TPM rate-limit bursts.
# 1 s is enough for a single-user desktop app; the old 6 s was excessively
# conservative and made every investigation 12 s slower than necessary.
_INTER_AGENT_PAUSE = 1


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

    1. Court researcher  — searches CourtListener + Descrybe
    2. Web researcher    — searches FTC / SEC / CFPB / news
    3. Documentor        — synthesizes both into a CaseIntelReport

    Args:
        log_cb: optional callback(msg) called for each progress message.
                When provided, used instead of stderr so callers running in
                a background thread can forward messages to the UI safely.
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

    # ── 1. Court research ─────────────────────────────────────────────────────
    log(f"Court researcher: {court_query[:100]}")
    court_findings: dict = {}
    try:
        court_findings = run_court_researcher(
            query=court_query,
            court_code=filters.court_code if filters else None,
            date_from=filters.date_from if filters else None,
            date_to=filters.date_to if filters else None,
            client=client,
        )
        n = court_findings.get("total_found", len(court_findings.get("cases", [])))
        log(f"Court researcher: {n} cases found")
    except Exception as e:
        log(f"Court researcher error: {e}")
        court_findings = {"cases": [], "total_found": 0, "error": str(e)}

    log(f"Pausing {_INTER_AGENT_PAUSE}s…")
    time.sleep(_INTER_AGENT_PAUSE)

    # ── 2. Web research ───────────────────────────────────────────────────────
    log(f"Web researcher: {web_query[:100]}")
    web_findings: dict = {}
    try:
        web_findings = run_web_researcher(query=web_query, client=client)
        n = web_findings.get("total_found", len(web_findings.get("findings", [])))
        log(f"Web researcher: {n} findings")
    except Exception as e:
        log(f"Web researcher error: {e}")
        web_findings = {"findings": [], "total_found": 0, "error": str(e)}

    log(f"Pausing {_INTER_AGENT_PAUSE}s…")
    time.sleep(_INTER_AGENT_PAUSE)

    # ── 3. Synthesis ──────────────────────────────────────────────────────────
    log("Documentor: synthesizing…")
    report = run_documentor(
        query=query,
        court_findings=court_findings,
        web_findings=web_findings,
        filters=filters,
        client=client,
    )
    log(f"Done — {report.total_cases_found} cases, {report.high_severity_count} high severity")
    return report
