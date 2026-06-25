"""
LegalPerigee — Streamlit GUI

Run with:
    streamlit run gui.py
"""

import json
import os
import queue
import sys
import threading
import time
from pathlib import Path

import anthropic
import streamlit as st
from dotenv import load_dotenv
from utils.auto_repair import (
    capture_error, get_pending_errors, analyze_error,
    apply_fix, preview_fix, restart_server, get_all_errors,
)

# ── Background auto-sync engine ───────────────────────────────────────────────
# Lives at module (process) level so it persists across Streamlit reruns.
# The GUI thread reads _SYNC_STATE to show live status; never writes directly.

_AUTO_SYNC_INTERVAL_HOURS = 6   # re-sync if last sync was more than this long ago

# "Fast" sources that auto-sync runs (skip heavy bulk downloads like OFAC/OpenStates).
# Defined in aggregator.sync_runner so the GUI and the scheduled job stay in lockstep.
from aggregator.sync_runner import DEFAULT_SOURCES as _AUTO_SYNC_SOURCES

_SYNC_STATE: dict = {
    "status": "idle",       # "idle" | "running" | "done" | "error"
    "message": "",          # last progress line
    "added": 0,
    "updated": 0,
    "started_at": 0.0,
    "finished_at": 0.0,
    "log": [],              # last N progress lines
}
_SYNC_LOCK = threading.Lock()
_SYNC_MSG_QUEUE: queue.Queue = queue.Queue(maxsize=200)


def _sync_prog(msg: str) -> None:
    """Progress callback used by background sync thread."""
    with _SYNC_LOCK:
        _SYNC_STATE["message"] = msg
        _SYNC_STATE["log"].append(msg)
        if len(_SYNC_STATE["log"]) > 100:
            _SYNC_STATE["log"] = _SYNC_STATE["log"][-100:]
    try:
        _SYNC_MSG_QUEUE.put_nowait(msg)
    except queue.Full:
        pass


def _run_background_sync(sources: list) -> None:
    """Executed in a daemon thread. Runs selected sources and updates _SYNC_STATE."""
    with _SYNC_LOCK:
        if _SYNC_STATE["status"] == "running":
            return
        _SYNC_STATE.update({"status": "running", "message": "Starting…",
                             "added": 0, "updated": 0,
                             "started_at": time.time(), "log": []})

    try:
        from aggregator.sync_runner import run_sources
        # incremental=True: only pull items newer than the last successful sync,
        # so a frequent background run stays cheap.
        result = run_sources(sources, progress_cb=_sync_prog, incremental=True)
        total_added = result["added"]
        total_updated = result["updated"]

        with _SYNC_LOCK:
            _SYNC_STATE.update({
                "status": "done",
                "message": f"✅ +{total_added} new, {total_updated} updated",
                "added": total_added,
                "updated": total_updated,
                "finished_at": time.time(),
            })
        _sync_prog(f"✅ Auto-sync complete: +{total_added} new, {total_updated} updated")

    except Exception as e:
        with _SYNC_LOCK:
            _SYNC_STATE.update({
                "status": "error",
                "message": f"Sync error: {e}",
                "finished_at": time.time(),
            })


# ── Background investigation engine ───────────────────────────────────────────
# Mirrors the auto-sync pattern: a daemon thread runs the investigation while
# the Streamlit UI stays fully interactive.  A @st.fragment polls every 1 s
# to show live log lines without blocking any other tab.

_INVEST_STATE: dict = {
    "status": "idle",   # "idle" | "running" | "done" | "error"
    "query": "",
    "log": [],
    "report": None,
    "error": None,
    "started_at": 0.0,
    "finished_at": 0.0,
}
_INVEST_LOCK = threading.Lock()


def _run_investigation_bg(query: str, filters, client) -> None:
    """Daemon thread target — runs the investigation and stores results."""
    with _INVEST_LOCK:
        _INVEST_STATE.update({
            "status": "running", "query": query,
            "log": [], "report": None, "error": None,
            "started_at": time.time(), "finished_at": 0.0,
        })

    def _log_cb(msg: str) -> None:
        ts = time.strftime("%H:%M:%S")
        with _INVEST_LOCK:
            _INVEST_STATE["log"].append(f"[{ts}] {msg}")
            if len(_INVEST_STATE["log"]) > 60:
                _INVEST_STATE["log"] = _INVEST_STATE["log"][-60:]

    try:
        from agents.orchestrator import run_investigation as _inv
        report = _inv(query=query, filters=filters, client=client, log_cb=_log_cb)
        with _INVEST_LOCK:
            _INVEST_STATE.update({
                "status": "done", "report": report,
                "finished_at": time.time(),
            })
    except Exception as _e:
        with _INVEST_LOCK:
            _INVEST_STATE.update({
                "status": "error", "error": str(_e),
                "finished_at": time.time(),
            })


def _maybe_trigger_auto_sync() -> None:
    """
    Called once per session on first load.
    Starts background sync if the data is stale (> AUTO_SYNC_INTERVAL_HOURS old).
    """
    from database.db import get_sync_log
    with _SYNC_LOCK:
        if _SYNC_STATE["status"] == "running":
            return  # already going

    # Check last successful sync time from DB
    try:
        logs = get_sync_log(50)
        recent = [l for l in logs if l.get("status") == "success"]
        if recent:
            # started_at is a string like "2026-06-07 01:47:01"
            import datetime
            latest_str = max(l["started_at"] for l in recent)
            latest_dt = datetime.datetime.fromisoformat(latest_str)
            age_hours = (datetime.datetime.now() - latest_dt).total_seconds() / 3600
            if age_hours < _AUTO_SYNC_INTERVAL_HOURS:
                return  # fresh enough
    except Exception:
        pass  # DB not ready yet — skip

    # Data is stale or never synced: start background sync
    t = threading.Thread(
        target=_run_background_sync,
        args=(_AUTO_SYNC_SOURCES,),
        daemon=True,
        name="lp-auto-sync",
    )
    t.start()


# Load .env for non-sensitive defaults ONLY (SMTP host/port).
# override=False so Keychain values (loaded later by load_all_keys) always win.
load_dotenv(
    dotenv_path=os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
    override=False,
)

# ── Page config (must be first Streamlit call) ────────────────────────────────
st.set_page_config(
    page_title="LegalPerigee",
    page_icon="⚖️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ── CSS ───────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
  /* ── Header banner — slimmer, same brand feel ───────────────────────────── */
  .lp-header {
    background: linear-gradient(135deg, #1a2744 0%, #0d1b2a 100%);
    padding: 0.85rem 1.8rem 0.75rem;
    border-radius: 10px;
    margin-bottom: 0.9rem;
    border-left: 5px solid #c9a84c;
  }
  .lp-header h1 { color:#e8d9b0; font-size:1.55rem; font-weight:700; margin:0; letter-spacing:.04em; }
  .lp-header p  { color:#8fa3bf; margin:.2rem 0 0; font-size:.82rem; }

  /* ── Severity badges ─────────────────────────────────────────────────────── */
  .badge-high   { background:#c0392b; color:#fff; padding:2px 10px; border-radius:12px; font-size:.75rem; font-weight:600; }
  .badge-medium { background:#d67f1e; color:#fff; padding:2px 10px; border-radius:12px; font-size:.75rem; font-weight:600; }
  .badge-low    { background:#27ae60; color:#fff; padding:2px 10px; border-radius:12px; font-size:.75rem; font-weight:600; }
  .badge-unknown{ background:#7f8c8d; color:#fff; padding:2px 10px; border-radius:12px; font-size:.75rem; font-weight:600; }

  /* ── Case cards ──────────────────────────────────────────────────────────── */
  .case-card {
    background:#f8f9fc; border:1px solid #dde3ee;
    border-left:4px solid #1a2744; border-radius:8px;
    padding:1.1rem 1.4rem; margin-bottom:.8rem;
  }
  .case-card h4 { margin:0 0 .5rem; color:#1a2744; }
  .case-meta { color:#555; font-size:.84rem; margin-bottom:.4rem; }

  /* ── Stat cards ──────────────────────────────────────────────────────────── */
  .stat-card { background:#f0f4ff; border:1px solid #c5d0e8; border-radius:8px; padding:1rem 1.2rem; text-align:center; }
  .stat-card .num { font-size:2.1rem; font-weight:700; color:#1a2744; }
  .stat-card .lbl { font-size:.78rem; color:#667; text-transform:uppercase; letter-spacing:.05em; }

  /* ── Progress log ────────────────────────────────────────────────────────── */
  .progress-log {
    background:#0d1b2a; color:#7ec8a0; font-family:monospace;
    font-size:.81rem; padding:1rem; border-radius:8px;
    max-height:200px; overflow-y:auto; white-space:pre-wrap;
  }

  /* ── Document viewer ─────────────────────────────────────────────────────── */
  .doc-file-item {
    background:#f4f6fb; border:1px solid #e0e4f0; border-radius:6px;
    padding:.6rem .9rem; margin-bottom:.4rem; cursor:pointer;
    font-size:.87rem;
  }
  .doc-file-item:hover { background:#e8ecf8; }
  .doc-file-selected {
    background:#1a2744 !important; color:#e8d9b0 !important;
    border-color:#1a2744 !important;
  }
  .doc-empty-state {
    text-align:center; padding:3rem 1rem;
    color:#aaa; border:2px dashed #dde3ee; border-radius:12px;
  }

  .tip-box { background:#1e2d45; border:1px solid #3a5272; border-radius:8px;
             padding:.8rem 1rem; font-size:.82rem; color:#b0c4d8; margin-top:.5rem; }

  /* ── INPUT FIELDS — Fix #1: visible borders + bright placeholders ────────── */
  /* Text inputs */
  [data-testid="stTextInput"] input,
  [data-testid="stTextArea"] textarea,
  [data-testid="stDateInput"] input {
    background: #1c2b40 !important;
    border: 1.5px solid #3a5272 !important;
    border-radius: 6px !important;
    color: #dce8f5 !important;
    font-size: 0.88rem !important;
    padding: 0.45rem 0.7rem !important;
    transition: border-color 0.15s ease;
  }
  [data-testid="stTextInput"] input:focus,
  [data-testid="stTextArea"] textarea:focus,
  [data-testid="stDateInput"] input:focus {
    border-color: #6fa3d8 !important;
    box-shadow: 0 0 0 2px rgba(111,163,216,0.18) !important;
    outline: none !important;
  }
  /* Placeholder text — clearly readable, not invisible */
  [data-testid="stTextInput"] input::placeholder,
  [data-testid="stTextArea"] textarea::placeholder,
  [data-testid="stDateInput"] input::placeholder {
    color: #607d99 !important;
    font-style: italic;
    opacity: 1 !important;
  }

  /* Selectbox / dropdown ─────────────────────────────────────────────────────*/
  [data-testid="stSelectbox"] > div > div,
  [data-testid="stMultiSelect"] > div > div {
    background: #1c2b40 !important;
    border: 1.5px solid #3a5272 !important;
    border-radius: 6px !important;
    color: #dce8f5 !important;
  }
  [data-testid="stSelectbox"] > div > div:focus-within,
  [data-testid="stMultiSelect"] > div > div:focus-within {
    border-color: #6fa3d8 !important;
    box-shadow: 0 0 0 2px rgba(111,163,216,0.18) !important;
  }
  /* Selectbox inner text and placeholder */
  [data-testid="stSelectbox"] span,
  [data-testid="stSelectbox"] [data-baseweb="select"] span {
    color: #dce8f5 !important;
  }
  /* Dropdown option list */
  [data-baseweb="popover"] [role="option"] {
    background: #1c2b40 !important;
    color: #dce8f5 !important;
  }
  [data-baseweb="popover"] [role="option"]:hover,
  [data-baseweb="popover"] [aria-selected="true"] {
    background: #253f5e !important;
  }

  /* Form labels — clearer, slightly larger ───────────────────────────────────*/
  [data-testid="stTextInput"] label,
  [data-testid="stTextArea"] label,
  [data-testid="stSelectbox"] label,
  [data-testid="stDateInput"] label,
  [data-testid="stMultiSelect"] label {
    color: #9dc3e8 !important;
    font-size: 0.82rem !important;
    font-weight: 600 !important;
    letter-spacing: 0.02em;
    margin-bottom: 3px !important;
  }

  /* ── TABS — Fix #2: tighter, better contrast, visible active indicator ─────*/
  [data-testid="stTabs"] [data-baseweb="tab-list"] {
    gap: 2px;
    border-bottom: 2px solid #253f5e;
    padding-bottom: 0;
  }
  [data-testid="stTabs"] [data-baseweb="tab"] {
    background: transparent !important;
    border: none !important;
    border-bottom: 3px solid transparent !important;
    border-radius: 0 !important;
    color: #7a9bbf !important;
    font-size: 0.80rem !important;
    font-weight: 500;
    padding: 0.45rem 0.7rem !important;
    transition: color 0.12s, border-color 0.12s;
    white-space: nowrap;
  }
  [data-testid="stTabs"] [data-baseweb="tab"]:hover {
    color: #c8dff0 !important;
    border-bottom-color: #3a5272 !important;
  }
  [data-testid="stTabs"] [aria-selected="true"][data-baseweb="tab"] {
    color: #e8d9b0 !important;
    border-bottom: 3px solid #c9a84c !important;
    font-weight: 700 !important;
    background: transparent !important;
  }

  /* ── BUTTONS — Fix #3: clear primary vs disabled hierarchy ─────────────────*/
  /* Primary action buttons (red ones like Investigate) are fine; improve grays */
  [data-testid="stButton"] > button {
    border-radius: 6px !important;
    font-size: 0.84rem !important;
    font-weight: 600 !important;
    transition: opacity 0.15s, box-shadow 0.15s;
  }
  [data-testid="stButton"] > button:not([disabled]):hover {
    opacity: 0.9;
    box-shadow: 0 2px 8px rgba(0,0,0,0.35);
  }
  /* Disabled buttons — make the disabled state more obviously distinct */
  [data-testid="stButton"] > button[disabled] {
    opacity: 0.35 !important;
    cursor: not-allowed !important;
    filter: grayscale(30%);
  }

  /* ── SLIDER — Fix #4: visible track ─────────────────────────────────────── */
  [data-testid="stSlider"] [data-baseweb="slider"] [role="slider"] {
    background: #c9a84c !important;
    border: 2px solid #e8d9b0 !important;
  }
  [data-testid="stSlider"] div[data-testid="stSliderTrack"] > div:first-child {
    background: #253f5e !important;
  }
  [data-testid="stSlider"] div[data-testid="stSliderTrack"] > div:nth-child(2) {
    background: #c9a84c !important;
  }

  /* ── SIDEBAR — Fix #5: cleaner section headers, less cluttered ──────────── */
  [data-testid="stSidebar"] {
    background: #0d1929 !important;
    border-right: 1px solid #1e3048;
  }
  [data-testid="stSidebar"] h2, [data-testid="stSidebar"] h3 {
    color: #c9a84c !important;
    font-size: 0.88rem !important;
    font-weight: 700 !important;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    margin-top: 0.6rem !important;
    margin-bottom: 0.2rem !important;
  }
  [data-testid="stSidebar"] .stButton > button {
    background: #17283d !important;
    border: 1px solid #2e4868 !important;
    color: #9dc3e8 !important;
    font-size: 0.79rem !important;
    font-weight: 500 !important;
    padding: 0.3rem 0.5rem !important;
    text-align: left !important;
  }
  [data-testid="stSidebar"] .stButton > button:hover {
    background: #1f3650 !important;
    color: #e8d9b0 !important;
    border-color: #c9a84c !important;
  }
  /* Sidebar dividers — more visible */
  [data-testid="stSidebar"] hr {
    border-color: #1e3048 !important;
    margin: 0.6rem 0 !important;
  }

  /* ── FILE UPLOADER — cleaner drop zone ──────────────────────────────────── */
  [data-testid="stFileUploader"] > section {
    background: #141f2e !important;
    border: 2px dashed #3a5272 !important;
    border-radius: 8px !important;
  }
  [data-testid="stFileUploader"] > section:hover {
    border-color: #6fa3d8 !important;
    background: #182638 !important;
  }
  [data-testid="stFileUploader"] small,
  [data-testid="stFileUploader"] span {
    color: #7a9bbf !important;
    font-size: 0.82rem !important;
  }

  /* ── EXPANDER — cleaner open/close ─────────────────────────────────────── */
  [data-testid="stExpander"] summary {
    background: #131f30 !important;
    border: 1px solid #253f5e !important;
    border-radius: 6px !important;
    padding: 0.45rem 0.8rem !important;
    color: #9dc3e8 !important;
    font-weight: 600 !important;
    font-size: 0.84rem !important;
  }
  [data-testid="stExpander"] summary:hover {
    background: #1a2e44 !important;
    border-color: #4a7aaa !important;
  }

  /* ── RADIO buttons — more visible ──────────────────────────────────────── */
  [data-testid="stRadio"] label {
    color: #b0c8e0 !important;
    font-size: 0.84rem !important;
  }
  [data-testid="stRadio"] [aria-checked="true"] + div label {
    color: #e8d9b0 !important;
    font-weight: 600 !important;
  }

  /* ── Info / warning / success boxes — slightly more opaque ─────────────── */
  [data-testid="stAlert"] {
    border-radius: 8px !important;
    font-size: 0.83rem !important;
  }

  /* ── General main content area — consistent spacing ─────────────────────── */
  .main .block-container {
    padding-top: 0.8rem !important;
    padding-bottom: 1.5rem !important;
    max-width: 1100px;
  }

  /* ── Case Library rich card buttons ─────────────────────────────────────── */
  /* Applied via a wrapping <div class="case-card-btn"> in the list */
  .case-card-btn > div > div > button,
  .case-card-btn button {
    background: #111d2e !important;
    border: 1px solid #253f5e !important;
    border-left: 4px solid #2e4f72 !important;
    border-radius: 8px !important;
    padding: 0.7rem 1rem 0.65rem !important;
    text-align: left !important;
    line-height: 1.55 !important;
    white-space: pre-wrap !important;
    color: #c8dff0 !important;
    transition: border-left-color 0.15s, background 0.15s !important;
    margin-bottom: 0 !important;
  }
  .case-card-btn > div > div > button:hover,
  .case-card-btn button:hover {
    background: #162336 !important;
    border-left-color: #c9a84c !important;
    color: #e8d9b0 !important;
  }

  /* Status chip inside button labels */
  .clc-chip {
    display: inline-block;
    background: #1e3a5f;
    color: #7ab4d8;
    border-radius: 3px;
    padding: 0px 6px;
    font-size: 0.70rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    vertical-align: middle;
  }

  /* ── Case detail modal (st.dialog) styling ───────────────────────────────── */
  [data-testid="stDialog"] {
    border-radius: 12px !important;
  }
  [data-testid="stDialog"] > div {
    background: #0d1929 !important;
    border: 1px solid #253f5e !important;
    border-radius: 12px !important;
    padding: 1.5rem 2rem !important;
  }
  .case-detail-header {
    border-bottom: 2px solid #253f5e;
    padding-bottom: 0.75rem;
    margin-bottom: 1rem;
  }
  .case-detail-header h2 {
    color: #e8d9b0;
    font-size: 1.25rem;
    font-weight: 700;
    margin: 0 0 0.3rem;
    line-height: 1.35;
  }
  .case-detail-header .source-badge {
    display: inline-block;
    background: #1a3a6e;
    color: #8ab0ff;
    border-radius: 5px;
    padding: 2px 10px;
    font-size: 0.75rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
  }
  .case-section-label {
    color: #c9a84c;
    font-size: 0.75rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.08em;
    margin: 1rem 0 0.3rem;
    border-bottom: 1px solid #1e3048;
    padding-bottom: 0.2rem;
  }
  .case-section-body {
    color: #b0c8e0;
    font-size: 0.87rem;
    line-height: 1.6;
    background: #111d2e;
    border-radius: 6px;
    padding: 0.65rem 0.9rem;
    margin-bottom: 0.3rem;
  }
  .case-party-box {
    background: #0e1829;
    border: 1px solid #253f5e;
    border-radius: 7px;
    padding: 0.6rem 0.9rem;
  }
  .case-party-box .party-role {
    color: #7a9bbf;
    font-size: 0.72rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.06em;
    margin-bottom: 0.2rem;
  }
  .case-party-box .party-name {
    color: #dce8f5;
    font-size: 0.88rem;
    font-weight: 500;
    line-height: 1.4;
  }

  #MainMenu { visibility:hidden; }
  footer    { visibility:hidden; }
</style>
""", unsafe_allow_html=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def _badge(severity: str) -> str:
    return f'<span class="badge-{severity}">{severity.upper()}</span>'


from utils.keychain import save_key, load_key, delete_key, keyring_available, load_all_keys, ALL_KEYS


def _valid_key(k: str) -> bool:
    k = k.strip()
    return bool(k and k.startswith("sk-") and len(k) > 20)


def _check_api_key() -> bool:
    return _valid_key(st.session_state.get("api_key", ""))


def _get_api_key() -> str:
    return st.session_state.get("api_key", "").strip()


def _save_env() -> None:
    """Write ONLY non-sensitive defaults to .env (SMTP host/port).
    All API keys and passwords go exclusively to macOS Keychain."""
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    lines = [
        "# LegalPerigee — non-sensitive defaults only.\n",
        "# ALL API keys and passwords are stored in macOS Keychain.\n",
        "# Enter them once in the sidebar; they persist securely across restarts.\n",
        "#\n",
        "# These two SMTP settings are safe to store here (not secrets):\n",
        f"ALERT_SMTP_HOST={os.environ.get('ALERT_SMTP_HOST', 'smtp.gmail.com')}\n",
        f"ALERT_SMTP_PORT={os.environ.get('ALERT_SMTP_PORT', '587')}\n",
    ]
    try:
        with open(env_path, "w") as f:
            f.writelines(lines)
    except Exception:
        pass


def _test_api_key(key: str) -> tuple[bool, str]:
    """Make a minimal API call to verify the key is accepted by Anthropic."""
    try:
        client = anthropic.Anthropic(api_key=key.strip())
        client.messages.create(
            model="claude-haiku-4-5",
            max_tokens=1,
            messages=[{"role": "user", "content": "hi"}],
        )
        return True, "✅ Key verified — Anthropic accepted it."
    except anthropic.AuthenticationError:
        return False, "❌ Invalid key — Anthropic rejected it (401). Generate a fresh key at console.anthropic.com → API Keys."
    except anthropic.PermissionDeniedError:
        return False, "❌ Key exists but lacks permissions (403). Check your Anthropic plan."
    except Exception as e:
        return False, f"⚠️ Could not verify key: {e}"


# ── Sidebar ───────────────────────────────────────────────────────────────────
# Load ALL keys from Keychain into os.environ on every page render.
# This ensures keys are always available even after a hot-reload.
if "keychain_loaded" not in st.session_state:
    load_all_keys()
    st.session_state["keychain_loaded"] = True

# Trigger auto-sync once per session (non-blocking background thread)
if "auto_sync_triggered" not in st.session_state:
    st.session_state["auto_sync_triggered"] = True
    _maybe_trigger_auto_sync()

with st.sidebar:
    st.markdown("## ⚖️ LegalPerigee")
    st.caption("Legal Case Intelligence Platform")

    # ── Live sync status widget ───────────────────────────────────────────────
    @st.fragment(run_every="8s")
    def _sync_status_widget():
        with _SYNC_LOCK:
            status  = _SYNC_STATE["status"]
            message = _SYNC_STATE["message"]
            added   = _SYNC_STATE["added"]
            updated = _SYNC_STATE["updated"]
            fin     = _SYNC_STATE["finished_at"]
            started = _SYNC_STATE["started_at"]

        if status == "running":
            elapsed = int(time.time() - started)
            short_msg = message[:55] + "…" if len(message) > 55 else message
            st.markdown(
                f'<div style="background:#0d2a1f;border:1px solid #1e5c38;border-radius:6px;'
                f'padding:6px 10px;margin:4px 0;font-size:0.78rem;color:#5ddb8a;">'
                f'🔄 <b>Syncing…</b> ({elapsed}s)<br>'
                f'<span style="color:#3a8a5c;">{short_msg}</span></div>',
                unsafe_allow_html=True,
            )
        elif status == "done" and fin:
            ago = int(time.time() - fin)
            if ago < 120:
                ago_str = f"{ago}s ago"
            elif ago < 3600:
                ago_str = f"{ago // 60}m ago"
            else:
                ago_str = f"{ago // 3600}h ago"
            st.markdown(
                f'<div style="background:#0d2218;border:1px solid #1a4a2e;border-radius:6px;'
                f'padding:5px 10px;margin:4px 0;font-size:0.78rem;color:#4db87a;">'
                f'✅ Synced {ago_str} · +{added} new, {updated} updated</div>',
                unsafe_allow_html=True,
            )
        elif status == "error":
            st.markdown(
                f'<div style="background:#2a0d0d;border:1px solid #5c1e1e;border-radius:6px;'
                f'padding:5px 10px;margin:4px 0;font-size:0.78rem;color:#e05555;">'
                f'⚠️ Sync issue — check Sync Manager</div>',
                unsafe_allow_html=True,
            )
        # else: idle — show nothing

    _sync_status_widget()

    st.divider()

    # ── Feature availability summary ─────────────────────────────────────────
    if not _check_api_key():
        st.markdown(
            """
<div style="background:#1a3a6e;border-radius:8px;padding:10px 12px;margin-bottom:10px;font-size:0.82rem;">
<b style="color:#8ab0ff;">✅ Works right now — no account needed:</b><br>
&nbsp;&nbsp;📚 Case Library (20+ sources)<br>
&nbsp;&nbsp;📄 Document Viewer<br>
&nbsp;&nbsp;🔔 Alerts<br>
&nbsp;&nbsp;📊 Legislative data + trends<br>
&nbsp;&nbsp;⚖️ Precedent search<br>
<br>
<b style="color:#f0c060;">🔑 Unlock AI features (optional):</b><br>
&nbsp;&nbsp;🔍 AI Investigation Agent<br>
&nbsp;&nbsp;🧠 AI Legal Analysis<br>
&nbsp;&nbsp;🕵️ Media Forensics
</div>
""",
            unsafe_allow_html=True,
        )

    # ── Anthropic API Key ─────────────────────────────────────────────────────
    st.markdown("### 🔑 Anthropic API Key")

    if not _valid_key(st.session_state.get("api_key", "")):
        _kc = load_key("ANTHROPIC_API_KEY")
        if _valid_key(_kc):
            st.session_state["api_key"] = _kc
            os.environ["ANTHROPIC_API_KEY"] = _kc

    if _check_api_key():
        st.success("Active ✅  *(Keychain)*", icon="🔐")

    with st.expander(
        "Change Key" if _check_api_key() else "🔑 Add Key (optional — unlocks AI)",
        expanded=not _check_api_key(),
    ):
        st.caption("Free at [console.anthropic.com](https://console.anthropic.com) → API Keys · Stored in macOS Keychain, never in any file.")
        key_in = st.text_input(
            "Paste key",
            type="password",
            placeholder="sk-ant-...",
            label_visibility="collapsed",
            key="api_key_input",
        )
        if key_in:
            key_in = key_in.strip()
            if _valid_key(key_in):
                st.session_state["api_key"] = key_in
                os.environ["ANTHROPIC_API_KEY"] = key_in
                save_key("ANTHROPIC_API_KEY", key_in)
                st.success("Key saved to Keychain ✅")
            else:
                st.error("Must start with `sk-` and be ≥ 20 characters.", icon="🔑")

    if _check_api_key():
        if st.button("🔌 Test Connection", use_container_width=True):
            with st.spinner("Verifying with Anthropic…"):
                ok, msg = _test_api_key(_get_api_key())
            if ok:
                st.success(msg)
                save_key("ANTHROPIC_API_KEY", _get_api_key())
                st.caption("🔐 Saved to macOS Keychain — persists across restarts.")
            else:
                st.error(msg)

    st.divider()

    # ── Integration Keys (all optional) ──────────────────────────────────────
    st.markdown("### 🗝️ Integration Keys")
    st.caption("All stored in macOS Keychain — never written to any file.")

    _INTEGRATIONS = [
        {
            "key":   "COURTLISTENER_API_TOKEN",
            "label": "CourtListener Token",
            "help":  "Raises rate limits. Free at [courtlistener.com/help/api](https://www.courtlistener.com/help/api/)",
            "ph":    "paste token…",
        },
        {
            "key":   "CONGRESS_API_KEY",
            "label": "Congress.gov API Key",
            "help":  "Free at [api.congress.gov](https://api.congress.gov/sign-up/)",
            "ph":    "paste key…",
        },
        {
            "key":   "OPENSTATES_API_KEY",
            "label": "OpenStates API Key",
            "help":  "All 50 state legislatures. Free at [openstates.org/accounts/login](https://openstates.org/accounts/login/)",
            "ph":    "paste key…",
        },
        {
            "key":   "REGULATIONS_GOV_KEY",
            "label": "Regulations.gov API Key",
            "help":  "Full federal dockets + public comments. Free at [api.regulations.gov](https://api.regulations.gov/)",
            "ph":    "paste key…",
        },
    ]

    with st.expander("Court & Legislative Keys", expanded=False):
        for _intg in _INTEGRATIONS:
            _existing = load_key(_intg["key"])
            _disp = "••••••••" if _existing else ""
            _new_val = st.text_input(
                _intg["label"],
                type="password",
                placeholder=_disp or _intg["ph"],
                help=_intg["help"],
                key=f"intg_{_intg['key']}",
            )
            if _new_val and _new_val.strip():
                save_key(_intg["key"], _new_val.strip())
                os.environ[_intg["key"]] = _new_val.strip()
                st.success(f"{_intg['label']} saved ✅", icon="🔐")
            elif _existing:
                os.environ.setdefault(_intg["key"], _existing)

    with st.expander("Email Alert Config", expanded=False):
        st.caption("Used to send case alert emails. Gmail: enable 2FA → App Passwords.")
        _email_from = load_key("ALERT_EMAIL_FROM")
        _new_email = st.text_input(
            "Sender Email",
            placeholder=_email_from or "you@gmail.com",
            key="intg_ALERT_EMAIL_FROM",
        )
        if _new_email and _new_email.strip():
            save_key("ALERT_EMAIL_FROM", _new_email.strip())
            os.environ["ALERT_EMAIL_FROM"] = _new_email.strip()

        _email_pw = load_key("ALERT_EMAIL_PASSWORD")
        _new_pw = st.text_input(
            "App Password",
            type="password",
            placeholder="••••••••" if _email_pw else "Gmail app password…",
            key="intg_ALERT_EMAIL_PASSWORD",
        )
        if _new_pw and _new_pw.strip():
            save_key("ALERT_EMAIL_PASSWORD", _new_pw.strip())
            os.environ["ALERT_EMAIL_PASSWORD"] = _new_pw.strip()

        _smtp_host = st.text_input(
            "SMTP Host",
            value=os.environ.get("ALERT_SMTP_HOST", "smtp.gmail.com"),
            key="intg_ALERT_SMTP_HOST",
        )
        if _smtp_host:
            os.environ["ALERT_SMTP_HOST"] = _smtp_host

        _smtp_port = st.text_input(
            "SMTP Port",
            value=os.environ.get("ALERT_SMTP_PORT", "587"),
            key="intg_ALERT_SMTP_PORT",
        )
        if _smtp_port:
            os.environ["ALERT_SMTP_PORT"] = _smtp_port

        if _email_from and _email_pw:
            st.success("Email alerts configured ✅", icon="📧")
        else:
            st.info("Enter sender email + app password to enable alerts.", icon="📧")

    st.divider()
    st.markdown("### 📌 Example Queries")
    _examples = [
        # ── Investigate tab ──────────────────────────
        "Wire fraud mortgage scheme federal cases",
        "Civil rights housing discrimination enforcement",
        "Police misconduct excessive force settlements",
        "Securities fraud Ponzi scheme",
        "Employment discrimination class action",
        "Consumer fraud predatory lending",
        "Human trafficking federal prosecutions",
        "Environmental enforcement violations",
        "Medical malpractice wrongful death",
        "Voting rights violations",
    ]
    st.markdown("### 📊 Legislative Watch Examples")
    _leg_examples = [
        "Voting access restrictions",
        "Tenant protection preemption bills",
        "Criminal justice reform legislation",
        "Housing discrimination bills",
        "Environmental justice legislation",
    ]
    for _lq in _leg_examples:
        if st.button(_lq, key=f"leg_{_lq[:18]}", use_container_width=True):
            st.session_state["lw_bill_search"] = _lq
    for _q in _examples:
        if st.button(_q, key=f"ex_{_q[:18]}", use_container_width=True):
            st.session_state["query_input"] = _q
            st.session_state["active_tab"] = "investigate"

    st.divider()
    st.markdown("""
<div class="tip-box">
<b>Platform Guide:</b><br>
🔍 <b>Investigate</b> — AI-powered case research<br>
📚 <b>Case Library</b> — Browse &amp; sync 20+ sources<br>
📊 <b>Legislative Watch</b> — Track bills &amp; waves<br>
🕵️ <b>Media Forensics</b> — Detect deepfakes &amp; AI media<br>
🔔 <b>Alerts</b> — Email alerts for new cases<br>
📂 <b>Document Viewer</b> — View any file format
</div>""", unsafe_allow_html=True)

    # ── Auto-Repair Panel ─────────────────────────────────────────────────────
    pending = get_pending_errors()
    if pending:
        st.divider()
        st.markdown(
            f'<div style="background:#c0392b;color:#fff;border-radius:6px;'
            f'padding:.5rem .8rem;font-weight:700;font-size:.85rem;">'
            f'🔧 {len(pending)} Error{"s" if len(pending)>1 else ""} Detected</div>',
            unsafe_allow_html=True,
        )
        for err in pending:
            with st.expander(
                f"❌ {err['exception_type']}: {err['exception_msg'][:50]}…",
                expanded=True,
            ):
                st.caption(f"📁 {err['primary_file']} · line {err['primary_line']}")
                if err.get("context"):
                    st.caption(f"Context: {err['context']}")

                if err.get("diagnosis"):
                    st.info(f"**Diagnosis:** {err['diagnosis']}")
                    fix = err.get("fix", {})
                    if fix.get("fix_summary"):
                        st.success(f"**Fix:** {fix['fix_summary']}")
                    # H-2: Show proposed diff and require explicit approval before writing
                    pv = preview_fix(err["id"])
                    if pv.get("patches"):
                        with st.expander(f"🔍 Review {pv['count']} proposed patch(es) before applying"):
                            for p in pv["patches"]:
                                st.caption(f"**File:** `{p.get('file','')}`")
                                st.code(f"- {p.get('removes','')[:300]}", language="diff")
                                st.code(f"+ {p.get('adds','')[:300]}", language="diff")
                        st.warning("Review the patch above carefully before approving.", icon="⚠️")
                    c1, c2 = st.columns(2)
                    with c1:
                        if st.button("✅ I reviewed the patch — Apply & Restart",
                                     key=f"apply_{err['id']}", use_container_width=True,
                                     type="primary"):
                            # H-2: Pass human_approved=True only when attorney clicks this button
                            result = apply_fix(err["id"], human_approved=True)
                            if result["success"]:
                                st.success(f"Fixed: {', '.join(result['files_changed'])}")
                                st.info("Restarting in 2 seconds…")
                                import time as _t; _t.sleep(2)
                                restart_server()
                            else:
                                st.error(f"Apply failed: {result.get('errors','')}")
                    with c2:
                        if st.button("🗑 Dismiss", key=f"dismiss_{err['id']}",
                                     use_container_width=True):
                            from utils.auto_repair import mark_fixed
                            mark_fixed(err["id"])
                            st.rerun()
                else:
                    if st.button("🔍 Diagnose & Fix",
                                 key=f"diag_{err['id']}", use_container_width=True,
                                 type="primary",
                                 disabled=not _check_api_key()):
                        with st.spinner("Sending to Claude for diagnosis…"):
                            analyze_error(err["id"], api_key=_get_api_key())
                        st.rerun()


# ── Header ────────────────────────────────────────────────────────────────────

st.markdown("""
<div class="lp-header">
  <h1>⚖️ LegalPerigee</h1>
  <p>Ethical · Analytical · Evidence-Based Legal Intelligence &nbsp;|&nbsp;
  🔍 Investigate &nbsp; 📚 Case Library &nbsp; 📊 Legislative Watch &nbsp;
  🕵️ Media Forensics &nbsp; 🔔 Alerts &nbsp; 📂 Documents</p>
</div>
""", unsafe_allow_html=True)


# ── First-run / no-key banner ─────────────────────────────────────────────────

if not _check_api_key() and not st.session_state.get("banner_dismissed"):
    with st.container():
        _col_msg, _col_x = st.columns([10, 1])
        with _col_msg:
            st.info(
                "**Welcome to LegalPerigee.** &nbsp; "
                "📚 Case Library · 📄 Document Viewer · 🔔 Alerts · 📊 Legislative data · ⚖️ Precedent search "
                "**all work right now — no account needed.** &nbsp; "
                "Add an Anthropic API key in the sidebar to also unlock AI Investigation, AI Analysis, and Media Forensics.",
                icon="⚖️",
            )
        with _col_x:
            if st.button("✕", key="dismiss_banner", help="Dismiss"):
                st.session_state["banner_dismissed"] = True
                st.rerun()

# ── Case detail dialog ────────────────────────────────────────────────────────
def _render_case_detail_page(case_id: str) -> None:
    """
    Full-page case detail view — replaces the case list when a case is selected.
    Shows ALL available data including raw_json fields per source type.
    Call inside the lib_browse_tab context.
    """
    from database.db import get_case as _gc
    import re as _re

    sel = _gc(case_id)
    if not sel:
        st.error("Case not found in database.")
        if st.button("← Back to Library"):
            st.session_state.pop("case_detail_id", None)
            st.rerun()
        return

    _D_ICONS = {
        "courtlistener": "🏛️", "harvard_cap": "📖", "oyez_scotus": "⚖️",
        "ftc": "🏢", "sec": "📈", "sec_edgar": "📊", "cfpb": "🏦",
        "eeoc": "👥", "hud": "🏠", "doj_civil_rights": "⚖️",
        "federal_register": "📋", "regulations_gov": "📝",
        "ofac_sanctions": "🚫", "congress": "🏛️", "govtrack": "🗳️",
        "openstates": "🗺️", "ny_ag": "🗽", "ca_ag": "🌴", "tx_ag": "⭐",
        "fl_ag": "🌞", "wa_ag": "🌲", "il_ag": "🏙️", "ma_ag": "🦞",
        "eurlex": "🇪🇺", "uk_ico": "🇬🇧", "canada_opc": "🇨🇦",
        "reuters_legal": "📰", "justia": "📚", "ssrn": "🎓",
        "scotusblog": "⚖️", "investigation": "🔍",
    }
    src = sel["source"] or ""
    src_icon  = _D_ICONS.get(src, "📁")
    src_label = src.replace("_", " ").upper()

    # Parse raw_json once — used throughout
    raw: dict = {}
    if sel.get("raw_json"):
        try:
            raw = json.loads(sel["raw_json"]) or {}
        except Exception:
            raw = {}

    def _clean(val):
        if not val:
            return None
        v = str(val).strip()
        if v in ("[]", "{}", "null", "None", ""):
            return None
        try:
            parsed = json.loads(v)
            if isinstance(parsed, list):
                return ", ".join(str(x) for x in parsed) if parsed else None
            if isinstance(parsed, dict):
                return ", ".join(f"{k}: {pv}" for k, pv in parsed.items()) if parsed else None
        except Exception:
            pass
        return v

    def _fmt_date(val):
        if not val:
            return "—"
        m = _re.search(r'(\w+ \d+,?\s+\d{4})', str(val))
        if m:
            return m.group(1)
        if _re.match(r'\d{4}-\d{2}-\d{2}', str(val)):
            return str(val)[:10]
        return str(val)[:24]

    def _strip_html(s: str) -> str:
        return _re.sub(r'<[^>]+>', '', s or "").strip()

    def _section(icon: str, title: str):
        st.markdown(
            f'<div class="case-section-label">{icon} {title}</div>',
            unsafe_allow_html=True,
        )

    def _body(text: str):
        st.markdown(
            f'<div class="case-section-body">{text}</div>',
            unsafe_allow_html=True,
        )

    def _kv_box(label: str, value: str, col=None):
        html = (
            f'<div class="case-party-box" style="margin-bottom:0.5rem;">'
            f'<div class="party-role">{label}</div>'
            f'<div class="party-name">{value}</div>'
            f'</div>'
        )
        (col or st).markdown(html, unsafe_allow_html=True)

    # ── Back button ───────────────────────────────────────────────────────────
    back_col, title_col = st.columns([1, 6])
    with back_col:
        if st.button("← Library", use_container_width=True):
            st.session_state.pop("case_detail_id", None)
            st.rerun()

    # ── Header ────────────────────────────────────────────────────────────────
    st.markdown(
        f'<div class="case-detail-header">'
        f'<div style="margin-bottom:0.4rem;">'
        f'<span class="source-badge">{src_icon} {src_label}</span>'
        f'</div>'
        f'<h2 style="margin:0;line-height:1.3;">{sel["case_name"] or "Untitled Case"}</h2>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── Key facts ─────────────────────────────────────────────────────────────
    kf1, kf2, kf3, kf4 = st.columns(4)
    kf1.metric("Court / Agency", _clean(sel["court"]) or "—")
    kf2.metric("Status",         _clean(sel["status"]) or "—")
    kf3.metric("Filed",          _fmt_date(sel["filing_date"]))
    kf4.metric("Decision Date",  _fmt_date(sel["decision_date"]))

    # ── Meta row ─────────────────────────────────────────────────────────────
    meta_parts = []
    if _clean(sel["docket_number"]):
        meta_parts.append(f"**Docket:** {sel['docket_number']}")
    if _clean(sel["jurisdiction"]):
        meta_parts.append(f"**Jurisdiction:** {sel['jurisdiction']}")
    if sel.get("citation"):
        try:
            cites = json.loads(sel["citation"])
            if cites:
                meta_parts.append(f"**Citation:** {', '.join(str(c) for c in cites)}")
        except Exception:
            if sel["citation"] not in ("[]", "null"):
                meta_parts.append(f"**Citation:** {sel['citation']}")
    if _clean(sel.get("judge")):
        meta_parts.append(f"**Judge:** {sel['judge']}")
    if meta_parts:
        st.markdown("  ·  ".join(meta_parts))

    # ── Primary action buttons ────────────────────────────────────────────────
    btn_cols = st.columns(4)
    _col_i = 0
    if sel.get("document_url"):
        btn_cols[_col_i].markdown(f"[🔗 View Source]({sel['document_url']})")
        _col_i += 1
    if sel.get("opinion_pdf_url"):
        btn_cols[_col_i].markdown(f"[📄 Opinion PDF]({sel['opinion_pdf_url']})")
        _col_i += 1
    # CourtListener opinion PDFs from raw_json
    for op in raw.get("opinions", []):
        dl = op.get("download_url", "")
        if dl and _col_i < 4:
            btn_cols[_col_i].markdown(f"[📄 Opinion PDF]({dl})")
            _col_i += 1
    if sel.get("document_url") and btn_cols[min(_col_i, 3)].button(
        "📂 Document Viewer", key=f"cd_docview_{case_id}", use_container_width=True
    ):
        docs = st.session_state.setdefault("documents", {})
        import httpx as _httpx
        _doc_url = sel["document_url"]
        try:
            from tools.search_tools import _validate_url as _vu
            _vu(_doc_url)
        except ValueError as _ve:
            st.error(f"URL blocked: {_ve}")
            _doc_url = None
        if _doc_url:
            try:
                with _httpx.Client(timeout=15, follow_redirects=True) as _c:
                    _r = _c.get(_doc_url)
                    fname = (sel["case_name"] or "case")[:40].replace("/", "-") + ".html"
                    docs[fname] = _r.content
                    st.session_state["documents"] = docs
                    st.session_state["selected_doc"] = fname
                    st.session_state["case_detail_id"] = None   # clear so nav works
                    st.success(f"✅ Opened in Document Viewer — click the **📂 Document Viewer** tab above to view it.")
            except Exception as _e:
                st.error(f"Could not fetch: {_e}")

    st.divider()

    # ══════════════════════════════════════════════════════════════════════════
    # MAIN CONTENT — left column (wide) + right column (metadata)
    # ══════════════════════════════════════════════════════════════════════════
    left, right = st.columns([3, 1])

    with left:
        # ── Summary ──────────────────────────────────────────────────────────
        if _clean(sel.get("summary")):
            _section("📝", "Summary")
            _body(sel["summary"])

        # ── Legal Question (Oyez) ─────────────────────────────────────────────
        q_text = _strip_html(raw.get("question", ""))
        if q_text:
            _section("❓", "Legal Question Presented")
            _body(q_text)

        # ── Description (Oyez) ───────────────────────────────────────────────
        desc = _strip_html(raw.get("description", ""))
        if desc and desc != _clean(sel.get("summary")):
            _section("📖", "Case Description")
            _body(desc)

        # ── Abstract (Federal Register) ───────────────────────────────────────
        if raw.get("abstract"):
            _section("📋", "Abstract")
            _body(raw["abstract"])

        # ── Regulatory Action (Federal Register) ──────────────────────────────
        if raw.get("action"):
            _section("📌", "Regulatory Action")
            _body(raw["action"])

        # ── Allegations / Cause of Action ────────────────────────────────────
        if _clean(sel.get("allegations")):
            _section("⚖️", "Allegations / Cause of Action")
            _body(sel["allegations"])

        # ── Procedural History (CourtListener) ───────────────────────────────
        ph = _clean(raw.get("procedural_history", ""))
        if ph:
            _section("📜", "Procedural History")
            _body(ph)

        # ── Posture (CourtListener) ───────────────────────────────────────────
        posture = _clean(raw.get("posture", ""))
        if posture:
            _section("🔄", "Case Posture")
            _body(posture)

        # ── Syllabus (CourtListener) ──────────────────────────────────────────
        syllabus = _clean(raw.get("syllabus", ""))
        if syllabus:
            _section("📑", "Syllabus")
            _body(syllabus)

        # ── Opinions & Documents (CourtListener raw) ──────────────────────────
        opinions = raw.get("opinions", [])
        if opinions:
            _section("📄", f"Opinion Documents ({len(opinions)})")
            for i, op in enumerate(opinions):
                op_label = f"Opinion {i + 1}"
                if op.get("per_curiam"):
                    op_label += " (Per Curiam)"
                with st.expander(op_label, expanded=(i == 0)):
                    op_cols = st.columns([2, 2, 1])
                    if op.get("download_url"):
                        op_cols[0].markdown(f"[📥 Download PDF]({op['download_url']})")
                    if op.get("local_path"):
                        op_cols[1].caption(f"Path: {op['local_path']}")
                    if op.get("cites"):
                        op_cols[2].caption(f"Cites {len(op['cites'])} cases")
                    # Text snippet
                    snippet = op.get("snippet", "")
                    if snippet and snippet.strip():
                        st.markdown(
                            f'<div class="case-section-body" style="font-family:monospace;'
                            f'font-size:0.82rem;white-space:pre-wrap;">'
                            f'{snippet[:2000].strip()}'
                            f'{"…" if len(snippet) > 2000 else ""}'
                            f'</div>',
                            unsafe_allow_html=True,
                        )

        # ── Congress Bill Details ─────────────────────────────────────────────
        if src in ("congress", "govtrack", "openstates"):
            la = raw.get("latestAction") or {}
            if isinstance(la, dict) and (la.get("text") or la.get("actionDate")):
                _section("🗳️", "Latest Legislative Action")
                la_date = la.get("actionDate", "")
                la_text = la.get("text", "")
                st.markdown(
                    f'<div class="case-section-body">'
                    f'{"**" + la_date + "** — " if la_date else ""}{la_text}'
                    f'</div>',
                    unsafe_allow_html=True,
                )

    with right:
        # ── Parties ──────────────────────────────────────────────────────────
        plaintiffs_v = _clean(sel.get("plaintiffs"))
        defendants_v = _clean(sel.get("defendants"))
        if plaintiffs_v or defendants_v:
            _section("👤", "Parties")
            if plaintiffs_v:
                _kv_box("Plaintiff / Complainant", plaintiffs_v)
            if defendants_v:
                _kv_box("Defendant / Respondent", defendants_v)

        # ── Case classification ───────────────────────────────────────────────
        class_parts = []
        if _clean(sel.get("case_type")):      class_parts.append(("Case Type",               _clean(sel["case_type"])))
        if _clean(sel.get("harm_types")):     class_parts.append(("Harm Types",               _clean(sel["harm_types"])))
        if _clean(sel.get("protected_classes")): class_parts.append(("Protected Classes",     _clean(sel["protected_classes"])))
        if _clean(sel.get("financial_harm")): class_parts.append(("Financial Harm / Relief",  _clean(sel["financial_harm"])))
        if class_parts:
            _section("📊", "Classification")
            for lbl, val in class_parts:
                _kv_box(lbl, val)

        # ── CourtListener extra metadata ──────────────────────────────────────
        if src == "courtlistener":
            cl_parts = []
            if raw.get("attorney"):         cl_parts.append(("Attorney(s)",     raw["attorney"]))
            if raw.get("suitNature"):       cl_parts.append(("Nature of Suit",  raw["suitNature"]))
            if raw.get("court_jurisdiction"): cl_parts.append(("Jurisdiction",  raw["court_jurisdiction"]))
            if raw.get("citeCount"):        cl_parts.append(("Times Cited",     str(raw["citeCount"])))
            if raw.get("panel_names") and raw["panel_names"]:
                cl_parts.append(("Panel Judges", ", ".join(raw["panel_names"])))
            if raw.get("lexisCite"):        cl_parts.append(("LexisCite",       raw["lexisCite"]))
            if raw.get("neutralCite"):      cl_parts.append(("Neutral Cite",    raw["neutralCite"]))
            if raw.get("scdb_id"):          cl_parts.append(("SCDB ID",         raw["scdb_id"]))
            if cl_parts:
                _section("🏛️", "CourtListener Details")
                for lbl, val in cl_parts:
                    _kv_box(lbl, str(val)[:200])
            if raw.get("absolute_url"):
                st.markdown(f"[🔗 CourtListener page](https://www.courtlistener.com{raw['absolute_url']})")

        # ── Oyez extra metadata ───────────────────────────────────────────────
        if src == "oyez_scotus":
            timeline = raw.get("timeline", [])
            if timeline:
                _section("📅", "Case Timeline")
                for evt in timeline:
                    event_name = evt.get("event", "")
                    dates = evt.get("dates", [])
                    if dates:
                        import datetime as _dt
                        try:
                            d = _dt.datetime.utcfromtimestamp(dates[0]).strftime("%b %d, %Y")
                        except Exception:
                            d = str(dates[0])
                        st.markdown(f"**{event_name}** — {d}")
                    else:
                        st.markdown(f"**{event_name}**")
            if raw.get("term"):
                _kv_box("SCOTUS Term", str(raw["term"]))
            if raw.get("view_count"):
                _kv_box("View Count", f"{raw['view_count']:,}")
            if raw.get("justia_url"):
                st.markdown(f"[🔗 Justia page]({raw['justia_url']})")

        # ── Federal Register extra ────────────────────────────────────────────
        if src == "federal_register":
            fr_parts = []
            if raw.get("type"):             fr_parts.append(("Document Type",   raw["type"]))
            if raw.get("docket_id"):        fr_parts.append(("Docket ID",       raw["docket_id"]))
            if raw.get("document_number"):  fr_parts.append(("Document Number", raw["document_number"]))
            agencies = raw.get("agencies", [])
            if agencies:
                names = [a.get("name", str(a)) if isinstance(a, dict) else str(a) for a in agencies]
                fr_parts.append(("Agencies", ", ".join(names)))
            if fr_parts:
                _section("📋", "Register Details")
                for lbl, val in fr_parts:
                    _kv_box(lbl, val[:200])

        # ── Regulations.gov extra ─────────────────────────────────────────────
        if src == "regulations_gov":
            rg_parts = []
            if raw.get("agency"):           rg_parts.append(("Agency",          raw["agency"]))
            if raw.get("comment_count"):    rg_parts.append(("Public Comments",  str(raw["comment_count"])))
            dk = raw.get("docket")
            if isinstance(dk, dict) and dk.get("id"):
                rg_parts.append(("Docket", dk["id"]))
            if rg_parts:
                _section("📝", "Regulations.gov Details")
                for lbl, val in rg_parts:
                    _kv_box(lbl, val)

        # ── Congress extra ────────────────────────────────────────────────────
        if src in ("congress", "govtrack"):
            cg_parts = []
            if raw.get("type"):            cg_parts.append(("Bill Type",      raw["type"]))
            if raw.get("number"):          cg_parts.append(("Bill Number",    str(raw["number"])))
            if raw.get("originChamber"):   cg_parts.append(("Origin Chamber", raw["originChamber"]))
            if raw.get("congress"):        cg_parts.append(("Congress",       str(raw["congress"]) + "th"))
            if raw.get("updateDate"):      cg_parts.append(("Last Updated",   raw["updateDate"][:10]))
            if cg_parts:
                _section("🏛️", "Bill Details")
                for lbl, val in cg_parts:
                    _kv_box(lbl, val)
            if raw.get("url"):
                st.markdown(f"[🔗 Congress.gov page]({raw['url']})")

        # ── Last updated ──────────────────────────────────────────────────────
        if sel.get("last_updated"):
            st.caption(f"DB updated: {sel['last_updated'][:16]}")
        st.caption(f"ID: `{case_id}`")


# ── Top-level tabs ────────────────────────────────────────────────────────────

tab_investigate, tab_library, tab_legwatch, tab_precedent, tab_forensics, tab_alerts, tab_docs = st.tabs([
    "🔍 Investigate", "📚 Case Library", "📊 Legislative Watch",
    "⚖️ Precedent", "🕵️ Media Forensics", "🔔 Alerts", "📂 Document Viewer",
])


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 1 — INVESTIGATE
# ═══════════════════════════════════════════════════════════════════════════════

with tab_investigate:
    from models.case_report import SearchFilters

    # ── Query + run button ──────────────────────────────────────────────────────
    col_q, col_btn = st.columns([5, 1])
    with col_q:
        query = st.text_area(
            "Query",
            value=st.session_state.get("query_input", ""),
            placeholder='e.g. "housing discrimination cases in California" or "wire fraud securities" or any legal matter',
            height=80,
            label_visibility="collapsed",
        )
    with col_btn:
        st.markdown("<br>", unsafe_allow_html=True)
        run_btn = st.button(
            "🔍 Investigate",
            type="primary",
            use_container_width=True,
            disabled=not _check_api_key(),
        )

    if not _check_api_key():
        st.info("**🔑 Add an Anthropic API key** in the sidebar to run AI-powered investigations.  \n*No account yet? Get one free at [console.anthropic.com](https://console.anthropic.com)*", icon="ℹ️")

    # ── Search Filters ──────────────────────────────────────────────────────────
    # fmt: off
    COURT_OPTIONS: dict[str, str] = {
        "All Courts": "",
        # Supreme Court
        "U.S. Supreme Court": "scotus",
        # Circuits
        "1st Circuit": "ca1", "2nd Circuit": "ca2", "3rd Circuit": "ca3",
        "4th Circuit": "ca4", "5th Circuit": "ca5", "6th Circuit": "ca6",
        "7th Circuit": "ca7", "8th Circuit": "ca8", "9th Circuit": "ca9",
        "10th Circuit": "ca10", "11th Circuit": "ca11",
        "DC Circuit": "cadc", "Federal Circuit": "cafc",
        # Major district courts
        "S.D.N.Y.": "nysd", "E.D.N.Y.": "nyed", "N.D.N.Y.": "nynd",
        "N.D. Cal.": "cand", "C.D. Cal.": "cacd", "S.D. Cal.": "casd",
        "D.D.C.": "dcd",
        "N.D. Ill.": "ilnd", "S.D. Ill.": "ilsd",
        "S.D. Tex.": "txsd", "N.D. Tex.": "txnd",
        "E.D. Va.": "vaed", "W.D. Va.": "vawd",
        "D. Mass.": "mad",  "N.D. Ga.": "gand",
        "M.D. Fla.": "flmd","S.D. Fla.": "flsd",
        "W.D. Wash.": "wawd",
        # State supreme courts
        "Cal. Supreme": "cal",    "N.Y. Court of Appeals": "ny",
        "Tex. Supreme": "tex",    "Fla. Supreme": "fla",
        "Ill. Supreme": "ill",    "Pa. Supreme": "pa",
        "Ohio Supreme": "ohio",   "Ga. Supreme": "ga",
    }
    # fmt: on

    CRIME_PRESETS = [
        # Fraud & financial crime
        "wire fraud", "securities fraud", "mortgage fraud",
        "insurance fraud", "bank fraud", "Ponzi scheme",
        "identity theft", "money laundering", "extortion",
        # Consumer & civil
        "consumer fraud", "predatory lending", "false advertising",
        "data privacy breach", "product liability", "medical malpractice",
        # Civil rights & discrimination
        "civil rights violation", "employment discrimination",
        "housing discrimination", "racial discrimination",
        "police misconduct", "voting rights", "disability discrimination",
        # Criminal
        "racketeering RICO", "human trafficking", "drug trafficking",
        "assault battery", "homicide", "robbery",
        # Emerging tech
        "AI fraud", "deepfake fraud", "algorithmic discrimination",
        "cybercrime", "surveillance",
        # Environmental & other
        "environmental violation", "healthcare fraud",
    ]

    PROTECTED_CLASSES = [
        "Race", "Black / African American", "Hispanic / Latino", "Asian American",
        "Native American", "White", "Sexual Orientation", "LGBTQ+",
        "Gender", "Women", "Non-binary", "Disability", "Religion",
        "National Origin", "Age", "Veteran Status", "Pregnancy",
    ]

    with st.expander("🎯 Search Filters", expanded=True):
        fc1, fc2 = st.columns(2)

        with fc1:
            crime_presets_sel = st.multiselect(
                "Crime / Issue Type",
                CRIME_PRESETS,
                key="filter_crimes",
                help="Select one or more, or type a custom term below",
            )
            crime_custom = st.text_input(
                "Custom issue type",
                placeholder="e.g. predatory lending, wage theft…",
                key="filter_crime_custom",
                label_visibility="collapsed",
            )
            crime_types = crime_presets_sel + (
                [c.strip() for c in crime_custom.split(",") if c.strip()]
            )

            area = st.text_input(
                "Area / Location",
                placeholder="e.g. California, New York City, Southern District of Texas",
                key="filter_area",
            )

        with fc2:
            protected_classes = st.multiselect(
                "Affected Group / Protected Class",
                PROTECTED_CLASSES,
                key="filter_classes",
            )

            court_label = st.selectbox(
                "Court",
                list(COURT_OPTIONS.keys()),
                key="filter_court",
            )
            court_code = COURT_OPTIONS[court_label]

        fd1, fd2, fd3 = st.columns(3)
        with fd1:
            date_from = st.text_input("Filed After", placeholder="YYYY-MM-DD", key="filter_date_from")
        with fd2:
            date_to = st.text_input("Filed Before", placeholder="YYYY-MM-DD", key="filter_date_to")
        with fd3:
            case_status = st.selectbox(
                "Case Status",
                ["Any", "Filed", "Pending", "Settled", "Dismissed", "Verdict / Judgment"],
                key="filter_status",
            )

    # Build SearchFilters from UI
    _filters = SearchFilters(
        crime_types=crime_types,
        protected_classes=[p.lower().replace(" / ", "_").replace(" ", "_") for p in protected_classes],
        area=area.strip() or None,
        court_code=court_code or None,
        court_label=court_label if court_label != "All Courts" else None,
        date_from=date_from.strip() or None,
        date_to=date_to.strip() or None,
        case_status=None if case_status == "Any" else case_status.lower(),
    )

    # If no free-text query but filters are set, auto-generate a query summary
    _effective_query = query.strip()
    if not _effective_query and not _filters.is_empty():
        _effective_query = "Cases matching: " + _filters.as_query_string()
    elif not _effective_query:
        _effective_query = ""

    # Show resolved query preview when filters active
    if not _filters.is_empty() and _effective_query:
        st.caption(f"🔍 Searching: **{_effective_query}**" + (
            f" | Filters: {_filters.as_query_string()}" if not _effective_query.startswith("Cases matching") else ""
        ))

    # ── Runner — non-blocking ───────────────────────────────────────────────────
    # Investigation runs in a daemon thread so the UI stays fully interactive.
    # A @st.fragment below polls _INVEST_STATE every 1 s for live log updates.

    if run_btn and _effective_query:
        with _INVEST_LOCK:
            already = _INVEST_STATE["status"] == "running"
        if not already:
            os.environ["ANTHROPIC_API_KEY"] = _get_api_key()
            client = anthropic.Anthropic(api_key=_get_api_key())
            _t = threading.Thread(
                target=_run_investigation_bg,
                args=(_effective_query, _filters if not _filters.is_empty() else None, client),
                daemon=True,
            )
            _t.start()
            st.rerun()

    # ── Live investigation status (polls every 1 s, non-blocking) ──────────────
    @st.fragment(run_every="1s")
    def _invest_status_widget() -> None:
        with _INVEST_LOCK:
            status   = _INVEST_STATE["status"]
            log_snap = list(_INVEST_STATE["log"])
            report   = _INVEST_STATE["report"]
            err      = _INVEST_STATE["error"]
            started  = _INVEST_STATE["started_at"]
            finished = _INVEST_STATE["finished_at"]

        if status == "running":
            elapsed = time.time() - started
            st.info(
                f"🔎 Investigation running… ({elapsed:.0f}s elapsed)  \n"
                "You can freely browse other tabs — results will appear here when done.",
                icon="⏳",
            )
            if log_snap:
                st.markdown(
                    '<div class="progress-log">'
                    + "<br>".join(log_snap[-20:])
                    + "</div>",
                    unsafe_allow_html=True,
                )

        elif status == "done" and report is not None:
            # Save to session state and store docs — only once per completion
            if st.session_state.get("_last_invest_query") != _INVEST_STATE["query"]:
                st.session_state["last_report"] = report
                st.session_state["_last_invest_query"] = _INVEST_STATE["query"]
                md_bytes   = report.to_markdown().encode()
                json_bytes = report.model_dump_json(indent=2).encode()
                _docs = st.session_state.setdefault("documents", {})
                safe_q = _INVEST_STATE["query"][:40].replace("/", "-").replace(" ", "_")
                _docs[f"report_{safe_q}.md"]   = md_bytes
                _docs[f"report_{safe_q}.json"] = json_bytes
                st.session_state["documents"] = _docs
            dur = finished - started
            st.success(
                f"✅ Found **{report.total_cases_found} cases** "
                f"({report.high_severity_count} high severity) in {dur:.0f}s",
            )

        elif status == "error" and err:
            st.error(
                f"Investigation failed: {err}  \n"
                "🔧 Go to **Auto-Repair** in the sidebar to diagnose and fix.",
                icon="❌",
            )

    _invest_status_widget()

    # ── Report display ──────────────────────────────────────────────────────────

    report = st.session_state.get("last_report")

    if report:
        import pandas as pd
        import altair as alt

        findings = report.findings
        st.divider()

        # ── Stat row ──────────────────────────────────────────────────────────
        medium_n = sum(1 for f in findings if f.severity.value == "medium")
        low_n    = sum(1 for f in findings if f.severity.value == "low")
        c1, c2, c3, c4, c5 = st.columns(5)
        for col, num, label, color in [
            (c1, report.total_cases_found, "Total Cases", "#1a2744"),
            (c2, report.high_severity_count, "High Severity", "#c0392b"),
            (c3, medium_n, "Medium Severity", "#d67f1e"),
            (c4, low_n, "Low Severity", "#27ae60"),
            (c5, len(report.sources_searched), "Sources", "#555"),
        ]:
            col.markdown(
                f'<div class="stat-card">'
                f'<div class="num" style="color:{color}">{num}</div>'
                f'<div class="lbl">{label}</div></div>',
                unsafe_allow_html=True,
            )

        st.markdown("<br>", unsafe_allow_html=True)

        # ── Citation verification banner ───────────────────────────────────────
        cv = getattr(report, "citation_verification", None)
        if cv:
            u_count = len(cv.get("unverified", []))
            v_count = len(cv.get("verified", []))
            total   = cv.get("total_checked", 0)
            if total == 0:
                st.info(f"🔍 **Citation Check:** {cv.get('note', '')}", icon="ℹ️")
            elif u_count > 0:
                st.warning(
                    f"⚠️ **Citation Check:** {v_count}/{total} citations verified — "
                    f"{u_count} unverified. {cv.get('note', '')}",
                    icon="⚠️",
                )
            else:
                st.success(
                    f"✅ **Citation Check:** All {total} citation(s) verified in CourtListener.",
                    icon="✅",
                )

        # ── Tabs ──────────────────────────────────────────────────────────────
        t_dash, t_cases, t_notes, t_md, t_json = st.tabs([
            "📊 Dashboard", "🗂 Cases", "🔬 Notes", "📄 Export", "{ } JSON"
        ])

        # ════════════════════════════════════════════════════════════════════
        # DASHBOARD TAB
        # ════════════════════════════════════════════════════════════════════
        with t_dash:
            st.markdown(f"### {report.summary}")

            if findings:
                row1_l, row1_r = st.columns(2)

                # ── Severity donut ────────────────────────────────────────
                with row1_l:
                    sev_counts = {}
                    for f in findings:
                        sev_counts[f.severity.value] = sev_counts.get(f.severity.value, 0) + 1
                    sev_df = pd.DataFrame(
                        [(k.title(), v) for k, v in sev_counts.items()],
                        columns=["Severity", "Count"],
                    )
                    sev_colors = {
                        "High": "#c0392b", "Medium": "#d67f1e",
                        "Low": "#27ae60", "Unknown": "#95a5a6",
                    }
                    sev_chart = (
                        alt.Chart(sev_df, title="Cases by Severity")
                        .mark_arc(innerRadius=55, outerRadius=90)
                        .encode(
                            theta=alt.Theta("Count:Q"),
                            color=alt.Color(
                                "Severity:N",
                                scale=alt.Scale(
                                    domain=list(sev_colors.keys()),
                                    range=list(sev_colors.values()),
                                ),
                                legend=alt.Legend(orient="bottom"),
                            ),
                            tooltip=["Severity:N", "Count:Q"],
                        )
                        .properties(height=240)
                    )
                    st.altair_chart(sev_chart, use_container_width=True)

                # ── Harm types bar ────────────────────────────────────────
                with row1_r:
                    harm_counts: dict[str, int] = {}
                    for f in findings:
                        for h in f.harm_types:
                            harm_counts[h.value.replace("_", " ").title()] = (
                                harm_counts.get(h.value.replace("_", " ").title(), 0) + 1
                            )
                    if harm_counts:
                        harm_df = pd.DataFrame(
                            sorted(harm_counts.items(), key=lambda x: -x[1]),
                            columns=["Harm Type", "Count"],
                        )
                        harm_chart = (
                            alt.Chart(harm_df, title="Harm Types")
                            .mark_bar(color="#1a2744", cornerRadiusEnd=4)
                            .encode(
                                x=alt.X("Count:Q", axis=alt.Axis(tickMinStep=1)),
                                y=alt.Y("Harm Type:N", sort="-x"),
                                tooltip=["Harm Type:N", "Count:Q"],
                            )
                            .properties(height=240)
                        )
                        st.altair_chart(harm_chart, use_container_width=True)
                    else:
                        st.info("No harm type data in findings.")

                row2_l, row2_r = st.columns(2)

                # ── Protected classes bar ────────────────────────────────
                with row2_l:
                    pc_counts: dict[str, int] = {}
                    for f in findings:
                        for p in f.protected_classes:
                            label = p.value.replace("_", " ").title()
                            pc_counts[label] = pc_counts.get(label, 0) + 1
                    if pc_counts:
                        pc_df = pd.DataFrame(
                            sorted(pc_counts.items(), key=lambda x: -x[1]),
                            columns=["Protected Class", "Count"],
                        )
                        pc_chart = (
                            alt.Chart(pc_df, title="Protected Classes Affected")
                            .mark_bar(color="#c9a84c", cornerRadiusEnd=4)
                            .encode(
                                x=alt.X("Count:Q", axis=alt.Axis(tickMinStep=1)),
                                y=alt.Y("Protected Class:N", sort="-x"),
                                tooltip=["Protected Class:N", "Count:Q"],
                            )
                            .properties(height=240)
                        )
                        st.altair_chart(pc_chart, use_container_width=True)
                    else:
                        st.caption("No protected class data in findings.")

                # ── Courts bar ───────────────────────────────────────────
                with row2_r:
                    court_counts: dict[str, int] = {}
                    for f in findings:
                        court = f.court_name or f.jurisdiction or "Unknown"
                        if court and court != "Unknown":
                            court_counts[court] = court_counts.get(court, 0) + 1
                    if court_counts:
                        ct_df = pd.DataFrame(
                            sorted(court_counts.items(), key=lambda x: -x[1])[:12],
                            columns=["Court", "Count"],
                        )
                        ct_chart = (
                            alt.Chart(ct_df, title="Cases by Court")
                            .mark_bar(color="#2c5f8a", cornerRadiusEnd=4)
                            .encode(
                                x=alt.X("Count:Q", axis=alt.Axis(tickMinStep=1)),
                                y=alt.Y("Court:N", sort="-x"),
                                tooltip=["Court:N", "Count:Q"],
                            )
                            .properties(height=240)
                        )
                        st.altair_chart(ct_chart, use_container_width=True)
                    else:
                        st.caption("No court data in findings.")

                # ── Timeline ──────────────────────────────────────────────
                dated = [
                    f for f in findings
                    if f.filing_date and len(f.filing_date) >= 4
                ]
                if len(dated) >= 2:
                    st.markdown("#### Filing Timeline")
                    tl_df = pd.DataFrame([
                        {
                            "Case": f.case_name[:40],
                            "Date": f.filing_date[:10],
                            "Severity": f.severity.value.title(),
                        }
                        for f in dated
                    ])
                    tl_df["Date"] = pd.to_datetime(tl_df["Date"], errors="coerce")
                    tl_df = tl_df.dropna(subset=["Date"]).sort_values("Date")
                    tl_chart = (
                        alt.Chart(tl_df, title="Cases Over Time")
                        .mark_circle(size=80, opacity=0.85)
                        .encode(
                            x=alt.X("Date:T", title="Filing Date"),
                            y=alt.Y("Case:N", sort=None, title=""),
                            color=alt.Color(
                                "Severity:N",
                                scale=alt.Scale(
                                    domain=["High", "Medium", "Low", "Unknown"],
                                    range=["#c0392b", "#d67f1e", "#27ae60", "#95a5a6"],
                                ),
                            ),
                            tooltip=["Case:N", "Date:T", "Severity:N"],
                        )
                        .properties(height=max(180, len(tl_df) * 32))
                    )
                    st.altair_chart(tl_chart, use_container_width=True)

            # Sources list
            if report.sources_searched:
                with st.expander("Sources searched"):
                    for s in report.sources_searched:
                        st.markdown(f"- {s}")

        # ════════════════════════════════════════════════════════════════════
        # CASES TAB — filterable cards
        # ════════════════════════════════════════════════════════════════════
        with t_cases:
            if not findings:
                st.info("No findings. Try a broader query or adjust filters.", icon="ℹ️")
            else:
                # In-results filters
                fa, fb, fc, fd = st.columns([2, 2, 2, 1])
                with fa:
                    sev_filter = st.multiselect(
                        "Severity", ["high", "medium", "low", "unknown"],
                        default=["high", "medium", "low", "unknown"],
                        key="case_sev_filter",
                    )
                with fb:
                    all_harms = sorted({
                        h.value for f in findings for h in f.harm_types
                    })
                    harm_filter = st.multiselect("Harm Type", all_harms, key="case_harm_filter")
                with fc:
                    all_courts = sorted({
                        f.court_name or f.jurisdiction or ""
                        for f in findings
                        if f.court_name or f.jurisdiction
                    })
                    court_filter = st.multiselect("Court", all_courts, key="case_court_filter")
                with fd:
                    sort_by = st.selectbox("Sort", ["Severity ↓", "Date ↓", "Date ↑", "Name"], key="case_sort")

                # Apply filters
                visible = [
                    f for f in findings
                    if f.severity.value in sev_filter
                    and (not harm_filter or any(h.value in harm_filter for h in f.harm_types))
                    and (not court_filter or (f.court_name or f.jurisdiction or "") in court_filter)
                ]

                sev_order = {"high": 0, "medium": 1, "low": 2, "unknown": 3}
                if sort_by == "Severity ↓":
                    visible.sort(key=lambda f: sev_order.get(f.severity.value, 9))
                elif sort_by == "Date ↓":
                    visible.sort(key=lambda f: f.filing_date or "", reverse=True)
                elif sort_by == "Date ↑":
                    visible.sort(key=lambda f: f.filing_date or "")
                elif sort_by == "Name":
                    visible.sort(key=lambda f: f.case_name)

                st.caption(f"Showing **{len(visible)}** of {len(findings)} cases")

                sev_border = {
                    "high": "#c0392b", "medium": "#e67e22",
                    "low": "#27ae60", "unknown": "#95a5a6",
                }

                for i, finding in enumerate(visible, 1):
                    sev = finding.severity.value
                    border = sev_border.get(sev, "#dde3ee")
                    pc_tags = " ".join(
                        f'<span style="background:#eef2ff;color:#3a4a7b;padding:1px 7px;border-radius:10px;font-size:.75rem;">'
                        f'{p.value.replace("_"," ").title()}</span>'
                        for p in finding.protected_classes
                    )
                    harm_tags = " ".join(
                        f'<span style="background:#fff4e0;color:#7a4800;padding:1px 7px;border-radius:10px;font-size:.75rem;">'
                        f'{h.value.replace("_"," ").title()}</span>'
                        for h in finding.harm_types
                    )

                    st.markdown(
                        f'<div style="border-left:5px solid {border};background:#f8f9fc;'
                        f'border-radius:8px;padding:1rem 1.4rem;margin-bottom:.6rem;">'
                        f'<div style="display:flex;justify-content:space-between;align-items:flex-start;">'
                        f'<div><strong style="font-size:1rem;color:#1a2744;">#{i} &nbsp;{finding.case_name}</strong></div>'
                        f'<div>{_badge(sev)}</div></div>'
                        f'<div style="color:#666;font-size:.82rem;margin:.3rem 0 .5rem;">'
                        f'{finding.court_name or finding.jurisdiction or "Unknown court"}'
                        f' &nbsp;·&nbsp; Filed: {finding.filing_date or "Unknown"}'
                        f' &nbsp;·&nbsp; {finding.legal_status or "Status unknown"}</div>'
                        f'<div style="margin-bottom:.4rem;">{harm_tags} {pc_tags}</div>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

                    with st.expander("View full details"):
                        d1, d2 = st.columns(2)
                        with d1:
                            st.markdown(f"**Defendant / AI Actor:** {finding.ai_actor or '—'}")
                            st.markdown(f"**Victims:** {finding.victim_description}")
                            st.markdown(f"**Verifiable Harm:** {finding.verifiable_harm}")
                        with d2:
                            st.markdown(f"**Practice Alleged:** {finding.deceptive_practice}")
                            if finding.protected_classes:
                                st.markdown(f"**Protected Classes:** {', '.join(p.value for p in finding.protected_classes)}")

                        if finding.sources:
                            st.markdown("**Sources:**")
                            for src in finding.sources:
                                link = f"[{src.title}]({src.url})" if src.url else src.title
                                st.markdown(
                                    f"- **{src.source_type}**: {link}"
                                    + (f" _{src.date}_" if src.date else "")
                                )
                                if src.excerpt:
                                    st.caption(f"> {src.excerpt[:300]}")

        # ════════════════════════════════════════════════════════════════════
        # NOTES TAB
        # ════════════════════════════════════════════════════════════════════
        with t_notes:
            st.markdown("### Investigator Notes")
            st.markdown(report.investigator_notes)

        # ════════════════════════════════════════════════════════════════════
        # EXPORT TAB
        # ════════════════════════════════════════════════════════════════════
        with t_md:
            st.markdown("#### Export Report")
            md_text   = report.to_markdown()
            json_text = report.model_dump_json(indent=2)
            e1, e2, e3, e4 = st.columns(4)
            with e1:
                st.download_button("⬇️ Markdown", data=md_text,
                    file_name="legalperigee_report.md", mime="text/markdown",
                    use_container_width=True)
            with e2:
                st.download_button("⬇️ JSON", data=json_text,
                    file_name="legalperigee_report.json", mime="application/json",
                    use_container_width=True)
            with e3:
                if st.button("⬇️ Word (.docx)", use_container_width=True, key="exp_word"):
                    from exporters.word_export import export_to_docx
                    with st.spinner("Generating Word document…"):
                        docx_bytes = export_to_docx(report)
                    st.download_button("📄 Download .docx", data=docx_bytes,
                        file_name="legalperigee_report.docx",
                        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                        use_container_width=True, key="exp_word_dl")
            with e4:
                if st.button("⬇️ PDF", use_container_width=True, key="exp_pdf"):
                    from exporters.pdf_export import export_to_pdf
                    with st.spinner("Generating PDF…"):
                        pdf_bytes = export_to_pdf(report)
                    st.download_button("📄 Download .pdf", data=pdf_bytes,
                        file_name="legalperigee_report.pdf", mime="application/pdf",
                        use_container_width=True, key="exp_pdf_dl")
            st.divider()
            st.markdown(md_text)

        # ════════════════════════════════════════════════════════════════════
        # JSON TAB
        # ════════════════════════════════════════════════════════════════════
        with t_json:
            st.code(report.model_dump_json(indent=2), language="json")

    elif not run_btn or not _effective_query:
        # ── Feature cards ──────────────────────────────────────────────────
        st.markdown("### Welcome to LegalPerigee")
        st.caption("Full-spectrum legal case intelligence — civil, criminal, regulatory, and legislative.")
        st.markdown("")

        r1c1, r1c2, r1c3 = st.columns(3)
        with r1c1:
            st.markdown("""
<div style="background:#f0f4ff;border:1px solid #c5d0e8;border-radius:10px;padding:1.1rem 1.2rem;height:170px;">
<div style="font-size:1.5rem;">🔍</div>
<strong>Investigate</strong><br>
<span style="font-size:.85rem;color:#555;">AI-powered research across CourtListener, FTC, SEC, CFPB, and the web. Enter any legal question and get a full case intelligence report.</span>
</div>""", unsafe_allow_html=True)
        with r1c2:
            st.markdown("""
<div style="background:#f0f4ff;border:1px solid #c5d0e8;border-radius:10px;padding:1.1rem 1.2rem;height:170px;">
<div style="font-size:1.5rem;">📚</div>
<strong>Case Library</strong><br>
<span style="font-size:.85rem;color:#555;">20+ sources synced locally — federal courts, all 50 state AGs, SEC EDGAR, OFAC sanctions, international enforcement, legal news.</span>
</div>""", unsafe_allow_html=True)
        with r1c3:
            st.markdown("""
<div style="background:#f0f4ff;border:1px solid #c5d0e8;border-radius:10px;padding:1.1rem 1.2rem;height:170px;">
<div style="font-size:1.5rem;">📊</div>
<strong>Legislative Watch</strong><br>
<span style="font-size:.85rem;color:#555;">Track bills across all 50 state legislatures and Congress. Detect coordinated campaigns, pre-emption threats, and fast-moving legislation.</span>
</div>""", unsafe_allow_html=True)

        st.markdown("")
        r2c1, r2c2, r2c3 = st.columns(3)
        with r2c1:
            st.markdown("""
<div style="background:#f0f4ff;border:1px solid #c5d0e8;border-radius:10px;padding:1.1rem 1.2rem;height:155px;">
<div style="font-size:1.5rem;">🕵️</div>
<strong>Media Forensics</strong><br>
<span style="font-size:.85rem;color:#555;">Detect deepfakes, AI-manipulated images, video fraud, and AI-generated text. Upload any file for Claude Vision analysis.</span>
</div>""", unsafe_allow_html=True)
        with r2c2:
            st.markdown("""
<div style="background:#f0f4ff;border:1px solid #c5d0e8;border-radius:10px;padding:1.1rem 1.2rem;height:155px;">
<div style="font-size:1.5rem;">🔔</div>
<strong>Alerts</strong><br>
<span style="font-size:.85rem;color:#555;">Set keyword + jurisdiction alert rules. Get email digests when new matching cases are found — plus real-time CourtListener notifications.</span>
</div>""", unsafe_allow_html=True)
        with r2c3:
            st.markdown("""
<div style="background:#f0f4ff;border:1px solid #c5d0e8;border-radius:10px;padding:1.1rem 1.2rem;height:155px;">
<div style="font-size:1.5rem;">📂</div>
<strong>Document Viewer</strong><br>
<span style="font-size:.85rem;color:#555;">Open and read any file: PDF, DOCX, XLSX, PPTX, HEIC, video, and more. All investigation reports save here automatically.</span>
</div>""", unsafe_allow_html=True)

        st.markdown("")
        st.info(
            "**Getting started:** Enter your Anthropic API key in the sidebar, "
            "then go to **📚 Case Library → ⬇️ Sync Manager** to populate the database.",
            icon="🚀",
        )


# ═══════════════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════════
# TAB 2 — CASE LIBRARY
# ═══════════════════════════════════════════════════════════════════════════════

with tab_library:
    from database.db import (
        count_cases, get_case, get_sync_log, init_db,
        search_cases, source_stats,
    )
    init_db()

    total = count_cases()

    # ══════════════════════════════════════════════════════════════════════════
    # SYNC MANAGER
    # ══════════════════════════════════════════════════════════════════════════
    lib_browse_tab, lib_timeline_tab2, lib_sync_tab = st.tabs([
        "🗂 Browse Cases", "📈 Timeline", "⬇️ Sync Manager"
    ])

    with lib_sync_tab:
        st.markdown("### ⬇️ Sync Manager")
        st.caption("Select sources to pull and click **Run Selected Syncs**. "
                   "Each sync adds only new cases — no duplicates.")

        # Source categories with checkboxes
        SYNC_SOURCES = {
            "🏛️ Federal Courts": [
                ("courtlistener",     "CourtListener (all federal circuits + PACER)",        True),
                ("harvard_cap",       "Harvard Caselaw Access Project (6.7M cases, all states)", True),
                ("oyez_scotus",       "SCOTUS / Oyez (Supreme Court — all terms + audio)",   True),
                ("scotusblog",        "SCOTUSblog (dockets, analysis, argument previews)",    False),
            ],
            "🏢 Federal Agencies": [
                ("ftc_sec_cfpb",      "FTC + SEC + CFPB enforcement actions",                True),
                ("eeoc_hud_doj",      "EEOC + HUD + DOJ Civil Rights Division",              True),
                ("fcc_occ",           "FCC + OCC (telecom + banking enforcement)",            False),
                ("federal_register",  "Federal Register (all proposed + final rules)",        True),
                ("regulations_gov",   "Regulations.gov (full dockets + public comments)",     True),
                ("sec_edgar",         "SEC EDGAR (8-K fraud disclosures, 10-K risk factors)", True),
                ("ofac_sanctions",    "OFAC Treasury Sanctions List (SDN — 15K+ entities)",  False),
                ("congress",          "Congress.gov — legislation (needs API key)",           False),
                ("govtrack",          "GovTrack (bills, votes, member profiles)",             True),
            ],
            "🗺️ State Courts & Legislatures": [
                ("all_states",        "All 50 State AG offices",                             False),
                ("priority_states",   "Priority State AGs: NY, CA, TX, FL, WA, IL, MA, CO, NJ, PA, OH, MI", True),
                ("state_ecourts",     "State eCourts: NY Appellate, CA, TX, FL opinions",   True),
                ("openstates",        "OpenStates — all 50 state legislatures (needs API key)", False),
            ],
            "📰 Legal News & Research": [
                ("reuters_legal",     "Reuters Legal",                                       True),
                ("above_the_law",     "Above the Law",                                       False),
                ("justia",            "Justia (free federal opinions)",                      True),
                ("ssrn",              "SSRN academic legal papers",                          False),
                ("google_scholar",    "Google Scholar case law",                             False),
            ],
            "🌍 International": [
                ("international",     "EUR-Lex (EU) + UK ICO + Canada OPC",                 True),
            ],
        }

        selected_sources = set()
        for category, sources in SYNC_SOURCES.items():
            st.markdown(f"**{category}**")
            cols = st.columns(2)
            for j, (src_id, label, default) in enumerate(sources):
                if cols[j % 2].checkbox(label, value=default, key=f"sync_chk_{src_id}"):
                    selected_sources.add(src_id)

        st.markdown("<br>", unsafe_allow_html=True)

        # ── Quick auto-sync button + background sync live log ─────────────────
        with _SYNC_LOCK:
            _bg_status = _SYNC_STATE["status"]
            _bg_msg    = _SYNC_STATE["message"]
            _bg_log    = list(_SYNC_STATE["log"])
            _bg_added  = _SYNC_STATE["added"]
            _bg_upd    = _SYNC_STATE["updated"]

        qcol1, qcol2 = st.columns([2, 3])
        with qcol1:
            quick_btn = st.button(
                "⚡ Quick Auto-Sync" if _bg_status != "running" else "🔄 Syncing…",
                disabled=(_bg_status == "running"),
                use_container_width=True,
                help=f"Runs {len(_AUTO_SYNC_SOURCES)} fast sources in background. "
                     "Does not block the UI.",
            )
        with qcol2:
            if _bg_status == "running":
                st.info(f"🔄 {_bg_msg[:60]}", icon=None)
            elif _bg_status == "done" and _SYNC_STATE["finished_at"]:
                st.success(f"✅ Last auto-sync: +{_bg_added} new, {_bg_upd} updated")
            elif _bg_status == "error":
                st.error("⚠️ Auto-sync had errors — see log below")

        if quick_btn:
            t = threading.Thread(
                target=_run_background_sync,
                args=(_AUTO_SYNC_SOURCES,),
                daemon=True,
                name="lp-manual-auto-sync",
            )
            t.start()
            st.rerun()

        if _bg_log:
            with st.expander("🔍 Auto-sync log", expanded=(_bg_status == "running")):
                st.code("\n".join(_bg_log[-40:]), language=None)

        st.divider()

        run_sync_btn = st.button(
            f"▶️ Run {len(selected_sources)} Selected Sync(s)",
            type="primary", use_container_width=True,
            disabled=not selected_sources,
        )

        if run_sync_btn and selected_sources:
            sync_log_ph = st.empty()
            sync_msgs: list[str] = []
            total_added = total_updated = 0

            def _prog(msg: str) -> None:  # noqa: E306
                sync_msgs.append(msg)
                sync_log_ph.markdown(
                    f'<div class="progress-log">{"<br>".join(sync_msgs[-30:])}</div>',
                    unsafe_allow_html=True,
                )

            # ── Run each selected sync ────────────────────────────────────────
            # Each source is wrapped in try/except so one failure never stops others.

            def _run(label, fn, *args, **kwargs):
                """Run a sync function safely, logging errors to the progress bar."""
                try:
                    return fn(*args, **kwargs)
                except Exception as _e:
                    _prog(f"  ❌ {label} error: {_e}")
                    return {"added": 0, "updated": 0}

            def _run_ab(label, fn, *args, **kwargs):
                """Run a (added, updated) returning sync function safely."""
                try:
                    return fn(*args, **kwargs)
                except Exception as _e:
                    _prog(f"  ❌ {label} error: {_e}")
                    return 0, 0

            if "courtlistener" in selected_sources:
                from aggregator.courtlistener_fetch import run_full_sync
                _prog("Starting CourtListener…")
                r = _run("CourtListener", run_full_sync, max_per_query=30, progress_cb=_prog)
                total_added += r["added"]; total_updated += r["updated"]

            if "harvard_cap" in selected_sources:
                from aggregator.caselaw_fetch import run_cap_sync
                _prog("Starting Harvard Caselaw Access Project…")
                r = _run("Harvard CAP", run_cap_sync, max_per_query=30, progress_cb=_prog)
                total_added += r["added"]; total_updated += r["updated"]

            if "oyez_scotus" in selected_sources:
                from aggregator.scotus_fetch import fetch_oyez
                _prog("Starting Oyez SCOTUS…")
                a, u = _run_ab("Oyez SCOTUS", fetch_oyez, progress_cb=_prog)
                total_added += a; total_updated += u

            if "scotusblog" in selected_sources:
                from aggregator.scotus_fetch import fetch_scotusblog
                _prog("Starting SCOTUSblog…")
                a, u = _run_ab("SCOTUSblog", fetch_scotusblog, progress_cb=_prog)
                total_added += a; total_updated += u

            if "ftc_sec_cfpb" in selected_sources:
                from aggregator.regulatory_fetch import run_regulatory_sync
                _prog("Starting FTC + SEC + CFPB…")
                r = _run("FTC/SEC/CFPB", run_regulatory_sync, progress_cb=_prog)
                total_added += r["added"]; total_updated += r["updated"]

            if "eeoc_hud_doj" in selected_sources:
                from aggregator.civil_rights_fetch import run_civil_rights_sync
                _prog("Starting EEOC + HUD + DOJ Civil Rights…")
                r = _run("EEOC/HUD/DOJ", run_civil_rights_sync, progress_cb=_prog)
                total_added += r["added"]; total_updated += r["updated"]

            if "fcc_occ" in selected_sources:
                from aggregator.civil_rights_fetch import fetch_fcc, fetch_occ
                _prog("Starting FCC + OCC…")
                a1, u1 = _run_ab("FCC", fetch_fcc, progress_cb=_prog)
                a2, u2 = _run_ab("OCC", fetch_occ, progress_cb=_prog)
                total_added += a1+a2; total_updated += u1+u2

            if "federal_register" in selected_sources:
                from aggregator.federal_register_fetch import run_federal_register_sync
                _prog("Starting Federal Register…")
                r = _run("Federal Register", run_federal_register_sync, progress_cb=_prog)
                total_added += r["added"]; total_updated += r["updated"]

            if "congress" in selected_sources:
                from aggregator.congress_fetch import run_congress_sync
                _prog("Starting Congress.gov…")
                r = _run("Congress.gov", run_congress_sync, progress_cb=_prog)
                total_added += r["added"]; total_updated += r["updated"]

            if "all_states" in selected_sources:
                from aggregator.all_states_fetch import run_all_states_sync
                _prog("Starting all 50 State AG offices…")
                r = _run("All States AG", run_all_states_sync, progress_cb=_prog)
                total_added += r["added"]; total_updated += r["updated"]

            if "priority_states" in selected_sources:
                from aggregator.all_states_fetch import run_all_states_sync
                priority = ["New York", "California", "Texas", "Florida", "Washington",
                            "Illinois", "Massachusetts", "Colorado", "New Jersey",
                            "Pennsylvania", "Ohio", "Michigan"]
                _prog(f"Starting {len(priority)} priority state AGs…")
                r = _run("Priority States AG", run_all_states_sync,
                         states=priority, progress_cb=_prog)
                total_added += r["added"]; total_updated += r["updated"]

            if "reuters_legal" in selected_sources:
                from aggregator.legal_news_fetch import fetch_reuters_legal
                _prog("Starting Reuters Legal…")
                a, u = _run_ab("Reuters Legal", fetch_reuters_legal, progress_cb=_prog)
                total_added += a; total_updated += u

            if "above_the_law" in selected_sources:
                from aggregator.legal_news_fetch import fetch_above_the_law
                _prog("Starting Above the Law…")
                a, u = _run_ab("Above the Law", fetch_above_the_law, progress_cb=_prog)
                total_added += a; total_updated += u

            if "justia" in selected_sources:
                from aggregator.legal_news_fetch import fetch_justia
                _prog("Starting Justia…")
                a, u = _run_ab("Justia", fetch_justia, progress_cb=_prog)
                total_added += a; total_updated += u

            if "ssrn" in selected_sources:
                from aggregator.legal_news_fetch import fetch_ssrn
                _prog("Starting SSRN…")
                a, u = _run_ab("SSRN", fetch_ssrn, progress_cb=_prog)
                total_added += a; total_updated += u

            if "google_scholar" in selected_sources:
                from aggregator.legal_news_fetch import fetch_google_scholar
                _prog("Starting Google Scholar (rate-limited — may skip)…")
                a, u = _run_ab("Google Scholar", fetch_google_scholar, progress_cb=_prog)
                total_added += a; total_updated += u

            # ── New sources ───────────────────────────────────────────────────
            if "regulations_gov" in selected_sources:
                from aggregator.regulations_docket_fetch import run_regulations_sync
                _prog("Starting Regulations.gov (full dockets + comments)…")
                r = _run("Regulations.gov", run_regulations_sync, progress_cb=_prog)
                total_added += r["added"]; total_updated += r["updated"]

            if "sec_edgar" in selected_sources:
                from aggregator.edgar_fetch import run_edgar_sync
                _prog("Starting SEC EDGAR (fraud disclosures + 8-K filings)…")
                r = _run("SEC EDGAR", run_edgar_sync, progress_cb=_prog)
                total_added += r["added"]; total_updated += r["updated"]

            if "ofac_sanctions" in selected_sources:
                from aggregator.ofac_fetch import run_ofac_sync
                _prog("Starting OFAC Treasury Sanctions List (large download)…")
                r = _run("OFAC", run_ofac_sync, progress_cb=_prog)
                total_added += r["added"]; total_updated += r["updated"]

            if "govtrack" in selected_sources:
                from aggregator.govtrack_fetch import run_govtrack_sync
                _prog("Starting GovTrack (bills + votes)…")
                r = _run("GovTrack", run_govtrack_sync, progress_cb=_prog)
                total_added += r["added"]; total_updated += r["updated"]

            if "openstates" in selected_sources:
                from aggregator.openstates_fetch import run_openstates_sync
                _prog("Starting OpenStates (all 50 state legislatures)…")
                r = _run("OpenStates", run_openstates_sync, progress_cb=_prog)
                total_added += r["added"]; total_updated += r["updated"]

            if "state_ecourts" in selected_sources:
                from aggregator.state_ecourts_fetch import run_state_ecourts_sync
                _prog("Starting State eCourts (NY, CA, TX, FL appellate opinions)…")
                r = _run("State eCourts", run_state_ecourts_sync, progress_cb=_prog)
                total_added += r["added"]; total_updated += r["updated"]

            if "international" in selected_sources:
                from aggregator.international_fetch import run_international_sync
                _prog("Starting International sources (EUR-Lex + UK ICO + Canada OPC)…")
                r = _run("International", run_international_sync, progress_cb=_prog)
                total_added += r["added"]; total_updated += r["updated"]

            _prog(f"✅ All syncs complete: +{total_added} new cases, {total_updated} updated")
            st.success(f"✅ Sync complete — **+{total_added}** new cases added, {total_updated} updated")
            st.rerun()

        # Congress API key notice
        if "congress" in selected_sources:
            if not os.environ.get("CONGRESS_API_KEY"):
                st.info("Congress.gov requires a free API key. "
                        "Register at [api.congress.gov](https://api.congress.gov/sign-up/) then enter it in the sidebar → **Integration Keys → Congress.gov API Key**.", icon="🗝️")

        # Sync history
        with st.expander("Sync history"):
            logs = get_sync_log(20)
            if logs:
                import pandas as _pdlog
                st.dataframe(
                    _pdlog.DataFrame(logs)[["source","started_at","cases_added","cases_updated","status","message"]],
                    use_container_width=True, hide_index=True,
                )
            else:
                st.caption("No syncs yet.")

    # ── Source stats bar ──────────────────────────────────────────────────────
    stats = source_stats()
    if stats:
        scols = st.columns(len(stats) + 1)
        source_icons = {
            # Federal courts
            "courtlistener": "🏛️", "harvard_cap": "📖",
            "oyez_scotus": "⚖️", "scotusblog": "📰",
            # Federal agencies
            "ftc": "🏢", "sec": "📈", "cfpb": "🏦",
            "sec_edgar": "📊", "eeoc": "👥", "hud": "🏠",
            "doj_civil_rights": "⚖️", "fcc": "📡", "occ": "🏦",
            "federal_register": "📋", "regulations_gov": "📝",
            "ofac_sanctions": "🚫", "congress": "🏛️",
            "govtrack": "🗳️",
            # State courts & AGs
            "ny_ag": "🗽", "ca_ag": "🌴", "tx_ag": "⭐",
            "fl_ag": "🌞", "wa_ag": "🌲", "il_ag": "🏙️",
            "ma_ag": "🦞", "co_ag": "🏔️", "nj_ag": "🌊",
            "pa_ag": "🔔", "oh_ag": "🌰", "mi_ag": "🚗",
            "ny_courts": "🏛️", "ca_courts": "⚖️",
            "tx_courts": "⚖️", "fl_courts": "⚖️",
            # Legislative
            "openstates": "🗺️",
            # International
            "eurlex": "🇪🇺", "uk_ico": "🇬🇧", "canada_opc": "🇨🇦",
            # Legal news
            "reuters_legal": "📰", "above_the_law": "⚖️",
            "justia": "📚", "ssrn": "🎓", "google_scholar": "🔍",
            # Other
            "investigation": "🔍",
        }
        _src_labels = {
            "courtlistener":"CourtListener","harvard_cap":"Harvard CAP",
            "oyez_scotus":"SCOTUS/Oyez","federal_register":"Fed Register",
            "regulations_gov":"Regulations.gov","sec_edgar":"SEC EDGAR",
            "ofac_sanctions":"OFAC Sanctions","govtrack":"GovTrack",
            "openstates":"OpenStates","eurlex":"EUR-Lex (EU)",
            "uk_ico":"UK ICO","canada_opc":"Canada OPC",
            "doj_civil_rights":"DOJ Civil Rights",
        }
        for i, s in enumerate(stats):
            icon  = source_icons.get(s["source"], "📁")
            label = _src_labels.get(s["source"],
                                    s["source"].replace("_"," ").title())
            scols[i].metric(
                f"{icon} {label}",
                f"{s['total']:,}",
                help=f"Source: {s['source']}\nLast updated: {s['last_updated'] or 'never'}",
            )
        with scols[-1]:
            st.metric("📋 Total", f"{total:,}")

        st.divider()

    with lib_timeline_tab2:
            all_cases_for_tl = search_cases(limit=2000)
            import pandas as _pd2
            import altair as _alt2
            dated_tl = [c for c in all_cases_for_tl
                        if c.get("filing_date") and len(c["filing_date"]) >= 4]
            if len(dated_tl) < 2:
                st.info("Not enough dated cases for a timeline yet. Sync more cases first.", icon="📅")
            else:
                tl_df = _pd2.DataFrame([{
                    "Date":   c["filing_date"][:10],
                    "Source": c["source"].upper(),
                    "Case":   (c["case_name"] or "")[:45],
                    "Court":  c["court"] or "Unknown",
                } for c in dated_tl])
                tl_df["Date"] = _pd2.to_datetime(tl_df["Date"], errors="coerce")
                tl_df = tl_df.dropna(subset=["Date"]).sort_values("Date")

                # Cases per month area chart
                tl_month = (tl_df.set_index("Date")
                            .resample("ME").size().reset_index())
                tl_month.columns = ["Month", "Cases"]
                area = (_alt2.Chart(tl_month, title="Cases Filed Per Month")
                        .mark_area(
                            line={"color": "#1a2744"},
                            color=_alt2.Gradient(
                                gradient="linear",
                                stops=[_alt2.GradientStop(color="#1a2744", offset=0),
                                       _alt2.GradientStop(color="#8fa3bf44", offset=1)],
                                x1=1, x2=1, y1=1, y2=0,
                            ))
                        .encode(
                            x=_alt2.X("Month:T", title="Date"),
                            y=_alt2.Y("Cases:Q", title="Cases"),
                            tooltip=["Month:T", "Cases:Q"],
                        )
                        .properties(height=280))
                st.altair_chart(area, use_container_width=True)

                # Source breakdown over time
                src_time = (_alt2.Chart(tl_df, title="Cases by Source Over Time")
                            .mark_bar(size=6)
                            .encode(
                                x=_alt2.X("yearmonth(Date):T", title=""),
                                y=_alt2.Y("count():Q", title="Count"),
                                color=_alt2.Color("Source:N",
                                    scale=_alt2.Scale(scheme="tableau10")),
                                tooltip=["yearmonth(Date):T", "Source:N", "count():Q"],
                            )
                            .properties(height=200))
                st.altair_chart(src_time, use_container_width=True)

                # Growth stats
                g1, g2, g3 = st.columns(3)
                first = tl_df["Date"].min().strftime("%Y-%m-%d")
                last  = tl_df["Date"].max().strftime("%Y-%m-%d")
                g1.metric("First case", first)
                g2.metric("Most recent", last)
                g3.metric("Date span", f"{(tl_df['Date'].max()-tl_df['Date'].min()).days:,} days")

    with lib_browse_tab:
        if total == 0:
            st.markdown("#### 📥 Library is empty — choose sources to sync")
            q1, q2, q3 = st.columns(3)
            with q1:
                st.markdown("""**🏛️ Court Records**
- CourtListener (federal)
- Harvard CAP (6.7M cases)
- SCOTUS / Oyez
- State eCourts (NY, CA, TX, FL)""")
            with q2:
                st.markdown("""**🏢 Federal Agencies**
- FTC · SEC · CFPB
- EEOC · HUD · DOJ
- SEC EDGAR (fraud filings)
- Federal Register · OFAC""")
            with q3:
                st.markdown("""**🗺️ Legislative**
- Congress.gov · GovTrack
- All 50 State AGs
- OpenStates (state bills)
- International: EU · UK · Canada""")
            st.info("👆 Go to **⬇️ Sync Manager** tab to select and run your first sync.", icon="🚀")
        else:
            # ── Router: full-page detail view OR card list ───────────────────
            # IMPORTANT: never call st.stop() here — it halts the entire script
            # and prevents other tabs (Document Viewer, etc.) from rendering.
            if st.session_state.get("case_detail_id"):
                _render_case_detail_page(st.session_state["case_detail_id"])
            else:
                # ── Search & filter bar ──────────────────────────────────────
                sa, sb, sc, sd = st.columns([3, 1, 1, 1])
                with sa:
                    lib_q = st.text_input("Search cases", placeholder="e.g. deepfake, lending, chatbot…",
                                          key="lib_search", label_visibility="collapsed")
                with sb:
                    lib_source = st.selectbox("Source", ["All"] + [s["source"] for s in stats],
                                              key="lib_source")
                with sc:
                    lib_date_from = st.text_input("From", placeholder="YYYY-MM-DD", key="lib_date_from")
                with sd:
                    lib_date_to = st.text_input("To", placeholder="YYYY-MM-DD", key="lib_date_to")

                PAGE_SIZE = 25
                page_n = st.session_state.get("lib_page", 0)

                results = search_cases(
                    q=lib_q,
                    source=None if lib_source == "All" else lib_source,
                    date_from=lib_date_from or None,
                    date_to=lib_date_to or None,
                    limit=PAGE_SIZE,
                    offset=page_n * PAGE_SIZE,
                )

                p1, p2, p3 = st.columns([1, 3, 1])
                with p1:
                    if page_n > 0 and st.button("← Prev", key="lib_prev"):
                        st.session_state["lib_page"] = page_n - 1
                        st.rerun()
                with p2:
                    st.caption(f"Page {page_n + 1} · showing {len(results)} cases")
                with p3:
                    if len(results) == PAGE_SIZE and st.button("Next →", key="lib_next"):
                        st.session_state["lib_page"] = page_n + 1
                        st.rerun()

                if not results:
                    st.info("No cases match your search.", icon="🔍")
                else:
                    # Source → icon map
                    _ICONS = {
                        "courtlistener": "🏛️", "harvard_cap": "📖", "oyez_scotus": "⚖️",
                        "ftc": "🏢", "sec": "📈", "sec_edgar": "📊", "cfpb": "🏦",
                        "eeoc": "👥", "hud": "🏠", "doj_civil_rights": "⚖️",
                        "federal_register": "📋", "regulations_gov": "📝",
                        "ofac_sanctions": "🚫", "congress": "🏛️", "govtrack": "🗳️",
                        "openstates": "🗺️", "ny_ag": "🗽", "ca_ag": "🌴", "tx_ag": "⭐",
                        "fl_ag": "🌞", "wa_ag": "🌲", "il_ag": "🏙️", "ma_ag": "🦞",
                        "eurlex": "🇪🇺", "uk_ico": "🇬🇧", "canada_opc": "🇨🇦",
                        "reuters_legal": "📰", "justia": "📚", "ssrn": "🎓",
                        "investigation": "🔍",
                    }

                    st.caption("Click any case to open full details →")

                    for case in results:
                        src_icon   = _ICONS.get(case["source"], "📁")
                        src_label  = (case["source"] or "").replace("_", " ").upper()
                        case_name  = (case["case_name"] or "Untitled")
                        court      = case["court"] or "—"
                        filed      = case["filing_date"] or "—"
                        status     = case["status"] or ""
                        summary    = case["summary"] or ""

                        # Build a rich 3-line label: title / metadata / summary snippet
                        title_line   = f"{src_icon} **{case_name[:78]}{'…' if len(case_name) > 78 else ''}**"
                        meta_line    = f"{court}  ·  {filed}  ·  `{src_label}`" + (f"  ·  *{status}*" if status else "")
                        snippet      = summary[:130].rstrip() + ("…" if len(summary) > 130 else "") if summary else ""
                        snippet_line = f"_{snippet}_" if snippet else ""

                        label_parts = [title_line, meta_line]
                        if snippet_line:
                            label_parts.append(snippet_line)
                        label = "\n".join(label_parts)

                        # Wrap in a div so CSS can scope to these buttons
                        st.markdown('<div class="case-card-btn">', unsafe_allow_html=True)
                        if st.button(label, key=f"lib_case_{case['id']}", use_container_width=True):
                            st.session_state["case_detail_id"] = case["id"]
                            st.rerun()
                        st.markdown('</div>', unsafe_allow_html=True)

    # (Sync history is in the Sync Manager tab)


# ═══════════════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════════
# TAB 3 — LEGISLATIVE WATCH
# ═══════════════════════════════════════════════════════════════════════════════

with tab_legwatch:
    from analyzers.trend_analyzer import (
        topic_trends, geographic_spread, detect_waves,
        detect_preemption_bills, fast_advancing_bills, find_similar_bills,
    )
    from analyzers.legislative_analyzer import analyze_bill, batch_triage
    from database.db import get_case, count_cases

    st.markdown("### 📊 Legislative Watch")
    st.caption(
        "Track legislative trends, detect coordinated campaigns, and identify "
        "bills that could harm communities — before they become law."
    )

    # ── Sub-tabs ──────────────────────────────────────────────────────────────
    lw_overview, lw_waves, lw_preempt, lw_fast, lw_similar, lw_analyze = st.tabs([
        "📈 Trends", "🌊 Wave Detector", "🚫 Pre-emption",
        "⚡ Fast Moving", "🔗 Coordinated Bills", "🔍 Bill Analysis"
    ])

    # ════════════════════════════════════════════════════════════════════════
    # TRENDS OVERVIEW
    # ════════════════════════════════════════════════════════════════════════
    with lw_overview:
        import pandas as _pd_lw
        import altair as _alt_lw

        leg_total = count_cases()

        col_days, col_refresh = st.columns([3,1])
        with col_days:
            days_back = st.slider("Lookback window (days)", 30, 730, 365, 30,
                                  key="lw_days")
        with col_refresh:
            st.markdown("<br>", unsafe_allow_html=True)
            run_trends = st.button("🔄 Refresh", use_container_width=True, key="lw_refresh")

        if leg_total == 0:
            st.info("No legislative data yet. Sync **Congress.gov**, **GovTrack**, "
                    "or **OpenStates** in the Case Library → Sync Manager.", icon="📥")
        else:
            with st.spinner("Analyzing trends…"):
                trends = topic_trends(days_back)
                spread = geographic_spread(min(days_back, 180))

            if not trends:
                st.info("Not enough dated bills for trend analysis. Try syncing more legislative sources.", icon="📅")
            else:
                # ── Topic activity bar ────────────────────────────────────────
                st.markdown("#### Topic Activity (all time)")
                topic_totals = {t: sum(m.values()) for t, m in trends.items()}
                topic_df = _pd_lw.DataFrame(
                    sorted(topic_totals.items(), key=lambda x: -x[1]),
                    columns=["Topic", "Bills"],
                )
                bar = (_alt_lw.Chart(topic_df, title="Bills by Topic")
                       .mark_bar(cornerRadiusEnd=4)
                       .encode(
                           x=_alt_lw.X("Bills:Q"),
                           y=_alt_lw.Y("Topic:N", sort="-x"),
                           color=_alt_lw.Color("Bills:Q",
                               scale=_alt_lw.Scale(scheme="blues")),
                           tooltip=["Topic:N","Bills:Q"],
                       ).properties(height=max(200, len(topic_df)*22)))
                st.altair_chart(bar, use_container_width=True)

                # ── Monthly trend lines for top 5 topics ─────────────────────
                st.markdown("#### Monthly Trends — Top Topics")
                top5 = sorted(topic_totals.items(), key=lambda x: -x[1])[:5]
                rows = []
                for topic, _ in top5:
                    for month, count in trends[topic].items():
                        rows.append({"Topic": topic, "Month": month, "Bills": count})
                if rows:
                    tdf = _pd_lw.DataFrame(rows)
                    tdf["Month"] = _pd_lw.to_datetime(tdf["Month"], errors="coerce")
                    tdf = tdf.dropna(subset=["Month"])
                    line = (_alt_lw.Chart(tdf, title="Bill Introductions per Month")
                            .mark_line(point=True)
                            .encode(
                                x=_alt_lw.X("Month:T", title=""),
                                y=_alt_lw.Y("Bills:Q"),
                                color="Topic:N",
                                tooltip=["Topic:N","Month:T","Bills:Q"],
                            ).properties(height=280))
                    st.altair_chart(line, use_container_width=True)

                # ── Geographic spread ─────────────────────────────────────────
                if spread:
                    st.markdown("#### Geographic Activity — Where Bills Are Moving")
                    top_topic = max(spread.items(), key=lambda x: len(x[1]), default=(None, {}))[0]
                    if top_topic:
                        topic_sel = st.selectbox("Show spread for topic",
                                                  list(spread.keys()), key="lw_geo_topic",
                                                  index=list(spread.keys()).index(top_topic) if top_topic in spread else 0)
                        geo_df = _pd_lw.DataFrame(
                            sorted(spread.get(topic_sel,{}).items(), key=lambda x: -x[1]),
                            columns=["State","Bills"]
                        )
                        if not geo_df.empty:
                            geo_bar = (_alt_lw.Chart(geo_df)
                                       .mark_bar(color="#c9a84c", cornerRadiusEnd=4)
                                       .encode(
                                           x=_alt_lw.X("Bills:Q"),
                                           y=_alt_lw.Y("State:N", sort="-x"),
                                           tooltip=["State:N","Bills:Q"],
                                       ).properties(height=min(400, len(geo_df)*22+40)))
                            st.altair_chart(geo_bar, use_container_width=True)

    # ════════════════════════════════════════════════════════════════════════
    # WAVE DETECTOR
    # ════════════════════════════════════════════════════════════════════════
    with lw_waves:
        st.markdown("#### 🌊 Coordinated Legislative Wave Detector")
        st.caption(
            "Detects when the same topic appears in 3+ states within the lookback window — "
            "the signature of coordinated model-legislation campaigns."
        )

        wave_days = st.slider("Detection window (days)", 30, 180, 90, key="lw_wave_days")
        min_states = st.slider("Minimum states to flag", 2, 10, 3, key="lw_min_states")

        with st.spinner("Scanning for legislative waves…"):
            waves = detect_waves(wave_days, min_states)

        if not waves:
            st.success("No legislative waves detected in this window. "
                       "Try syncing more state legislative data.", icon="✅")
        else:
            st.warning(f"**{len(waves)} active wave(s) detected** across {wave_days}-day window", icon="🌊")
            for wave in waves:
                sev = wave["severity"]
                sev_color = {"HIGH": "#c0392b", "MEDIUM": "#d67f1e", "WATCH": "#27ae60"}
                border = sev_color.get(sev, "#888")
                st.markdown(
                    f'<div style="border-left:5px solid {border};background:#f8f9fc;'
                    f'border-radius:8px;padding:1rem 1.4rem;margin-bottom:.8rem;">'
                    f'<strong style="font-size:1rem;color:#1a2744;">{wave["topic"]}</strong>'
                    f'&nbsp;&nbsp;<span style="background:{border};color:#fff;padding:2px 10px;'
                    f'border-radius:10px;font-size:.75rem;font-weight:700;">{sev}</span><br>'
                    f'<span style="color:#555;font-size:.85rem;">'
                    f'{wave["state_count"]} states · {wave["total_bills"]} total bills</span><br>'
                    f'<span style="color:#888;font-size:.82rem;">States: {", ".join(wave["states"][:10])}'
                    f'{"…" if len(wave["states"])>10 else ""}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                with st.expander(f"Sample bills in this wave ({len(wave['sample_bills'])} shown)"):
                    for b in wave["sample_bills"]:
                        url  = b.get("document_url","")
                        name = b.get("case_name","")[:80]
                        state = b.get("jurisdiction","")
                        date  = b.get("filing_date","")
                        line  = f"**{state}** · {name}"
                        if url:
                            line += f" — [View]({url})"
                        st.markdown(f"- {line} _{date}_")

    # ════════════════════════════════════════════════════════════════════════
    # PRE-EMPTION TRACKER
    # ════════════════════════════════════════════════════════════════════════
    with lw_preempt:
        st.markdown("#### 🚫 Pre-emption Bill Tracker")
        st.caption(
            "Bills that strip local governments of authority — often the most dangerous "
            "for communities because one state bill can void every city ordinance simultaneously."
        )

        preempt_days = st.slider("Lookback (days)", 30, 365, 180, key="lw_preempt_days")

        with st.spinner("Scanning for pre-emption bills…"):
            preempt_bills = detect_preemption_bills(preempt_days)

        if not preempt_bills:
            st.success("No pre-emption bills detected in this window.", icon="✅")
        else:
            st.error(f"**{len(preempt_bills)} pre-emption bill(s) found** — "
                     "these remove local government authority", icon="🚫")
            for bill in preempt_bills[:20]:
                topics_str = ", ".join(bill["topics"][:3]) or "General"
                st.markdown(
                    f'<div style="border-left:5px solid #c0392b;background:#fff5f5;'
                    f'border-radius:8px;padding:.9rem 1.3rem;margin-bottom:.6rem;">'
                    f'<strong>{bill["case_name"][:100]}</strong><br>'
                    f'<span style="color:#888;font-size:.83rem;">'
                    f'{bill["state"]} · {bill["filing_date"]} · {bill["status"][:80]}</span><br>'
                    f'<span style="color:#c0392b;font-size:.82rem;">Topics: {topics_str}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                if bill.get("document_url"):
                    st.markdown(f"  [View bill]({bill['document_url']})")

    # ════════════════════════════════════════════════════════════════════════
    # FAST-MOVING BILLS
    # ════════════════════════════════════════════════════════════════════════
    with lw_fast:
        st.markdown("#### ⚡ Fast-Moving Bills")
        st.caption(
            "Bills that have advanced to committee, floor vote, or passage recently — "
            "these require immediate community attention."
        )

        with st.spinner("Finding fast-advancing bills…"):
            fast_bills = fast_advancing_bills(30)

        if not fast_bills:
            st.info("No fast-advancing bills detected in the last 30 days.", icon="ℹ️")
        else:
            st.warning(f"**{len(fast_bills)} bills advanced in the last 30 days**", icon="⚡")
            for bill in fast_bills[:25]:
                topics_str = ", ".join(bill["topics"][:3]) or "—"
                status = bill.get("status","")[:80]
                urgent = any(k in status.lower() for k in ["pass","sign","enact","chapter"])
                color  = "#c0392b" if urgent else "#d67f1e"
                st.markdown(
                    f'<div style="border-left:4px solid {color};background:#f8f9fc;'
                    f'border-radius:8px;padding:.8rem 1.2rem;margin-bottom:.5rem;">'
                    f'<strong>{bill["case_name"][:100]}</strong><br>'
                    f'<span style="color:#888;font-size:.83rem;">'
                    f'{bill["state"]} · {bill["filing_date"]}</span><br>'
                    f'<span style="color:{color};font-size:.82rem;font-weight:600;">{status}</span><br>'
                    f'<span style="color:#555;font-size:.8rem;">Topics: {topics_str}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )

    # ════════════════════════════════════════════════════════════════════════
    # SIMILAR / COORDINATED BILLS
    # ════════════════════════════════════════════════════════════════════════
    with lw_similar:
        st.markdown("#### 🔗 Coordinated Model Legislation Detector")
        st.caption(
            "Bills with near-identical text across multiple states — "
            "the fingerprint of coordinated campaigns using model legislation."
        )

        sim_threshold = st.slider("Similarity threshold", 0.4, 0.9, 0.6, 0.05,
                                   key="lw_sim", help="Higher = more similar required")

        with st.spinner("Scanning for similar bill text across states…"):
            clusters = find_similar_bills(sim_threshold)

        if not clusters:
            st.info("No near-duplicate bills found at this threshold.", icon="✅")
        else:
            st.warning(f"**{len(clusters)} cluster(s) of similar bills** across multiple states", icon="🔗")
            for cluster in clusters:
                topics_str = ", ".join(cluster["topics"][:3]) or "—"
                st.markdown(
                    f'<div style="border-left:4px solid #7b2d8b;background:#f9f5ff;'
                    f'border-radius:8px;padding:1rem 1.4rem;margin-bottom:.8rem;">'
                    f'<strong>{cluster["lead_bill"]}</strong><br>'
                    f'<span style="color:#888;font-size:.83rem;">'
                    f'{cluster["state_count"]} states · {cluster["bill_count"]} bills · '
                    f'Topics: {topics_str}</span><br>'
                    f'<span style="color:#7b2d8b;font-size:.81rem;">{cluster["warning"]}</span><br>'
                    f'<span style="color:#555;font-size:.81rem;">States: {", ".join(cluster["states"])}</span>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
                with st.expander(f"Bills in this cluster ({cluster['bill_count']})"):
                    for b in cluster["bills"]:
                        url   = b.get("document_url","")
                        name  = b.get("case_name","")[:80]
                        state = b.get("jurisdiction","")
                        date  = b.get("filing_date","")
                        line  = f"**{state}** · {name} _{date}_"
                        if url: line += f" — [View]({url})"
                        st.markdown(f"- {line}")

    # ════════════════════════════════════════════════════════════════════════
    # AI BILL ANALYSIS
    # ════════════════════════════════════════════════════════════════════════
    with lw_analyze:
        st.markdown("#### 🔍 AI Community Impact Analysis")
        st.caption(
            "Claude analyzes any bill for community harm, protected class implications, "
            "constitutional concerns, and specific mobilization actions."
        )

        if not _check_api_key():
            st.info("**🔑 AI bill analysis** requires an Anthropic API key (sidebar).  \nThe data browsing, trends, and wave detection above work without a key.", icon="ℹ️")
        else:
            # ── Select a bill ──────────────────────────────────────────────
            ana_col1, ana_col2 = st.columns([3,1])
            with ana_col1:
                bill_search = st.text_input("Search for a bill to analyze",
                                            placeholder="e.g. voting rights Texas, housing preemption",
                                            key="lw_bill_search")
            with ana_col2:
                st.markdown("<br>", unsafe_allow_html=True)
                search_btn = st.button("🔍 Find Bills", use_container_width=True, key="lw_search_btn")

            if search_btn and bill_search:
                from database.db import search_cases
                candidates = search_cases(
                    q=bill_search,
                    case_type="legislation",
                    limit=10,
                )
                # Also search without type filter
                if not candidates:
                    candidates = search_cases(q=bill_search, limit=10)
                candidates = [c for c in candidates
                              if any(t in (c.get("case_type","") or "").lower()
                                     for t in ["legislat","bill","vote","act"])
                              or c.get("source") in {"congress","govtrack","openstates"}]
                st.session_state["lw_candidates"] = candidates

            candidates = st.session_state.get("lw_candidates", [])
            if candidates:
                bill_options = {
                    f"{c.get('jurisdiction','?')} — {c.get('case_name','?')[:80]}": c
                    for c in candidates
                }
                selected_label = st.selectbox("Select bill", list(bill_options.keys()), key="lw_bill_sel")
                selected_bill  = bill_options[selected_label]

                if st.button("🤖 Run Community Impact Analysis", type="primary",
                             use_container_width=True, key="lw_analyze_btn"):
                    with st.spinner("Analyzing bill for community impact…"):
                        import anthropic as _ant_lw
                        analysis = analyze_bill(
                            selected_bill,
                            client=_ant_lw.Anthropic(api_key=_get_api_key()),
                        )
                    st.session_state["lw_analysis"] = analysis

            # ── Show analysis results ──────────────────────────────────────
            analysis = st.session_state.get("lw_analysis")
            if analysis:
                if analysis.get("error"):
                    st.error(f"Analysis error: {analysis['error']}")
                else:
                    sev   = analysis.get("harm_severity","UNCLEAR")
                    sev_c = {"CRITICAL":"#c0392b","HIGH":"#d67f1e",
                             "MEDIUM":"#f39c12","LOW":"#27ae60"}.get(sev,"#888")

                    # Header
                    st.markdown(
                        f'<div style="background:#1a2744;border-radius:8px;padding:1.2rem 1.5rem;'
                        f'margin-bottom:1rem;border-left:5px solid {sev_c};">'
                        f'<span style="color:#e8d9b0;font-size:1rem;font-weight:700;">'
                        f'{analysis.get("bill_name","")[:80]}</span><br>'
                        f'<span style="background:{sev_c};color:#fff;padding:2px 12px;'
                        f'border-radius:10px;font-size:.8rem;font-weight:700;">{sev} HARM</span>'
                        f'&nbsp;&nbsp;<span style="color:#8fa3bf;font-size:.85rem;">'
                        f'{analysis.get("time_sensitivity","")}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

                    # Summary
                    if analysis.get("plain_english_summary"):
                        st.info(analysis["plain_english_summary"])

                    # Who benefits / who is harmed
                    b_col, h_col = st.columns(2)
                    with b_col:
                        st.markdown("**✅ Who Benefits:**")
                        for item in analysis.get("who_benefits", []):
                            st.markdown(f"- {item}")
                    with h_col:
                        st.markdown("**🔴 Who Is Harmed:**")
                        for item in analysis.get("who_is_harmed", []):
                            st.markdown(f"- {item}")

                    st.divider()

                    # Protected classes + pre-emption
                    p_col, pe_col = st.columns(2)
                    with p_col:
                        if analysis.get("protected_classes_affected"):
                            st.markdown("**Protected Classes Affected:**")
                            st.markdown(", ".join(analysis["protected_classes_affected"]))
                        if analysis.get("constitutional_concerns"):
                            st.markdown("**⚖️ Constitutional Concerns:**")
                            for c in analysis["constitutional_concerns"]:
                                st.markdown(f"- {c}")
                    with pe_col:
                        if analysis.get("is_preemption"):
                            st.error(f"🚫 **PRE-EMPTION BILL**: {analysis.get('preemption_scope','')}")
                        if analysis.get("historical_precedents"):
                            st.markdown("**📚 Historical Precedents:**")
                            for p in analysis["historical_precedents"][:3]:
                                st.markdown(f"- {p}")

                    # Mobilization actions
                    if analysis.get("mobilization_actions"):
                        st.markdown("#### 🚨 Mobilization Actions")
                        for action in analysis["mobilization_actions"]:
                            st.markdown(f"- **{action}**")

                    if analysis.get("contact_targets"):
                        st.markdown("**Who to Contact:**")
                        for contact in analysis["contact_targets"]:
                            st.markdown(f"- {contact}")

                    if analysis.get("investigator_notes"):
                        with st.expander("🔬 Investigator Notes"):
                            st.markdown(analysis["investigator_notes"])

                    # Save to doc viewer
                    docs = st.session_state.setdefault("documents", {})
                    import json as _json_lw
                    rname = f"bill_analysis_{Path(analysis.get('bill_name','bill')).stem[:30]}.json"
                    docs[rname] = _json_lw.dumps(analysis, indent=2).encode()
                    st.session_state["documents"] = docs
                    st.caption(f"💾 Analysis saved to Document Viewer: {rname}")

            # ── Batch triage ───────────────────────────────────────────────
            st.divider()
            st.markdown("#### ⚡ Batch Triage — Fast Scan 10 Bills")
            st.caption("Quickly rate the harm potential of the most recent legislative bills in the database.")
            if st.button("▶️ Run Batch Triage", use_container_width=True, key="lw_triage_btn"):
                from database.db import search_cases as _sc_lw
                recent = [b for b in _sc_lw(limit=30)
                          if b.get("source") in {"congress","govtrack","openstates"}
                          or "legislat" in (b.get("case_type","") or "").lower()][:10]
                if not recent:
                    st.info("No legislative bills in database. Sync Congress.gov or OpenStates first.", icon="📥")
                else:
                    with st.spinner(f"Triaging {len(recent)} bills…"):
                        import anthropic as _ant_lw2
                        triaged = batch_triage(recent, _ant_lw2.Anthropic(api_key=_get_api_key()))

                    for bill in triaged:
                        t = bill.get("_triage", {})
                        sev   = t.get("harm_severity","UNCLEAR")
                        sev_c = {"CRITICAL":"#c0392b","HIGH":"#d67f1e","MEDIUM":"#f39c12","LOW":"#27ae60"}.get(sev,"#888")
                        urgent = t.get("requires_immediate_action", False)
                        st.markdown(
                            f'<div style="border-left:4px solid {sev_c};padding:.6rem .9rem;'
                            f'background:#f8f9fc;border-radius:6px;margin-bottom:.4rem;">'
                            f'<span style="font-weight:600;">{bill.get("case_name","")[:80]}</span>&nbsp;'
                            f'<span style="background:{sev_c};color:#fff;padding:1px 8px;'
                            f'border-radius:8px;font-size:.75rem;">{sev}</span>'
                            f'{"&nbsp;🚨 URGENT" if urgent else ""}<br>'
                            f'<span style="color:#666;font-size:.82rem;">{t.get("one_line_concern","")}</span>'
                            f'</div>',
                            unsafe_allow_html=True,
                        )


# ═══════════════════════════════════════════════════════════════════════════════
# ═══════════════════════════════════════════════════════════════════════════════
# TAB — PRECEDENT RESEARCH
# ═══════════════════════════════════════════════════════════════════════════════

with tab_precedent:
    from analyzers.precedent_analyzer import (
        search_cases_cl, search_cases_cap,
        get_citing_cases, compare_cases, analyze_legal_evolution,
    )

    st.markdown("### ⚖️ Precedent Research")
    st.caption(
        "Search old and new cases, compare rulings across eras, trace citation chains, "
        "and use AI to analyze how legal standards have evolved."
    )

    prec_mode = st.radio(
        "Mode",
        ["🔎 Discover Precedents", "🔍 Compare Two Cases",
         "📈 Legal Evolution (Topic Over Time)", "🔗 Citation Chain"],
        horizontal=True,
        key="prec_mode",
    )
    st.divider()

    # ════════════════════════════════════════════════════════════════════════
    # ════════════════════════════════════════════════════════════════════════
    # MODE 0 — DISCOVER PRECEDENTS
    # ════════════════════════════════════════════════════════════════════════
    if prec_mode == "🔎 Discover Precedents":
        from analyzers.precedent_analyzer import discover_precedents

        st.markdown("#### 🔎 Describe your situation — we'll find the relevant precedents")
        st.caption(
            "You don't need to know the case names. Describe the legal situation in plain English. "
            "Claude will identify the legal issues, generate precise search queries, search "
            "CourtListener and the Harvard CAP archive, then rank and explain the most "
            "relevant cases — from landmark rulings to recent decisions."
        )

        disco_situation = st.text_area(
            "Describe the legal situation",
            height=130,
            placeholder=(
                "Examples:\n"
                "• A landlord used an algorithm to screen tenants and it disproportionately rejected Black applicants\n"
                "• Police searched a suspect's phone without a warrant after a traffic stop\n"
                "• An employer fired someone for organizing coworkers on social media\n"
                "• A company used facial recognition to track employees without consent\n"
                "• A municipality is trying to ban a community organization from public parks"
            ),
            key="disco_situation",
        )

        disco_col1, disco_col2 = st.columns([2,1])
        with disco_col1:
            st.caption(
                "The more detail you provide — jurisdiction, type of harm, parties involved, "
                "relevant laws if known — the better the results."
            )
        with disco_col2:
            disco_btn = st.button(
                "🔎 Find Precedents",
                type="primary",
                use_container_width=True,
                disabled=not (disco_situation.strip() and _check_api_key()),
                key="disco_btn",
            )

        if not _check_api_key():
            st.info("**🔑 AI precedent discovery** requires an Anthropic API key (sidebar).  \nThe CourtListener search results above work without a key.", icon="ℹ️")

        if disco_btn and disco_situation.strip():
            st.session_state.pop("disco_result", None)
            steps_ph = st.empty()
            steps_ph.info("Step 1/3 — Identifying legal issues…", icon="🧠")

            with st.spinner("Searching for precedents across legal history…"):
                import anthropic as _ant_disco
                result = discover_precedents(
                    disco_situation.strip(),
                    client=_ant_disco.Anthropic(api_key=_get_api_key()),
                )
            steps_ph.empty()
            st.session_state["disco_result"] = result

        result = st.session_state.get("disco_result")

        if result and result.get("error"):
            st.error(f"Search error: {result['error']}")
            if result.get("plan"):
                with st.expander("Debug — analysis plan"):
                    st.json(result["plan"])

        elif result:
            # ── Summary header ────────────────────────────────────────────
            issues   = result.get("core_legal_issues", [])
            area     = result.get("primary_legal_area", "")
            statutes = result.get("key_statutes", [])
            total    = result.get("total_searched", 0)
            ranked   = result.get("ranked_precedents", [])
            note     = result.get("investigator_note","")

            st.markdown(
                f'<div style="background:#1a2744;border-radius:10px;padding:1rem 1.4rem;'
                f'margin-bottom:1rem;border-left:5px solid #c9a84c;">'
                f'<span style="color:#c9a84c;font-weight:700;font-size:.95rem;">Legal Area: </span>'
                f'<span style="color:#e8d9b0;">{area}</span><br>'
                f'<span style="color:#8fa3bf;font-size:.83rem;">Searched {total} cases · '
                f'Found {len(ranked)} relevant precedents</span>'
                f'</div>',
                unsafe_allow_html=True,
            )

            if issues:
                st.markdown("**Core Legal Issues Identified:**")
                for iss in issues:
                    st.markdown(f"- {iss}")

            if statutes:
                st.caption(f"Relevant statutes: {' · '.join(statutes)}")

            if note:
                st.info(f"**Investigator Note:** {note}")

            st.divider()

            # ── Ranked precedents ─────────────────────────────────────────
            if not ranked:
                st.warning("No strongly relevant precedents found. Try adding more detail to your description.", icon="🔍")
            else:
                st.markdown(f"#### Top {len(ranked)} Precedents — ranked by relevance")

                era_colors = {
                    "landmark":    "#c0392b",
                    "foundational":"#d67f1e",
                    "recent":      "#2c5f8a",
                    "current":     "#27ae60",
                }

                for i, case in enumerate(ranked, 1):
                    score = int(case.get("relevance_score", 0))
                    era   = case.get("era","").lower()
                    ec    = era_colors.get(era, "#888")
                    score_bar = "█" * min(score,10) + "░" * (10-min(score,10))

                    st.markdown(
                        f'<div style="border-left:5px solid {ec};background:#f8f9fc;'
                        f'border-radius:8px;padding:1rem 1.4rem;margin-bottom:.7rem;">'
                        f'<div style="display:flex;justify-content:space-between;align-items:flex-start;">'
                        f'<strong style="color:#1a2744;font-size:1rem;">#{i} &nbsp;{case.get("case_name","?")}</strong>'
                        f'<span style="font-size:.75rem;color:{ec};">{era.upper()}</span>'
                        f'</div>'
                        f'<span style="color:#888;font-size:.82rem;">'
                        f'{case.get("court","")} · {case.get("date_decided","?")[:4]}</span><br>'
                        f'<span style="font-family:monospace;font-size:.75rem;color:{ec};">'
                        f'{score_bar}</span> '
                        f'<span style="font-size:.78rem;color:#555;">Relevance {score}/10</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

                    with st.expander(f"📋 Why this case matters"):
                        st.markdown(f"**Relevance:** {case.get('relevance_explanation','')}")
                        st.markdown(f"**Legal Principle:** {case.get('legal_principle','')}")
                        st.markdown(f"**How to Use:** {case.get('how_to_use','')}")
                        if case.get("url"):
                            st.markdown(f"[🔗 View full case]({case['url']})")

                # ── Quick-compare any two ─────────────────────────────────
                st.divider()
                st.markdown("#### Compare any two from these results")
                opts_map = {
                    f"#{i} {c.get('case_name','?')[:60]} ({c.get('date_decided','?')[:4]})": c
                    for i, c in enumerate(ranked, 1)
                }
                opt_keys = list(opts_map.keys())
                if len(opt_keys) >= 2:
                    qc1, qc2, qc3 = st.columns([2,2,1])
                    with qc1:
                        sel_a_lbl = st.selectbox("Case A (reference)", opt_keys,
                                                  index=0, key="disco_sel_a")
                    with qc2:
                        sel_b_lbl = st.selectbox("Case B (comparison)", opt_keys,
                                                  index=min(1, len(opt_keys)-1),
                                                  key="disco_sel_b")
                    with qc3:
                        st.markdown("<br>", unsafe_allow_html=True)
                        quick_cmp = st.button("⚖️ Compare", use_container_width=True,
                                              key="disco_quick_cmp")

                    if quick_cmp:
                        case_a = opts_map[sel_a_lbl]
                        case_b = opts_map[sel_b_lbl]
                        with st.spinner("Comparing cases…"):
                            import anthropic as _ant_qcmp
                            cmp_result = compare_cases(
                                case_a, case_b,
                                client=_ant_qcmp.Anthropic(api_key=_get_api_key()),
                            )
                        st.session_state["prec_comparison"] = cmp_result
                        st.session_state["prec_cmp_a"] = case_a
                        st.session_state["prec_cmp_b"] = case_b
                        st.session_state["show_disco_cmp"] = True

                # Show comparison result if triggered from discover mode
                if st.session_state.get("show_disco_cmp"):
                    cmp = st.session_state.get("prec_comparison",{})
                    case_a = st.session_state.get("prec_cmp_a",{})
                    case_b = st.session_state.get("prec_cmp_b",{})
                    if cmp and not cmp.get("error"):
                        rel = cmp.get("precedent_relationship","?").upper()
                        rel_c = {"CONTROLLING":"#c0392b","PERSUASIVE":"#d67f1e",
                                 "DISTINGUISHED":"#7b2d8b","OVERRULED":"#c0392b",
                                 "PARALLEL":"#27ae60","UNRELATED":"#888"}.get(rel,"#888")
                        st.markdown(
                            f'<div style="background:#1a2744;border-radius:8px;padding:1rem 1.4rem;'
                            f'border-left:5px solid {rel_c};margin-top:.8rem;">'
                            f'<span style="color:#e8d9b0;font-weight:700;">Precedent: </span>'
                            f'<span style="background:{rel_c};color:#fff;padding:2px 12px;'
                            f'border-radius:10px;font-size:.85rem;">{rel}</span></div>',
                            unsafe_allow_html=True,
                        )
                        if cmp.get("key_shift"):
                            st.warning(f"**Key Legal Shift:** {cmp['key_shift']}", icon="⚖️")
                        h_a, h_b = st.columns(2)
                        with h_a:
                            st.markdown(f"**{case_a.get('case_name','A')[:50]}**")
                            st.markdown(cmp.get("case_a_holding","—"))
                        with h_b:
                            st.markdown(f"**{case_b.get('case_name','B')[:50]}**")
                            st.markdown(cmp.get("case_b_holding","—"))
                        if cmp.get("legal_evolution"):
                            st.markdown("**Legal Evolution:**")
                            st.markdown(cmp["legal_evolution"])
                        if cmp.get("strategic_notes"):
                            with st.expander("⚖️ Strategic Notes"):
                                st.markdown(cmp["strategic_notes"])

    # MODE 1 — COMPARE TWO CASES
    # ════════════════════════════════════════════════════════════════════════
    elif prec_mode == "🔍 Compare Two Cases":
        st.markdown("#### Find and compare any two cases to analyze their precedent relationship")
        st.caption("Search by case name, legal issue, citation, or keyword. "
                   "Use date ranges to find old vs. new cases.")

        col_a, col_b = st.columns(2)

        with col_a:
            st.markdown("**📜 Case A — Older / Reference Case**")
            prec_query_a   = st.text_input("Search", placeholder="e.g. Brown v Board of Education, 347 U.S. 483",
                                           key="prec_qa")
            prec_date_a_mn = st.text_input("Decided after",  placeholder="YYYY (e.g. 1950)", key="prec_da_min")
            prec_date_a_mx = st.text_input("Decided before", placeholder="YYYY (e.g. 1990)", key="prec_da_max")
            prec_source_a  = st.radio("Source", ["CourtListener", "Harvard CAP (historical)"],
                                       key="prec_src_a", horizontal=True)
            search_a_btn   = st.button("🔍 Search", key="prec_srch_a", use_container_width=True)

        with col_b:
            st.markdown("**📄 Case B — Newer / Comparison Case**")
            prec_query_b   = st.text_input("Search", placeholder="e.g. Students for Fair Admissions v Harvard",
                                           key="prec_qb")
            prec_date_b_mn = st.text_input("Decided after",  placeholder="YYYY (e.g. 2000)", key="prec_db_min")
            prec_date_b_mx = st.text_input("Decided before", placeholder="YYYY", key="prec_db_max")
            prec_source_b  = st.radio("Source", ["CourtListener", "Harvard CAP (historical)"],
                                       key="prec_src_b", horizontal=True)
            search_b_btn   = st.button("🔍 Search", key="prec_srch_b", use_container_width=True)

        # ── Search handlers ───────────────────────────────────────────────────
        def _year_to_date(y, suffix="-01-01"):
            return f"{y.strip()}{suffix}" if y and y.strip().isdigit() else None

        if search_a_btn and prec_query_a:
            with st.spinner("Searching…"):
                fn = search_cases_cap if "Harvard" in prec_source_a else search_cases_cl
                st.session_state["prec_results_a"] = fn(
                    prec_query_a,
                    date_min=_year_to_date(prec_date_a_mn),
                    date_max=_year_to_date(prec_date_a_mx, "-12-31"),
                )

        if search_b_btn and prec_query_b:
            with st.spinner("Searching…"):
                fn = search_cases_cap if "Harvard" in prec_source_b else search_cases_cl
                st.session_state["prec_results_b"] = fn(
                    prec_query_b,
                    date_min=_year_to_date(prec_date_b_mn),
                    date_max=_year_to_date(prec_date_b_mx, "-12-31"),
                )

        # ── Case selectors ────────────────────────────────────────────────────
        results_a = st.session_state.get("prec_results_a", [])
        results_b = st.session_state.get("prec_results_b", [])

        col_sel_a, col_sel_b = st.columns(2)
        selected_a = selected_b = None

        with col_sel_a:
            if results_a:
                opts_a = {f"{c['case_name'][:60]} ({c['date_decided'][:4]})": c for c in results_a}
                sel_label_a = st.selectbox("Select Case A", list(opts_a.keys()), key="prec_sel_a")
                selected_a  = opts_a[sel_label_a]
                st.caption(f"📅 {selected_a['date_decided']} · {selected_a['court']}")
                if selected_a.get("url"):
                    st.markdown(f"[🔗 View case]({selected_a['url']})")

        with col_sel_b:
            if results_b:
                opts_b = {f"{c['case_name'][:60]} ({c['date_decided'][:4]})": c for c in results_b}
                sel_label_b = st.selectbox("Select Case B", list(opts_b.keys()), key="prec_sel_b")
                selected_b  = opts_b[sel_label_b]
                st.caption(f"📅 {selected_b['date_decided']} · {selected_b['court']}")
                if selected_b.get("url"):
                    st.markdown(f"[🔗 View case]({selected_b['url']})")

        # ── Compare button ────────────────────────────────────────────────────
        st.markdown("")
        can_compare = selected_a and selected_b and _check_api_key()
        compare_btn = st.button("⚖️ Compare Cases & Analyze Precedent",
                                type="primary", use_container_width=True,
                                disabled=not can_compare,
                                key="prec_compare_btn")
        if not _check_api_key():
            st.caption("API key required for AI analysis.")

        if compare_btn and selected_a and selected_b:
            with st.spinner("Analyzing precedent relationship…"):
                import anthropic as _ant_prec
                analysis = compare_cases(
                    selected_a, selected_b,
                    client=_ant_prec.Anthropic(api_key=_get_api_key()),
                )
            st.session_state["prec_comparison"] = analysis

        # ── Display comparison ────────────────────────────────────────────────
        analysis = st.session_state.get("prec_comparison")
        if analysis and not analysis.get("error"):
            rel   = analysis.get("precedent_relationship", "unknown").upper()
            cite  = analysis.get("citation_value", "UNKNOWN")
            rel_colors = {
                "CONTROLLING":"#c0392b","PERSUASIVE":"#d67f1e","DISTINGUISHED":"#7b2d8b",
                "OVERRULED":"#c0392b","PARALLEL":"#27ae60","UNRELATED":"#888",
            }
            cite_colors = {"HIGH":"#c0392b","MEDIUM":"#d67f1e","LOW":"#27ae60","NONE":"#888"}

            # Header banner
            st.markdown(
                f'<div style="background:#1a2744;border-radius:10px;padding:1.2rem 1.5rem;'
                f'margin-bottom:1rem;border-left:5px solid {rel_colors.get(rel,"#888")};">'
                f'<span style="color:#e8d9b0;font-size:1.1rem;font-weight:700;">'
                f'Precedent Relationship: </span>'
                f'<span style="background:{rel_colors.get(rel,"#888")};color:#fff;padding:3px 14px;'
                f'border-radius:10px;font-weight:700;font-size:.9rem;">{rel}</span>'
                f'&nbsp;&nbsp;<span style="color:#8fa3bf;font-size:.85rem;">'
                f'Citation Value: <strong style="color:{cite_colors.get(cite,"#888")}">{cite}</strong>'
                f'</span></div>',
                unsafe_allow_html=True,
            )

            if analysis.get("legal_issue"):
                st.info(f"**Legal Issue:** {analysis['legal_issue']}")

            if analysis.get("key_shift"):
                st.warning(f"**Key Shift:** {analysis['key_shift']}", icon="⚖️")

            # Side-by-side holdings
            h_a, h_b = st.columns(2)
            with h_a:
                st.markdown(f"**📜 {selected_a.get('case_name','Case A')[:50]}**")
                st.markdown(f"*{analysis.get('case_a_era','')}*")
                st.markdown(analysis.get("case_a_holding","—"))
            with h_b:
                st.markdown(f"**📄 {selected_b.get('case_name','Case B')[:50]}**")
                st.markdown(f"*{analysis.get('case_b_era','')}*")
                st.markdown(analysis.get("case_b_holding","—"))

            st.divider()

            # Similarities & differences
            sim_col, diff_col = st.columns(2)
            with sim_col:
                st.markdown("**✅ Similarities**")
                for s in analysis.get("similarities",[]):
                    st.markdown(f"- {s}")
            with diff_col:
                st.markdown("**🔴 Key Distinctions**")
                for d in analysis.get("differences",[]):
                    st.markdown(f"- {d}")

            # Legal evolution + strategy
            if analysis.get("legal_evolution"):
                st.markdown("**📈 Legal Evolution**")
                st.markdown(analysis["legal_evolution"])

            if analysis.get("precedent_explanation"):
                with st.expander("📋 Precedent Analysis Detail"):
                    st.markdown(analysis["precedent_explanation"])

            if analysis.get("strategic_notes"):
                with st.expander("⚖️ Strategic Notes for Litigators"):
                    st.markdown(analysis["strategic_notes"])

            # Save to doc viewer
            import json as _json_prec
            docs = st.session_state.setdefault("documents", {})
            rname = f"precedent_{selected_a.get('case_name','A')[:20]}_vs_{selected_b.get('case_name','B')[:20]}.json".replace(" ","_")
            docs[rname] = _json_prec.dumps(analysis, indent=2).encode()
            st.session_state["documents"] = docs
            st.caption(f"💾 Analysis saved to Document Viewer: {rname}")

        elif analysis and analysis.get("error"):
            st.error(f"Analysis error: {analysis['error']}")

    # ════════════════════════════════════════════════════════════════════════
    # MODE 2 — LEGAL EVOLUTION
    # ════════════════════════════════════════════════════════════════════════
    elif prec_mode == "📈 Legal Evolution (Topic Over Time)":
        st.markdown("#### Track how courts have ruled on a legal topic across decades")
        st.caption("Search broadly — the engine will find cases spanning different eras "
                   "and analyze how the legal standard evolved.")

        evo_topic   = st.text_input("Legal topic or issue",
                                    placeholder="e.g. Fourth Amendment digital privacy, employment discrimination standard, qualified immunity",
                                    key="evo_topic")
        ec1, ec2, ec3 = st.columns(3)
        with ec1:
            evo_from = st.text_input("From year", placeholder="e.g. 1960", key="evo_from")
        with ec2:
            evo_to   = st.text_input("To year",   placeholder="e.g. 2024", key="evo_to")
        with ec3:
            evo_source = st.radio("Source", ["CourtListener","Harvard CAP"],
                                  key="evo_src", horizontal=True)
        evo_max = st.slider("Max cases to analyze", 5, 20, 10, key="evo_max")

        evo_btn = st.button("📈 Analyze Legal Evolution", type="primary",
                            use_container_width=True,
                            disabled=not (evo_topic and _check_api_key()),
                            key="evo_btn")

        if evo_btn and evo_topic:
            with st.spinner(f"Finding cases on '{evo_topic}' across eras…"):
                def _yr(y, sfx="-01-01"):
                    return f"{y.strip()}{sfx}" if y and y.strip().isdigit() else None

                fn = search_cases_cap if "Harvard" in evo_source else search_cases_cl
                evo_cases = fn(
                    evo_topic,
                    date_min=_yr(evo_from),
                    date_max=_yr(evo_to, "-12-31"),
                    max_results=evo_max,
                )

            if not evo_cases:
                st.info("No cases found. Try broader search terms or a different source.", icon="🔍")
            else:
                st.success(f"Found {len(evo_cases)} cases — analyzing evolution…")
                with st.spinner("Running AI legal evolution analysis…"):
                    import anthropic as _ant_evo
                    evo_analysis = analyze_legal_evolution(
                        evo_topic, evo_cases,
                        client=_ant_evo.Anthropic(api_key=_get_api_key()),
                    )
                st.session_state["evo_analysis"] = evo_analysis
                st.session_state["evo_cases"]    = evo_cases

        evo_analysis = st.session_state.get("evo_analysis")
        evo_cases    = st.session_state.get("evo_cases", [])

        if evo_analysis and not evo_analysis.get("error"):
            traj = evo_analysis.get("trajectory","stable").upper()
            traj_c = {"EXPANDING":"#27ae60","CONTRACTING":"#c0392b",
                      "STABLE":"#2c5f8a","CONTESTED":"#d67f1e","FRAGMENTED":"#7b2d8b"}.get(traj,"#888")

            st.markdown(
                f'<div style="background:#1a2744;border-radius:10px;padding:1.1rem 1.4rem;'
                f'margin-bottom:1rem;border-left:5px solid {traj_c};">'
                f'<span style="color:#e8d9b0;font-weight:700;font-size:1rem;">'
                f'{evo_analysis.get("topic","")}</span>&nbsp;&nbsp;'
                f'<span style="background:{traj_c};color:#fff;padding:2px 12px;border-radius:10px;'
                f'font-size:.8rem;font-weight:700;">{traj}</span>&nbsp;'
                f'<span style="color:#8fa3bf;font-size:.83rem;">'
                f'{evo_analysis.get("date_range","")} · {evo_analysis.get("cases_analyzed",0)} cases'
                f'</span></div>',
                unsafe_allow_html=True,
            )

            st.info(evo_analysis.get("legal_arc_summary",""))

            # Turning points timeline
            turning = evo_analysis.get("key_turning_points", [])
            if turning:
                st.markdown("#### 🔄 Key Turning Points")
                for tp in turning:
                    yr   = tp.get("year","")
                    name = tp.get("case_name","")
                    shift= tp.get("shift","")
                    st.markdown(
                        f'<div style="border-left:3px solid #c9a84c;padding:.5rem .9rem;margin-bottom:.4rem;background:#f8f9fc;border-radius:0 6px 6px 0;">'
                        f'<strong style="color:#1a2744;">{yr} — {name}</strong><br>'
                        f'<span style="color:#555;font-size:.87rem;">{shift}</span>'
                        f'</div>',
                        unsafe_allow_html=True,
                    )

            # Current standard + tensions
            cs_col, nt_col = st.columns(2)
            with cs_col:
                if evo_analysis.get("current_standard"):
                    st.markdown("**📌 Current Standard**")
                    st.markdown(evo_analysis["current_standard"])
            with nt_col:
                if evo_analysis.get("notable_tensions"):
                    st.markdown("**⚡ Notable Tensions / Circuit Splits**")
                    st.markdown(evo_analysis["notable_tensions"])

            with st.expander("⚖️ Practical Implications & Investigator Notes"):
                if evo_analysis.get("practical_implications"):
                    st.markdown("**Practical Implications:**")
                    st.markdown(evo_analysis["practical_implications"])
                if evo_analysis.get("investigator_notes"):
                    st.markdown("**Investigator Notes:**")
                    st.markdown(evo_analysis["investigator_notes"])

            # Case list
            with st.expander(f"📚 All {len(evo_cases)} cases analyzed"):
                sorted_cases = sorted(evo_cases, key=lambda x: x.get("date_decided",""))
                for c in sorted_cases:
                    yr   = c.get("date_decided","?")[:4]
                    name = c.get("case_name","?")[:70]
                    court= c.get("court","")
                    url  = c.get("url","")
                    line = f"**{yr}** — {name} · _{court}_"
                    if url: line += f" — [View]({url})"
                    st.markdown(f"- {line}")

        elif evo_analysis and evo_analysis.get("error"):
            st.error(f"Analysis error: {evo_analysis['error']}")

    # ════════════════════════════════════════════════════════════════════════
    # MODE 3 — CITATION CHAIN
    # ════════════════════════════════════════════════════════════════════════
    elif prec_mode == "🔗 Citation Chain":
        st.markdown("#### Trace which cases cite a given case — and which it cites")
        st.caption("Enter a CourtListener case ID or search for a case to see its full citation network.")

        cite_col1, cite_col2 = st.columns([3,1])
        with cite_col1:
            cite_query = st.text_input("Search for a case",
                                       placeholder="e.g. Roe v Wade, Miranda v Arizona",
                                       key="cite_q")
        with cite_col2:
            st.markdown("<br>", unsafe_allow_html=True)
            cite_search_btn = st.button("🔍 Find", use_container_width=True, key="cite_srch")

        if cite_search_btn and cite_query:
            with st.spinner("Searching CourtListener…"):
                results = search_cases_cl(cite_query, max_results=8)
            st.session_state["cite_results"] = results

        cite_results = st.session_state.get("cite_results", [])
        if cite_results:
            opts = {f"{c['case_name'][:70]} ({c['date_decided'][:4]})": c for c in cite_results}
            sel_label = st.selectbox("Select case", list(opts.keys()), key="cite_sel")
            sel_case  = opts[sel_label]
            case_id   = str(sel_case.get("id",""))

            if sel_case.get("url"):
                st.markdown(f"📅 {sel_case['date_decided']} · {sel_case['court']} · [View on CourtListener]({sel_case['url']})")

            chain_btn = st.button("🔗 Load Citation Chain", type="primary",
                                  use_container_width=True, key="cite_chain_btn",
                                  disabled=not case_id)

            if chain_btn and case_id:
                with st.spinner("Fetching citation chain…"):
                    citing  = get_citing_cases(case_id, max_results=15)
                    cited_by = get_cited_cases(case_id, max_results=15)
                st.session_state["citing"]   = citing
                st.session_state["cited_by"] = cited_by
                st.session_state["chain_case"] = sel_case

            citing   = st.session_state.get("citing", [])
            cited_by = st.session_state.get("cited_by", [])
            chain_case = st.session_state.get("chain_case")

            if chain_case or citing or cited_by:
                chain_left, chain_right = st.columns(2)

                with chain_left:
                    st.markdown(f"**⬅️ Cases this case CITES** ({len(cited_by)} found)")
                    st.caption("Its own precedents — cases it relied on")
                    if not cited_by:
                        st.caption("None found or requires CourtListener token for full access.")
                    for c in cited_by:
                        name = c.get("case_name","?")[:65]
                        url  = c.get("url","")
                        line = f"- {name}"
                        if url: line += f" — [View]({url})"
                        st.markdown(line)

                with chain_right:
                    st.markdown(f"**➡️ Cases that CITE this case** ({len(citing)} found)")
                    st.caption("Later cases that followed this precedent")
                    if not citing:
                        st.caption("None found.")
                    for c in citing:
                        name  = c.get("case_name","?")[:65]
                        date  = c.get("date_decided","?")[:4]
                        court = c.get("court","")
                        url   = c.get("url","")
                        line  = f"- **{date}** {name} · _{court}_"
                        if url: line += f" — [View]({url})"
                        st.markdown(line)


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4 — MEDIA FORENSICS
# ═══════════════════════════════════════════════════════════════════════════════

with tab_forensics:
    from analyzers.media_analyzer import analyze_image, analyze_video, analyze_text

    st.markdown("### 🕵️ Media Forensics — AI Manipulation Detector")
    st.caption(
        "Detect AI-generated deepfakes, face swaps, manipulated images, "
        "AI-written text, and synthetic video. Results provide investigative leads — "
        "obtain certified forensic analysis for legal proceedings."
    )

    # ── Risk badge helper ─────────────────────────────────────────────────────
    def _risk_badge(risk: str) -> str:
        colors = {"HIGH": "#c0392b", "MEDIUM": "#d67f1e", "LOW": "#27ae60", "NONE": "#95a5a6"}
        return (
            f'<span style="background:{colors.get(risk,"#95a5a6")};color:#fff;'
            f'padding:3px 12px;border-radius:12px;font-weight:700;font-size:.85rem;">'
            f'{risk} RISK</span>'
        )

    def _verdict_color(verdict: str) -> str:
        if "LIKELY_MANIPULATED" in verdict or "LIKELY_AI" in verdict: return "#c0392b"
        if "POSSIBLY" in verdict: return "#d67f1e"
        if "AUTHENTIC" in verdict or "HUMAN" in verdict: return "#27ae60"
        return "#95a5a6"

    # ── Mode selector ─────────────────────────────────────────────────────────
    mode = st.radio(
        "What do you want to analyze?",
        ["🖼️ Image", "🎬 Video", "📝 Text"],
        horizontal=True,
        key="forensics_mode",
    )

    st.divider()

    # ══════════════════════════════════════════════════════════════════════════
    # IMAGE ANALYSIS
    # ══════════════════════════════════════════════════════════════════════════
    if mode == "🖼️ Image":
        st.markdown("#### Upload Image for Deepfake / Manipulation Analysis")
        st.caption("Supports: JPG, PNG, WebP, GIF, **HEIC/HEIF** (iPhone), BMP, TIFF · Max 20 MB")

        img_file = st.file_uploader(
            "Drop image here",
            type=["jpg", "jpeg", "png", "webp", "gif", "heic", "heif", "bmp", "tiff", "tif"],
            key="forensics_img",
            label_visibility="collapsed",
        )

        col_tips, col_btn = st.columns([4, 1])
        with col_tips:
            st.caption(
                "🔍 Checks for: facial boundary artifacts · skin over-smoothing · "
                "GAN patterns · lighting inconsistencies · clone stamps · "
                "EXIF metadata · compression artifacts"
            )
        with col_btn:
            analyze_img_btn = st.button(
                "🔍 Analyze", type="primary",
                use_container_width=True,
                disabled=not (img_file and _check_api_key()),
            )

        if not _check_api_key():
            st.info("**🔑 AI forensic analysis** requires an Anthropic API key (sidebar).  \nGet one free at [console.anthropic.com](https://console.anthropic.com)", icon="ℹ️")

        if analyze_img_btn and img_file:
            # H-7: Informed consent disclosure before transmitting to Anthropic API
            st.warning(
                "**Privacy Notice:** This image will be transmitted to Anthropic's API servers "
                "for analysis. **Do not upload attorney-client privileged evidence** unless your "
                "firm has a data processing agreement with Anthropic. "
                "All transmissions are logged locally in "
                "`~/Library/Logs/LegalPerigee_transmissions.log`.",
                icon="⚠️",
            )
            with st.spinner("Analyzing image with Claude Vision…"):
                img_bytes = img_file.read()
                result = analyze_image(img_bytes, img_file.name, client=anthropic.Anthropic(api_key=_get_api_key()))

            # ── Results display ───────────────────────────────────────────────
            verdict = result.get("verdict", "INCONCLUSIVE")
            risk = result.get("risk_level", "NONE")
            confidence = result.get("confidence", 0)

            # Header row
            v1, v2, v3 = st.columns(3)
            v1.markdown(
                f'<div style="padding:1rem;background:#f8f9fc;border-radius:8px;text-align:center;">'
                f'<div style="font-size:1.1rem;font-weight:700;color:{_verdict_color(verdict)};">'
                f'{verdict.replace("_"," ")}</div>'
                f'<div style="font-size:.8rem;color:#888;">Verdict</div></div>',
                unsafe_allow_html=True,
            )
            v2.markdown(
                f'<div style="padding:1rem;background:#f8f9fc;border-radius:8px;text-align:center;">'
                f'{_risk_badge(risk)}<br>'
                f'<div style="font-size:.8rem;color:#888;margin-top:.3rem;">Risk Level</div></div>',
                unsafe_allow_html=True,
            )
            v3.markdown(
                f'<div style="padding:1rem;background:#f8f9fc;border-radius:8px;text-align:center;">'
                f'<div style="font-size:1.8rem;font-weight:700;color:#1a2744;">{confidence}%</div>'
                f'<div style="font-size:.8rem;color:#888;">Confidence</div></div>',
                unsafe_allow_html=True,
            )

            st.markdown("<br>", unsafe_allow_html=True)
            if result.get("summary"):
                st.info(f"**Summary:** {result['summary']}")

            # Artifacts found
            artifacts = result.get("artifacts_found", [])
            if artifacts:
                st.markdown("**⚠️ Manipulation Artifacts Detected:**")
                for a in artifacts:
                    st.markdown(f"- 🔴 {a}")

            authentic = result.get("authentic_indicators", [])
            if authentic:
                st.markdown("**✅ Authentic Indicators:**")
                for a in authentic:
                    st.markdown(f"- 🟢 {a}")

            # Full analysis
            c_left, c_right = st.columns(2)
            with c_left:
                if result.get("forensic_notes"):
                    with st.expander("🔬 Forensic Notes"):
                        st.markdown(result["forensic_notes"])
                if result.get("manipulation_type"):
                    st.caption(f"Manipulation type: **{result['manipulation_type'].replace('_',' ').title()}**")

            with c_right:
                if result.get("legal_recommendation"):
                    with st.expander("⚖️ Legal Recommendation"):
                        st.markdown(result["legal_recommendation"])

            # EXIF metadata
            meta = result.get("metadata", {})
            if meta:
                with st.expander("📋 File Metadata (EXIF)"):
                    col_m1, col_m2 = st.columns(2)
                    col_m1.metric("Format", meta.get("format", "—"))
                    col_m1.metric("Size", meta.get("size", "—"))
                    col_m2.metric("EXIF Data", "Present ✅" if meta.get("has_exif") else "Missing ⚠️")
                    col_m2.metric("Camera", meta.get("camera", "Unknown").strip() or "Not found")
                    if meta.get("software"):
                        st.caption(f"Software: {meta['software']}")
                    if meta.get("date_taken"):
                        st.caption(f"Date taken: {meta['date_taken']}")
                    if not meta.get("has_exif"):
                        st.warning("No EXIF data detected. Authentic photos usually contain EXIF. "
                                   "Stripped EXIF can indicate processing or manipulation.", icon="⚠️")

            # Show image alongside results
            st.image(img_bytes, caption=img_file.name, use_container_width=True)

            # Save to doc viewer
            docs = st.session_state.setdefault("documents", {})
            report_name = f"forensics_{Path(img_file.name).stem}_report.json"
            docs[report_name] = json.dumps(result, indent=2).encode()
            st.session_state["documents"] = docs
            st.caption(f"💾 Report saved to Document Viewer: {report_name}")

    # ══════════════════════════════════════════════════════════════════════════
    # VIDEO ANALYSIS
    # ══════════════════════════════════════════════════════════════════════════
    elif mode == "🎬 Video":
        st.markdown("#### Upload Video for Deepfake Detection")
        st.caption("Supports: MP4, **MOV/QT** (QuickTime), AVI, MKV, WebM, M4V · Max 200 MB · Requires ffmpeg ✅")

        vid_file = st.file_uploader(
            "Drop video here",
            type=["mp4", "mov", "qt", "avi", "mkv", "webm", "m4v", "3gp"],
            key="forensics_vid",
            label_visibility="collapsed",
        )

        n_frames = st.slider("Frames to analyze", 4, 12, 6, key="forensics_nframes",
                             help="More frames = better accuracy but slower and more API calls")

        col_info, col_vbtn = st.columns([4, 1])
        with col_info:
            st.caption(
                "🔍 Extracts evenly-spaced frames · Checks each for: facial boundary artifacts · "
                "lip-sync inconsistencies · unnatural blinking · GAN fingerprints"
            )
        with col_vbtn:
            analyze_vid_btn = st.button(
                "🔍 Analyze", type="primary",
                use_container_width=True,
                disabled=not (vid_file and _check_api_key()),
            )

        if analyze_vid_btn and vid_file:
            st.info(f"Analyzing {n_frames} frames from video. This takes ~{n_frames * 8}s…", icon="⏳")
            progress_bar = st.progress(0)
            status_text = st.empty()

            with st.spinner("Extracting and analyzing frames…"):
                vid_bytes = vid_file.read()
                result = analyze_video(vid_bytes, vid_file.name, n_frames,
                                       client=anthropic.Anthropic(api_key=_get_api_key()))
                progress_bar.progress(100)

            if result.get("error"):
                st.error(f"Analysis failed: {result['error']}")
            else:
                verdict = result.get("overall_verdict", "INCONCLUSIVE")
                risk = result.get("risk_level", "NONE")
                manip = result.get("manipulated_frames", 0)
                total = result.get("frames_analyzed", 0)

                u1, u2, u3 = st.columns(3)
                u1.markdown(
                    f'<div style="padding:1rem;background:#f8f9fc;border-radius:8px;text-align:center;">'
                    f'<div style="font-size:1.05rem;font-weight:700;color:{_verdict_color(verdict)};">'
                    f'{verdict.replace("_"," ")}</div><div style="font-size:.8rem;color:#888;">Verdict</div></div>',
                    unsafe_allow_html=True,
                )
                u2.markdown(
                    f'<div style="padding:1rem;background:#f8f9fc;border-radius:8px;text-align:center;">'
                    f'{_risk_badge(risk)}<br>'
                    f'<div style="font-size:.8rem;color:#888;margin-top:.3rem;">Risk Level</div></div>',
                    unsafe_allow_html=True,
                )
                u3.markdown(
                    f'<div style="padding:1rem;background:#f8f9fc;border-radius:8px;text-align:center;">'
                    f'<div style="font-size:1.8rem;font-weight:700;color:#1a2744;">{manip}/{total}</div>'
                    f'<div style="font-size:.8rem;color:#888;">Suspicious Frames</div></div>',
                    unsafe_allow_html=True,
                )

                st.markdown("<br>", unsafe_allow_html=True)
                if result.get("summary"):
                    st.info(f"**Summary:** {result['summary']}")

                artifacts = result.get("all_artifacts", [])
                if artifacts:
                    st.markdown("**⚠️ Artifacts Detected Across Frames:**")
                    for a in artifacts:
                        st.markdown(f"- 🔴 {a}")

                with st.expander(f"📊 Per-Frame Results ({total} frames)"):
                    for fr in result.get("frame_results", []):
                        fv = fr.get("verdict", "?")
                        fc = fr.get("confidence", 0)
                        fa = fr.get("artifacts_found", [])
                        color = _verdict_color(fv)
                        st.markdown(
                            f'**Frame {fr.get("frame","?")}** @ {fr.get("timestamp","?")}s — '
                            f'<span style="color:{color};font-weight:600;">{fv.replace("_"," ")}</span> '
                            f'({fc}% confidence)',
                            unsafe_allow_html=True,
                        )
                        if fa:
                            st.caption("Artifacts: " + "; ".join(fa))

                docs = st.session_state.setdefault("documents", {})
                report_name = f"forensics_{Path(vid_file.name).stem}_report.json"
                docs[report_name] = json.dumps(result, indent=2).encode()
                st.session_state["documents"] = docs
                st.caption(f"💾 Report saved to Document Viewer: {report_name}")

    # ══════════════════════════════════════════════════════════════════════════
    # TEXT ANALYSIS
    # ══════════════════════════════════════════════════════════════════════════
    elif mode == "📝 Text":
        st.markdown("#### Analyze Text for AI Generation & Scam Patterns")
        st.caption("Paste emails, messages, contracts, social media posts, news articles, or any suspect text.")

        text_input = st.text_area(
            "Paste text here",
            height=220,
            placeholder="Paste the suspect text here — email, message, social post, document excerpt…",
            key="forensics_text",
            label_visibility="collapsed",
        )

        word_count = len(text_input.split()) if text_input else 0
        st.caption(f"{word_count} words · {len(text_input)} characters")

        col_ti, col_tb = st.columns([4, 1])
        with col_ti:
            st.caption(
                "🔍 Checks for: AI generation patterns · hedge phrases · "
                "scam urgency language · impersonation markers · "
                "emotional manipulation · unnatural uniformity"
            )
        with col_tb:
            analyze_txt_btn = st.button(
                "🔍 Analyze", type="primary",
                use_container_width=True,
                disabled=not (text_input.strip() and _check_api_key()),
            )

        if analyze_txt_btn and text_input.strip():
            with st.spinner("Analyzing text…"):
                result = analyze_text(text_input, client=anthropic.Anthropic(api_key=_get_api_key()))

            if result.get("error"):
                st.error(result["error"])
            else:
                verdict = result.get("verdict", "INCONCLUSIVE")
                ai_prob = result.get("ai_probability", 0)
                scam_prob = result.get("scam_probability", 0)
                risk = result.get("risk_level", "NONE")

                t1, t2, t3, t4 = st.columns(4)
                t1.markdown(
                    f'<div style="padding:1rem;background:#f8f9fc;border-radius:8px;text-align:center;">'
                    f'<div style="font-size:.95rem;font-weight:700;color:{_verdict_color(verdict)};">'
                    f'{verdict.replace("_"," ")}</div><div style="font-size:.78rem;color:#888;">Verdict</div></div>',
                    unsafe_allow_html=True,
                )
                t2.markdown(
                    f'<div style="padding:1rem;background:#f8f9fc;border-radius:8px;text-align:center;">'
                    f'<div style="font-size:1.7rem;font-weight:700;color:#c9a84c;">{ai_prob}%</div>'
                    f'<div style="font-size:.78rem;color:#888;">AI Generated</div></div>',
                    unsafe_allow_html=True,
                )
                t3.markdown(
                    f'<div style="padding:1rem;background:#f8f9fc;border-radius:8px;text-align:center;">'
                    f'<div style="font-size:1.7rem;font-weight:700;color:#c0392b;">{scam_prob}%</div>'
                    f'<div style="font-size:.78rem;color:#888;">Scam Likelihood</div></div>',
                    unsafe_allow_html=True,
                )
                t4.markdown(
                    f'<div style="padding:1rem;background:#f8f9fc;border-radius:8px;text-align:center;">'
                    f'{_risk_badge(risk)}<br>'
                    f'<div style="font-size:.78rem;color:#888;margin-top:.3rem;">Risk</div></div>',
                    unsafe_allow_html=True,
                )

                st.markdown("<br>", unsafe_allow_html=True)
                if result.get("summary"):
                    st.info(f"**Summary:** {result['summary']}")

                col_tl, col_tr = st.columns(2)
                with col_tl:
                    ai_markers = result.get("ai_markers_found", [])
                    if ai_markers:
                        st.markdown("**🤖 AI Generation Markers:**")
                        for m in ai_markers:
                            st.markdown(f"- {m}")
                    scam_markers = result.get("scam_markers_found", [])
                    if scam_markers:
                        st.markdown("**🚨 Scam/Fraud Markers:**")
                        for m in scam_markers:
                            st.markdown(f"- 🔴 {m}")

                with col_tr:
                    authentic = result.get("authentic_indicators", [])
                    if authentic:
                        st.markdown("**✅ Authentic Indicators:**")
                        for a in authentic:
                            st.markdown(f"- 🟢 {a}")
                    if result.get("forensic_notes"):
                        with st.expander("🔬 Forensic Notes"):
                            st.markdown(result["forensic_notes"])
                    if result.get("legal_recommendation"):
                        with st.expander("⚖️ Legal Recommendation"):
                            st.markdown(result["legal_recommendation"])

                docs = st.session_state.setdefault("documents", {})
                ts = __import__("time").strftime("%H%M%S")
                report_name = f"forensics_text_{ts}_report.json"
                docs[report_name] = json.dumps(result, indent=2).encode()
                st.session_state["documents"] = docs
                st.caption(f"💾 Report saved to Document Viewer: {report_name}")


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 4 — ALERTS
# ═══════════════════════════════════════════════════════════════════════════════

with tab_alerts:
    from database.db import (
        init_alerts_table, get_alert_rules, save_alert_rule, delete_alert_rule,
    )
    from alerts.email_sender import smtp_configured, check_and_send_alerts

    init_alerts_table()

    st.markdown("### 🔔 Case Alerts")
    st.caption(
        "Get email notifications when new cases matching your criteria are found. "
        "Alerts are checked automatically after every sync."
    )

    # ── SMTP status ───────────────────────────────────────────────────────────
    if smtp_configured():
        st.success("Email configured ✅", icon="📧")
    else:
        with st.expander("⚙️ Configure Email (required to send alerts)", expanded=True):
            st.info(
                "Enter your sender email and app password in the **sidebar → Integration Keys → Email Alert Config**. "
                "All credentials are stored in macOS Keychain — never written to any file.",
                icon="🔐",
            )
            st.caption(
                "For Gmail: enable 2FA → Google Account → Security → App Passwords → "
                "generate a password for 'Mail'."
            )

    st.divider()

    # ── Create new rule ───────────────────────────────────────────────────────
    with st.expander("➕ Create New Alert Rule", expanded=True):
        ar1, ar2 = st.columns(2)
        with ar1:
            alert_name  = st.text_input("Rule Name", placeholder="e.g. AI Lending Discrimination NY")
            alert_email = st.text_input("Send alerts to", placeholder="you@example.com")
            alert_kw    = st.text_input("Keywords", placeholder="e.g. AI lending discrimination")
        with ar2:
            alert_courts = st.text_input("Courts (optional)", placeholder="e.g. SDNY, ca9")
            alert_states = st.text_input("States (optional)", placeholder="e.g. New York, California")

        if st.button("💾 Save Alert Rule", type="primary", use_container_width=True):
            if alert_name and alert_email:
                rule_data = {
                    "name":       alert_name,
                    "keywords":   alert_kw,
                    "courts":     alert_courts,
                    "states":     alert_states,
                    "harm_types": "",
                    "email":      alert_email,
                }
                save_alert_rule(rule_data)

                # Also register on CourtListener for real-time federal filings
                from aggregator.courtlistener_alerts import sync_alert_to_courtlistener
                cl_result = sync_alert_to_courtlistener(rule_data)
                if cl_result.get("status") == "created":
                    st.success(f"✅ Alert rule '{alert_name}' saved + registered on CourtListener (ID {cl_result.get('id')}) for real-time federal alerts.")
                elif cl_result.get("status") == "skipped":
                    st.success(f"✅ Alert rule '{alert_name}' saved.")
                    st.info("Add your CourtListener token in the sidebar → **Integration Keys** to enable real-time federal court email alerts.", icon="🏛️")
                else:
                    st.success(f"✅ Alert rule '{alert_name}' saved.")
                    st.warning(f"CourtListener alert: {cl_result.get('error','')}", icon="⚠️")
                st.rerun()
            else:
                st.error("Rule name and email are required.")

    # ── Existing rules ────────────────────────────────────────────────────────
    rules = get_alert_rules()
    if rules:
        st.markdown(f"#### Active Rules ({len(rules)})")
        for rule in rules:
            with st.container():
                rc1, rc2, rc3 = st.columns([3, 2, 1])
                with rc1:
                    st.markdown(f"**{rule['name']}**")
                    if rule.get("keywords"):
                        st.caption(f"Keywords: {rule['keywords']}")
                    if rule.get("states"):
                        st.caption(f"States: {rule['states']}")
                with rc2:
                    st.caption(f"📧 {rule['email']}")
                    if rule.get("last_checked"):
                        st.caption(f"Last checked: {rule['last_checked'][:16]}")
                with rc3:
                    if st.button("🗑", key=f"del_rule_{rule['id']}", help="Delete rule"):
                        delete_alert_rule(rule["id"])
                        st.rerun()
                st.divider()
    else:
        st.info("No alert rules yet. Create one above.", icon="🔔")

    # ── Manual check ─────────────────────────────────────────────────────────
    if rules and smtp_configured():
        if st.button("▶️ Check Alerts Now", use_container_width=True):
            alert_log_ph = st.empty()
            alert_msgs: list[str] = []

            def _alert_cb(msg: str) -> None:
                alert_msgs.append(msg)
                alert_log_ph.markdown(
                    f'<div class="progress-log">{"<br>".join(alert_msgs[-15:])}</div>',
                    unsafe_allow_html=True,
                )

            with st.spinner("Checking alerts…"):
                result = check_and_send_alerts(days_lookback=7, progress_cb=_alert_cb)
            st.success(
                f"✅ Checked {result['alerts_checked']} rules · "
                f"{result['emails_sent']} email(s) sent"
            )


# ═══════════════════════════════════════════════════════════════════════════════
# TAB 5 — DOCUMENT VIEWER
# ═══════════════════════════════════════════════════════════════════════════════

with tab_docs:  # noqa: F811

    from viewers.document_viewer import (
        icon_for, fmt_size, render_file,
        MIME_MAP,
    )

    # ── Upload + session store ──────────────────────────────────────────────────

    ACCEPTED = list(MIME_MAP.keys())

    st.markdown(
        "Upload any document, court filing, opinion, evidence file, or report. "
        "Files stay in-session only — nothing leaves your machine."
    )

    uploaded = st.file_uploader(
        "Upload documents",
        accept_multiple_files=True,
        type=[e.lstrip(".") for e in ACCEPTED],
        label_visibility="collapsed",
        help="Supports: PDF, DOCX, XLSX, CSV, PPTX, images (HEIC, PNG, JPG), "
             "video (MOV, MP4), HTML, JSON, Markdown, and code files.",
    )

    # Always get a fresh reference from session state
    if "documents" not in st.session_state:
        st.session_state["documents"] = {}
    docs: dict[str, bytes] = st.session_state["documents"]

    if uploaded:
        _new_files = False
        for uf in uploaded:
            if uf.name not in docs:          # only process genuinely new files
                raw = uf.read()
                if raw:                      # skip empty / zero-byte files
                    docs[uf.name] = raw
                    _new_files = True
        st.session_state["documents"] = docs
        if _new_files:
            st.rerun()  # force refresh only when new content arrived

    # ── No documents yet ──────────────────────────────────────────────────────
    if not docs:
        st.markdown("""
<div class="doc-empty-state">
  <h3>📂 No documents yet</h3>
  <p>Drag and drop files above, or run an investigation — reports are added here automatically.</p>
  <p style="font-size:.85rem;color:#bbb;">
    PDF · DOCX · XLSX · CSV · PPTX · PNG · JPG · HEIC · MOV · HTML · JSON · MD · XML
  </p>
</div>""", unsafe_allow_html=True)

    else:
        # ── File list + viewer ─────────────────────────────────────────────────
        file_names = list(docs.keys())

        # Auto-select first file if nothing selected
        if "selected_doc" not in st.session_state or st.session_state["selected_doc"] not in docs:
            st.session_state["selected_doc"] = file_names[0]

        col_list, col_view = st.columns([1, 3])

        with col_list:
            st.caption(f"**{len(docs)} file{'s' if len(docs) != 1 else ''}** — click to view")

            sort_mode = st.radio("Sort", ["Name", "Size", "Type"], horizontal=True,
                                 label_visibility="collapsed", key="doc_sort")

            def _sort_key(n: str):
                if sort_mode == "Name":  return n.lower()
                if sort_mode == "Size":  return -len(docs[n])
                return (n.rsplit(".", 1)[-1].lower(), n.lower())

            sorted_names = sorted(file_names, key=_sort_key)

            filter_q = st.text_input("Filter", placeholder="Filter filenames...",
                                     label_visibility="collapsed", key="doc_filter")
            if filter_q:
                sorted_names = [n for n in sorted_names if filter_q.lower() in n.lower()]

            for fname in sorted_names:
                is_selected = (fname == st.session_state["selected_doc"])
                # Show selected file highlighted; others as secondary buttons
                if st.button(
                    f"{icon_for(fname)}  {fname}",
                    key=f"sel_{fname}",
                    use_container_width=True,
                    type="primary" if is_selected else "secondary",
                    help=fmt_size(len(docs[fname])),
                ):
                    st.session_state["selected_doc"] = fname
                    st.rerun()

            st.divider()
            to_remove = st.selectbox("Remove", ["— select —"] + file_names,
                                     key="doc_remove_sel", label_visibility="collapsed")
            rc1, rc2 = st.columns(2)
            with rc1:
                if st.button("🗑 Remove", key="doc_remove_btn", use_container_width=True):
                    if to_remove in docs:
                        del docs[to_remove]
                        st.session_state["documents"] = docs
                        remaining = [n for n in file_names if n != to_remove]
                        st.session_state["selected_doc"] = remaining[0] if remaining else ""
                        st.rerun()
            with rc2:
                if st.button("🗑 All", key="doc_clear_all", use_container_width=True):
                    st.session_state["documents"] = {}
                    st.session_state.pop("selected_doc", None)
                    st.rerun()

        with col_view:
            sel = st.session_state.get("selected_doc", "")
            if not sel or sel not in docs:
                sel = sorted_names[0] if sorted_names else ""

            if sel and sel in docs:
                render_file(sel, docs[sel])
            else:
                st.info("No files match your filter.", icon="🔍")


# (Help tab removed — Quick Start Guide is shown by the installer on first launch)

