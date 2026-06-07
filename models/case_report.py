from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class HarmType(str, Enum):
    # Financial
    FINANCIAL_LOSS      = "financial_loss"
    SECURITIES_FRAUD    = "securities_fraud"
    WIRE_FRAUD          = "wire_fraud"
    BANK_FRAUD          = "bank_fraud"
    TAX_FRAUD           = "tax_fraud"
    INSURANCE_FRAUD     = "insurance_fraud"
    MORTGAGE_FRAUD      = "mortgage_fraud"
    IDENTITY_THEFT      = "identity_theft"
    MONEY_LAUNDERING    = "money_laundering"
    # Consumer
    CONSUMER_DECEPTION  = "consumer_deception"
    FALSE_ADVERTISING   = "false_advertising"
    PREDATORY_LENDING   = "predatory_lending"
    # Civil Rights & Discrimination
    CIVIL_RIGHTS        = "civil_rights"
    EMPLOYMENT          = "employment_discrimination"
    HOUSING             = "housing_discrimination"
    EDUCATION           = "education_discrimination"
    VOTING_RIGHTS       = "voting_rights"
    POLICE_MISCONDUCT   = "police_misconduct"
    # Criminal
    ASSAULT_BATTERY     = "assault_battery"
    HOMICIDE            = "homicide"
    DRUG_OFFENSE        = "drug_offense"
    RACKETEERING        = "racketeering"
    EXTORTION           = "extortion"
    HUMAN_TRAFFICKING   = "human_trafficking"
    # Other civil
    REPUTATIONAL_DAMAGE = "reputational_damage"
    DATA_PRIVACY        = "data_privacy"
    MEDICAL_MALPRACTICE = "medical_malpractice"
    PRODUCT_LIABILITY   = "product_liability"
    ENVIRONMENTAL       = "environmental"
    INTELLECTUAL_PROP   = "intellectual_property"
    BREACH_CONTRACT     = "breach_of_contract"
    OTHER               = "other"


class CaseSeverity(str, Enum):
    HIGH    = "high"
    MEDIUM  = "medium"
    LOW     = "low"
    UNKNOWN = "unknown"


class ProtectedClass(str, Enum):
    RACE             = "race"
    SEXUAL_ORIENTATION = "sexual_orientation"
    GENDER           = "gender"
    DISABILITY       = "disability"
    RELIGION         = "religion"
    NATIONAL_ORIGIN  = "national_origin"
    AGE              = "age"
    VETERAN_STATUS   = "veteran_status"
    PREGNANCY        = "pregnancy"
    OTHER            = "other"


class SearchFilters(BaseModel):
    """Structured filters a user can apply to narrow a case search."""
    crime_types: list[str]           = Field(default_factory=list, description="Crime or legal issue types")
    protected_classes: list[str]     = Field(default_factory=list, description="Affected protected classes")
    area: Optional[str]              = Field(None, description="State, city, or geographic region")
    court_code: Optional[str]        = Field(None, description="CourtListener court code, e.g. ca9, nysd, scotus")
    court_label: Optional[str]       = Field(None, description="Human-readable court name")
    date_from: Optional[str]         = Field(None, description="Filed on or after (YYYY-MM-DD)")
    date_to: Optional[str]           = Field(None, description="Filed on or before (YYYY-MM-DD)")
    case_status: Optional[str]       = Field(None, description="filed | settled | dismissed | ongoing | verdict")

    def is_empty(self) -> bool:
        return not any([
            self.crime_types, self.protected_classes, self.area,
            self.court_code, self.date_from, self.date_to, self.case_status,
        ])

    def as_query_string(self) -> str:
        """Build a natural-language summary of the active filters for use in prompts."""
        parts = []
        if self.crime_types:
            parts.append("crime/issue types: " + ", ".join(self.crime_types))
        if self.protected_classes:
            parts.append("protected classes: " + ", ".join(self.protected_classes))
        if self.area:
            parts.append(f"area: {self.area}")
        if self.court_label:
            parts.append(f"court: {self.court_label}")
        if self.date_from or self.date_to:
            parts.append(f"date range: {self.date_from or 'any'} – {self.date_to or 'present'}")
        if self.case_status:
            parts.append(f"status: {self.case_status}")
        return "; ".join(parts)


class Source(BaseModel):
    source_type: str = Field(description="court_filing | news | regulatory | academic")
    title: str
    url: Optional[str] = None
    date: Optional[str] = None
    excerpt: Optional[str] = None


class CaseFinding(BaseModel):
    case_name: str
    jurisdiction: Optional[str] = None
    court_name: Optional[str]   = None
    filing_date: Optional[str]  = None
    harm_types: list[HarmType]  = Field(default_factory=list)
    protected_classes: list[ProtectedClass] = Field(default_factory=list)
    severity: CaseSeverity      = CaseSeverity.UNKNOWN
    ai_actor: Optional[str]     = Field(None, description="Company or system alleged to have caused harm")
    victim_description: str     = Field(description="Who was harmed and how")
    deceptive_practice: str     = Field(description="Specific AI-driven or discriminatory practice alleged")
    verifiable_harm: str        = Field(description="Documented, concrete harm — financial figures, reputational facts")
    legal_status: Optional[str] = Field(None, description="Filed, settled, dismissed, ongoing, etc.")
    sources: list[Source]       = Field(default_factory=list)


class CaseIntelReport(BaseModel):
    query: str          = Field(description="Original research query")
    filters_applied: Optional[SearchFilters] = None
    generated_at: str   = Field(default_factory=lambda: datetime.utcnow().isoformat() + "Z")
    findings: list[CaseFinding] = Field(default_factory=list)
    total_cases_found: int   = 0
    high_severity_count: int = 0
    summary: str             = Field(description="Executive summary of findings")
    investigator_notes: str  = Field(description="Analytical notes — patterns, gaps, caveats")
    sources_searched: list[str] = Field(default_factory=list)

    def to_markdown(self) -> str:
        lines = [
            "# LegalPerigee Case Intelligence Report",
            "",
            f"**Query:** {self.query}",
        ]
        if self.filters_applied and not self.filters_applied.is_empty():
            lines.append(f"**Filters:** {self.filters_applied.as_query_string()}")
        lines += [
            f"**Generated:** {self.generated_at}",
            f"**Cases Found:** {self.total_cases_found} ({self.high_severity_count} high severity)",
            "",
            "---",
            "",
            "## Executive Summary",
            "",
            self.summary,
            "",
            "---",
            "",
            "## Case Findings",
            "",
        ]

        for i, finding in enumerate(self.findings, 1):
            pc = ", ".join(p.value for p in finding.protected_classes) or "—"
            lines += [
                f"### {i}. {finding.case_name}",
                "",
                "| Field | Value |",
                "|-------|-------|",
                f"| Severity | **{finding.severity.value.upper()}** |",
                f"| Court | {finding.court_name or finding.jurisdiction or 'Unknown'} |",
                f"| Filing Date | {finding.filing_date or 'Unknown'} |",
                f"| Legal Status | {finding.legal_status or 'Unknown'} |",
                f"| AI Actor | {finding.ai_actor or 'Unknown'} |",
                f"| Harm Types | {', '.join(h.value for h in finding.harm_types)} |",
                f"| Protected Classes | {pc} |",
                "",
                f"**Victims:** {finding.victim_description}",
                "",
                f"**Practice Alleged:** {finding.deceptive_practice}",
                "",
                f"**Verifiable Harm:** {finding.verifiable_harm}",
                "",
            ]
            if finding.sources:
                lines.append("**Sources:**")
                for src in finding.sources:
                    link = f"[{src.title}]({src.url})" if src.url else src.title
                    lines.append(f"- {link}" + (f" ({src.date})" if src.date else ""))
                lines.append("")

        lines += [
            "---",
            "",
            "## Investigator Notes",
            "",
            self.investigator_notes,
            "",
            "---",
            "",
            "## Sources Searched",
            "",
        ]
        for src in self.sources_searched:
            lines.append(f"- {src}")

        return "\n".join(lines)
