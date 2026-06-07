"""
LegalPerigee — native desktop window launcher.

Starts Streamlit on a background port, then opens the app in a
native macOS WKWebView window (no browser tabs, no address bar).

Fast-launch strategy: the window opens immediately with a splash page
so the dock stops bouncing right away; the app navigates to Streamlit
as soon as the server is ready.
"""

import os
import signal
import subprocess
import sys
import threading
import time
import urllib.request
import warnings

# M-4: Targeted warning suppression — NEVER suppress ssl, security, or
# InsecureRequest categories.  Only silence known-noisy pywebview/macOS startup
# messages that have no security relevance.
warnings.filterwarnings("ignore", category=DeprecationWarning, module="webview")
warnings.filterwarnings("ignore", category=DeprecationWarning, module="objc")
warnings.filterwarnings("ignore", category=ResourceWarning)
warnings.filterwarnings("ignore", message=".*NSWindow.*")
warnings.filterwarnings("ignore", message=".*AppKit.*")
# Do NOT suppress: ssl.SSLError, InsecureRequestWarning, or any security category

PORT = 8501
PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))
_STREAMLIT_URL = f"http://localhost:{PORT}"

# ── Load .env (non-sensitive config only) ─────────────────────────────────────
env_file = os.path.join(PROJECT_DIR, ".env")
if os.path.exists(env_file):
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                k = k.strip()
                if k != "ANTHROPIC_API_KEY" and v.strip():
                    os.environ.setdefault(k, v.strip())

# ── Load ALL API keys from macOS Keychain into os.environ ────────────────────
# Every module uses os.getenv() as normal — no module needs to know about
# Keychain. Keys are loaded once here so they are available app-wide.
sys.path.insert(0, PROJECT_DIR)
try:
    from utils.keychain import load_all_keys
    load_all_keys()
except Exception:
    pass

# ── Check if Streamlit is already running (instant reuse) ─────────────────────
def _streamlit_alive() -> bool:
    """Return True if Streamlit is already responding on PORT."""
    try:
        urllib.request.urlopen(_STREAMLIT_URL, timeout=1)
        return True
    except Exception:
        return False

log_path = os.path.expanduser("~/Library/Logs/LegalPerigee.log")
os.makedirs(os.path.dirname(log_path), exist_ok=True)
log_file = open(log_path, "a")

if _streamlit_alive():
    # Already running — reuse it; window opens instantly
    proc = None
    _already_running = True
else:
    _already_running = False
    # Kill any stale process occupying the port (not responding to HTTP)
    try:
        result = subprocess.run(
            ["lsof", "-ti", f":{PORT}"],
            capture_output=True, text=True,
        )
        for pid in result.stdout.split():
            os.kill(int(pid), signal.SIGKILL)
        time.sleep(0.3)
    except Exception:
        pass

    # ── Start Streamlit in background ─────────────────────────────────────────
    streamlit_bin = os.path.join(os.path.dirname(sys.executable), "streamlit")
    proc = subprocess.Popen(
        [
            streamlit_bin, "run",
            os.path.join(PROJECT_DIR, "gui.py"),
            "--server.headless", "true",
            "--server.port", str(PORT),
            "--server.address", "localhost",
            "--server.runOnSave", "false",
            "--server.fileWatcherType", "none",
            "--browser.gatherUsageStats", "false",
            "--logger.level", "error",
        ],
        stdout=log_file,
        stderr=log_file,
        cwd=PROJECT_DIR,
    )

# ── Splash screen HTML ────────────────────────────────────────────────────────
_SPLASH_STEPS_JS = (
    '["Launching Python runtime…","Loading intelligence modules…",'
    '"Starting case database…","Connecting to data sources…","Almost ready…"]'
)

SPLASH_HTML = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{
    background: #0f1b35;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    height: 100vh;
    font-family: -apple-system, BlinkMacSystemFont, "SF Pro Display", "Helvetica Neue", sans-serif;
    color: #e8eaf6;
    overflow: hidden;
  }}
  .logo-ring {{
    width: 96px; height: 96px;
    border-radius: 50%;
    background: linear-gradient(135deg, #1a3a6e 0%, #0f1b35 100%);
    border: 2px solid #2e4a8a;
    display: flex; align-items: center; justify-content: center;
    font-size: 48px;
    margin-bottom: 28px;
    box-shadow: 0 0 40px rgba(46,74,138,0.4);
    animation: pulse 2s ease-in-out infinite;
  }}
  @keyframes pulse {{
    0%, 100% {{ box-shadow: 0 0 40px rgba(46,74,138,0.4); }}
    50%       {{ box-shadow: 0 0 60px rgba(46,74,138,0.8); }}
  }}
  h1 {{
    font-size: 28px;
    font-weight: 600;
    letter-spacing: 0.04em;
    color: #c8d8ff;
    margin-bottom: 6px;
  }}
  .tagline {{
    font-size: 13px;
    color: #6b82b8;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    margin-bottom: 44px;
  }}
  .bar-wrap {{
    width: 260px;
    height: 3px;
    background: #1a2f5a;
    border-radius: 2px;
    overflow: hidden;
    margin-bottom: 18px;
  }}
  .bar {{
    height: 100%;
    width: 40%;
    background: linear-gradient(90deg, #3d6fd4, #8ab0ff);
    border-radius: 2px;
    animation: slide 1.4s ease-in-out infinite;
  }}
  @keyframes slide {{
    0%   {{ transform: translateX(-100%); }}
    60%  {{ transform: translateX(300%); }}
    100% {{ transform: translateX(300%); }}
  }}
  .status {{
    font-size: 12px;
    color: #4a6a9e;
    letter-spacing: 0.05em;
    min-height: 18px;
    transition: opacity 0.3s;
  }}
</style>
</head>
<body>
  <div class="logo-ring">⚖️</div>
  <h1>LegalPerigee</h1>
  <p class="tagline">Legal Case Intelligence Platform</p>
  <div class="bar-wrap"><div class="bar"></div></div>
  <p class="status" id="st">Launching Python runtime…</p>
  <script>
    var steps = {_SPLASH_STEPS_JS};
    var i = 0;
    var el = document.getElementById('st');
    setInterval(function() {{
      i = (i + 1) % steps.length;
      el.style.opacity = 0;
      setTimeout(function() {{
        el.textContent = steps[i];
        el.style.opacity = 1;
      }}, 150);
    }}, 2800);
  </script>
</body>
</html>"""

# ── Open native window immediately (splash) ───────────────────────────────────
import webview  # noqa: E402

window = webview.create_window(
    title="⚖️  LegalPerigee",
    html=SPLASH_HTML,
    width=1440,
    height=940,
    min_size=(1000, 700),
    background_color="#0f1b35",
    text_select=True,
    zoomable=True,
)

def on_closed():
    """Terminate Streamlit when the window closes (only if we started it)."""
    if proc is not None:
        try:
            proc.terminate()
            proc.wait(timeout=3)
        except Exception:
            pass
    log_file.close()

window.events.closed += on_closed

def _wait_and_navigate():
    """Poll Streamlit in a background thread; navigate when ready."""
    # If already running, navigate immediately with no splash delay
    if _already_running:
        window.load_url(_STREAMLIT_URL)
        return

    deadline = time.time() + 60          # wait up to 60 s
    poll_interval = 0.4
    while time.time() < deadline:
        try:
            urllib.request.urlopen(_STREAMLIT_URL, timeout=1)
            window.load_url(_STREAMLIT_URL)
            return
        except Exception:
            time.sleep(poll_interval)
            poll_interval = min(poll_interval * 1.2, 2.0)  # back off gently

    # Timeout — show an error in the splash
    window.evaluate_js(
        "document.getElementById('st').textContent = "
        "'Startup timed out. Check ~/Library/Logs/LegalPerigee.log';"
        "document.getElementById('st').style.color='#e05555';"
    )
    log_file.write("LegalPerigee: Streamlit failed to start within 60 s\n")
    log_file.flush()

# Start the poll thread before the webview event loop
_nav_thread = threading.Thread(target=_wait_and_navigate, daemon=True)
_nav_thread.start()

# gui=True required on macOS for WKWebView to run on the main thread
webview.start(gui="cocoa", debug=False)
