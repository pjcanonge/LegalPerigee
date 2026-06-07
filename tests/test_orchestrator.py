"""
Tests for agents/orchestrator.py

All agent calls and the citation verifier are mocked — no API keys required.
Covers:
- _build_court_query() and _build_web_query() filter expansion
- run_investigation() parallel execution path
- run_investigation() error handling when an agent raises
- log_cb messages sent during parallel execution
- Citation verification called and attached to report
"""

from unittest.mock import MagicMock, patch, call
import pytest

from models.case_report import CaseIntelReport, SearchFilters
from agents.orchestrator import _build_court_query, _build_web_query


# ── Query builders ────────────────────────────────────────────────────────────

def test_build_court_query_no_filters():
    result = _build_court_query("housing discrimination", None)
    assert result == "housing discrimination"


def test_build_court_query_with_crime_types():
    filters = SearchFilters(crime_types=["fraud", "wire_fraud"])
    result = _build_court_query("securities", filters)
    assert "fraud" in result
    assert "wire_fraud" in result


def test_build_court_query_with_area():
    filters = SearchFilters(area="California")
    result = _build_court_query("employment", filters)
    assert "California" in result


def test_build_web_query_includes_court_label():
    filters = SearchFilters(court_label="9th Circuit")
    result = _build_web_query("civil rights", filters)
    assert "9th Circuit" in result


def test_build_court_query_empty_filters():
    filters = SearchFilters()
    result = _build_court_query("fraud", filters)
    assert result == "fraud"


# ── run_investigation() ───────────────────────────────────────────────────────

def _fake_client():
    return MagicMock()


def _mock_court_findings():
    return {"cases": [{"case_name": "Smith v. Jones", "court": "SDNY"}], "total_found": 1}


def _mock_web_findings():
    return {"findings": [{"title": "News Story"}], "total_found": 1}


def _mock_report() -> CaseIntelReport:
    return CaseIntelReport(
        query="test",
        summary="2 results found",
        investigator_notes="none",
        total_cases_found=2,
        high_severity_count=0,
    )


def test_run_investigation_calls_both_agents(monkeypatch):
    """Both researchers should be called exactly once."""
    with patch("agents.orchestrator.run_court_researcher", return_value=_mock_court_findings()) as mock_court, \
         patch("agents.orchestrator.run_web_researcher",   return_value=_mock_web_findings())   as mock_web, \
         patch("agents.orchestrator.run_documentor",        return_value=_mock_report()), \
         patch("utils.citation_verifier.verify_report_citations", return_value={}), \
         patch("agents.orchestrator.time.sleep"):

        from agents.orchestrator import run_investigation
        report = run_investigation("test query", client=_fake_client())

    mock_court.assert_called_once()
    mock_web.assert_called_once()
    assert report.total_cases_found == 2


def test_run_investigation_log_cb_receives_messages():
    """log_cb should receive at least one message per stage."""
    log_messages = []

    with patch("agents.orchestrator.run_court_researcher", return_value=_mock_court_findings()), \
         patch("agents.orchestrator.run_web_researcher",   return_value=_mock_web_findings()), \
         patch("agents.orchestrator.run_documentor",        return_value=_mock_report()), \
         patch("utils.citation_verifier.verify_report_citations", return_value={}), \
         patch("agents.orchestrator.time.sleep"):

        from agents.orchestrator import run_investigation
        run_investigation("test", client=_fake_client(), log_cb=log_messages.append)

    assert len(log_messages) >= 3   # launch, at least 2 completions, synthesis
    combined = " ".join(log_messages)
    assert "parallel" in combined.lower() or "⚡" in combined


def test_run_investigation_court_error_continues():
    """If court researcher raises, investigation should still complete via web data."""
    with patch("agents.orchestrator.run_court_researcher", side_effect=RuntimeError("court down")), \
         patch("agents.orchestrator.run_web_researcher",   return_value=_mock_web_findings()), \
         patch("agents.orchestrator.run_documentor",        return_value=_mock_report()), \
         patch("utils.citation_verifier.verify_report_citations", return_value={}), \
         patch("agents.orchestrator.time.sleep"):

        from agents.orchestrator import run_investigation
        report = run_investigation("test", client=_fake_client())

    assert report is not None


def test_run_investigation_web_error_continues():
    """If web researcher raises, investigation should still complete via court data."""
    with patch("agents.orchestrator.run_court_researcher", return_value=_mock_court_findings()), \
         patch("agents.orchestrator.run_web_researcher",   side_effect=RuntimeError("web down")), \
         patch("agents.orchestrator.run_documentor",        return_value=_mock_report()), \
         patch("utils.citation_verifier.verify_report_citations", return_value={}), \
         patch("agents.orchestrator.time.sleep"):

        from agents.orchestrator import run_investigation
        report = run_investigation("test", client=_fake_client())

    assert report is not None


def test_run_investigation_citation_verification_attached():
    """Citation verification results should be stored on the returned report."""
    cv_result = {
        "verified": ["Smith v. Jones"],
        "unverified": [],
        "skipped": 0,
        "total_checked": 1,
        "note": "All verified",
    }

    with patch("agents.orchestrator.run_court_researcher", return_value=_mock_court_findings()), \
         patch("agents.orchestrator.run_web_researcher",   return_value=_mock_web_findings()), \
         patch("agents.orchestrator.run_documentor",        return_value=_mock_report()), \
         patch("utils.citation_verifier.verify_report_citations", return_value=cv_result), \
         patch("agents.orchestrator.time.sleep"):

        from agents.orchestrator import run_investigation
        report = run_investigation("test", client=_fake_client())

    assert report.citation_verification is not None
    assert report.citation_verification["total_checked"] == 1


def test_run_investigation_no_api_key_raises():
    """Missing API key should raise ValueError before any agent is called."""
    import os
    with patch.dict(os.environ, {"ANTHROPIC_API_KEY": ""}):
        from agents.orchestrator import run_investigation
        with pytest.raises(ValueError, match="API key"):
            run_investigation("test", client=None)
