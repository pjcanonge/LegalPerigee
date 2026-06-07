#!/usr/bin/env python3
"""Generate a properly formatted PDF briefing of LegalPerigee data sources."""

import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import datetime
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    HRFlowable, PageBreak, KeepTogether, Image,
)

W      = letter[0] - 1.6 * inch   # usable page width
LOGO   = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "logo.png")

# ── Colors ────────────────────────────────────────────────────────────────────
NAVY  = colors.HexColor("#1a2744")
GOLD  = colors.HexColor("#c9a84c")
RED   = colors.HexColor("#c0392b")
BLUE  = colors.HexColor("#2c5f8a")
TEAL  = colors.HexColor("#1a7a5e")
PURP  = colors.HexColor("#6b3fa0")
LGRAY = colors.HexColor("#f4f6fb")
MGRAY = colors.HexColor("#777777")
DGRAY = colors.HexColor("#444444")
WHITE = colors.white

# ── Base paragraph styles ─────────────────────────────────────────────────────
def ps(name, base=None, **kw):
    kwargs = dict(fontName="Helvetica", fontSize=10, leading=14,
                  textColor=colors.black, spaceAfter=4)
    kwargs.update(kw)
    return ParagraphStyle(name, **kwargs)

BODY  = ps("body",  fontSize=9.5, leading=14, spaceAfter=5)
CELL  = ps("cell",  fontSize=8.5, leading=12, spaceAfter=0)
CELLB = ps("cellb", fontSize=8.5, leading=12, spaceAfter=0, fontName="Helvetica-Bold", textColor=NAVY)
CELLH = ps("cellh", fontSize=8.5, leading=12, spaceAfter=0, fontName="Helvetica-Bold", textColor=WHITE)
CELLN = ps("celln", fontSize=8,   leading=11, spaceAfter=0, textColor=MGRAY, fontName="Helvetica-Oblique")
H1    = ps("h1",    fontSize=16, fontName="Helvetica-Bold", textColor=NAVY, spaceBefore=18, spaceAfter=4)
H2    = ps("h2",    fontSize=12, fontName="Helvetica-Bold", textColor=NAVY, spaceBefore=14, spaceAfter=4)
H3    = ps("h3",    fontSize=10, fontName="Helvetica-Bold", textColor=BLUE, spaceBefore=8, spaceAfter=2)
NOTE  = ps("note",  fontSize=8,  fontName="Helvetica-Oblique", textColor=MGRAY, spaceAfter=6)
FOOT  = ps("foot",  fontSize=7.5,fontName="Helvetica", textColor=MGRAY, alignment=TA_CENTER)
CTITL = ps("ct",    fontSize=24, fontName="Helvetica-Bold", textColor=WHITE, alignment=TA_CENTER, spaceAfter=2)
CSUBT = ps("cs",    fontSize=12, fontName="Helvetica-Bold", textColor=GOLD,  alignment=TA_CENTER, spaceAfter=2)
CMETA = ps("cm",    fontSize=9,  fontName="Helvetica",      textColor=GOLD,  alignment=TA_CENTER, spaceAfter=0)

def P(text, style=BODY):
    """Safe paragraph — converts None/empty to blank."""
    return Paragraph(str(text) if text else "", style)

def bullet(text):
    return Paragraph(f"&#8226; &nbsp;{text}", BODY)

def sp(n=8):
    return Spacer(1, n)

def hr(color=colors.HexColor("#dde3ee"), thickness=0.5):
    return HRFlowable(width="100%", thickness=thickness, color=color, spaceAfter=4)

# ── Table builder ─────────────────────────────────────────────────────────────

def make_table(headers, rows, col_widths, header_color=NAVY, note_text=None):
    """Build a table where every cell is a Paragraph (no overflow)."""
    data = [[P(h, CELLH) for h in headers]]
    for row in rows:
        data.append([P(str(c) if c else "", CELL) for c in row])

    t = Table(data, colWidths=col_widths, repeatRows=1)
    style = [
        # Header row
        ("BACKGROUND",    (0, 0), (-1, 0),  header_color),
        ("ROWBACKGROUNDS",(0, 1), (-1, -1), [WHITE, LGRAY]),
        ("GRID",          (0, 0), (-1, -1), 0.3, colors.HexColor("#ccd0e0")),
        ("TOPPADDING",    (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING",   (0, 0), (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0), (-1, -1), 6),
        ("VALIGN",        (0, 0), (-1, -1), "TOP"),
    ]
    t.setStyle(TableStyle(style))
    elems = [t]
    if note_text:
        elems.append(P(f"* {note_text}", NOTE))
    elems.append(sp(10))
    return elems


# ── Cover page ────────────────────────────────────────────────────────────────

# Styles used only on the cover (defined here to keep them out of global scope)
_CV_TITLE = ParagraphStyle("cv_title", fontName="Helvetica-Bold", fontSize=26,
                            textColor=WHITE, leading=30, spaceAfter=6)
_CV_SUB   = ParagraphStyle("cv_sub",   fontName="Helvetica-Bold", fontSize=12,
                            textColor=GOLD,  leading=16, spaceAfter=8)
_CV_META  = ParagraphStyle("cv_meta",  fontName="Helvetica",      fontSize=9,
                            textColor=colors.HexColor("#8fa3bf"), leading=13)


def make_cover():
    LOGO_SIZE = 1.0 * inch   # logo cell width/height
    TEXT_W    = W - LOGO_SIZE - 0.3 * inch  # remaining width for text

    # ── Logo cell ─────────────────────────────────────────────────────────────
    if os.path.exists(LOGO):
        logo_img = Image(LOGO, width=LOGO_SIZE, height=LOGO_SIZE)
        logo_cell = logo_img
    else:
        logo_cell = Paragraph("⚖", ParagraphStyle("lc", fontSize=40,
                              textColor=GOLD, alignment=TA_CENTER))

    # ── Title text cell ───────────────────────────────────────────────────────
    title_block = [
        Paragraph("LEGALPERIGEE", _CV_TITLE),
        Paragraph("DATA SOURCES &amp; INTELLIGENCE BRIEFING", _CV_SUB),
        Paragraph(
            f"Prepared: {datetime.now().strftime('%B %d, %Y')}  ·  "
            "Ethical · Analytical · Evidence-Based",
            _CV_META,
        ),
    ]

    # ── Single-row, two-column header table ───────────────────────────────────
    header_tbl = Table(
        [[logo_cell, title_block]],
        colWidths=[LOGO_SIZE + 0.18*inch, TEXT_W],
    )
    header_tbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0), (-1, -1), NAVY),
        ("VALIGN",        (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING",    (0, 0), (-1, -1), 22),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 22),
        ("LEFTPADDING",   (0, 0), (0, 0),   18),   # logo left padding
        ("LEFTPADDING",   (1, 0), (1, 0),   16),   # text left padding
        ("RIGHTPADDING",  (0, 0), (-1, -1), 18),
        ("LINEBELOW",     (0, 0), (-1, -1),  3, GOLD),
    ]))

    # ── Subtitle bar below the main header ───────────────────────────────────
    sub_bar = Table(
        [[Paragraph(
            "Complete inventory of court records, regulatory data, legislative sources, "
            "and real-time monitoring tools available for AI fraud investigation.",
            ParagraphStyle("sb", fontName="Helvetica", fontSize=9.5,
                           textColor=colors.HexColor("#c8d8ee"), leading=14),
        )]],
        colWidths=[W + 0.8*inch],
    )
    sub_bar.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), colors.HexColor("#0d1b2a")),
        ("TOPPADDING",    (0,0), (-1,-1), 10),
        ("BOTTOMPADDING", (0,0), (-1,-1), 10),
        ("LEFTPADDING",   (0,0), (-1,-1), 18),
        ("RIGHTPADDING",  (0,0), (-1,-1), 18),
    ]))

    return [header_tbl, sub_bar, sp(18)]


# ═══════════════════════════════════════════════════════════════════════════════
#  DOCUMENT CONTENT
# ═══════════════════════════════════════════════════════════════════════════════

def build():
    story = []
    story += make_cover()

    # ── Executive Summary ─────────────────────────────────────────────────────
    story += [P("Executive Summary", H1), hr(NAVY, 1.5)]
    story.append(P(
        "LegalPerigee aggregates AI fraud and civil rights case intelligence from federal courts, "
        "state courts, regulatory agencies, legislative bodies, and legal news. This document "
        "details every active source, the specific records available per query, and a roadmap "
        "of additional sources ready for integration."
    ))
    story.append(P(
        "The system operates in two modes: <b>live investigation</b> — real-time API queries "
        "during a search — and <b>library aggregation</b> — background sync building a searchable "
        "local database. Together they cover ~20 active sources with ~27 more available to add."
    ))
    story.append(sp(4))

    # ══════════════════════════════════════════════════════════════════════════
    story.append(PageBreak())
    story += [P("Part 1 — Currently Active Sources", H1), hr(NAVY, 1.5)]

    # 1.1 Live investigation
    story += [P("1.1  Live Investigation Sources", H2)]
    story.append(P(
        "Queried in real time every time you run an investigation in the 🔍 Investigate tab:"
    ))
    story += make_table(
        ["Source", "Records Searched", "Coverage", "Access"],
        [
            ["CourtListener", "Opinions, PACER dockets, parties, filing dates, docket numbers, citations",
             "All 13 federal circuits + district courts", "Free REST API"],
            ["Web Search\n(Anthropic)", "FTC / SEC / CFPB press releases, news, legal blogs, enforcement summaries",
             "Entire public web, real time", "Built-in tool"],
            ["Descrybe", "Authority-ranked U.S. case law, statutes, regulations, citation analysis",
             "Federal + state case law", "MCP (optional)"],
        ],
        col_widths=[1.3*inch, 2.6*inch, 2.0*inch, 1.4*inch],
        header_color=NAVY,
    )

    # 1.2 Library sources
    story += [P("1.2  Case Library — Synced Sources", H2)]
    story.append(P("Pulled into the local database via the Sync Manager and fully searchable:"))
    story += make_table(
        ["Source", "Records Available", "Volume", "Tier"],
        [
            ["CourtListener", "Opinions, dockets, RECAP filings, parties, judges, citation counts, document links",
             "Millions of cases", "1"],
            ["Harvard Caselaw\nAccess Project", "Full case metadata, decision dates, jurisdiction, citations — all 50 states + federal",
             "6.7 million cases", "1"],
            ["Oyez / SCOTUS", "Case facts, holdings, voting records, oral argument audio links",
             "All terms since 1955", "2"],
            ["SCOTUSblog", "Case dockets, analysis, amicus briefs, argument previews",
             "Current + recent terms", "2"],
            ["FTC", "Enforcement actions, consent orders, penalty amounts, complaints",
             "Ongoing", "1"],
            ["SEC", "Litigation releases, enforcement orders, AI-related securities fraud",
             "Ongoing", "1"],
            ["CFPB", "Consumer finance enforcement, fair lending, algorithmic credit scoring",
             "Ongoing", "1"],
            ["EEOC", "Employment discrimination enforcement, AI hiring bias, settlements",
             "Ongoing", "1"],
            ["HUD", "Housing discrimination enforcement, algorithmic redlining, fair housing",
             "Ongoing", "1"],
            ["DOJ Civil Rights", "Pattern-or-practice investigations, consent decrees, AI discrimination",
             "Ongoing", "1"],
            ["FCC", "Telecom enforcement — AI robocalls, deepfake voice fraud",
             "Ongoing", "1"],
            ["OCC", "Banking AI enforcement, algorithmic lending, fintech oversight",
             "Ongoing", "1"],
            ["Federal Register", "Proposed + final AI rules, agency notices, docket numbers",
             "All agencies, ongoing", "1"],
            ["Congress.gov", "AI-related bills, sponsor, committee, latest action, vote history",
             "117th–119th Congress", "1"],
            ["All 50 State AGs + DC", "Enforcement press releases — AI keyword filtered, all 51 jurisdictions",
             "Ongoing", "2"],
            ["Reuters Legal", "Legal news, AI fraud reporting, tech law analysis",
             "Ongoing", "3"],
            ["Above the Law", "Legal industry news, AI law developments",
             "Ongoing", "3"],
            ["Justia", "Free federal opinions, circuit court decisions",
             "All federal courts", "2"],
            ["SSRN", "Academic legal papers on AI law, discrimination, consumer protection",
             "Ongoing publications", "3"],
            ["Google Scholar", "Free case law — federal + state opinions",
             "All U.S. courts", "3"],
        ],
        col_widths=[1.4*inch, 3.2*inch, 1.5*inch, 0.6*inch],
        header_color=BLUE,
        note_text="Tier 1 = highest priority for AI fraud. Tier 2 = strong secondary. Tier 3 = supplementary.",
    )

    # ══════════════════════════════════════════════════════════════════════════
    story.append(PageBreak())
    story += [P("Part 2 — Record Types Available Per Query", H1), hr(NAVY, 1.5)]

    story += [P("2.1  Court Records", H2)]
    story += make_table(
        ["Record Type", "Fields Available", "Source"],
        [
            ["Case Docket", "Case name, docket number, court, judge, date filed, nature of suit, cause of action, parties",
             "CourtListener / PACER"],
            ["Published Opinion", "Full text, citation, holding, date decided, authoring judge, majority/dissent, cited cases",
             "CourtListener / Harvard CAP"],
            ["PACER Filing", "Complaints, motions, orders, judgments — individual document links via RECAP",
             "CourtListener RECAP"],
            ["Case Parties", "Plaintiff names, defendant names, attorney names, firm names",
             "CourtListener"],
            ["Citation Network", "Cases that cite this case, cases cited by this case, citation count over time",
             "CourtListener / Descrybe"],
            ["SCOTUS Record", "Oral argument audio, full voting record, amicus briefs, case summary",
             "Oyez API"],
        ],
        col_widths=[1.5*inch, 3.4*inch, 1.8*inch],
        header_color=BLUE,
    )

    story += [P("2.2  Regulatory & Enforcement Records", H2)]
    story += make_table(
        ["Record Type", "Fields Available", "Source"],
        [
            ["FTC Enforcement", "Respondent, charges, penalty amount, consent order terms, effective date",
             "FTC.gov"],
            ["SEC Litigation", "Defendant, charges, civil/criminal, penalty, disgorgement, injunction",
             "SEC.gov"],
            ["CFPB Action", "Company, violation type, consumer harm, restitution amount, compliance order",
             "CFPB.gov"],
            ["EEOC Charge", "Employer, protected class, charge type, settlement, consent decree terms",
             "EEOC.gov"],
            ["HUD Enforcement", "Respondent, fair housing violation, conciliation agreement, penalty",
             "HUD.gov"],
            ["DOJ Civil Rights", "Target entity, pattern/practice finding, consent decree, monitoring period",
             "Justice.gov"],
            ["Federal Register Rule", "Agency, rule title, docket ID, affected parties, comment period, effective date",
             "FederalRegister.gov"],
        ],
        col_widths=[1.5*inch, 3.4*inch, 1.8*inch],
        header_color=TEAL,
    )

    story += [P("2.3  Legislative Records", H2)]
    story += make_table(
        ["Record Type", "Fields Available", "Source"],
        [
            ["Federal Bill", "Bill number, title, sponsor, co-sponsors, committee, latest action, vote counts, full text link",
             "Congress.gov API"],
            ["State Bill", "Bill ID, state, sponsor, status, committee hearings, vote history",
             "OpenStates (available)"],
            ["Committee Hearing", "Date, committee, witnesses, topic, transcript link",
             "Congress.gov"],
            ["Floor Vote", "Vote date, outcome, member votes by party, roll call number",
             "Congress.gov / GovTrack"],
        ],
        col_widths=[1.5*inch, 3.4*inch, 1.8*inch],
        header_color=PURP,
    )

    # ══════════════════════════════════════════════════════════════════════════
    story.append(PageBreak())
    story += [P("Part 3 — Additional Sources Available for Integration", H1), hr(NAVY, 1.5)]

    story += [P("3.1  Bills & Legislation Tracking", H2)]
    story += make_table(
        ["Source", "Records Available", "Value for AI Fraud Cases", "Access"],
        [
            ["GovTrack", "Bill tracking, voting records, committee assignments, passage probability",
             "Track AI bills through Congress", "Free JSON API"],
            ["ProPublica Congress", "Full bill text, co-sponsors, vote history, committee hearings, lobbying data",
             "Follow AI lobbying and legislation", "Free API key"],
            ["OpenStates", "All 50 state legislatures — bills, votes, legislators, committees",
             "State AI legislation (biometric, deepfake, hiring laws)",
             "Free API"],
            ["LegiScan", "Real-time bill monitoring, all 50 states + Congress, keyword alerts",
             "Instant notification when AI fraud bills advance", "Free tier + paid"],
        ],
        col_widths=[1.3*inch, 2.3*inch, 2.0*inch, 1.1*inch],
        header_color=NAVY,
    )

    story += [P("3.2  Court Filing Records (PACER Level)", H2)]
    story += make_table(
        ["Source", "Records Available", "Note"],
        [
            ["PACER Direct", "Every federal filing: complaints, answers, motions, orders, judgments, transcripts — real-time",
             "PACER account required ($0.10/page)"],
            ["CMECF Alerts", "Instant email when any docket you follow receives a new filing",
             "PACER account required"],
            ["NY NYSCEF", "New York state court e-filings — civil, commercial, matrimonial",
             "Free public access"],
            ["CA eCourt", "California appellate + superior court filings and opinions",
             "Free public access"],
            ["TX eFileTexas", "Texas state court e-filings across all trial and appellate courts",
             "Free public access"],
        ],
        col_widths=[1.4*inch, 3.2*inch, 2.1*inch],
        header_color=BLUE,
    )

    story += [P("3.3  Financial & Regulatory Dockets", H2)]
    story += make_table(
        ["Source", "Records Available", "Value", "Access"],
        [
            ["Regulations.gov", "Full regulatory dockets with all public comments, agency responses, final rule documents",
             "See who is commenting on AI rules and why", "Free API"],
            ["SEC EDGAR", "10-K, 10-Q, 8-K filings — fraud disclosures, risk factors, material AI events",
             "AI fraud appears here before court cases are filed", "Free API"],
            ["FinCEN", "Financial crime reports, suspicious activity reports (limited public)",
             "AI-enabled financial fraud", "Partial"],
            ["OFAC Sanctions", "Sanctioned entities list — confirm if AI fraud actor is sanctioned",
             "Background checks on defendants", "Free"],
        ],
        col_widths=[1.3*inch, 2.5*inch, 1.7*inch, 1.2*inch],
        header_color=TEAL,
    )

    story += [P("3.4  Real-Time Monitoring", H2)]
    story += make_table(
        ["Source", "What It Monitors", "Status"],
        [
            ["CourtListener Alerts", "New cases filed matching your keywords — MCP already connected",
             "Ready to build — MCP connected"],
            ["PACER Email Alerts", "New filings on specific dockets the moment they are filed",
             "Needs PACER account"],
            ["GovTrack Alerts", "Bills with specific keywords advance in Congress",
             "Free — needs integration"],
            ["Federal Register", "New AI rules published today — already integrated",
             "Available — add cron schedule"],
            ["LegiScan Push", "Real-time push when any state AI bill receives a hearing or vote",
             "Needs LegiScan API key"],
        ],
        col_widths=[1.5*inch, 3.2*inch, 2.0*inch],
        header_color=PURP,
    )

    story += [P("3.5  International Sources", H2)]
    story += make_table(
        ["Source", "Coverage", "Relevance"],
        [
            ["EUR-Lex (EU)", "EU AI Act enforcement, GDPR cases, Digital Services Act actions",
             "Multinational AI fraud actors operating in EU"],
            ["UK ICO", "UK AI and data protection enforcement, fines, investigation decisions",
             "UK deepfake and AI fraud cases"],
            ["Canada OPC", "Canadian privacy and AI enforcement, PIPEDA complaints and orders",
             "Cross-border AI fraud cases"],
            ["OECD AI Policy", "Country-by-country AI policy tracker, regulatory frameworks",
             "Comparative law and jurisdiction analysis"],
        ],
        col_widths=[1.4*inch, 2.8*inch, 2.5*inch],
        header_color=colors.HexColor("#7a4f1e"),
    )

    # ══════════════════════════════════════════════════════════════════════════
    story.append(PageBreak())
    story += [P("Part 4 — Priority Integration Roadmap", H1), hr(NAVY, 1.5)]
    story.append(P(
        "The following sources are ranked by investigative value for AI fraud, "
        "civil rights cases, and consumer protection:"
    ))
    story.append(sp(6))

    def priority_block(label, color, items):
        # Label bar
        lbl = Table([[P(label, CELLH)]], colWidths=[W])
        lbl.setStyle(TableStyle([
            ("BACKGROUND",    (0,0),(-1,-1), color),
            ("TOPPADDING",    (0,0),(-1,-1), 6),
            ("BOTTOMPADDING", (0,0),(-1,-1), 6),
            ("LEFTPADDING",   (0,0),(-1,-1), 10),
        ]))
        elems = [lbl, sp(4)]
        for name, desc in items:
            elems.append(P(f"<b>{name}</b>", H3))
            elems.append(P(desc, BODY))
            elems.append(sp(2))
        elems.append(sp(8))
        return elems

    story += priority_block("▶  IMMEDIATE — Highest Impact", RED, [
        ("CourtListener Alert Subscriptions",
         "The MCP server is already connected. Wire it to auto-subscribe to new AI fraud "
         "case filings. Investigators are notified the moment a new matching case is filed "
         "anywhere in the federal court system."),
        ("SEC EDGAR API",
         "AI company fraud disclosures appear in 8-K filings before court cases are filed. "
         "This is the earliest warning signal available and integrates via a free REST API."),
        ("OpenStates — All 50 State Legislatures",
         "Covers biometric privacy laws (Illinois BIPA), deepfake laws, AI hiring laws. "
         "Every state AI law that could become an enforcement case starts here."),
    ])

    story += priority_block("▶  SHORT TERM — Strong Value", BLUE, [
        ("Regulations.gov Full Dockets",
         "Public comments on AI rules often name specific companies and document harms "
         "before formal enforcement. Rich investigative leads, free API."),
        ("PACER Direct Integration",
         "Full complaint text, not just metadata. Access actual allegations, exhibits, "
         "and evidence in AI fraud cases. Requires PACER account ($0.10/page)."),
        ("GovTrack + ProPublica Congress API",
         "Complete legislative picture — who is sponsoring AI bills, who is lobbying "
         "against them. Follow the money from bill introduction to passage."),
        ("LegiScan Real-Time Alerts",
         "Know within hours when any state AI fraud bill receives a committee hearing "
         "or floor vote across all 50 states."),
    ])

    story += priority_block("▶  LONGER TERM — Comprehensive Coverage", TEAL, [
        ("EU AI Act Enforcement (EUR-Lex)",
         "Multinational AI fraud cases often face EU enforcement in parallel. "
         "Defendants tracked here may also face substantial EU penalties."),
        ("FinCEN / OFAC Financial Records",
         "Financial crime and sanctions data — confirm whether AI fraud actors "
         "have prior financial crime history or are already sanctioned."),
        ("NY NYSCEF / CA eCourt / TX eFileTexas",
         "Most consumer class actions are filed in state courts, not federal. "
         "State court e-filing access closes the largest remaining gap in coverage."),
    ])

    # ── Summary Table ──────────────────────────────────────────────────────────
    story.append(PageBreak())
    story += [P("Summary — Complete Source Inventory", H1), hr(NAVY, 1.5)]
    story.append(sp(4))

    sum_rows = [
        ["Federal Courts",        "3 active",  "3 available",  "6+"],
        ["Federal Agencies",      "8 active",  "4 available",  "12+"],
        ["State Courts & AGs",    "51 AGs",    "50 eCourts",   "100+"],
        ["Legislative",           "Congress",  "GovTrack, OpenStates, LegiScan, ProPublica", "6+"],
        ["Legal News & Research", "5 active",  "4 available",  "9+"],
        ["International",         "0",         "4 available",  "4+"],
        ["Financial / Sanctions", "0",         "3 available",  "3+"],
        ["Real-Time Monitoring",  "Partial",   "PACER, GovTrack, LegiScan, FR", "5+"],
    ]

    tbl_data = [[P(h, CELLH) for h in ["Category", "Currently Active", "Available to Add", "Total Potential"]]]
    for row in sum_rows:
        tbl_data.append([P(row[0], CELLB), P(row[1], CELL), P(row[2], CELL), P(row[3], CELL)])
    # Totals row
    tbl_data.append([
        P("TOTAL", CELLB),
        P("~20 active sources", ps("t", fontName="Helvetica-Bold", fontSize=8.5, textColor=GOLD)),
        P("~27 additional available", ps("t2", fontName="Helvetica-Bold", fontSize=8.5, textColor=GOLD)),
        P("~47+", ps("t3", fontName="Helvetica-Bold", fontSize=8.5, textColor=GOLD)),
    ])

    stbl = Table(tbl_data, colWidths=[1.7*inch, 1.6*inch, 2.6*inch, 1.2*inch])
    stbl.setStyle(TableStyle([
        ("BACKGROUND",    (0, 0),  (-1, 0),  NAVY),
        ("BACKGROUND",    (0, -1), (-1, -1), NAVY),
        ("ROWBACKGROUNDS",(0, 1),  (-1, -2), [WHITE, LGRAY]),
        ("GRID",          (0, 0),  (-1, -1), 0.3, colors.HexColor("#ccd0e0")),
        ("TOPPADDING",    (0, 0),  (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0),  (-1, -1), 5),
        ("LEFTPADDING",   (0, 0),  (-1, -1), 6),
        ("RIGHTPADDING",  (0, 0),  (-1, -1), 6),
        ("VALIGN",        (0, 0),  (-1, -1), "TOP"),
    ]))
    story += [stbl, sp(20)]

    # Footer
    story += [
        hr(),
        sp(4),
        P(f"CONFIDENTIAL — LegalPerigee Data Sources Briefing · "
          f"Generated {datetime.now().strftime('%Y-%m-%d %H:%M')} · "
          "For internal investigative use only", FOOT),
    ]
    return story


# ── Page header/footer callbacks ──────────────────────────────────────────────

def _on_page(canvas, doc):
    """Draw a slim navy header bar + page number on every page after page 1."""
    canvas.saveState()
    page = doc.page

    if page > 1:
        # Slim top bar
        canvas.setFillColor(NAVY)
        canvas.rect(0, letter[1] - 0.38*inch, letter[0], 0.38*inch, fill=1, stroke=0)
        # Gold accent line
        canvas.setFillColor(GOLD)
        canvas.rect(0, letter[1] - 0.42*inch, letter[0], 0.04*inch, fill=1, stroke=0)
        # Logo (small)
        if os.path.exists(LOGO):
            canvas.drawImage(LOGO, 0.55*inch, letter[1] - 0.34*inch,
                             width=0.28*inch, height=0.28*inch,
                             preserveAspectRatio=True, mask="auto")
        # Title text
        canvas.setFillColor(WHITE)
        canvas.setFont("Helvetica-Bold", 8)
        canvas.drawString(0.9*inch, letter[1] - 0.24*inch, "LEGALPERIGEE")
        canvas.setFillColor(GOLD)
        canvas.setFont("Helvetica", 7.5)
        canvas.drawString(1.72*inch, letter[1] - 0.24*inch,
                          "Data Sources & Intelligence Briefing")

    # Footer — page number + confidential
    canvas.setFillColor(MGRAY)
    canvas.setFont("Helvetica", 7.5)
    canvas.drawString(0.8*inch, 0.4*inch, "CONFIDENTIAL — For internal investigative use only")
    canvas.drawRightString(letter[0] - 0.8*inch, 0.4*inch, f"Page {page}")
    # Footer rule
    canvas.setStrokeColor(colors.HexColor("#dde3ee"))
    canvas.setLineWidth(0.4)
    canvas.line(0.8*inch, 0.52*inch, letter[0] - 0.8*inch, 0.52*inch)

    canvas.restoreState()


# ── Build ─────────────────────────────────────────────────────────────────────
OUT = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                   "data", "LegalPerigee_Sources_Briefing.pdf")
os.makedirs(os.path.dirname(OUT), exist_ok=True)

doc = SimpleDocTemplate(
    OUT, pagesize=letter,
    leftMargin=0.8*inch,  rightMargin=0.8*inch,
    topMargin=0.55*inch,  bottomMargin=0.7*inch,
    title="LegalPerigee Data Sources Briefing",
    author="LegalPerigee",
)
doc.build(build(), onFirstPage=_on_page, onLaterPages=_on_page)
print(f"✅  PDF saved: {OUT}")
