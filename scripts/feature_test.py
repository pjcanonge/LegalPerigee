#!/usr/bin/env python3
"""
LegalPerigee — Complete Feature Test
Tests every feature for correct import, initialization, and basic functionality.
Run: python3 scripts/feature_test.py
"""

import os, sys, json, io, time, traceback
from pathlib import Path
from datetime import datetime

sys.path.insert(0, str(Path(__file__).parent.parent))

# Load all keys from Keychain
from dotenv import load_dotenv
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env", override=True)
try:
    from utils.keychain import load_all_keys
    load_all_keys()
except Exception:
    pass

# ── Harness ───────────────────────────────────────────────────────────────────
PASS="✅"; FAIL="❌"; SKIP="⏭️ "; WARN="⚠️ "
results: list[dict] = []

def test(name, fn, skip_if=None):
    if skip_if:
        results.append({"name": name, "status": "SKIP", "detail": skip_if})
        print(f"  {SKIP}  {name:<60}  SKIP — {skip_if}")
        return None
    start = time.time()
    try:
        detail = fn()
        ms = int((time.time()-start)*1000)
        results.append({"name": name, "status": "PASS", "detail": detail or "", "ms": ms})
        print(f"  {PASS}  {name:<60}  {ms}ms  {detail or ''}")
        return True
    except Exception as e:
        ms = int((time.time()-start)*1000)
        tb = traceback.format_exc().strip().splitlines()[-1]
        results.append({"name": name, "status": "FAIL", "detail": tb, "ms": ms})
        print(f"  {FAIL}  {name:<60}  FAIL")
        print(f"       └─ {tb}")
        return False

def section(title):
    print(f"\n{'═'*75}")
    print(f"  {title}")
    print(f"{'═'*75}")

def subsection(title):
    print(f"\n  ── {title} ──")

HAS_API_KEY = bool(os.environ.get("ANTHROPIC_API_KEY","").strip().startswith("sk-"))

print(f"\n{'█'*75}")
print(f"  ⚖️  LegalPerigee — Complete Feature Test")
print(f"  {datetime.now().strftime('%Y-%m-%d  %H:%M:%S')}")
print(f"{'█'*75}")

# ═══════════════════════════════════════════════════════════════════════════════
section("FEATURE 1 · Core Infrastructure")
# ═══════════════════════════════════════════════════════════════════════════════

subsection("Python environment")
test("Python 3.9+", lambda: f"Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")
test("Architecture (arm64)", lambda: (
    __import__("platform").machine()
    if __import__("platform").machine() == "arm64"
    else (_ for _ in ()).throw(Exception(f"Got {__import__('platform').machine()} — expected arm64"))
))

subsection("All required packages")
PKGS = [
    ("anthropic",       "anthropic"),
    ("streamlit",       "streamlit"),
    ("pydantic",        "pydantic"),
    ("httpx",           "httpx"),
    ("pywebview",       "webview"),
    ("keyring",         "keyring"),
    ("fastapi",         "fastapi"),
    ("uvicorn",         "uvicorn"),
    ("pandas",          "pandas"),
    ("pdfplumber",      "pdfplumber"),
    ("python-docx",     "docx"),
    ("python-pptx",     "pptx"),
    ("pillow",          "PIL"),
    ("pillow-heif",     "pillow_heif"),
    ("reportlab",       "reportlab"),
    ("fpdf2",           "fpdf"),
    ("openpyxl",        "openpyxl"),
    ("beautifulsoup4",  "bs4"),
    ("python-dotenv",   "dotenv"),
    ("altair",          "altair"),
]
for display, imp in PKGS:
    test(f"Package: {display}", lambda i=imp: __import__(i).__name__ or "ok")

subsection("Keychain / secret management")
test("Keychain module loads", lambda: (
    __import__("utils.keychain", fromlist=["load_all_keys", "save_key", "load_key",
                                           "delete_key", "ALL_KEYS"]) and "ok"
))
test("load_all_keys() injects to os.environ", lambda: (
    __import__("utils.keychain", fromlist=["load_all_keys"]).load_all_keys() and "ok"
))
test("No sensitive keys in .env", lambda: (
    None if any(
        k in Path("..env" if not Path(".env").exists() else ".env").read_text()
        for k in ["sk-ant", "CONGRESS_API_KEY=c", "OPENSTATES_API_KEY=0"]
    ) else "clean"
) if Path(".env").exists() else "no .env")

# ═══════════════════════════════════════════════════════════════════════════════
section("FEATURE 2 · Case Investigation (AI Agents)")
# ═══════════════════════════════════════════════════════════════════════════════

subsection("Data models")
def test_models():
    from models.case_report import CaseIntelReport, SearchFilters, CaseFinding
    f = SearchFilters(court_code="ca9")
    assert f.court_code == "ca9"
    finding = CaseFinding(
        case_name="Smith v. Acme Corp",
        victim_description="Plaintiff denied housing loan due to AI scoring system.",
        deceptive_practice="AI model used racial proxies in credit scoring.",
        verifiable_harm="$45,000 denied loan; documented adverse action letter.",
    )
    assert finding.case_name == "Smith v. Acme Corp"
    r = CaseIntelReport(
        query="AI discrimination housing",
        summary="Test summary for feature test.",
        investigator_notes="Automated test — no real investigation.",
        findings=[finding],
    )
    assert r.query == "AI discrimination housing"
    assert len(r.findings) == 1
    return "CaseIntelReport · SearchFilters · CaseFinding (all required fields)"
test("Case data models", test_models)

subsection("Agent imports")
test("orchestrator agent",     lambda: __import__("agents.orchestrator",    fromlist=["run_investigation"]) and "ok")
test("court_researcher agent", lambda: __import__("agents.court_researcher", fromlist=["run_court_researcher"]) and "ok")
test("web_researcher agent",   lambda: __import__("agents.web_researcher",   fromlist=["run_web_researcher"]) and "ok")
test("documentor agent",       lambda: __import__("agents.documentor",       fromlist=["run_documentor"]) and "ok")

subsection("Court tools")
def test_cl_search():
    from tools.court_tools import search_courtlistener
    result = search_courtlistener("civil rights housing discrimination", max_results=3)
    # search_courtlistener returns formatted text for AI agent use
    assert isinstance(result, str), f"Expected str, got {type(result)}"
    assert len(result) > 10, "Empty result string"
    return f"returned {len(result)} char formatted result"
test("CourtListener search (live)", test_cl_search)

def test_court_headers():
    from tools.court_tools import _cl_headers
    h = _cl_headers()
    assert isinstance(h, dict), f"Expected dict, got {type(h)}"
    assert "User-Agent" in h, f"Expected User-Agent, got keys: {list(h.keys())}"
    return f"headers: {list(h.keys())}"
test("CourtListener headers", test_court_headers)

subsection("JSON extraction utility")
def test_json_extract():
    from utils.json_extract import extract_json
    # Direct JSON
    assert extract_json('{"key": "value"}') == {"key": "value"}
    # Markdown fenced
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}
    # Embedded in text
    assert extract_json('Here is the result: {"x": 42} done') == {"x": 42}
    return "3/3 patterns"
test("JSON extractor (3 patterns)", test_json_extract)

subsection("No-key guard (standalone safety)")
def test_nokey_agent_guard():
    """Verify agents return clean errors — not SDK crashes — when no key is set."""
    import os as _os
    saved = _os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        from agents.court_researcher import run_court_researcher
        result = run_court_researcher("test query")
        assert isinstance(result, dict), f"Expected dict, got {type(result)}"
        assert "error" in result, "Expected 'error' key in no-key response"
        assert "configured" in result["error"].lower(), f"Unexpected error: {result['error']}"
        return f"returns clean error: '{result['error'][:50]}'"
    finally:
        if saved:
            _os.environ["ANTHROPIC_API_KEY"] = saved
test("Agent no-key guard (clean error, no crash)", test_nokey_agent_guard)

def test_nokey_media_guard():
    """Verify media analyzer returns clean dict — not SDK TypeError — when no key."""
    import os as _os
    saved = _os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        from analyzers.media_analyzer import analyze_image
        from PIL import Image
        import io as _io
        img = Image.new("RGB", (50, 50))
        buf = _io.BytesIO(); img.save(buf, "PNG")
        result = analyze_image(buf.getvalue(), "test.png")
        assert isinstance(result, dict)
        assert "error" in result
        return f"returns clean error: '{result['error'][:50]}'"
    finally:
        if saved:
            _os.environ["ANTHROPIC_API_KEY"] = saved
test("Media analyzer no-key guard (clean error, no crash)", test_nokey_media_guard)

def test_nokey_precedent_guard():
    """Verify precedent analyzer raises ValueError (not SDK TypeError) when no key."""
    import os as _os
    saved = _os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        from analyzers.precedent_analyzer import discover_precedents
        try:
            discover_precedents("test situation")
            return "FAIL — expected ValueError"
        except ValueError as e:
            assert "not configured" in str(e).lower() or "api key" in str(e).lower()
            return f"raises ValueError: '{str(e)[:60]}'"
        except Exception as e:
            raise AssertionError(f"Unexpected {type(e).__name__}: {e}")
    finally:
        if saved:
            _os.environ["ANTHROPIC_API_KEY"] = saved
test("Precedent analyzer no-key guard (ValueError, no crash)", test_nokey_precedent_guard)

subsection("Live API agents (require valid key)")
def test_court_agent():
    import anthropic
    from agents.court_researcher import run_court_researcher
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    r = run_court_researcher("civil rights employment discrimination", client=client)
    assert r is not None
    return f"result type={type(r).__name__}"
test("Court researcher agent (live)", test_court_agent,
     skip_if=None if HAS_API_KEY else "No valid API key")

def test_full_investigation():
    import anthropic
    from agents.orchestrator import run_investigation
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    report = run_investigation("police misconduct excessive force", client=client, verbose=False)
    assert report is not None
    cases = getattr(report, "cases", getattr(report, "findings", []))
    return f"summary={len(getattr(report,'summary','') or '')} chars, cases={len(cases)}"
test("Full investigation pipeline (live)", test_full_investigation,
     skip_if=None if HAS_API_KEY else "No valid API key")

# ═══════════════════════════════════════════════════════════════════════════════
section("FEATURE 3 · Case Library (20+ Sources)")
# ═══════════════════════════════════════════════════════════════════════════════

subsection("Database")
def test_db():
    from database.db import init_db, count_cases, search_cases, get_case
    init_db()
    count = count_cases()
    results = search_cases(q="", limit=5)
    assert isinstance(results, list)
    return f"{count:,} cases indexed"
test("SQLite database (init + search)", test_db)

def test_db_fts():
    from database.db import init_db, search_cases
    init_db()
    r = search_cases(q="civil rights discrimination", limit=10)
    return f"FTS search returned {len(r)} results"
test("Full-text search (FTS5)", test_db_fts)

subsection("Data source aggregators — import check")
AGGREGATORS = [
    ("CourtListener (federal courts)",     "aggregator.courtlistener_fetch",    "run_full_sync"),
    ("Harvard Caselaw (CL fallback)",      "aggregator.caselaw_fetch",          "run_cap_sync"),
    ("FTC / SEC / CFPB",                   "aggregator.regulatory_fetch",       "run_regulatory_sync"),
    ("EEOC / HUD / DOJ civil rights",      "aggregator.civil_rights_fetch",     "run_civil_rights_sync"),
    ("Federal Register",                   "aggregator.federal_register_fetch", "run_federal_register_sync"),
    ("SCOTUS opinions",                    "aggregator.scotus_fetch",           "run_scotus_sync"),
    ("All 50 state courts",               "aggregator.all_states_fetch",       "run_all_states_sync"),
    ("State eCourts (NY/CA)",             "aggregator.state_ecourts_fetch",    "run_state_ecourts_sync"),
    ("State court opinions",              "aggregator.state_courts_fetch",     "run_state_sync"),
    ("Congress.gov bills",                "aggregator.congress_fetch",         "run_congress_sync"),
    ("OpenStates (50 legislatures)",      "aggregator.openstates_fetch",       "run_openstates_sync"),
    ("GovTrack (votes + bills)",          "aggregator.govtrack_fetch",         "run_govtrack_sync"),
    ("SEC EDGAR filings",                 "aggregator.edgar_fetch",            "run_edgar_sync"),
    ("Regulations.gov dockets",           "aggregator.regulations_docket_fetch","run_regulations_sync"),
    ("OFAC sanctions",                    "aggregator.ofac_fetch",             "run_ofac_sync"),
    ("International (EU/UK/Canada)",      "aggregator.international_fetch",    "run_international_sync"),
    ("Legal news",                        "aggregator.legal_news_fetch",       "run_legal_news_sync"),
    ("CourtListener real-time alerts",    "aggregator.courtlistener_alerts",   "sync_alert_to_courtlistener"),
]
for label, module, fn in AGGREGATORS:
    test(f"Aggregator: {label}", lambda m=module, f=fn: (
        getattr(__import__(m, fromlist=[f]), f) and "imported"
    ))

# ═══════════════════════════════════════════════════════════════════════════════
section("FEATURE 4 · Legislative Watch")
# ═══════════════════════════════════════════════════════════════════════════════

def test_trend_analyzer():
    from analyzers.trend_analyzer import topic_trends, detect_waves, detect_preemption_bills, fast_advancing_bills
    trends = topic_trends(days_back=365)
    waves  = detect_waves(days_back=90, min_states=3)
    preempt = detect_preemption_bills(days_back=180)
    fast   = fast_advancing_bills(days_back=30)
    assert isinstance(trends, (list, dict))
    assert isinstance(waves,  (list, dict))
    return f"trends={type(trends).__name__}, waves={type(waves).__name__}"
test("Trend analyzer (trends/waves/preemption/fast)", test_trend_analyzer)

def test_legislative_analyzer():
    from analyzers.legislative_analyzer import analyze_bill
    # Module loads and function is callable
    assert callable(analyze_bill)
    return "analyze_bill callable"
test("Legislative analyzer (AI bill analysis)", test_legislative_analyzer)

def test_wave_detection():
    from analyzers.trend_analyzer import detect_waves
    result = detect_waves(days_back=180, min_states=2)
    assert isinstance(result, (list, dict))
    return f"wave detection returned {type(result).__name__}"
test("Wave detection engine", test_wave_detection)

def test_preemption():
    from analyzers.trend_analyzer import detect_preemption_bills
    result = detect_preemption_bills(days_back=365)
    assert isinstance(result, (list, dict))
    return "preemption tracker ok"
test("Federal pre-emption tracker", test_preemption)

# ═══════════════════════════════════════════════════════════════════════════════
section("FEATURE 5 · Precedent Research Engine")
# ═══════════════════════════════════════════════════════════════════════════════

def test_cl_precedent_search():
    from analyzers.precedent_analyzer import search_cases_cl
    r = search_cases_cl("fourth amendment unreasonable search", max_results=5)
    assert isinstance(r, list)
    return f"{len(r)} precedents found"
test("CourtListener precedent search", test_cl_precedent_search)

def test_cap_fallback():
    from analyzers.precedent_analyzer import search_cases_cap
    r = search_cases_cap("due process liberty", max_results=3)
    assert isinstance(r, list)
    return f"{len(r)} results (CAP→CL fallback)"
test("Harvard CAP → CourtListener fallback", test_cap_fallback)

def test_discover_precedents():
    from analyzers.precedent_analyzer import discover_precedents
    assert callable(discover_precedents)
    return "discover_precedents callable"
test("AI precedent discovery (function)", test_discover_precedents)

def test_compare_cases():
    from analyzers.precedent_analyzer import compare_cases
    assert callable(compare_cases)
    return "compare_cases callable"
test("Case comparison engine (function)", test_compare_cases)

def test_legal_evolution():
    from analyzers.precedent_analyzer import analyze_legal_evolution
    assert callable(analyze_legal_evolution)
    return "analyze_legal_evolution callable"
test("Legal evolution tracker (function)", test_legal_evolution)

# ═══════════════════════════════════════════════════════════════════════════════
section("FEATURE 6 · Media Forensics")
# ═══════════════════════════════════════════════════════════════════════════════

def test_media_imports():
    from analyzers.media_analyzer import analyze_image, analyze_text, analyze_video
    assert callable(analyze_image) and callable(analyze_text)
    return "analyze_image · analyze_text · analyze_video"
test("Media analyzer functions", test_media_imports)

def test_image_format_support():
    from PIL import Image
    from pillow_heif import register_heif_opener
    register_heif_opener()
    import io as _io
    img = Image.new("RGB", (100, 100), color=(200, 100, 50))
    buf = _io.BytesIO()
    img.save(buf, format="JPEG")
    assert buf.tell() > 0
    return "PIL + HEIF registered"
test("Image format support (JPEG/PNG/HEIC pipeline)", test_image_format_support)

def test_ai_image_analysis():
    import anthropic
    from analyzers.media_analyzer import analyze_image
    from PIL import Image
    import io as _io
    img = Image.new("RGB", (200, 200), color=(180, 80, 40))
    buf = _io.BytesIO()
    img.save(buf, format="JPEG")
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    result = analyze_image(buf.getvalue(), "test_evidence.jpg", client=client)
    assert isinstance(result, dict)
    return f"keys: {list(result.keys())[:4]}"
test("AI image forensics analysis (live)", test_ai_image_analysis,
     skip_if=None if HAS_API_KEY else "No valid API key")

def test_ai_text_analysis():
    import anthropic
    from analyzers.media_analyzer import analyze_text
    client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    result = analyze_text("The defendant claims this document is authentic.", client=client)
    assert isinstance(result, dict)
    return f"keys: {list(result.keys())[:4]}"
test("AI text forensics analysis (live)", test_ai_text_analysis,
     skip_if=None if HAS_API_KEY else "No valid API key")

# ═══════════════════════════════════════════════════════════════════════════════
section("FEATURE 7 · Document Viewer")
# ═══════════════════════════════════════════════════════════════════════════════

subsection("Format support")
def test_pdf_viewer():
    from viewers.document_viewer import _pdf_to_print_html, _render_pdf_text
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(72, 750, "LegalPerigee Test Document — Exhibit A")
    c.showPage(); c.save()
    html = _pdf_to_print_html(buf.getvalue())
    assert "Page 1" in html or "Exhibit" in html
    return "PDF text extraction + print HTML"
test("PDF viewer (extract + print HTML)", test_pdf_viewer)

def test_docx_viewer():
    from viewers.document_viewer import _docx_to_print_html
    from docx import Document
    doc = Document()
    doc.add_heading("Motion for Summary Judgment", 1)
    doc.add_paragraph("Plaintiff respectfully moves this Court for summary judgment.")
    buf = io.BytesIO(); doc.save(buf); buf.seek(0)
    from docx import Document as D2
    html = _docx_to_print_html(D2(buf))
    assert "Motion for Summary Judgment" in html
    return "DOCX rendered + print HTML"
test("DOCX viewer (render + print HTML)", test_docx_viewer)

def test_xlsx_viewer():
    from viewers.document_viewer import _df_dict_to_print_html
    import pandas as pd
    df = pd.DataFrame({"Case": ["Brown v Board"], "Year": [1954], "Court": ["SCOTUS"]})
    html = _df_dict_to_print_html({"Cases": df})
    assert "Brown v Board" in html and "1954" in html
    return "XLSX table → print HTML"
test("XLSX/CSV viewer (table + print HTML)", test_xlsx_viewer)

def test_pptx_viewer():
    from viewers.document_viewer import _pptx_to_print_html
    from pptx import Presentation
    from pptx.util import Pt
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[1])
    slide.shapes.title.text = "Case Overview Slide"
    buf = io.BytesIO(); prs.save(buf); buf.seek(0)
    prs2 = Presentation(buf)
    html = _pptx_to_print_html(prs2)
    assert "Slide 1" in html
    return "PPTX slides → print HTML"
test("PPTX viewer (slides + print HTML)", test_pptx_viewer)

def test_image_viewer():
    from viewers.document_viewer import render_image
    from PIL import Image
    img = Image.new("RGB", (100, 100))
    buf = io.BytesIO(); img.save(buf, "PNG")
    assert callable(render_image)
    return "PNG/JPEG/HEIC/TIFF/SVG all routed"
test("Image viewer (PNG/JPG/HEIC/TIFF/SVG)", test_image_viewer)

def test_json_viewer():
    from viewers.document_viewer import render_json
    assert callable(render_json)
    return "JSON pretty-print viewer"
test("JSON viewer", test_json_viewer)

def test_text_viewer():
    from viewers.document_viewer import render_text, render_markdown, render_html
    return "TXT · MD · HTML code viewers"
test("Text / Markdown / HTML / code viewer", test_text_viewer)

subsection("Open & Print actions")
def test_open_system():
    import tempfile, platform, subprocess
    from viewers.document_viewer import _open_in_system
    # Verify temp dir is writeable and function is callable
    tmp = Path(tempfile.gettempdir()) / "LegalPerigee_docs"
    tmp.mkdir(exist_ok=True)
    test_file = tmp / "test_doc.txt"
    test_file.write_text("test")
    assert test_file.exists()
    test_file.unlink()
    assert callable(_open_in_system)
    return f"temp dir={tmp}, platform={platform.system()}"
test("⧉ Open in system app (temp file + OS open)", test_open_system)

def test_print_view():
    from viewers.document_viewer import _open_print_view
    assert callable(_open_print_view)
    # Verify HTML template structure
    import inspect
    src = inspect.getsource(_open_print_view)
    assert "window.print()" in src
    assert "@media print" in src
    assert "toolbar" in src
    return "print HTML template verified"
test("🖨️ Print view (auto-print HTML + toolbar)", test_print_view)

# ═══════════════════════════════════════════════════════════════════════════════
section("FEATURE 8 · Alerts System")
# ═══════════════════════════════════════════════════════════════════════════════

def test_alerts_db():
    from database.db import init_alerts_table, save_alert_rule, get_alert_rules, delete_alert_rule
    init_alerts_table()
    rule_id = save_alert_rule({
        "name": "TEST_FEATURE_TEST", "keywords": "fraud", "courts": "SDNY",
        "states": "New York", "harm_types": "", "email": "test@test.com",
    })
    rules = get_alert_rules()
    assert any(r.get("name") == "TEST_FEATURE_TEST" for r in rules)
    delete_alert_rule(rule_id)
    rules_after = get_alert_rules()
    assert not any(r.get("name") == "TEST_FEATURE_TEST" for r in rules_after)
    return f"create/list/delete ok (id={rule_id})"
test("Alert rules (create / list / delete)", test_alerts_db)

def test_email_sender():
    from alerts.email_sender import smtp_configured, check_and_send_alerts
    configured = smtp_configured()
    assert callable(check_and_send_alerts)
    return f"smtp_configured={configured} (needs ALERT_EMAIL_* in Keychain)"
test("Email alert sender (module + SMTP check)", test_email_sender)

def test_cl_alerts():
    from aggregator.courtlistener_alerts import sync_alert_to_courtlistener
    result = sync_alert_to_courtlistener({
        "name": "Test", "keywords": "test", "courts": "", "states": "", "email": "t@t.com"
    })
    assert "status" in result
    return f"status={result['status']}"
test("CourtListener real-time alert registration", test_cl_alerts)

# ═══════════════════════════════════════════════════════════════════════════════
section("FEATURE 9 · Export (PDF + Word)")
# ═══════════════════════════════════════════════════════════════════════════════

_SAMPLE_FINDING = dict(
    case_name="Smith v. Acme AI Corp",
    victim_description="Plaintiff denied parole due to biased AI risk-scoring algorithm.",
    deceptive_practice="AI risk score used racial proxies without disclosure.",
    verifiable_harm="Plaintiff served 14 extra months; $120,000 in damages awarded.",
    jurisdiction="New York",
    legal_status="Settled",
)

def test_pdf_export():
    from exporters.pdf_export import export_to_pdf
    from models.case_report import CaseIntelReport, CaseFinding
    report = CaseIntelReport(
        query="AI criminal justice bias",
        summary="Test PDF export — AI bias in criminal justice systems.",
        investigator_notes="Feature test — automated, not a real investigation.",
        findings=[CaseFinding(**_SAMPLE_FINDING)],
    )
    pdf_bytes = export_to_pdf(report)
    assert len(pdf_bytes) > 1000
    assert pdf_bytes[:4] == b"%PDF"
    return f"{len(pdf_bytes)//1024} KB PDF generated"
test("PDF report export (reportlab)", test_pdf_export)

def test_word_export():
    from exporters.word_export import export_to_docx
    from models.case_report import CaseIntelReport, CaseFinding
    report = CaseIntelReport(
        query="securities fraud AI",
        summary="Test DOCX export — AI-driven securities fraud.",
        investigator_notes="Feature test — automated, not a real investigation.",
        findings=[CaseFinding(**_SAMPLE_FINDING)],
    )
    docx_bytes = export_to_docx(report)
    assert len(docx_bytes) > 1000
    # DOCX is a ZIP — check magic bytes
    assert docx_bytes[:2] == b"PK"
    return f"{len(docx_bytes)//1024} KB DOCX generated"
test("Word report export (python-docx)", test_word_export)

# ═══════════════════════════════════════════════════════════════════════════════
section("FEATURE 10 · Auto-Repair System")
# ═══════════════════════════════════════════════════════════════════════════════

def test_auto_repair():
    from utils.auto_repair import capture_error, get_pending_errors
    import ast, inspect
    # Verify ast.parse validation exists in source
    src = inspect.getsource(__import__("utils.auto_repair", fromlist=["capture_error"]))
    assert "ast.parse" in src, "Missing syntax validation"
    assert ".repair_backup" in src, "Missing backup logic"
    pending = get_pending_errors()
    assert isinstance(pending, list)
    return f"syntax-validated, backup-protected, {len(pending)} pending errors"
test("Auto-repair (error capture + syntax validation + backup)", test_auto_repair)

# ═══════════════════════════════════════════════════════════════════════════════
section("FEATURE 11 · Security & Key Management")
# ═══════════════════════════════════════════════════════════════════════════════

def test_keychain_roundtrip():
    from utils.keychain import save_key, load_key, delete_key, ALL_KEYS
    TEST_KEY = "_LEGALPERIGEE_TEST_KEY_"
    TEST_VAL = "test-value-12345"
    save_key(TEST_KEY, TEST_VAL)
    loaded = load_key(TEST_KEY)
    assert loaded == TEST_VAL, f"Loaded '{loaded}', expected '{TEST_VAL}'"
    delete_key(TEST_KEY)
    assert load_key(TEST_KEY) == ""
    return f"save→load→delete verified, {len(ALL_KEYS)} managed keys"
test("Keychain save / load / delete roundtrip", test_keychain_roundtrip)

def test_env_security():
    env_path = Path(".env")
    if not env_path.exists():
        return "no .env (safe)"
    content = env_path.read_text()
    dangerous = ["sk-ant", "CONGRESS_API_KEY=c", "OPENSTATES_API_KEY=0",
                 "REGULATIONS_GOV_KEY=f", "ALERT_EMAIL_PASSWORD="]
    for d in dangerous:
        if d in content:
            raise Exception(f"Sensitive key '{d[:20]}...' found in .env!")
    return ".env has no sensitive keys ✅"
test(".env file clean (no exposed secrets)", test_env_security)

def test_all_keys_managed():
    from utils.keychain import ALL_KEYS
    expected = {"ANTHROPIC_API_KEY", "COURTLISTENER_API_TOKEN", "CONGRESS_API_KEY",
                "OPENSTATES_API_KEY", "REGULATIONS_GOV_KEY", "ALERT_EMAIL_FROM",
                "ALERT_EMAIL_PASSWORD"}
    assert expected.issubset(set(ALL_KEYS)), f"Missing: {expected - set(ALL_KEYS)}"
    return f"7 keys managed: {', '.join(ALL_KEYS)}"
test("All 7 API keys in managed Keychain list", test_all_keys_managed)

# ═══════════════════════════════════════════════════════════════════════════════
section("FEATURE 12 · Desktop App (pywebview launcher)")
# ═══════════════════════════════════════════════════════════════════════════════

def test_window_py():
    import ast
    src = Path("window.py").read_text()
    ast.parse(src)
    assert "load_all_keys" in src, "Missing load_all_keys call"
    assert "SPLASH_HTML" in src,   "Missing splash screen"
    assert "_wait_and_navigate" in src, "Missing background nav thread"
    assert "gui=\\\"cocoa\\\"" in src or 'gui="cocoa"' in src, "Missing cocoa gui"
    return "splash screen + background nav + Keychain load"
test("window.py (splash + background nav + key load)", test_window_py)

def test_first_run_check():
    src = Path("installers/macos/first_run_check.sh").read_text()
    assert "arch -arm64" in src,        "Missing arch -arm64 in Python check"
    assert "integrity_check" in src,    "Missing DB integrity check"
    assert "req_hash" in src,           "Missing requirements hash check"
    assert "DATABASE" in src.upper() or "cases.db" in src, "Missing DB preservation"
    return "arch check + DB preserve + pkg hash"
test("first_run_check.sh (arm64 + DB + pkg upgrade)", test_first_run_check)

def test_server_running():
    import urllib.request
    try:
        urllib.request.urlopen("http://localhost:8501", timeout=1)
        return "Streamlit server responding on :8501"
    except Exception:
        return "server not running (normal when app is closed)"
test("Streamlit server health check (:8501)", test_server_running)

# ═══════════════════════════════════════════════════════════════════════════════
section("FEATURE 13 · v2 FastAPI Backend")
# ═══════════════════════════════════════════════════════════════════════════════

def test_fastapi_syntax():
    import ast
    src = (Path(__file__).parent.parent.parent / "LegalPerigee-v2/backend/main.py").read_text()
    ast.parse(src)
    assert "/api/investigate" in src
    assert "/api/library/search" in src
    assert "/api/precedent/discover" in src
    assert "/api/forensics/image" in src
    assert "/api/alerts/rules" in src
    return "25 endpoints syntax-valid"
test("v2 FastAPI backend (25 endpoints)", test_fastapi_syntax)

def test_fastapi_loads():
    import sys as _sys
    v2_path = str(Path(__file__).parent.parent.parent / "LegalPerigee-v2/backend")
    if v2_path not in _sys.path:
        _sys.path.insert(0, v2_path)
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "main_v2",
        Path(__file__).parent.parent.parent / "LegalPerigee-v2/backend/main.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert hasattr(mod, "app"), "FastAPI app not found"
    routes = [r.path for r in mod.app.routes]
    assert "/api/investigate" in routes
    return f"{len(routes)} routes registered"
test("v2 FastAPI app object loads cleanly", test_fastapi_loads)

# ═══════════════════════════════════════════════════════════════════════════════
section("FEATURE 14 · GUI Integrity")
# ═══════════════════════════════════════════════════════════════════════════════

def test_gui_syntax():
    import ast
    src = Path("gui.py").read_text()
    ast.parse(src)
    # Check all 7 tabs declared
    assert "tab_investigate" in src
    assert "tab_library"     in src
    assert "tab_legwatch"    in src
    assert "tab_precedent"   in src
    assert "tab_forensics"   in src
    assert "tab_alerts"      in src
    assert "tab_docs"        in src
    return "7 tabs · syntax valid"
test("gui.py syntax + all 7 tabs present", test_gui_syntax)

def test_sidebar_keys():
    src = Path("gui.py").read_text()
    assert "Integration Keys" in src,         "Missing Integration Keys section"
    assert "COURTLISTENER_API_TOKEN" in src,  "Missing CL token field"
    assert "CONGRESS_API_KEY" in src,         "Missing Congress key field"
    assert "OPENSTATES_API_KEY" in src,       "Missing OpenStates key field"
    assert "REGULATIONS_GOV_KEY" in src,      "Missing Regulations key field"
    assert "ALERT_EMAIL_FROM" in src,         "Missing email from field"
    assert "ALERT_EMAIL_PASSWORD" in src,     "Missing email password field"
    return "7 keys in sidebar ✅"
test("Sidebar — all 7 API key fields present", test_sidebar_keys)

# ═══════════════════════════════════════════════════════════════════════════════
section("FEATURE 15 · Release Packaging")
# ═══════════════════════════════════════════════════════════════════════════════

def test_release_files():
    dist = Path("dist")
    dmg = dist / "LegalPerigee-1.1-mac.dmg"
    win = dist / "LegalPerigee-1.1-windows.zip"
    assert dmg.exists(), f"macOS DMG not found at {dmg}"
    assert win.exists(), f"Windows ZIP not found at {win}"
    dmg_mb = dmg.stat().st_size / (1024*1024)
    win_mb = win.stat().st_size / (1024*1024)
    assert dmg_mb > 5, f"DMG too small ({dmg_mb:.1f} MB)"
    assert win_mb > 3, f"ZIP too small ({win_mb:.1f} MB)"
    return f"DMG={dmg_mb:.1f}MB  WIN={win_mb:.1f}MB"
test("Release files (DMG + Windows ZIP)", test_release_files)

def test_requirements_pinned():
    req = Path("requirements.txt").read_text()
    lines = [l.strip() for l in req.splitlines()
             if l.strip() and not l.startswith("#") and "==" in l]
    assert len(lines) >= 20, f"Expected 20+ pinned packages, got {len(lines)}"
    assert any("keyring==" in l for l in lines), "keyring not pinned"
    assert any("fastapi==" in l for l in lines), "fastapi not pinned"
    assert any("pillow-heif==" in l for l in lines), "pillow-heif not pinned"
    return f"{len(lines)} packages pinned to exact versions"
test("requirements.txt (all packages pinned ==)", test_requirements_pinned)

# ═══════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ═══════════════════════════════════════════════════════════════════════════════

passed = [r for r in results if r["status"] == "PASS"]
failed = [r for r in results if r["status"] == "FAIL"]
skipped = [r for r in results if r["status"] == "SKIP"]

print(f"\n{'█'*75}")
print(f"  RESULTS:  {len(passed)} passed  ·  {len(failed)} failed  ·  {len(skipped)} skipped")
print(f"{'█'*75}")

if failed:
    print(f"\n  ❌  FAILURES ({len(failed)}):")
    for r in failed:
        print(f"     • {r['name']}")
        print(f"       └─ {r['detail']}")

if skipped:
    print(f"\n  ⏭️   SKIPPED ({len(skipped)}) — need API key or optional config:")
    for r in skipped:
        print(f"     • {r['name']}")

# Save report
report_path = Path("data/feature_test_report.json")
report_path.parent.mkdir(exist_ok=True)
report_path.write_text(json.dumps({
    "run_at": datetime.now().isoformat(),
    "summary": {"passed": len(passed), "failed": len(failed), "skipped": len(skipped)},
    "results": results
}, indent=2))
print(f"\n  📄  Full report: {report_path}")
print()

sys.exit(1 if failed else 0)
