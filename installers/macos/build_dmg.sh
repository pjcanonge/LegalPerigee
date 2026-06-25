#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# LegalPerigee — macOS DMG Builder (self-contained / relocatable)
#
# Builds a distributable LegalPerigee.app whose project source is bundled INSIDE
# the app (Contents/Resources/app), with a relocatable launcher that creates its
# venv and stores its database under ~/Library/Application Support/LegalPerigee.
# That means the DMG runs on ANY Mac — it does not depend on a project folder
# pre-existing at a hardcoded path.
#
# Usage:   bash installers/macos/build_dmg.sh
#          VERSION=1.5.0 bash installers/macos/build_dmg.sh   # override version
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
INSTALLER_DIR="$PROJECT_DIR/installers/macos"
APP_NAME="LegalPerigee"

if [ -z "${VERSION:-}" ]; then
    VERSION=$(grep -m1 '## \[[0-9]' "$PROJECT_DIR/CHANGELOG.md" | sed 's/.*\[\(.*\)\].*/\1/')
fi
DMG_NAME="${APP_NAME}-${VERSION}.dmg"
DMG_PATH="$INSTALLER_DIR/$DMG_NAME"
STAGING="$INSTALLER_DIR/.dmg_staging"
APP="$STAGING/${APP_NAME}.app"

# Prefer the venv python (has Pillow) but fall back to system python3.
PY="$PROJECT_DIR/.venv/bin/python3"; [ -x "$PY" ] || PY="$(command -v python3 || true)"

echo ""
echo "⚖️  LegalPerigee v$VERSION — self-contained DMG Builder"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── Assemble a fresh, self-contained .app bundle ──────────────────────────────
rm -rf "$STAGING"; mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources/app"

# Info.plist (version from CHANGELOG; build = major+minor, e.g. 1.5.0 -> 15)
BUILD="$(echo "$VERSION" | awk -F. '{print $1$2}')"
cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key><string>${APP_NAME}</string>
    <key>CFBundleIconFile</key><string>AppIcon</string>
    <key>CFBundleIdentifier</key><string>ai.legalperigee.app</string>
    <key>CFBundleName</key><string>${APP_NAME}</string>
    <key>CFBundleDisplayName</key><string>${APP_NAME}</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>${VERSION}</string>
    <key>CFBundleVersion</key><string>${BUILD}</string>
    <key>LSMinimumSystemVersion</key><string>12.0</string>
    <key>NSHighResolutionCapable</key><true/>
    <key>LSUIElement</key><false/>
</dict>
</plist>
PLIST

# Icon (committed at repo root)
[ -f "$PROJECT_DIR/AppIcon.icns" ] && cp "$PROJECT_DIR/AppIcon.icns" "$APP/Contents/Resources/AppIcon.icns"

# Bundle the project source (read-only at runtime). Exclude VCS, venvs, caches,
# the DB, build artifacts, docs, and the installers/CI themselves.
echo "📦  Bundling project source…"
rsync -a \
    --exclude '.git' --exclude '.github' \
    --exclude '.venv' --exclude '__pycache__' --exclude '*.pyc' \
    --exclude 'data/cases.db*' \
    --exclude 'installers' --exclude 'releases' \
    --exclude '*.dmg' --exclude '*.zip' \
    --exclude 'LegalPerigee-v2' --exclude '.dmg_staging' \
    "$PROJECT_DIR"/ "$APP/Contents/Resources/app/"

# Relocatable launcher — venv + data live in Application Support (writable).
cat > "$APP/Contents/MacOS/${APP_NAME}" <<'LAUNCH'
#!/bin/bash
# LegalPerigee — self-contained launcher
HERE="$(cd "$(dirname "$0")" && pwd)"
APP_SRC="$(cd "$HERE/../Resources/app" && pwd)"
SUPPORT="$HOME/Library/Application Support/LegalPerigee"
VENV="$SUPPORT/.venv"
LOG="$HOME/Library/Logs/LegalPerigee.log"

export LP_DATA_DIR="$SUPPORT/data"
mkdir -p "$SUPPORT" "$LP_DATA_DIR" "$(dirname "$LOG")"

export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:$PATH"

PY3="$(command -v python3 || true)"
if [ -z "$PY3" ]; then
    osascript -e 'display alert "LegalPerigee" message "Python 3 is required.\n\nInstall it from python.org or run:\n  xcode-select --install" as critical'
    exit 1
fi

# First launch (or after a Python upgrade): create the venv and install deps.
if [ ! -x "$VENV/bin/python3" ] || ! "$VENV/bin/python3" -c "import streamlit" 2>/dev/null; then
    osascript -e 'display notification "Setting up LegalPerigee (first launch, ~1–2 min)…" with title "LegalPerigee"' 2>/dev/null || true
    {
        "$PY3" -m venv "$VENV"
        "$VENV/bin/python3" -m pip install --upgrade pip
        "$VENV/bin/python3" -m pip install -r "$APP_SRC/requirements.txt"
    } >>"$LOG" 2>&1 || {
        osascript -e 'display alert "LegalPerigee" message "Setup failed installing dependencies. See ~/Library/Logs/LegalPerigee.log" as critical'
        exit 1
    }
fi

cd "$APP_SRC"
exec "$VENV/bin/python3" "$APP_SRC/window.py" >>"$LOG" 2>&1
LAUNCH
chmod +x "$APP/Contents/MacOS/${APP_NAME}"

ln -s /Applications "$STAGING/Applications"
echo "✅  Bundle assembled: $APP"

# ── Optional cosmetic DMG background (non-fatal) ──────────────────────────────
if [ -n "$PY" ] && "$PY" -c "import PIL" 2>/dev/null; then
    "$PY" - "$STAGING" "$VERSION" <<'PYBG' || echo "⚠️  Background image skipped (non-fatal)."
from PIL import Image, ImageDraw
import sys
staging, version = sys.argv[1], sys.argv[2]
W, H = 660, 400
img = Image.new("RGBA", (W, H), (18, 28, 52))
d = ImageDraw.Draw(img)
d.rectangle([0, 0, W, 6], fill=(201, 168, 76))
d.text((115, 185), "Drag  LegalPerigee  to  Applications", fill=(228, 217, 176))
d.text((155, 225), "Then double-click to launch", fill=(143, 163, 191))
d.text((165, 265), f"v{version} — Legal Case Intelligence", fill=(90, 120, 160))
img.convert("RGB").save(staging + "/.background.png")
PYBG
else
    echo "ℹ️  Pillow unavailable — skipping cosmetic background (non-fatal)."
fi

# ── Package the DMG (errors surfaced, not swallowed) ──────────────────────────
rm -f "$DMG_PATH"
TEMP_DMG="$INSTALLER_DIR/.temp.dmg"
if ! hdiutil create -volname "$APP_NAME" -srcfolder "$STAGING" \
        -ov -format UDRW -size 400m "$TEMP_DMG"; then
    echo "❌  hdiutil create failed."; rm -rf "$STAGING"; exit 1
fi

MOUNT_DIR=$(hdiutil attach "$TEMP_DMG" | grep "/Volumes" | awk '{print $3}')

# Window styling is cosmetic and GUI-only — never fail the build over it.
osascript <<ASEOF >/dev/null 2>&1 || true
tell application "Finder"
    tell disk "$APP_NAME"
        open
        set current view of container window to icon view
        set toolbar visible of container window to false
        set statusbar visible of container window to false
        set bounds of container window to {400, 100, 1060, 500}
        set theViewOptions to icon view options of container window
        set arrangement of theViewOptions to not arranged
        set icon size of theViewOptions to 128
        set position of item "${APP_NAME}.app" of container window to {180, 185}
        set position of item "Applications" of container window to {480, 185}
        close; open; update without registering applications; delay 2; close
    end tell
end tell
ASEOF

[ -n "${MOUNT_DIR:-}" ] && hdiutil detach "$MOUNT_DIR" >/dev/null 2>&1 || true
if ! hdiutil convert "$TEMP_DMG" -format UDZO -o "$DMG_PATH"; then
    echo "❌  hdiutil convert failed."; rm -f "$TEMP_DMG"; rm -rf "$STAGING"; exit 1
fi
rm -f "$TEMP_DMG"; rm -rf "$STAGING"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅  DMG: $DMG_PATH  ($(du -sh "$DMG_PATH" | cut -f1))"
echo "    Open DMG → drag to Applications → launch (first run sets up deps)."
echo ""
