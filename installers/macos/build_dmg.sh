#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# LegalPerigee — macOS DMG Builder
# VERSION is read from CHANGELOG.md or overridden via: VERSION=1.5.0 bash build_dmg.sh
# ─────────────────────────────────────────────────────────────────────────────
set -e

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
INSTALLER_DIR="$PROJECT_DIR/installers/macos"
APP_NAME="LegalPerigee"
# Auto-detect version from the first ## [X.Y.Z] line in CHANGELOG.md
if [ -z "$VERSION" ]; then
    VERSION=$(grep -m1 '## \[' "$PROJECT_DIR/CHANGELOG.md" | sed 's/.*\[\(.*\)\].*/\1/')
fi
DMG_NAME="${APP_NAME}-${VERSION}.dmg"
DMG_PATH="$INSTALLER_DIR/$DMG_NAME"
STAGING="$INSTALLER_DIR/.dmg_staging"
VENV_PYTHON="$PROJECT_DIR/.venv/bin/python3"

# Prefer the venv python (has Pillow) but fall back to system python3.
PY="$VENV_PYTHON"; [ -x "$PY" ] || PY="$(command -v python3 || true)"

echo ""
echo "⚖️  LegalPerigee v$VERSION — macOS DMG Builder"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Locate the app bundle. create_desktop_icon.py builds it on the Desktop, while
# users often drag it to /Applications — accept either, and build it if missing.
APP_PATH=""
for cand in "/Applications/${APP_NAME}.app" "$HOME/Desktop/${APP_NAME}.app"; do
    [ -d "$cand" ] && { APP_PATH="$cand"; break; }
done
if [ -z "$APP_PATH" ]; then
    echo "ℹ️  No ${APP_NAME}.app found in /Applications or ~/Desktop — building it…"
    [ -n "$PY" ] && "$PY" "$PROJECT_DIR/scripts/create_desktop_icon.py" || true
    [ -d "$HOME/Desktop/${APP_NAME}.app" ] && APP_PATH="$HOME/Desktop/${APP_NAME}.app"
fi
if [ -z "$APP_PATH" ]; then
    echo "❌  Could not find or build ${APP_NAME}.app."
    echo "    Run:  python3 scripts/create_desktop_icon.py   (creates it on your Desktop)"
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

# Optional cosmetic background image. Don't let a missing Pillow or a non-arm64
# Mac abort the whole build — this is decorative only.
if [ -n "$PY" ] && "$PY" -c "import PIL" 2>/dev/null; then
    "$PY" -c "
from PIL import Image, ImageDraw
import sys
staging = sys.argv[1]
# sys.argv[2] = VERSION
W, H = 660, 400
img = Image.new('RGBA', (W, H), (18, 28, 52))
draw = ImageDraw.Draw(img)
draw.rectangle([0, 0, W, 6], fill=(201, 168, 76))
draw.text((115, 185), 'Drag  LegalPerigee  to  Applications', fill=(228, 217, 176))
draw.text((155, 225), 'Then double-click to launch', fill=(143, 163, 191))
draw.text((165, 265), f'v{sys.argv[2]} — Legal Case Intelligence', fill=(90, 120, 160))
img.convert('RGB').save(staging + '/.background.png')
" "$STAGING" "$VERSION" || echo "⚠️  Background image step skipped (non-fatal)."
else
    echo "ℹ️  Pillow not available — skipping the cosmetic DMG background (non-fatal)."
fi

rm -f "$DMG_PATH"
TEMP_DMG="$INSTALLER_DIR/.temp.dmg"
# Keep hdiutil errors visible — these are the steps most likely to fail.
if ! hdiutil create -volname "$APP_NAME" -srcfolder "$STAGING" \
        -ov -format UDRW -size 100m "$TEMP_DMG"; then
    echo "❌  hdiutil create failed (see error above)."; rm -rf "$STAGING"; exit 1
fi

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

[ -n "$MOUNT_DIR" ] && hdiutil detach "$MOUNT_DIR" > /dev/null 2>&1 || true
if ! hdiutil convert "$TEMP_DMG" -format UDZO -o "$DMG_PATH"; then
    echo "❌  hdiutil convert failed (see error above)."; rm -f "$TEMP_DMG"; rm -rf "$STAGING"; exit 1
fi
rm -f "$TEMP_DMG"; rm -rf "$STAGING"

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "✅  DMG: $DMG_PATH  ($(du -sh "$DMG_PATH" | cut -f1))"
echo "    Users: Open DMG → Drag to Applications → Launch"
echo ""
