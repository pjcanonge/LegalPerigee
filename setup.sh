#!/bin/bash
# LegalPerigee — one-time environment setup
# Creates a native arm64 Python virtual environment and installs all dependencies.
set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$PROJECT_DIR/.venv"

echo ""
echo "⚖️  LegalPerigee — Environment Setup"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── 1. Find a native arm64 Python 3.11+ ──────────────────────────────────────
find_python() {
    for candidate in \
        /opt/homebrew/opt/python@3.12/bin/python3.12 \
        /opt/homebrew/opt/python@3.11/bin/python3.11 \
        /opt/homebrew/bin/python3.12 \
        /opt/homebrew/bin/python3.11 \
        /opt/homebrew/bin/python3 \
        /usr/local/bin/python3.12 \
        /usr/local/bin/python3.11 \
        /usr/local/bin/python3 \
        /usr/bin/python3; do          # Apple system Python 3.9 — arm64 on M-series Macs
        if [ -x "$candidate" ]; then
            arch="$("$candidate" -c 'import platform; print(platform.machine())' 2>/dev/null)"
            if [ "$arch" = "arm64" ]; then
                echo "$candidate"
                return 0
            fi
        fi
    done
    return 1
}

PYTHON="$(find_python 2>/dev/null)"

if [ -z "$PYTHON" ]; then
    echo ""
    echo "❌  No native arm64 Python found."
    echo ""
    echo "    Install Homebrew Python first:"
    echo "    1. Install Homebrew (if needed): https://brew.sh"
    echo "    2. Run: brew install python@3.11"
    echo "    3. Re-run this script."
    echo ""

    # Offer to install via Homebrew automatically
    if command -v brew &>/dev/null; then
        read -rp "Homebrew found. Install python@3.11 now? [y/N] " yn
        if [[ "$yn" =~ ^[Yy]$ ]]; then
            brew install python@3.11
            PYTHON="$(find_python)"
        fi
    fi

    [ -z "$PYTHON" ] && exit 1
fi

ARCH="$("$PYTHON" -c 'import platform; print(platform.machine())')"
VER="$("$PYTHON" --version 2>&1)"
echo "✅  Using: $PYTHON  ($VER, $ARCH)"

# ── 2. Create virtual environment ─────────────────────────────────────────────
echo ""
if [ -d "$VENV_DIR" ]; then
    echo "🔄  Recreating .venv (removes old environment)…"
    rm -rf "$VENV_DIR"
fi

echo "📦  Creating .venv (forced arm64 to avoid Rosetta conflicts)…"
# arch -arm64 ensures the universal Python binary runs as arm64,
# so all compiled .so packages install as arm64 and match the runtime.
arch -arm64 "$PYTHON" -m venv "$VENV_DIR"
VENV_PY="$VENV_DIR/bin/python3"
VENV_PIP="$VENV_DIR/bin/pip3"

# ── 3. Upgrade pip ────────────────────────────────────────────────────────────
echo "⬆️   Upgrading pip…"
arch -arm64 "$VENV_PIP" install --upgrade pip --quiet

# ── 4. Install dependencies ───────────────────────────────────────────────────
echo "📥  Installing requirements (this takes ~60 s the first time)…"
arch -arm64 "$VENV_PIP" install -r "$PROJECT_DIR/requirements.txt"

echo ""
echo "✅  All dependencies installed."

# ── 5. Patch the .app launcher to use the venv ───────────────────────────────
APP_PATH="$HOME/Desktop/LegalPerigee.app"
LAUNCHER="$APP_PATH/Contents/MacOS/LegalPerigee"

if [ -f "$LAUNCHER" ]; then
    echo "🔧  Updating desktop app to use the new environment…"
    cat > "$LAUNCHER" <<LAUNCHER
#!/bin/bash
# LegalPerigee launcher — opens in a native window via pywebview
PROJECT_DIR="$PROJECT_DIR"
VENV_DIR="$VENV_DIR"
PYTHON="\$VENV_DIR/bin/python3"
WINDOW_SCRIPT="$PROJECT_DIR/window.py"

cd "\$PROJECT_DIR" 2>/dev/null || {
    osascript -e 'display alert "LegalPerigee" message "Project folder not found at $PROJECT_DIR" as critical'
    exit 1
}

if [ ! -x "\$PYTHON" ]; then
    osascript -e 'display alert "LegalPerigee" message "Dependencies missing.\n\nOpen Terminal and run:\n\n  bash $PROJECT_DIR/setup.sh" as critical'
    exit 1
fi

exec arch -arm64 "\$PYTHON" "\$WINDOW_SCRIPT"
LAUNCHER
    chmod +x "$LAUNCHER"
    echo "✅  Desktop app updated."
fi

# ── 6. Done ───────────────────────────────────────────────────────────────────
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🎉  Setup complete!"
echo ""
echo "    To launch:  double-click LegalPerigee on your Desktop"
echo "    Or run:     $VENV_DIR/bin/streamlit run $PROJECT_DIR/gui.py"
echo ""
