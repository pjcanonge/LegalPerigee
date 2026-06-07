"""
Tests for models/case_report.py

Covers:
- CaseIntelReport construction and defaults
- CaseFinding severity and harm type enums
- SearchFilters.is_empty() and .as_query_string()
- CaseIntelReport.to_markdown() output structure
- citation_verification optional field round-trip
"""

import pytest
from models.case_report import (
    CaseIntelReport,
    CaseFinding,
    CaseSeverity,
    HarmType,
    ProtectedClass,
    SearchFilters,
    Source,
)


# ── CaseIntelReport defaults ──────────────────────────────────────────────────

def test_report_defaults():
    r = CaseIntelReport(
        query="test query",
        summary="test summary",
        investigator_notes="none",
    )
    assert r.total_cases_found == 0
    assert r.high_severity_count == 0
    assert r.findings == []
    assert r.sources_searched == []
    assert r.citation_verification is None
    assert r.generated_at.endswith("Z")


def test_report_citation_verification_field():
    r = CaseIntelReport(
        query="q",
        summary="s",
        investigator_notes="n",
        citation_verification={
            "verified": ["Smith v. Jones"],
            "unverified": [],
            "skipped": 0,
            "total_checked": 1,
            "note": "All verified",
        },
    )
    assert r.citation_verification["total_checked"] == 1
    assert "Smith v. Jones" in r.citation_verification["verified"]


# ── CaseFinding ───────────────────────────────────────────────────────────────

def test_finding_severity_default():
    f = CaseFinding(
        case_name="Doe v. Corp",
        victim_description="10 plaintiffs",
        deceptive_practice="false advertising",
        verifiable_harm="$500k loss",
    )
    assert f.severity == CaseSeverity.UNKNOWN


def test_finding_explicit_severity():
    f = CaseFinding(
        case_name="United States v. Fraud Inc",
        severity=CaseSeverity.HIGH,
        victim_description="1 million victims",
        deceptive_practice="Ponzi scheme",
        verifiable_harm="$50M loss",
    )
    assert f.severity == CaseSeverity.HIGH


def test_finding_harm_types():
    f = CaseFinding(
        case_name="Case X",
        harm_types=[HarmType.CIVIL_RIGHTS, HarmType.EMPLOYMENT],
        victim_description="employees",
        deceptive_practice="discriminatory hiring",
        verifiable_harm="lost wages",
    )
    assert HarmType.CIVIL_RIGHTS in f.harm_types
    assert HarmType.EMPLOYMENT in f.harm_types


def test_finding_protected_classes():
    f = CaseFinding(
        case_name="Case Y",
        protected_classes=[ProtectedClass.RACE, ProtectedClass.GENDER],
        victim_description="minority employees",
        deceptive_practice="pay discrimination",
        verifiable_harm="$200k wage gap",
    )
    assert ProtectedClass.RACE in f.protected_classes


# ── SearchFilters ─────────────────────────────────────────────────────────────

def test_filters_is_empty_true():
    f = SearchFilters()
    assert f.is_empty() is True


def test_filters_is_empty_false_crime_type():
    f = SearchFilters(crime_types=["fraud"])
    assert f.is_empty() is False


def test_filters_is_empty_false_area():
    f = SearchFilters(area="New York")
    assert f.is_empty() is False


def test_filters_as_query_string_full():
    f = SearchFilters(
        crime_types=["fraud", "wire_fraud"],
        protected_classes=["race"],
        area="California",
        court_label="9th Circuit",
        date_from="2020-01-01",
        date_to="2023-12-31",
        case_status="settled",
    )
    qs = f.as_query_string()
    assert "fraud" in qs
    assert "race" in qs
    assert "California" in qs
    assert "9th Circuit" in qs
    assert "2020-01-01" in qs
    assert "settled" in qs


def test_filters_as_query_string_empty():
    f = SearchFilters()
    assert f.as_query_string() == ""


# ── CaseIntelReport.to_markdown() ────────────────────────────────────────────

def _sample_report() -> CaseIntelReport:
    return CaseIntelReport(
        query="housing discrimination cases",
        summary="Found 1 relevant case.",
        investigator_notes="Pattern detected.",
        total_cases_found=1,
        high_severity_count=1,
        findings=[
            CaseFinding(
                case_name="Jones v. Big Realty",
                severity=CaseSeverity.HIGH,
                court_name="S.D.N.Y.",
                filing_date="2023-03-15",
                harm_types=[HarmType.HOUSING],
                protected_classes=[ProtectedClass.RACE],
                victim_description="Black applicants denied housing",
                deceptive_practice="Steering and denial",
                verifiable_harm="$2M settlement",
                legal_status="Settled",
                sources=[Source(
                    source_type="court_filing",
                    title="Complaint",
                    url="https://example.com/complaint",
                    date="2023-03-15",
                )],
            )
        ],
        sources_searched=["courtlistener", "web"],
    )


def test_to_markdown_contains_query():
    md = _sample_report().to_markdown()
    assert "housing discrimination cases" in md


def test_to_markdown_contains_case_name():
    md = _sample_report().to_markdown()
    assert "Jones v. Big Realty" in md


def test_to_markdown_contains_summary():
    md = _sample_report().to_markdown()
    assert "Found 1 relevant case." in md


def test_to_markdown_contains_severity():
    md = _sample_report().to_markdown()
    assert "HIGH" in md


def test_to_markdown_contains_source_link():
    md = _sample_report().to_markdown()
    assert "https://example.com/complaint" in md


def test_to_markdown_has_investigator_notes():
    md = _sample_report().to_markdown()
    assert "Pattern detected." in md


def test_to_markdown_sources_searched():
    md = _sample_report().to_markdown()
    assert "courtlistener" in md
