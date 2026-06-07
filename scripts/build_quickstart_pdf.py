#!/usr/bin/env python3
"""
Generate LegalPerigee Quick Start Guide — printable PDF.
Run: python3 scripts/build_quickstart_pdf.py
Output: dist/LegalPerigee-QuickStart.pdf
"""

import sys
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table,
    TableStyle,
)

# ── Palette ───────────────────────────────────────────────────────────────────
NAVY       = colors.HexColor("#0f1b35")
NAVY_MID   = colors.HexColor("#1a3a6e")
NAVY_LIGHT = colors.HexColor("#2e4a8a")
BLUE_ACC   = colors.HexColor("#3d6fd4")
GOLD       = colors.HexColor("#c8a84b")
GOLD_LIGHT = colors.HexColor("#f0d080")
WHITE      = colors.white
GRAY_LIGHT = colors.HexColor("#e8eaf6")
GRAY_MID   = colors.HexColor("#6b82b8")
TEXT_DARK  = colors.HexColor("#1a1a2e")
GREEN      = colors.HexColor("#27ae60")
RED_SOFT   = colors.HexColor("#c0392b")

# ── Styles ────────────────────────────────────────────────────────────────────
styles = getSampleStyleSheet()

def S(name, **kw):
    return ParagraphStyle(name, **kw)

# Base
base = S("Base", fontName="Helvetica", fontSize=9, leading=13,
          textColor=TEXT_DARK, spaceAfter=4)

# Hero title
hero_title = S("HeroTitle", fontName="Helvetica-Bold", fontSize=26,
               textColor=WHITE, alignment=TA_CENTER, spaceAfter=4)
hero_sub = S("HeroSub", fontName="Helvetica", fontSize=11,
             textColor=GRAY_LIGHT, alignment=TA_CENTER, spaceAfter=2)
hero_version = S("HeroVersion", fontName="Helvetica", fontSize=8,
                 textColor=GRAY_MID, alignment=TA_CENTER)

# Section headers
sec_hdr = S("SecHdr", fontName="Helvetica-Bold", fontSize=11,
            textColor=NAVY, spaceBefore=14, spaceAfter=4,
            borderPad=0)
step_num = S("StepNum", fontName="Helvetica-Bold", fontSize=22,
             textColor=BLUE_ACC, alignment=TA_CENTER)
step_title = S("StepTitle", fontName="Helvetica-Bold", fontSize=11,
               textColor=NAVY)
step_body = S("StepBody", fontName="Helvetica", fontSize=9,
              leading=13, textColor=TEXT_DARK, spaceAfter=2)
step_note = S("StepNote", fontName="Helvetica-Oblique", fontSize=8,
              textColor=GRAY_MID, spaceAfter=2)

# Feature card
feat_title = S("FeatTitle", fontName="Helvetica-Bold", fontSize=10,
               textColor=NAVY)
feat_body = S("FeatBody", fontName="Helvetica", fontSize=8.5,
              leading=12.5, textColor=TEXT_DARK)
feat_tag = S("FeatTag", fontName="Helvetica-Bold", fontSize=7.5,
             textColor=GREEN)
feat_tag_ai = S("FeatTagAI", fontName="Helvetica-Bold", fontSize=7.5,
                textColor=BLUE_ACC)

tip_body = S("TipBody", fontName="Helvetica", fontSize=8.5,
             leading=12.5, textColor=TEXT_DARK)
tip_label = S("TipLabel", fontName="Helvetica-Bold", fontSize=8.5,
              textColor=NAVY_LIGHT)

footer_s = S("Footer", fontName="Helvetica", fontSize=7.5,
             textColor=GRAY_MID, alignment=TA_CENTER)

# ── Helper: divider line ──────────────────────────────────────────────────────
def divider(color=GRAY_LIGHT, thickness=0.5, spaceB=4, spaceA=4):
    return HRFlowable(width="100%", thickness=thickness, color=color,
                      spaceBefore=spaceB, spaceAfter=spaceA)

def sp(h=6):
    return Spacer(1, h)

# ── Page dimensions ───────────────────────────────────────────────────────────
W, H = letter          # 8.5 × 11 in
MARGIN = 0.55 * inch
COL_W = (W - 2 * MARGIN)

# ── Hero header (dark navy banner) ───────────────────────────────────────────
def hero_block():
    """Returns a full-width dark navy header table."""
    inner = [
        [Paragraph("⚖️  LegalPerigee", hero_title)],
        [Paragraph("Full-Spectrum Legal Case Intelligence Platform", hero_sub)],
        [Paragraph("Quick Start Guide  ·  v1.1", hero_version)],
    ]
    t = Table([[Table(inner, colWidths=[COL_W - 0.4*inch],
                      style=TableStyle([
                          ("ALIGN",    (0,0), (-1,-1), "CENTER"),
                          ("VALIGN",   (0,0), (-1,-1), "MIDDLE"),
                          ("LEFTPADDING",  (0,0), (-1,-1), 0),
                          ("RIGHTPADDING", (0,0), (-1,-1), 0),
                          ("TOPPADDING",   (0,0), (-1,-1), 6),
                          ("BOTTOMPADDING",(0,0), (-1,-1), 6),
                      ]))
              ]],
             colWidths=[COL_W])
    t.setStyle(TableStyle([
        ("BACKGROUND",    (0,0), (-1,-1), NAVY),
        ("ROUNDEDCORNERS",(0,0), (-1,-1), [6,6,6,6]),
        ("LEFTPADDING",   (0,0), (-1,-1), 16),
        ("RIGHTPADDING",  (0,0), (-1,-1), 16),
        ("TOPPADDING",    (0,0), (-1,-1), 18),
        ("BOTTOMPADDING", (0,0), (-1,-1), 18),
    ]))
    return t

# ── "Works without key" callout ───────────────────────────────────────────────
def free_callout():
    left = [
        [Paragraph("✅  No Account Required to Start", S("FreeHdr",
            fontName="Helvetica-Bold", fontSize=9, textColor=GREEN))],
        [Paragraph(
            "Case Library · Document Viewer · Alerts · "
            "Legislative Trends · Precedent Search "
            "<font color='#6b82b8'>all work immediately — no login, no API key.</font>",
            S("FreeTxt", fontName="Helvetica", fontSize=8.5,
              leading=12, textColor=TEXT_DARK)
        )],
    ]
    right = [
        [Paragraph("🔑  To Unlock AI Features", S("FreeHdr2",
            fontName="Helvetica-Bold", fontSize=9, textColor=BLUE_ACC))],
        [Paragraph(
            "Get a free key at <font color='#3d6fd4'>console.anthropic.com</font> "
            "→ enter in the sidebar → AI Investigation, AI Analysis &amp; "
            "Media Forensics activate instantly.",
            S("FreeTxt2", fontName="Helvetica", fontSize=8.5,
              leading=12, textColor=TEXT_DARK)
        )],
    ]
    tl = Table(left,  colWidths=[(COL_W/2)-8])
    tr = Table(right, colWidths=[(COL_W/2)-8])
    tl.setStyle(TableStyle([
        ("LEFTPADDING",  (0,0),(-1,-1), 8),
        ("RIGHTPADDING", (0,0),(-1,-1), 8),
        ("TOPPADDING",   (0,0),(-1,-1), 6),
        ("BOTTOMPADDING",(0,0),(-1,-1), 6),
    ]))
    tr.setStyle(TableStyle([
        ("LEFTPADDING",  (0,0),(-1,-1), 8),
        ("RIGHTPADDING", (0,0),(-1,-1), 8),
        ("TOPPADDING",   (0,0),(-1,-1), 6),
        ("BOTTOMPADDING",(0,0),(-1,-1), 6),
    ]))
    outer = Table([[tl, tr]], colWidths=[COL_W/2, COL_W/2])
    outer.setStyle(TableStyle([
        ("BACKGROUND",  (0,0),(0,0), colors.HexColor("#e8f5e9")),
        ("BACKGROUND",  (1,0),(1,0), colors.HexColor("#e8edf8")),
        ("ROUNDEDCORNERS",(0,0),(-1,-1),[4,4,4,4]),
        ("LINEABOVE",   (0,0),(-1,-1), 1.5, GREEN),
        ("LINEABOVE",   (1,0),(1,-1),  1.5, BLUE_ACC),
        ("LEFTPADDING",  (0,0),(-1,-1), 0),
        ("RIGHTPADDING", (0,0),(-1,-1), 0),
        ("TOPPADDING",   (0,0),(-1,-1), 0),
        ("BOTTOMPADDING",(0,0),(-1,-1), 0),
    ]))
    return outer

# ── 3-step install guide ──────────────────────────────────────────────────────
def three_steps():
    steps = [
        ("1", "Install",
         "macOS: Open LegalPerigee-1.1-mac.dmg, drag ⚖️ LegalPerigee to Applications.",
         "Windows: Unzip LegalPerigee-1.1-windows.zip, right-click setup.ps1 → "
         "Run with PowerShell. A Desktop shortcut is created automatically.",
         "First launch takes ~2 minutes to set up the Python environment. "
         "Subsequent launches open in under 5 seconds."),
        ("2", "Open the App",
         "Double-click ⚖️ LegalPerigee. A dark splash screen appears immediately "
         "while the app finishes loading in the background.",
         "The app opens to the Case Library tab. All free features are available "
         "right away — no setup required.",
         "macOS: if prompted, go to System Settings → Privacy & Security → Open Anyway."),
        ("3", "Add API Key (Optional)",
         "To unlock AI Investigation, AI Analysis, and Media Forensics:",
         "1. Get a free key at console.anthropic.com → API Keys\n"
         "2. In the app sidebar, click 🔑 Add Key\n"
         "3. Paste your key and press Enter\n"
         "4. The key is saved to macOS Keychain — never stored in any file.",
         "The key persists across restarts. You only enter it once."),
    ]
    rows = []
    for num, title, line1, line2, note in steps:
        num_cell = Paragraph(num, S("Num", fontName="Helvetica-Bold",
            fontSize=28, textColor=BLUE_ACC, alignment=TA_CENTER))
        title_p = Paragraph(title, S("STitle", fontName="Helvetica-Bold",
            fontSize=10.5, textColor=NAVY, spaceAfter=4))
        body_p = Paragraph(
            line1 + "<br/><br/>" + line2,
            S("SBody", fontName="Helvetica", fontSize=8.5, leading=13,
              textColor=TEXT_DARK, spaceAfter=3)
        )
        note_p = Paragraph(
            "💡 " + note,
            S("SNote", fontName="Helvetica-Oblique", fontSize=8,
              leading=12, textColor=GRAY_MID)
        )
        content = Table(
            [[title_p], [body_p], [note_p]],
            colWidths=[COL_W - 0.7*inch - 12]
        )
        content.setStyle(TableStyle([
            ("LEFTPADDING",  (0,0),(-1,-1), 0),
            ("RIGHTPADDING", (0,0),(-1,-1), 0),
            ("TOPPADDING",   (0,0),(-1,-1), 2),
            ("BOTTOMPADDING",(0,0),(-1,-1), 2),
        ]))
        rows.append([num_cell, content])

    t = Table(rows, colWidths=[0.55*inch, COL_W - 0.55*inch])
    t.setStyle(TableStyle([
        ("VALIGN",       (0,0),(-1,-1), "TOP"),
        ("LEFTPADDING",  (0,0),(0,-1),  0),
        ("RIGHTPADDING", (0,0),(0,-1),  0),
        ("LEFTPADDING",  (1,0),(1,-1),  10),
        ("TOPPADDING",   (0,0),(-1,-1), 6),
        ("BOTTOMPADDING",(0,0),(-1,-1), 6),
        ("LINEBELOW",    (0,0),(-1,-2), 0.5, GRAY_LIGHT),
    ]))
    return t

# ── Feature reference grid ────────────────────────────────────────────────────
FEATURES = [
    {
        "icon": "🔍",
        "tab": "Investigate",
        "tag": "AI",
        "tagstyle": "ai",
        "title": "AI Investigation Agent",
        "body": (
            "Describe any legal matter in plain English — fraud, discrimination, "
            "civil rights, securities, criminal — and the AI runs a multi-source "
            "investigation across federal courts, regulatory agencies, and the web."
        ),
        "use": "Use when: You need a fast landscape of existing cases and enforcement actions on an unfamiliar legal matter.",
    },
    {
        "icon": "📚",
        "tab": "Case Library",
        "tag": "FREE",
        "tagstyle": "free",
        "title": "Case Library — 20+ Sources",
        "body": (
            "Browse and search 1,400+ indexed cases from CourtListener, SCOTUS, "
            "EEOC, FTC, SEC, all 50 state courts, Congress.gov, and more. "
            "Use Sync Manager to pull fresh cases on demand."
        ),
        "use": "Use when: You want to search specific courts, agencies, or date ranges without running a full AI investigation.",
    },
    {
        "icon": "📊",
        "tab": "Legislative Watch",
        "tag": "FREE + AI",
        "tagstyle": "both",
        "title": "Legislative Watch",
        "body": (
            "Tracks bills across all 50 state legislatures and Congress in real time. "
            "Detects multi-state legislative waves, federal pre-emption threats, "
            "and fast-advancing bills. AI can analyze any bill's legal implications."
        ),
        "use": "Use when: A client is in an industry facing new regulation, or you need to track opposing-interest legislation.",
    },
    {
        "icon": "⚖️",
        "tab": "Precedent",
        "tag": "FREE + AI",
        "tagstyle": "both",
        "title": "Precedent Research Engine",
        "body": (
            "Describe your legal situation and the AI identifies controlling precedents, "
            "landmark cases, and how the law has evolved over time. "
            "Direct CourtListener and Harvard CAP search also available without AI."
        ),
        "use": "Use when: Building case arguments, researching circuit splits, or tracing the evolution of a legal doctrine.",
    },
    {
        "icon": "🕵️",
        "tab": "Media Forensics",
        "tag": "AI",
        "tagstyle": "ai",
        "title": "Media Forensics — AI Manipulation Detector",
        "body": (
            "Upload images (JPG, PNG, HEIC/iPhone, TIFF), video clips, or text documents. "
            "Claude Vision analyzes for deepfakes, face swaps, AI-generated text, "
            "metadata tampering, GAN artifacts, and clone stamps."
        ),
        "use": "Use when: Authenticating evidence — photos, video, documents — before relying on them in proceedings.",
    },
    {
        "icon": "🔔",
        "tab": "Alerts",
        "tag": "FREE",
        "tagstyle": "free",
        "title": "Real-Time Alerts",
        "body": (
            "Create keyword-based monitoring rules with court, state, and topic filters. "
            "New matching cases trigger email alerts automatically. "
            "Integrates with CourtListener's real-time docket tracking."
        ),
        "use": "Use when: You need to monitor ongoing litigation, track a client's adversary, or watch an active docket.",
    },
    {
        "icon": "📄",
        "tab": "Document Viewer",
        "tag": "FREE",
        "tagstyle": "free",
        "title": "Document Viewer",
        "body": (
            "Open PDF, DOCX, XLSX, PPTX, images, JSON, and plain text "
            "inside the app. One-click Open in native app (Preview, Word, Excel) "
            "or Print via browser with professional print formatting."
        ),
        "use": "Use when: Reviewing case documents, evidence files, or exported reports without leaving the platform.",
    },
    {
        "icon": "📤",
        "tab": "Any tab",
        "tag": "FREE",
        "tagstyle": "free",
        "title": "Export — PDF & Word Reports",
        "body": (
            "Export any investigation as a formatted PDF report (court-ready letterhead "
            "style) or a Word document for further editing. "
            "Reports include case summaries, source citations, and investigator notes."
        ),
        "use": "Use when: Delivering research to clients, preparing litigation support memos, or archiving findings.",
    },
]

TAG_COLORS = {
    "free": (colors.HexColor("#e8f5e9"), GREEN),
    "ai":   (colors.HexColor("#e8edf8"), BLUE_ACC),
    "both": (colors.HexColor("#fef9e7"), colors.HexColor("#b7860b")),
}

def feature_card(f):
    bg, tc = TAG_COLORS[f["tagstyle"]]
    tag_p = Paragraph(
        f"{'✅' if f['tagstyle']=='free' else '🔑' if f['tagstyle']=='ai' else '✅🔑'}  {f['tag']}",
        S("Tag_"+f["tagstyle"], fontName="Helvetica-Bold", fontSize=7,
          textColor=tc, alignment=TA_RIGHT)
    )
    icon_tab = Paragraph(
        f"<font size='16'>{f['icon']}</font>  <b>{f['title']}</b>",
        S("FTitle", fontName="Helvetica-Bold", fontSize=9.5, textColor=NAVY,
          spaceAfter=3)
    )
    body_p = Paragraph(f['body'],
        S("FBody", fontName="Helvetica", fontSize=8.5, leading=12.5,
          textColor=TEXT_DARK, spaceAfter=3)
    )
    use_p = Paragraph(
        f"<i>{f['use']}</i>",
        S("FUse", fontName="Helvetica-Oblique", fontSize=8, leading=12,
          textColor=GRAY_MID)
    )
    tab_p = Paragraph(
        f"Tab: <b>{f['tab']}</b>",
        S("FTab", fontName="Helvetica", fontSize=7.5, textColor=GRAY_MID,
          spaceAfter=2)
    )
    inner = Table(
        [[tag_p], [icon_tab], [body_p], [use_p], [tab_p]],
        colWidths=[(COL_W / 2) - 14]
    )
    inner.setStyle(TableStyle([
        ("LEFTPADDING",  (0,0),(-1,-1), 0),
        ("RIGHTPADDING", (0,0),(-1,-1), 0),
        ("TOPPADDING",   (0,0),(-1,-1), 2),
        ("BOTTOMPADDING",(0,0),(-1,-1), 2),
    ]))
    outer = Table([[inner]], colWidths=[(COL_W / 2) - 6])
    outer.setStyle(TableStyle([
        ("BACKGROUND",   (0,0),(-1,-1), colors.HexColor("#f5f7fc")),
        ("LINEABOVE",    (0,0),(-1,-1), 2.5, tc),
        ("LEFTPADDING",  (0,0),(-1,-1), 10),
        ("RIGHTPADDING", (0,0),(-1,-1), 10),
        ("TOPPADDING",   (0,0),(-1,-1), 8),
        ("BOTTOMPADDING",(0,0),(-1,-1), 8),
    ]))
    return outer

def feature_grid():
    cards = [feature_card(f) for f in FEATURES]
    # 2-column grid
    rows = []
    for i in range(0, len(cards), 2):
        row = [cards[i], cards[i+1] if i+1 < len(cards) else Paragraph("", base)]
        rows.append(row)
    t = Table(rows, colWidths=[COL_W/2, COL_W/2], spaceBefore=4)
    t.setStyle(TableStyle([
        ("LEFTPADDING",  (0,0),(-1,-1), 0),
        ("RIGHTPADDING", (0,0),(-1,-1), 6),
        ("TOPPADDING",   (0,0),(-1,-1), 4),
        ("BOTTOMPADDING",(0,0),(-1,-1), 4),
        ("VALIGN",       (0,0),(-1,-1), "TOP"),
    ]))
    return t

# ── Tips & key info table ─────────────────────────────────────────────────────
TIPS = [
    ("Query tips",
     "Write queries in plain English. "
     "'Excessive force lawsuits against Chicago PD 2020–2024' works better than 'police use of force.'  "
     "Include party names, statutes, agencies, or dollar amounts when you have them."),
    ("Sync before you search",
     "First time using Case Library? Run a sync (Library → Sync Manager → Run Selected Syncs). "
     "CourtListener and Harvard CAP alone cover 6.7 million cases."),
    ("Alerts save hours",
     "Set up an alert for a client's adversary or an active case name. "
     "You'll get email notification the moment a new filing matches — no manual checking."),
    ("Evidence authentication",
     "Before relying on a photo or video in proceedings, run it through Media Forensics first. "
     "The AI checks 12+ deepfake indicators including EXIF metadata and GAN artifacts."),
    ("Export for the file",
     "Every investigation can be exported as a PDF memo or Word document. "
     "Use File → Export after any investigation for a citation-ready research document."),
    ("API keys are optional",
     "CourtListener, Congress.gov, OpenStates, and Regulations.gov all provide "
     "higher rate limits with free API keys (no credit card). "
     "Add them in the sidebar under 🗝️ Integration Keys."),
]

def tips_table():
    rows = [[
        Paragraph(label, S("TL", fontName="Helvetica-Bold", fontSize=8.5,
                            textColor=NAVY_LIGHT)),
        Paragraph(body, S("TB", fontName="Helvetica", fontSize=8.5,
                           leading=12.5, textColor=TEXT_DARK)),
    ] for label, body in TIPS]
    t = Table(rows, colWidths=[1.15*inch, COL_W - 1.15*inch])
    t.setStyle(TableStyle([
        ("VALIGN",       (0,0),(-1,-1), "TOP"),
        ("LEFTPADDING",  (0,0),(0,-1),  0),
        ("RIGHTPADDING", (0,0),(0,-1),  8),
        ("LEFTPADDING",  (1,0),(1,-1),  8),
        ("TOPPADDING",   (0,0),(-1,-1), 5),
        ("BOTTOMPADDING",(0,0),(-1,-1), 5),
        ("LINEBELOW",    (0,0),(-1,-2), 0.5, GRAY_LIGHT),
        ("BACKGROUND",   (0,0),(0,-1),  colors.HexColor("#f0f3fb")),
    ]))
    return t

# ── Build document ────────────────────────────────────────────────────────────
def build():
    out = Path(__file__).parent.parent / "dist" / "LegalPerigee-QuickStart.pdf"
    out.parent.mkdir(exist_ok=True)

    doc = SimpleDocTemplate(
        str(out),
        pagesize=letter,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=0.45*inch,
        bottomMargin=0.45*inch,
        title="LegalPerigee Quick Start Guide",
        author="LegalPerigee",
        subject="Legal Case Intelligence Platform — Quick Reference",
    )

    story = []

    # ── PAGE 1 ──────────────────────────────────────────────────────────────
    story.append(hero_block())
    story.append(sp(10))
    story.append(free_callout())
    story.append(sp(10))
    story.append(divider(NAVY_LIGHT, 1))

    story.append(Paragraph("Getting Started — 3 Steps", S("SH",
        fontName="Helvetica-Bold", fontSize=11, textColor=NAVY,
        spaceBefore=8, spaceAfter=6)))
    story.append(three_steps())
    story.append(sp(8))
    story.append(divider(NAVY_LIGHT, 1))

    story.append(Paragraph("Feature Reference", S("SH2",
        fontName="Helvetica-Bold", fontSize=11, textColor=NAVY,
        spaceBefore=8, spaceAfter=6)))

    # Legend
    legend_items = [
        ("✅ FREE", "Works without any API key", colors.HexColor("#e8f5e9"), GREEN),
        ("🔑 AI", "Requires Anthropic API key (free)", colors.HexColor("#e8edf8"), BLUE_ACC),
        ("✅🔑 FREE + AI", "Free features + optional AI enhancement", colors.HexColor("#fef9e7"), colors.HexColor("#b7860b")),
    ]
    leg_cells = []
    for sym, desc, bg, tc in legend_items:
        cell = Table([[
            Paragraph(sym,  S("LS", fontName="Helvetica-Bold", fontSize=7.5, textColor=tc)),
            Paragraph(desc, S("LD", fontName="Helvetica", fontSize=7.5, textColor=TEXT_DARK)),
        ]], colWidths=[0.85*inch, (COL_W/3) - 0.85*inch - 8])
        cell.setStyle(TableStyle([
            ("BACKGROUND",  (0,0),(-1,-1), bg),
            ("LEFTPADDING", (0,0),(-1,-1), 6),
            ("RIGHTPADDING",(0,0),(-1,-1), 6),
            ("TOPPADDING",  (0,0),(-1,-1), 4),
            ("BOTTOMPADDING",(0,0),(-1,-1), 4),
            ("VALIGN",      (0,0),(-1,-1), "MIDDLE"),
        ]))
        leg_cells.append(cell)
    leg = Table([leg_cells], colWidths=[COL_W/3]*3)
    leg.setStyle(TableStyle([
        ("LEFTPADDING",  (0,0),(-1,-1), 0),
        ("RIGHTPADDING", (0,0),(-1,-1), 4),
        ("TOPPADDING",   (0,0),(-1,-1), 0),
        ("BOTTOMPADDING",(0,0),(-1,-1), 6),
    ]))
    story.append(leg)
    story.append(feature_grid())

    # ── PAGE 2 ──────────────────────────────────────────────────────────────
    story.append(PageBreak())
    story.append(hero_block())
    story.append(sp(10))
    story.append(divider(NAVY_LIGHT, 1))

    story.append(Paragraph("Tips for Best Results", S("SH3",
        fontName="Helvetica-Bold", fontSize=11, textColor=NAVY,
        spaceBefore=8, spaceAfter=6)))
    story.append(tips_table())
    story.append(sp(10))
    story.append(divider(NAVY_LIGHT, 1))

    # ── Data sources callout ──────────────────────────────────────────────
    story.append(Paragraph("Data Sources Included", S("SH4",
        fontName="Helvetica-Bold", fontSize=11, textColor=NAVY,
        spaceBefore=8, spaceAfter=6)))

    sources = [
        ("Federal Courts",    "CourtListener (all circuits + PACER) · Harvard Caselaw (6.7M cases) · SCOTUS opinions"),
        ("Regulatory",        "FTC · SEC · CFPB · EEOC · HUD · DOJ Civil Rights · OFAC Sanctions"),
        ("Legislative",       "Congress.gov · OpenStates (50 states) · GovTrack · Federal Register · Regulations.gov"),
        ("State Courts",      "All 50 state AG opinions · NY NYSCEF · CA eCourt · State appellate courts"),
        ("International",     "EUR-Lex (EU) · UK ICO Decisions · Canada OPC Privacy Rulings"),
        ("News & Analysis",   "Legal news aggregator · Law360 · Reuters Legal"),
    ]
    src_rows = [[
        Paragraph(label, S("SrcL", fontName="Helvetica-Bold", fontSize=8.5,
                            textColor=NAVY_LIGHT)),
        Paragraph(content, S("SrcC", fontName="Helvetica", fontSize=8.5,
                              leading=12.5, textColor=TEXT_DARK)),
    ] for label, content in sources]
    src_t = Table(src_rows, colWidths=[1.1*inch, COL_W - 1.1*inch])
    src_t.setStyle(TableStyle([
        ("VALIGN",       (0,0),(-1,-1), "TOP"),
        ("LEFTPADDING",  (0,0),(0,-1),  0),
        ("RIGHTPADDING", (0,0),(0,-1),  8),
        ("LEFTPADDING",  (1,0),(1,-1),  8),
        ("TOPPADDING",   (0,0),(-1,-1), 5),
        ("BOTTOMPADDING",(0,0),(-1,-1), 5),
        ("LINEBELOW",    (0,0),(-1,-2), 0.5, GRAY_LIGHT),
        ("BACKGROUND",   (0,0),(0,-1),  colors.HexColor("#f0f3fb")),
    ]))
    story.append(src_t)
    story.append(sp(10))
    story.append(divider(NAVY_LIGHT, 1))

    # ── Security note ──────────────────────────────────────────────────────
    sec_note = Table([[
        Paragraph(
            "🔐  <b>Security &amp; Privacy</b>  —  All API keys are stored in macOS Keychain / "
            "Windows Credential Manager. Keys are never written to files, logs, or source code. "
            "The app runs entirely on your local machine — no case data or queries are sent to "
            "any server except the APIs you explicitly configure (CourtListener, Anthropic, etc.).",
            S("SecN", fontName="Helvetica", fontSize=8.5, leading=13, textColor=TEXT_DARK)
        )
    ]], colWidths=[COL_W])
    sec_note.setStyle(TableStyle([
        ("BACKGROUND",   (0,0),(-1,-1), colors.HexColor("#f0f3fb")),
        ("LINEABOVE",    (0,0),(-1,-1), 2, NAVY_LIGHT),
        ("LEFTPADDING",  (0,0),(-1,-1), 12),
        ("RIGHTPADDING", (0,0),(-1,-1), 12),
        ("TOPPADDING",   (0,0),(-1,-1), 10),
        ("BOTTOMPADDING",(0,0),(-1,-1), 10),
    ]))
    story.append(sec_note)
    story.append(sp(10))

    # ── Footer ──────────────────────────────────────────────────────────────
    story.append(Paragraph(
        "⚖️  LegalPerigee v1.1  ·  Ethical · Analytical · Evidence-Based Legal Intelligence  ·  "
        "Results provide investigative leads — obtain certified analysis for legal proceedings.",
        S("Foot", fontName="Helvetica", fontSize=7.5, textColor=GRAY_MID, alignment=TA_CENTER)
    ))

    doc.build(story)
    print(f"✅  PDF written → {out}  ({out.stat().st_size // 1024} KB)")
    return out

if __name__ == "__main__":
    build()
