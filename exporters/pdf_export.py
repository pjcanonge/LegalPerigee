"""
Export a CaseIntelReport as a formatted PDF using ReportLab.
"""

import io
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
    TableStyle,
)

from models.case_report import CaseIntelReport

# ── Colors ─────────────────────────────────────────────────────────────────────
NAVY  = colors.HexColor("#1a2744")
GOLD  = colors.HexColor("#c9a84c")
RED   = colors.HexColor("#c0392b")
ORG   = colors.HexColor("#d67f1e")
GRN   = colors.HexColor("#27ae60")
LGRAY = colors.HexColor("#f4f6fb")
MGRAY = colors.HexColor("#888888")

SEV_COLORS = {"high": RED, "medium": ORG, "low": GRN, "unknown": MGRAY}

# ── Styles ─────────────────────────────────────────────────────────────────────
_base = getSampleStyleSheet()

S = {
    "title": ParagraphStyle("LP_Title", fontSize=24, textColor=colors.white,
                             fontName="Helvetica-Bold", alignment=TA_CENTER, spaceAfter=4),
    "subtitle": ParagraphStyle("LP_Sub", fontSize=12, textColor=GOLD,
                                fontName="Helvetica-Bold", alignment=TA_CENTER, spaceAfter=20),
    "h1": ParagraphStyle("LP_H1", fontSize=16, textColor=NAVY,
                          fontName="Helvetica-Bold", spaceBefore=18, spaceAfter=6,
                          borderPad=4),
    "h2": ParagraphStyle("LP_H2", fontSize=12, textColor=NAVY,
                          fontName="Helvetica-Bold", spaceBefore=12, spaceAfter=4),
    "body": ParagraphStyle("LP_Body", fontSize=10, textColor=colors.black,
                            fontName="Helvetica", leading=14, spaceAfter=6),
    "small": ParagraphStyle("LP_Small", fontSize=8, textColor=MGRAY,
                             fontName="Helvetica", alignment=TA_CENTER),
    "label": ParagraphStyle("LP_Label", fontSize=9, textColor=NAVY,
                              fontName="Helvetica-Bold", spaceAfter=2),
    "value": ParagraphStyle("LP_Value", fontSize=9, textColor=colors.black,
                              fontName="Helvetica", spaceAfter=4),
    "bullet": ParagraphStyle("LP_Bullet", fontSize=9, textColor=colors.black,
                               fontName="Helvetica", leftIndent=16, spaceAfter=3,
                               bulletIndent=6, leading=13),
}


def _header_block(title: str, subtitle: str) -> list:
    """Dark navy cover header."""
    data = [[Paragraph(title, S["title"])],
            [Paragraph(subtitle, S["subtitle"])]]
    t = Table(data, colWidths=[7.5 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), NAVY),
        ("LEFTPADDING",  (0, 0), (-1, -1), 24),
        ("RIGHTPADDING", (0, 0), (-1, -1), 24),
        ("TOPPADDING",   (0, 0), (0, 0),  20),
        ("BOTTOMPADDING",(0, -1), (-1, -1), 16),
        ("LINEBELOW",    (0, 0), (-1, 0),  3, GOLD),
    ]))
    return [t, Spacer(1, 0.2 * inch)]


def _meta_table(report: CaseIntelReport) -> list:
    data = [
        ["Query",         report.query[:80] + ("…" if len(report.query) > 80 else "")],
        ["Generated",     report.generated_at[:19].replace("T", " ")],
        ["Total Cases",   str(report.total_cases_found)],
        ["High Severity", str(report.high_severity_count)],
    ]
    if report.filters_applied and not report.filters_applied.is_empty():
        data.append(["Filters", report.filters_applied.as_query_string()[:80]])

    t = Table(data, colWidths=[1.4 * inch, 6.1 * inch])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (0, -1), LGRAY),
        ("FONTNAME",      (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME",      (1, 0), (1, -1), "Helvetica"),
        ("FONTSIZE",      (0, 0), (-1, -1), 9),
        ("TEXTCOLOR",     (0, 0), (0, -1), NAVY),
        ("GRID",          (0, 0), (-1, -1), 0.5, colors.HexColor("#dde3ee")),
        ("LEFTPADDING",   (0, 0), (-1, -1), 8),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 8),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS",(0, 0), (-1, -1), [colors.white, LGRAY]),
    ]))
    return [t, Spacer(1, 0.25 * inch)]


def _case_block(i: int, finding) -> list:
    sev = finding.severity.value
    sev_color = SEV_COLORS.get(sev, MGRAY)
    elems = []

    # Case header row
    header_data = [[
        Paragraph(f"{i}. {finding.case_name}", S["h2"]),
        Paragraph(f'<font color="{sev_color.hexval()}">{sev.upper()}</font>',
                  ParagraphStyle("sev", fontSize=9, fontName="Helvetica-Bold",
                                 textColor=sev_color, alignment=TA_RIGHT)),
    ]]
    ht = Table(header_data, colWidths=[5.5 * inch, 2 * inch])
    ht.setStyle(TableStyle([
        ("LINEBELOW",    (0, 0), (-1, -1), 1, NAVY),
        ("TOPPADDING",   (0, 0), (-1, -1), 0),
        ("BOTTOMPADDING",(0, 0), (-1, -1), 4),
    ]))
    elems.append(ht)
    elems.append(Spacer(1, 4))

    # Metadata grid
    meta_rows = [
        ["Court",    finding.court_name or finding.jurisdiction or "—",
         "Filed",    finding.filing_date or "—"],
        ["Status",   finding.legal_status or "—",
         "AI Actor", finding.ai_actor or "—"],
    ]
    if finding.harm_types:
        meta_rows.append(["Harm Types", ", ".join(h.value for h in finding.harm_types), "", ""])
    if finding.protected_classes:
        meta_rows.append(["Protected", ", ".join(p.value for p in finding.protected_classes), "", ""])

    mt = Table(meta_rows, colWidths=[0.9*inch, 2.7*inch, 0.7*inch, 3.2*inch])
    mt.setStyle(TableStyle([
        ("FONTNAME",  (0, 0), (-1, -1), "Helvetica"),
        ("FONTNAME",  (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME",  (2, 0), (2, -1), "Helvetica-Bold"),
        ("FONTSIZE",  (0, 0), (-1, -1), 8.5),
        ("TEXTCOLOR", (0, 0), (0, -1), NAVY),
        ("TEXTCOLOR", (2, 0), (2, -1), NAVY),
        ("GRID",      (0, 0), (-1, -1), 0.25, colors.HexColor("#dde3ee")),
        ("BACKGROUND",(0, 0), (0, -1), LGRAY),
        ("BACKGROUND",(2, 0), (2, -1), LGRAY),
        ("LEFTPADDING", (0,0),(-1,-1), 5),
        ("TOPPADDING",  (0,0),(-1,-1), 4),
        ("BOTTOMPADDING",(0,0),(-1,-1), 4),
    ]))
    elems.append(mt)
    elems.append(Spacer(1, 6))

    def kv(label, text):
        elems.append(Paragraph(label, S["label"]))
        elems.append(Paragraph(text or "—", S["value"]))

    kv("Victims:", finding.victim_description)
    kv("Practice Alleged:", finding.deceptive_practice)
    kv("Verifiable Harm:", finding.verifiable_harm)

    if finding.sources:
        elems.append(Paragraph("Sources:", S["label"]))
        for src in finding.sources:
            elems.append(Paragraph(
                f"• [{src.source_type}] {src.title}"
                + (f" ({src.date})" if src.date else "")
                + (f"\n  {src.url}" if src.url else ""),
                S["bullet"],
            ))

    elems.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#dde3ee")))
    elems.append(Spacer(1, 8))
    return elems


def export_to_pdf(report: CaseIntelReport) -> bytes:
    """Generate a PDF from a CaseIntelReport. Returns bytes."""
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=letter,
        leftMargin=0.9 * inch, rightMargin=0.9 * inch,
        topMargin=0.75 * inch, bottomMargin=0.75 * inch,
    )

    story = []

    # Cover header
    story += _header_block(
        "⚖  LEGALPERIGEE",
        "CASE INTELLIGENCE REPORT — CONFIDENTIAL",
    )

    # Meta table
    story += _meta_table(report)

    # Executive Summary
    story.append(Paragraph("Executive Summary", S["h1"]))
    story.append(Paragraph(report.summary, S["body"]))

    if report.filters_applied and not report.filters_applied.is_empty():
        story.append(Paragraph("Search Filters Applied", S["h2"]))
        story.append(Paragraph(report.filters_applied.as_query_string(), S["body"]))

    story.append(PageBreak())

    # Case Findings
    story.append(Paragraph("Case Findings", S["h1"]))
    for i, finding in enumerate(report.findings, 1):
        story += _case_block(i, finding)

    # Investigator Notes
    story.append(PageBreak())
    story.append(Paragraph("Investigator Notes", S["h1"]))
    story.append(Paragraph(report.investigator_notes, S["body"]))

    # Sources
    if report.sources_searched:
        story.append(Paragraph("Sources Searched", S["h2"]))
        for s in report.sources_searched:
            story.append(Paragraph(f"• {s}", S["bullet"]))

    # Footer
    story.append(Spacer(1, 0.3 * inch))
    story.append(Paragraph(
        f"CONFIDENTIAL — LegalPerigee · Generated {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        S["small"],
    ))

    doc.build(story)
    return buf.getvalue()
