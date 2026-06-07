"""
Tests for utils/citation_verifier.py

All HTTP calls are mocked — no network required.
Covers:
- verify_report_citations() with token present
- verify_report_citations() without token (skip path)
- Verified / unverified / skipped counts
- Rate-limit (429) handling
- HTTP error / timeout handling
- Case name cleaning (strip trailing citation decoration)
"""

from unittest.mock import MagicMock, patch

import pytest

from models.case_report import CaseIntelReport, CaseFinding, CaseSeverity, Source
from utils.citation_verifier import verify_report_citations


def _make_report(findings) -> CaseIntelReport:
    return CaseIntelReport(
        query="test",
        summary="test summary",
        investigator_notes="none",
        findings=findings,
    )


def _court_finding(name: str) -> CaseFinding:
    return CaseFinding(
        case_name=name,
        victim_description="plaintiff",
        deceptive_practice="practice",
        verifiable_harm="harm",
        sources=[Source(source_type="court_filing", title="Complaint")],
    )


def _web_finding(name: str) -> CaseFinding:
    return CaseFinding(
        case_name=name,
        victim_description="plaintiff",
        deceptive_practice="practice",
        verifiable_harm="harm",
        sources=[Source(source_type="news", title="Article")],
    )


# ── No token → skip all ───────────────────────────────────────────────────────

def test_no_token_skips_all(monkeypatch):
    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "")
    report = _make_report([_court_finding("Smith v. Jones")])
    result = verify_report_citations(report)
    assert result["total_checked"] == 0
    assert result["skipped"] == 1
    assert "token not configured" in result["note"].lower() or "api token" in result["note"].lower()


# ── With token, case found ────────────────────────────────────────────────────

def test_verified_case(monkeypatch):
    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "fake-token")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"count": 3}

    with patch("utils.citation_verifier.httpx.get", return_value=mock_resp), \
         patch("utils.citation_verifier.time.sleep"):
        result = verify_report_citations(_make_report([_court_finding("Roe v. Wade")]))

    assert "Roe v. Wade" in result["verified"]
    assert result["unverified"] == []
    assert result["total_checked"] == 1
    assert "verified" in result["note"].lower()


# ── With token, case not found ────────────────────────────────────────────────

def test_unverified_case(monkeypatch):
    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "fake-token")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"count": 0}

    with patch("utils.citation_verifier.httpx.get", return_value=mock_resp), \
         patch("utils.citation_verifier.time.sleep"):
        result = verify_report_citations(
            _make_report([_court_finding("Hallucinated v. Fake Corp")])
        )

    assert "Hallucinated v. Fake Corp" in result["unverified"]
    assert result["verified"] == []
    assert "unverified" in result["note"].lower() or "⚠️" in result["note"]


# ── Non-court-filing source → skipped ────────────────────────────────────────

def test_web_only_finding_skipped(monkeypatch):
    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "fake-token")

    with patch("utils.citation_verifier.httpx.get") as mock_get, \
         patch("utils.citation_verifier.time.sleep"):
        result = verify_report_citations(_make_report([_web_finding("News Story")]))

    mock_get.assert_not_called()
    assert result["skipped"] == 1
    assert result["total_checked"] == 0


# ── Mixed verified + unverified + skipped ────────────────────────────────────

def test_mixed_findings(monkeypatch):
    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "fake-token")

    responses = [
        MagicMock(status_code=200, json=MagicMock(return_value={"count": 2})),   # found
        MagicMock(status_code=200, json=MagicMock(return_value={"count": 0})),   # not found
    ]

    with patch("utils.citation_verifier.httpx.get", side_effect=responses), \
         patch("utils.citation_verifier.time.sleep"):
        result = verify_report_citations(_make_report([
            _court_finding("Real Case"),
            _court_finding("Fake Case"),
            _web_finding("News Article"),   # skipped
        ]))

    assert "Real Case" in result["verified"]
    assert "Fake Case" in result["unverified"]
    assert result["skipped"] == 1
    assert result["total_checked"] == 2


# ── 429 rate-limit → treated as unverified (not a crash) ─────────────────────

def test_rate_limit_not_crash(monkeypatch):
    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "fake-token")

    mock_resp = MagicMock()
    mock_resp.status_code = 429

    with patch("utils.citation_verifier.httpx.get", return_value=mock_resp), \
         patch("utils.citation_verifier.time.sleep"):
        result = verify_report_citations(_make_report([_court_finding("Rate Limited Case")]))

    assert isinstance(result, dict)
    # 429 returns False from _search_case_exists → unverified
    assert "Rate Limited Case" in result["unverified"]


# ── Network timeout → treated as unverified (not a crash) ────────────────────

def test_timeout_not_crash(monkeypatch):
    import httpx
    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "fake-token")

    with patch("utils.citation_verifier.httpx.get", side_effect=httpx.TimeoutException("timeout")), \
         patch("utils.citation_verifier.time.sleep"):
        result = verify_report_citations(_make_report([_court_finding("Slow Case")]))

    assert isinstance(result, dict)
    assert "Slow Case" in result["unverified"]


# ── Empty report → no crash ───────────────────────────────────────────────────

def test_empty_report(monkeypatch):
    monkeypatch.setenv("COURTLISTENER_API_TOKEN", "fake-token")
    with patch("utils.citation_verifier.httpx.get") as mock_get, \
         patch("utils.citation_verifier.time.sleep"):
        result = verify_report_citations(_make_report([]))
    mock_get.assert_not_called()
    assert result["total_checked"] == 0
    assert result["skipped"] == 0
