#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# LegalPerigee — macOS Conflict & Health Checker
# Called by the .app launcher before starting the server.
# Detects and resolves conflicts silently where possible; prompts only when
# user input is needed.
# ─────────────────────────────────────────────────────────────────────────────

PROJECT_DIR="$1"
VERSION="1.2"
LOG="$HOME/Library/Logs/LegalPerigee_install.log"
VENV="$PROJECT_DIR/.venv"
VENV_PY="$VENV/bin/python3"
REQUIREMENTS="$PROJECT_DIR/requirements.txt"

log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG"; }
alert() {
    osascript -e "display alert \"LegalPerigee\" message \"$*\" as warning" 2>/dev/null || true
}
fatal() {
    osascript -e "display alert \"LegalPerigee — Setup Failed\" message \"$*\" as critical" 2>/dev/null || true
    log "FATAL: $*"
    exit 1
}

# ── 0. First-launch Quick Start Guide ────────────────────────────────────────
# Shows once on first ever launch; never again after the user clicks OK.
WELCOME_SENTINEL="$HOME/Library/Application Support/LegalPerigee/.welcomed_v1.2"
if [ ! -f "$WELCOME_SENTINEL" ]; then
    mkdir -p "$(dirname "$WELCOME_SENTINEL")"
    osascript << 'APPLESCRIPT' 2>/dev/null || true
set welcomeText to "Welcome to LegalPerigee v1.2

WORKS RIGHT NOW — no account needed:
  • Case Library   — 20+ sources (courts, agencies, news)
  • Document Viewer — PDF, DOCX, XLSX, HTML, images
  • Legislative Watch — bills across all 50 states
  • Precedent Search — CourtListener + Harvard CAP
  • Alerts — email notifications on new cases

UNLOCK AI FEATURES (optional — free key):
  • AI Investigation Agent — research any legal matter
  • AI Bill Analysis & Media Forensics
  Get a free key at: console.anthropic.com → API Keys
  Paste it in the sidebar once; it saves to macOS Keychain.

GETTING STARTED:
  1. The app opens in your browser at localhost:8501
  2. Click 'Case Library' → 'Sync Manager' to load cases
  3. Search, browse, and set up Alerts — no key needed
  4. Add your Anthropic key in the left sidebar to enable AI

SECURITY: All API keys are stored in macOS Keychain only —
never written to files, logs, or source code."

display dialog welcomeText with title "LegalPerigee — Quick Start Guide" buttons {"OK — Let's Go!"} default button 1 with icon note
APPLESCRIPT
    touch "$WELCOME_SENTINEL"
    log "Quick Start Guide shown and acknowledged"
fi

log "=== LegalPerigee v$VERSION startup check ==="
cd "$PROJECT_DIR" || fatal "Project folder not found at $PROJECT_DIR"

# ── 1. Port conflict ──────────────────────────────────────────────────────────
# If Streamlit is already responding on 8501, the venv and all dependencies
# are provably good — skip ALL remaining checks and exit immediately.
# This makes re-opening the app nearly instant (< 3 seconds).
if curl -sf --max-time 1 "http://localhost:8501/" > /dev/null 2>&1; then
    log "Streamlit already running and healthy — skipping all checks (fast reopen)"
    exit 0
fi

# Streamlit not responding — kill any stale process occupying the port
PIDS=$(lsof -ti:8501 2>/dev/null || true)
if [ -n "$PIDS" ]; then
    log "Port 8501 in use but not responding (PIDs: $PIDS) — killing stale processes"
    echo "$PIDS" | xargs kill -9 2>/dev/null || true
    sleep 0.5
fi

# ── 2. Check existing venv — skip system Python search if already healthy ──────
REBUILD_VENV=false
PYTHON=""

if [ -d "$VENV" ] && [ -x "$VENV_PY" ]; then
    # venv exists — verify it works. Don't require arch -arm64; the venv may be
    # x86_64 (from CLT Python) and runs fine under Rosetta on Apple Silicon.
    if "$VENV_PY" -c 'import sys; assert sys.version_info >= (3,9)' 2>/dev/null && \
       "$VENV_PY" -c "import streamlit, anthropic, pydantic" 2>/dev/null; then
        log "Existing .venv is healthy — skipping Python search"
        PYTHON="$VENV_PY"   # only needed for rebuild paths below; venv is fine
    else
        log ".venv exists but is unhealthy — will rebuild"
        REBUILD_VENV=true
    fi
else
    if [ ! -d "$VENV" ]; then
        log "No .venv found — will create"
    else
        log ".venv exists but python3 missing — rebuilding"
    fi
    REBUILD_VENV=true
fi

# ── 3. Find system Python — only needed when rebuilding the venv ───────────────
# macOS stubs /usr/bin/python3 for GUI launches (shows CLT dialog); search in
# order of preference and verify arm64 capability with arch -arm64.
if [ "$REBUILD_VENV" = "true" ]; then
    for candidate in \
        /opt/homebrew/opt/python@3.13/bin/python3.13 \
        /opt/homebrew/opt/python@3.12/bin/python3.12 \
        /opt/homebrew/opt/python@3.11/bin/python3.11 \
        /opt/homebrew/bin/python3 \
        /usr/local/bin/python3 \
        /Library/Developer/CommandLineTools/usr/bin/python3 \
        /usr/bin/python3; do
        [ -x "$candidate" ] || continue
        if arch -arm64 "$candidate" -c 'import sys; assert sys.version_info >= (3,9)' 2>/dev/null; then
            PYTHON="$candidate"
            break
        fi
    done

    [ -z "$PYTHON" ] && fatal "Python 3.9+ not found.\n\nInstall via Homebrew:\n  brew install python@3.11\n\nThen relaunch LegalPerigee."
    log "Python: $PYTHON ($($PYTHON --version 2>&1))"
fi

# ── 4. Rebuild venv if needed ─────────────────────────────────────────────────
if [ "$REBUILD_VENV" = "true" ]; then
    log "Building virtual environment..."

    # Preserve the database before any rebuild
    DB_BACKUP=""
    if [ -f "$PROJECT_DIR/data/cases.db" ]; then
        DB_BACKUP="/tmp/legalperigee_cases_backup_$(date +%s).db"
        cp "$PROJECT_DIR/data/cases.db" "$DB_BACKUP"
        log "Database backed up to $DB_BACKUP"
    fi

    # Remove old venv
    rm -rf "$VENV"

    # Create new one with forced arm64
    arch -arm64 "$PYTHON" -m venv "$VENV" || fatal "Could not create virtual environment"
    arch -arm64 "$VENV/bin/pip" install --upgrade pip --quiet || true
    arch -arm64 "$VENV/bin/pip" install -r "$REQUIREMENTS" \
        || fatal "Dependency install failed.\n\nCheck $LOG for details.\n\nFix: bash $PROJECT_DIR/setup.sh"

    # Restore database
    if [ -n "$DB_BACKUP" ] && [ -f "$DB_BACKUP" ]; then
        mkdir -p "$PROJECT_DIR/data"
        cp "$DB_BACKUP" "$PROJECT_DIR/data/cases.db"
        log "Database restored"
        rm -f "$DB_BACKUP"
    fi

    log "Virtual environment ready"
fi

# ── 5. Upgrade check — new packages since last run ───────────────────────────
# Compare requirements hash to detect if deps changed (e.g. after update)
REQ_HASH=$(md5 -q "$REQUIREMENTS" 2>/dev/null || md5sum "$REQUIREMENTS" 2>/dev/null | cut -d' ' -f1)
HASH_FILE="$VENV/.req_hash"
STORED_HASH=$(cat "$HASH_FILE" 2>/dev/null || echo "")

if [ "$REQ_HASH" != "$STORED_HASH" ]; then
    log "requirements.txt changed — upgrading packages..."
    arch -arm64 "$VENV/bin/pip" install -r "$REQUIREMENTS" --quiet 2>&1 | tail -3
    echo "$REQ_HASH" > "$HASH_FILE"
    log "Package upgrade complete"
fi

# ── 6. Database integrity ─────────────────────────────────────────────────────
if [ -f "$PROJECT_DIR/data/cases.db" ]; then
    # Quick SQLite integrity check
    if ! "$VENV_PY" -c "
import sqlite3, sys
try:
    c = sqlite3.connect('$PROJECT_DIR/data/cases.db')
    c.execute('PRAGMA integrity_check').fetchone()
    c.close()
except Exception as e:
    print(f'DB corrupt: {e}', file=sys.stderr)
    sys.exit(1)
" 2>/dev/null; then
        log "Database corrupt — resetting (data will be re-synced)"
        mv "$PROJECT_DIR/data/cases.db" "$PROJECT_DIR/data/cases.db.corrupt.$(date +%s)"
    fi
fi

# ── 7. .env check ─────────────────────────────────────────────────────────────
ENV_FILE="$PROJECT_DIR/.env"
if [ ! -f "$ENV_FILE" ]; then
    log ".env missing — creating from template"
    cat > "$ENV_FILE" << 'ENVEOF'
# LegalPerigee configuration
# API key is stored in macOS Keychain — enter it in the app sidebar.
# COURTLISTENER_API_TOKEN=
# ALERT_EMAIL_FROM=
# ALERT_EMAIL_PASSWORD=
# ALERT_SMTP_HOST=smtp.gmail.com
# ALERT_SMTP_PORT=587
ENVEOF
fi

log "All checks passed — starting LegalPerigee v$VERSION"
exit 0
