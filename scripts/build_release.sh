#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# LegalPerigee v1.1 — Self-Contained Release Builder
#
# Creates distributable packages that work on ANY machine:
#   macOS: LegalPerigee-1.1-mac.dmg    (drag-to-Applications, zero setup)
#   Windows: LegalPerigee-1.1-win/     (run setup.ps1, one-click install)
#
# Both packages include ALL project files — no pre-installed project folder needed.
# ─────────────────────────────────────────────────────────────────────────────

set -e
cd "$(dirname "${BASH_SOURCE[0]}")/.."

PROJECT_DIR="$(pwd)"
VERSION="1.2"
RELEASE_DIR="$PROJECT_DIR/dist"
  ARCHIVE_DIR="$PROJECT_DIR/releases/v$VERSION"  # also keep versioned copy
MAC_STAGE="$RELEASE_DIR/mac_staging"
WIN_STAGE="$RELEASE_DIR/win_staging"

echo ""
echo "⚖️  LegalPerigee v$VERSION — Release Builder"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""

# ── Security check — abort if any API keys are in source files ────────────────
# M-8 (v1.2): Expanded patterns — covers all credential formats, not just Anthropic
echo "🔒  Scanning source files for exposed API keys..."
LEAK_FOUND=false
while IFS= read -r -d '' file; do
    # Anthropic keys
    if grep -qE 'sk-ant-[A-Za-z0-9_-]{20,}' "$file" 2>/dev/null; then
        echo "  ❌ ANTHROPIC KEY FOUND IN FILE: $file"
        LEAK_FOUND=true
    fi
    # Any sk- prefix key assignment
    if grep -qE '^[A-Z_]+=sk-' "$file" 2>/dev/null; then
        echo "  ❌ KEY IN ENV FILE: $file"
        LEAK_FOUND=true
    fi
    # CourtListener / generic bearer tokens (Token <40-char string>)
    if grep -qE '\bToken [A-Za-z0-9]{30,}' "$file" 2>/dev/null; then
        echo "  ❌ POSSIBLE AUTH TOKEN IN FILE: $file"
        LEAK_FOUND=true
    fi
    # Credential assignments: KEY=, TOKEN=, SECRET=, PASSWORD= with real-looking values
    if grep -qE '^[A-Z_]+(KEY|TOKEN|SECRET|PASSWORD)\s*=\s*[A-Za-z0-9+/]{16,}' "$file" 2>/dev/null; then
        echo "  ❌ POSSIBLE CREDENTIAL IN FILE: $file"
        LEAK_FOUND=true
    fi
done < <(find "$PROJECT_DIR" \
    -not -path "*/.venv/*" \
    -not -path "*/.git/*" \
    -not -path "*/dist/*" \
    -not -path "*/__pycache__/*" \
    \( -name "*.env" -o -name "*.py" -o -name "*.sh" -o -name "*.json" -o -name "*.txt" -o -name "*.log" \) \
    -print0 2>/dev/null)

if [ "$LEAK_FOUND" = "true" ]; then
    echo ""
    echo "  ⛔ BUILD ABORTED — API key or credential found in a source file."
    echo "  Remove the key from the file above, then rebuild."
    echo "  Keys must only be stored in macOS Keychain (app sidebar)."
    exit 1
fi
echo "  ✅ No keys found in source files"
echo ""

# ── Clean release directory ───────────────────────────────────────────────────
rm -rf "$RELEASE_DIR"
mkdir -p "$MAC_STAGE" "$WIN_STAGE"


# ═══════════════════════════════════════════════════════════════════════════════
# macOS — Self-contained .app
# ═══════════════════════════════════════════════════════════════════════════════
echo "🍎  Building macOS package..."

APP_BUNDLE="$MAC_STAGE/LegalPerigee.app"
APP_CONTENTS="$APP_BUNDLE/Contents"
APP_MACOS="$APP_CONTENTS/MacOS"
APP_RES="$APP_CONTENTS/Resources"
APP_CODE="$APP_RES/app"           # all project code lives here

mkdir -p "$APP_MACOS" "$APP_RES" "$APP_CODE"

# ── Copy all project files into the bundle ────────────────────────────────────
echo "  Copying project files..."
rsync -a \
    --exclude ".venv" \
    --exclude ".git" \
    --exclude "__pycache__" \
    --exclude "*.pyc" \
    --exclude ".DS_Store" \
    --exclude "releases" \
    --exclude "node_modules" \
    --exclude "dist" \
    --exclude "data/*.db" \
    --exclude "data/*.db-shm" \
    --exclude "data/*.db-wal" \
    --exclude "data/*.db-journal" \
    --exclude "data/*.json" \
    --exclude "data/debug_*" \
    --exclude "data/security_*" \
    --exclude "*.repair_backup" \
    --exclude ".env" \
    "$PROJECT_DIR/" "$APP_CODE/"

# Write a clean .env template — NEVER copy the project .env (it may have stale keys)
cat > "$APP_CODE/.env" << 'ENVTEMPLATE'
# LegalPerigee — non-sensitive defaults only.
# ALL API keys are stored in macOS Keychain, never here.
# Enter keys once in the app sidebar → they save to Keychain automatically.
ALERT_SMTP_HOST=smtp.gmail.com
ALERT_SMTP_PORT=587
ENVTEMPLATE

# Copy icons + quick start docs
cp "$PROJECT_DIR/AppIcon.icns"   "$APP_RES/AppIcon.icns"
cp "$PROJECT_DIR/data/logo.png"  "$APP_RES/logo.png"  2>/dev/null || true
# Build quick start PDF and include in bundle root (visible in Finder alongside the .app)
python3 "$PROJECT_DIR/scripts/build_quickstart_pdf.py" 2>/dev/null || true
cp "$PROJECT_DIR/QUICKSTART.txt" "$MAC_STAGE/QUICKSTART.txt" 2>/dev/null || true
cp "$PROJECT_DIR/dist/LegalPerigee-QuickStart.pdf" "$MAC_STAGE/LegalPerigee-QuickStart.pdf" 2>/dev/null || true

# ── Info.plist ────────────────────────────────────────────────────────────────
cat > "$APP_CONTENTS/Info.plist" << 'PLIST'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleExecutable</key>   <string>LegalPerigee</string>
  <key>CFBundleIconFile</key>     <string>AppIcon</string>
  <key>CFBundleIdentifier</key>   <string>ai.legalperigee.app</string>
  <key>CFBundleName</key>         <string>LegalPerigee</string>
  <key>CFBundleDisplayName</key>  <string>LegalPerigee</string>
  <key>CFBundlePackageType</key>  <string>APPL</string>
  <key>CFBundleShortVersionString</key> <string>1.2</string>
  <key>CFBundleVersion</key>      <string>1</string>
  <key>LSMinimumSystemVersion</key> <string>12.0</string>
  <key>NSHighResolutionCapable</key> <true/>
</dict>
</plist>
PLIST

# ── Self-contained launcher ───────────────────────────────────────────────────
# This launcher finds Python, sets up the venv INSIDE the bundle, and launches.
cat > "$APP_MACOS/LegalPerigee" << 'LAUNCHER'
#!/bin/bash
# LegalPerigee v1.1 — Self-Contained Launcher
# Project is embedded at Contents/Resources/app/

# Resolve bundle paths regardless of where the .app was placed
BUNDLE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
APP_CODE="$BUNDLE_DIR/Contents/Resources/app"
VENV_DIR="$APP_CODE/.venv"
LOG_FILE="$HOME/Library/Logs/LegalPerigee.log"
CHECKER="$APP_CODE/installers/macos/first_run_check.sh"

# Data directory in user home (persists across updates)
DATA_DIR="$HOME/Library/Application Support/LegalPerigee"
mkdir -p "$DATA_DIR"

# Symlink data dir so db/logs go to user space
if [ ! -L "$APP_CODE/data" ]; then
    [ -d "$APP_CODE/data" ] && cp -r "$APP_CODE/data" "$DATA_DIR/" 2>/dev/null || true
    rm -rf "$APP_CODE/data"
    ln -sf "$DATA_DIR" "$APP_CODE/data"
fi

# Run conflict/health checker
if [ -f "$CHECKER" ]; then
    chmod +x "$CHECKER"
    bash "$CHECKER" "$APP_CODE" || exit 1
fi

PYTHON="$VENV_DIR/bin/python3"
if [ ! -x "$PYTHON" ]; then
    osascript -e "display alert \"LegalPerigee\" message \"First-time setup failed.\n\nOpen Terminal and run:\n  bash '$APP_CODE/setup.sh'\" as critical"
    exit 1
fi

# L-1 (v1.2): Detect CPU architecture at runtime — supports both Apple Silicon and Intel
ARCH=$(uname -m)
if [ "$ARCH" = "arm64" ]; then
    exec arch -arm64 "$PYTHON" "$APP_CODE/window.py"
else
    exec "$PYTHON" "$APP_CODE/window.py"
fi
LAUNCHER
chmod +x "$APP_MACOS/LegalPerigee"

# ── Build DMG ─────────────────────────────────────────────────────────────────
echo "  Building DMG..."
ln -s /Applications "$MAC_STAGE/Applications"

DMG_PATH="$RELEASE_DIR/LegalPerigee-${VERSION}-mac.dmg"
  mkdir -p "$RELEASE_DIR"
TEMP_DMG="$RELEASE_DIR/.temp_mac.dmg"
rm -f "$DMG_PATH"

# Build DMG directly from folder (no osascript — avoids Finder hangs)
hdiutil create \
    -volname "LegalPerigee $VERSION" \
    -srcfolder "$MAC_STAGE" \
    -ov -format UDZO \
    -fs HFS+ \
    "$DMG_PATH" > /dev/null 2>&1

MAC_SIZE=$(du -sh "$DMG_PATH" | cut -f1)
echo "  ✅ macOS DMG: $DMG_PATH ($MAC_SIZE)"


# ═══════════════════════════════════════════════════════════════════════════════
# Windows — Self-contained folder package
# ═══════════════════════════════════════════════════════════════════════════════
echo ""
echo "🪟  Building Windows package..."

WIN_DEST="$WIN_STAGE/LegalPerigee"
mkdir -p "$WIN_DEST"

# Copy all project files — exclude .env and all sensitive data files
rsync -a \
    --exclude ".venv" \
    --exclude ".git" \
    --exclude "__pycache__" \
    --exclude "*.pyc" \
    --exclude ".DS_Store" \
    --exclude "releases" \
    --exclude "node_modules" \
    --exclude "dist" \
    --exclude "data/*.db" \
    --exclude "data/*.db-shm" \
    --exclude "data/*.db-wal" \
    --exclude "data/*.db-journal" \
    --exclude "data/*.json" \
    --exclude "data/debug_*" \
    --exclude "data/security_*" \
    --exclude "*.repair_backup" \
    --exclude ".env" \
    "$PROJECT_DIR/" "$WIN_DEST/"

# Write a clean .env template for Windows too
cat > "$WIN_DEST/.env" << 'ENVTEMPLATE'
# LegalPerigee — non-sensitive defaults only.
# ALL API keys are stored in Windows Credential Manager, never here.
# Enter keys once in the app sidebar → they save to Credential Manager automatically.
ALERT_SMTP_HOST=smtp.gmail.com
ALERT_SMTP_PORT=587
ENVTEMPLATE

# Create a friendly Windows README
cat > "$WIN_DEST/INSTALL.txt" << 'WINTXT'
═══════════════════════════════════════════════════════
  ⚖  LegalPerigee v1.1 — Windows Installation
  Legal Case Intelligence Platform
═══════════════════════════════════════════════════════

QUICK START
───────────
1. Right-click "setup.ps1" in this folder
2. Select "Run with PowerShell"
3. Allow it to install dependencies (~2-5 minutes)
4. A LegalPerigee shortcut appears on your Desktop

If you see a "Run anyway" prompt, click it — the script
is safe and open-source.

REQUIREMENTS
────────────
• Windows 10 or 11 (64-bit)
• Internet connection (for first-time setup only)
• Python 3.9+ (auto-installed if missing)
• Edge WebView2 (auto-installed if missing)

FIRST LAUNCH
────────────
Enter your Anthropic API key in the sidebar.
Get a free key at: console.anthropic.com → API Keys

SUPPORT
───────
Logs: %TEMP%\LegalPerigee_setup.log
Data: %LOCALAPPDATA%\LegalPerigee\

═══════════════════════════════════════════════════════
WINTXT

# Add quick start docs to Windows package root
cp "$PROJECT_DIR/QUICKSTART.txt" "$WIN_DEST/QUICKSTART.txt" 2>/dev/null || true
cp "$PROJECT_DIR/dist/LegalPerigee-QuickStart.pdf" "$WIN_DEST/LegalPerigee-QuickStart.pdf" 2>/dev/null || true

# Zip the Windows package
WIN_ZIP="$RELEASE_DIR/LegalPerigee-${VERSION}-windows.zip"
cd "$WIN_STAGE"
zip -r "$WIN_ZIP" "LegalPerigee/" -x "*/\.*" > /dev/null 2>&1
cd "$PROJECT_DIR"

WIN_SIZE=$(du -sh "$WIN_ZIP" | cut -f1)
echo "  ✅ Windows ZIP: $WIN_ZIP ($WIN_SIZE)"


# ═══════════════════════════════════════════════════════════════════════════════
# Summary
# ═══════════════════════════════════════════════════════════════════════════════
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "🎉  Release v$VERSION ready for distribution"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "  📁 Release folder: $RELEASE_DIR"
echo ""
echo "  🍎 macOS:   LegalPerigee-${VERSION}-mac.dmg  ($MAC_SIZE)"
echo "     → User opens DMG, drags to Applications, double-clicks"
echo "     → First launch: installs deps automatically (~2 min)"
echo ""
echo "  🪟 Windows: LegalPerigee-${VERSION}-windows.zip  ($WIN_SIZE)"
echo "     → User unzips, right-clicks setup.ps1 → Run with PowerShell"
echo "     → Installs deps, creates Desktop shortcut automatically"
echo ""
echo "  ✅ Both packages include all source code — no project folder needed"
echo "  ✅ Case Library, Alerts & Document Viewer work without any key; add an Anthropic key to unlock AI features"
echo ""

# Copy to dist/ for easy access
mkdir -p "$PROJECT_DIR/dist"
cp "$DMG_PATH" "$PROJECT_DIR/dist/"
cp "$WIN_ZIP"  "$PROJECT_DIR/dist/"
echo "  📁 Also copied to: $PROJECT_DIR/dist/"
open "$PROJECT_DIR/dist" 2>/dev/null || true
