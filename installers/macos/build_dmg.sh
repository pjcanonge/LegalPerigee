#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# LegalPerigee v1.1 — macOS DMG Builder
# Output: installers/macos/LegalPerigee-1.1.dmg
# ─────────────────────────────────────────────────────────────────────────────
set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
INSTALLER_DIR="$PROJECT_DIR/installers/macos"
APP_NAME="LegalPerigee"
VERSION="1.2"
DMG_NAME="${APP_NAME}-${VERSION}.dmg"
DMG_PATH="$INSTALLER_DIR/$DMG_NAME"
APP_PATH="/Applications/${APP_NAME}.app"
STAGING="$INSTALLER_DIR/.dmg_staging"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python3"

echo ""
echo "⚖️  LegalPerigee v$VERSION — macOS DMG Builder"
echo "    Source: $APP_PATH"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if [ ! -d "$APP_PATH" ]; then
    echo "❌  LegalPerigee.app not found at $APP_PATH"
    echo "    Run:  python3 scripts/create_desktop_icon.py"
    exit 1
fi
echo "✅  App found: $APP_PATH"

rm -rf "$STAGING"; mkdir -p "$STAGING"
echo "📦  Copying app bundle (excluding .venv — rebuilt on first launch)…"
# Copy the whole bundle then delete the venv so the DMG stays small.
# first_run_check.sh rebuilds the venv automatically on first install.
cp -R "$APP_PATH" "$STAGING/${APP_NAME}.app"
rm -rf "$STAGING/${APP_NAME}.app/Contents/Resources/app/.venv"
ln -s /Applications "$STAGING/Applications"

# Background image
arch -arm64 "$VENV_PYTHON" -c "
from PIL import Image, ImageDraw
import sys
staging = sys.argv[1]
W, H = 660, 400
img = Image.new('RGBA', (W, H), (18, 28, 52))
draw = ImageDraw.Draw(img)
draw.rectangle([0, 0, W, 6], fill=(201, 168, 76))
draw.text((115, 185), 'Drag  LegalPerigee  to  Applications', fill=(228, 217, 176))
draw.text((155, 225), 'Then double-click to launch', fill=(143, 163, 191))
draw.text((165, 265), 'v1.2 — Legal Case Intelligence', fill=(90, 120, 160))
img.convert('RGB').save(staging + '/.background.png')
" "$STAGING"

rm -f "$DMG_PATH"
TEMP_DMG="$INSTALLER_DIR/.temp.dmg"
hdiutil create -volname "$APP_NAME" -srcfolder "$STAGING" \
    -ov -format UDRW -size 100m "$TEMP_DMG" > /dev/null 2>&1

MOUNT_DIR=$(hdiutil attach "$TEMP_DMG" | grep "/Volumes" | awk '{print $3}')

osascript << ASEOF > /dev/null 2>&1 || true
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

hdiutil detach "$MOUNT_DIR" > /dev/null 2>&1
hdiutil convert "$TEMP_DMG" -format UDZO -o "$DMG_PATH" > /dev/null 2>&1
rm -f "$TEMP_DMG"; rm -rf "$STAGING"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅  DMG: $DMG_PATH  ($(du -sh "$DMG_PATH" | cut -f1))"
echo "    Users: Open DMG → Drag to Applications → Launch"
echo ""
