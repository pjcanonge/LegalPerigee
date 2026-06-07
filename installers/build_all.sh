#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# LegalPerigee — Build All Installers
# Run from the project root: bash installers/build_all.sh
# ─────────────────────────────────────────────────────────────────────────────
set -e
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

echo ""
echo "⚖️  LegalPerigee — Installer Builder"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── macOS: rebuild .app then DMG ──────────────────────────────────────────────
echo "🍎  Building macOS installer..."
arch -arm64 .venv/bin/python3 scripts/create_desktop_icon.py
bash installers/macos/build_dmg.sh
echo ""

# ── Windows: generate launcher (icons already built) ─────────────────────────
echo "🪟  Preparing Windows installer files..."

# Regenerate the Windows launcher with current project path baked in
VENV_PYTHON=".venv/bin/python3"
arch -arm64 "$VENV_PYTHON" - << 'PYEOF'
import os
project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) \
    if '__file__' in dir() else os.getcwd()

bat = rf"""@echo off
title LegalPerigee
cd /d "{project_dir}"
if not exist ".venv\Scripts\python.exe" (
    echo Dependencies not installed. Running setup...
    powershell -ExecutionPolicy Bypass -File "installers\windows\setup.ps1"
    exit /b
)
start "" ".venv\Scripts\python.exe" window.py
"""
out = os.path.join(project_dir, "installers", "windows", "LegalPerigee.bat")
with open(out, "w", newline="\r\n") as f:
    f.write(bat)
print(f"  ✅ Windows launcher: {out}")
PYEOF

# Verify .ico exists
if [ -f "installers/windows/LegalPerigee.ico" ]; then
    echo "  ✅ Windows icon: installers/windows/LegalPerigee.ico"
else
    arch -arm64 .venv/bin/python3 -c "
import sys; sys.path.insert(0,'.')
from scripts.create_desktop_icon import draw_icon
imgs = [draw_icon(s) for s in [16,24,32,48,64,128,256]]
imgs[0].save('installers/windows/LegalPerigee.ico', format='ICO',
             sizes=[(s,s) for s in [16,24,32,48,64,128,256]],
             append_images=imgs[1:])
print('  ✅ Windows icon generated')
"
fi

echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅  Build complete!"
echo ""
echo "  macOS:   installers/macos/LegalPerigee-1.0.dmg"
echo "           → Drag to Applications → double-click to launch"
echo ""
echo "  Windows: installers/windows/"
echo "           setup.ps1          → right-click, Run with PowerShell"
echo "           LegalPerigee.bat   → double-click to launch"
echo "           installer.iss      → compile with Inno Setup for .exe"
echo ""
echo "  To build a Windows .exe installer:"
echo "    1. Copy the project to a Windows machine"
echo "    2. Install Inno Setup from jrsoftware.org/isdl.php"
echo "    3. Open installers/windows/installer.iss → Build → Compile"
echo "    4. Find LegalPerigee-Setup.exe in installers/windows/Output/"
echo ""
