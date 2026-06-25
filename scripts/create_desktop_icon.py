#!/usr/bin/env python3
"""
LegalPerigee — Desktop Icon & macOS App Bundle Creator

Draws the icon using Pillow, packages it as a proper .icns file,
and creates a double-clickable LegalPerigee.app on your Desktop.

Run once:
    python3 scripts/create_desktop_icon.py
"""

import math
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

# ── Ensure Pillow ─────────────────────────────────────────────────────────────
try:
    from PIL import Image, ImageDraw, ImageFont, ImageFilter
except ImportError:
    print("Installing Pillow...")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "Pillow"])
    from PIL import Image, ImageDraw, ImageFont, ImageFilter

PROJECT_DIR = Path(__file__).parent.parent.resolve()
DESKTOP      = Path.home() / "Desktop"
APP_NAME     = "LegalPerigee"


# ── Version detection ─────────────────────────────────────────────────────────

def detect_version() -> tuple[str, str]:
    """Read the latest version from CHANGELOG.md (same source as build_dmg.sh).

    Returns (short_version, build) e.g. ("1.4.0", "14"). Falls back to
    ("1.0", "1") if the changelog can't be parsed.
    """
    changelog = PROJECT_DIR / "CHANGELOG.md"
    try:
        for line in changelog.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            # First "## [X.Y.Z]" heading is the current release.
            if line.startswith("## [") and "]" in line:
                short = line[line.index("[") + 1:line.index("]")].strip()
                parts = short.split(".")
                if len(parts) >= 2 and parts[0].isdigit() and parts[1].isdigit():
                    build = f"{parts[0]}{parts[1]}"  # 1.4.0 -> "14"
                    return short, build
    except OSError:
        pass
    return "1.0", "1"

# ── Icon colors ───────────────────────────────────────────────────────────────
NAVY        = (18, 28, 52)
NAVY_MID    = (24, 38, 66)
NAVY_LIGHT  = (32, 52, 88)
GOLD        = (201, 168, 76)
GOLD_LIGHT  = (228, 200, 120)
GOLD_DIM    = (160, 132, 58)
WHITE_SOFT  = (230, 220, 195)


# ── Icon drawing ──────────────────────────────────────────────────────────────

def draw_icon(size: int) -> Image.Image:
    """Draw the LegalPerigee icon at `size × size` pixels."""
    # Draw at 4× for crisp anti-aliasing, then LANCZOS downscale
    S = size * 4
    img  = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    cx = S // 2
    cy = S // 2
    r  = S // 5  # corner radius

    # ── Background: layered rounded rects for a subtle gradient ────────────────
    steps = 18
    for i in range(steps, -1, -1):
        t = i / steps
        c = tuple(int(NAVY[j] + (NAVY_LIGHT[j] - NAVY[j]) * (1 - t)) for j in range(3))
        pad = int(i * S * 0.012)
        draw.rounded_rectangle(
            [pad, pad, S - 1 - pad, S - 1 - pad],
            radius=max(6, r - pad // 2),
            fill=c,
        )

    # ── Subtle orbit arc behind the scales ────────────────────────────────────
    arc_r  = int(S * 0.37)
    arc_w  = max(3, S // 70)
    arc_clr = (50, 80, 128, 160)

    # Create a separate layer for the semi-transparent arc
    arc_layer = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    arc_draw  = ImageDraw.Draw(arc_layer)
    arc_draw.arc(
        [cx - arc_r, cy - arc_r, cx + arc_r, cy + arc_r],
        start=200, end=340,
        fill=(60, 95, 150),
        width=arc_w,
    )
    # Small dots at arc endpoints
    for deg in (200, 340):
        rad = math.radians(deg)
        ax  = cx + arc_r * math.cos(rad)
        ay  = cy + arc_r * math.sin(rad)
        dr  = max(3, S // 55)
        arc_draw.ellipse([ax - dr, ay - dr, ax + dr, ay + dr], fill=(70, 110, 175))
    img.alpha_composite(arc_layer)
    draw = ImageDraw.Draw(img)

    # ── Scales geometry ────────────────────────────────────────────────────────
    top_y   = int(S * 0.185)
    base_y  = int(S * 0.790)
    beam_y  = int(S * 0.295)
    barm    = int(S * 0.295)   # half-width of beam arm
    tilt    = int(S * 0.014)   # slight tilt
    pw      = max(3, S // 52)  # pillar width (half)

    lx = cx - barm             # left beam end x
    rx = cx + barm             # right beam end x
    ly = beam_y + tilt         # left beam end y (lower)
    ry = beam_y - tilt         # right beam end y (higher)

    # ── Pillar ─────────────────────────────────────────────────────────────────
    # Shadow pass
    draw.rectangle([cx - pw + 3, top_y + 3, cx + pw + 3, base_y + 3],
                   fill=GOLD_DIM)
    # Main pillar
    draw.rectangle([cx - pw, top_y, cx + pw, base_y], fill=GOLD)

    # ── Base (trapezoid) ───────────────────────────────────────────────────────
    bw  = int(S * 0.20)
    bh  = max(5, S // 20)
    slant = bh // 3
    base_pts = [
        (cx - bw,          base_y),
        (cx + bw,          base_y),
        (cx + bw - slant,  base_y + bh),
        (cx - bw + slant,  base_y + bh),
    ]
    draw.polygon(base_pts, fill=GOLD_DIM)     # shadow
    off = 3
    shadow_base = [(x + off, y + off) for x, y in base_pts]
    draw.polygon(shadow_base, fill=GOLD_DIM)
    draw.polygon(base_pts, fill=GOLD)
    # Highlight top edge of base
    draw.line([cx - bw, base_y, cx + bw, base_y], fill=GOLD_LIGHT, width=max(2, S // 80))

    # ── Beam ───────────────────────────────────────────────────────────────────
    bth = max(3, S // 48)
    beam_shadow = [
        (lx + 3, ly - bth + 3), (rx + 3, ry - bth + 3),
        (rx + 3, ry + bth + 3), (lx + 3, ly + bth + 3),
    ]
    draw.polygon(beam_shadow, fill=GOLD_DIM)
    beam_pts = [
        (lx, ly - bth), (rx, ry - bth),
        (rx, ry + bth), (lx, ly + bth),
    ]
    draw.polygon(beam_pts, fill=GOLD)
    # Highlight on top of beam
    draw.line([lx, ly - bth, rx, ry - bth], fill=GOLD_LIGHT, width=max(2, S // 100))

    # ── Center pivot ───────────────────────────────────────────────────────────
    kn = max(6, S // 28)
    draw.ellipse([cx - kn, beam_y - kn, cx + kn, beam_y + kn], fill=GOLD_DIM)
    if kn > 4:
        draw.ellipse([cx - kn + 3, beam_y - kn + 3, cx + kn - 3, beam_y + kn - 3], fill=GOLD)
    if kn > 8:
        draw.ellipse([cx - kn + 7, beam_y - kn + 7, cx + kn - 7, beam_y + kn - 7], fill=GOLD_LIGHT)

    # ── Chains (dotted lines) ──────────────────────────────────────────────────
    def draw_chain(x1, y1, x2, y2):
        length  = math.hypot(x2 - x1, y2 - y1)
        segs    = max(4, int(length / (S // 28)))
        link_r  = max(2, S // 90)
        for i in range(segs + 1):
            t  = i / max(1, segs)
            px = x1 + (x2 - x1) * t
            py = y1 + (y2 - y1) * t
            draw.ellipse([px - link_r, py - link_r, px + link_r, py + link_r], fill=GOLD)

    chain_drop = int(S * 0.225)
    lpan_cy    = ly + chain_drop
    rpan_cy    = ry + chain_drop - int(S * 0.028)

    draw_chain(lx, ly, lx, lpan_cy)
    draw_chain(rx, ry, rx, rpan_cy)

    # ── Pans ───────────────────────────────────────────────────────────────────
    prx = int(S * 0.095)   # pan half-width
    pry = max(4, S // 42)  # pan half-height

    def draw_pan(pcx, pcy):
        # Dark fill for the inside of the pan (depth)
        draw.ellipse([pcx - prx, pcy, pcx + prx, pcy + pry * 2],
                     fill=(28, 42, 68))
        # Gold rim
        draw.ellipse([pcx - prx, pcy - pry, pcx + prx, pcy + pry],
                     fill=GOLD)
        # Highlight on top
        inner = max(2, prx - S // 55)
        draw.ellipse([pcx - inner, pcy - pry + 3, pcx + inner, pcy - pry + 6],
                     fill=GOLD_LIGHT)

    draw_pan(lx, lpan_cy - pry)
    draw_pan(rx, rpan_cy - pry)

    # ── Star accents ──────────────────────────────────────────────────────────
    for angle_deg, dist, alpha in [(38, 0.40, 90), (142, 0.40, 70)]:
        ang = math.radians(angle_deg)
        sx  = cx + int(S * dist * math.cos(ang))
        sy  = cy + int(S * dist * math.sin(ang))
        sr  = max(3, S // 65)
        # 4-point star
        star_clr = (*GOLD_DIM, alpha)
        for ang2 in (ang, ang + math.pi / 2, ang + math.pi, ang + 3 * math.pi / 2):
            ex = sx + int(sr * 1.8 * math.cos(ang2))
            ey = sy + int(sr * 1.8 * math.sin(ang2))
            draw.line([sx, sy, ex, ey], fill=(*GOLD, alpha), width=max(1, S // 120))
        draw.ellipse([sx - sr, sy - sr, sx + sr, sy + sr], fill=(*GOLD_DIM, alpha))

    # ── "LP" monogram ─────────────────────────────────────────────────────────
    if size >= 32:
        fsize = max(14, S // 11)
        font  = None
        for fp in [
            "/System/Library/Fonts/Supplemental/FuturaMediumItalic.ttf",
            "/System/Library/Fonts/Supplemental/Futura Medium Italic.ttf",
            "/System/Library/Fonts/HelveticaNeue.ttc",
            "/System/Library/Fonts/Helvetica.ttc",
            "/System/Library/Fonts/Arial.ttf",
            "/Library/Fonts/Arial.ttf",
        ]:
            if Path(fp).exists():
                try:
                    font = ImageFont.truetype(fp, fsize)
                    break
                except Exception:
                    continue
        if font is None:
            font = ImageFont.load_default()

        text = "LP"
        bb   = draw.textbbox((0, 0), text, font=font)
        tw   = bb[2] - bb[0]
        tx   = cx - tw // 2
        ty   = int(S * 0.855)

        # Slight text shadow
        draw.text((tx + 2, ty + 2), text, fill=(*GOLD_DIM, 160), font=font)
        draw.text((tx, ty), text, fill=GOLD_LIGHT, font=font)

    # ── Final border highlight ─────────────────────────────────────────────────
    draw.rounded_rectangle(
        [2, 2, S - 3, S - 3],
        radius=r,
        outline=(*GOLD_DIM, 60),
        width=4,
    )

    # ── Downscale ─────────────────────────────────────────────────────────────
    return img.resize((size, size), Image.LANCZOS)


# ── Build .iconset ────────────────────────────────────────────────────────────

ICONSET_SIZES = [
    (16,   "icon_16x16"),
    (32,   "icon_16x16@2x"),
    (32,   "icon_32x32"),
    (64,   "icon_32x32@2x"),
    (128,  "icon_128x128"),
    (256,  "icon_128x128@2x"),
    (256,  "icon_256x256"),
    (512,  "icon_256x256@2x"),
    (512,  "icon_512x512"),
    (1024, "icon_512x512@2x"),
]


def build_iconset(iconset_dir: Path) -> None:
    iconset_dir.mkdir(parents=True, exist_ok=True)
    seen: dict[int, Image.Image] = {}
    for size, name in ICONSET_SIZES:
        if size not in seen:
            print(f"  Drawing {size}×{size}…")
            seen[size] = draw_icon(size)
        seen[size].save(iconset_dir / f"{name}.png")
    print(f"  Saved {len(ICONSET_SIZES)} PNG files to {iconset_dir.name}")


def build_icns(iconset_dir: Path, icns_path: Path) -> bool:
    result = subprocess.run(
        ["iconutil", "-c", "icns", str(iconset_dir), "-o", str(icns_path)],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        print(f"  iconutil error: {result.stderr}")
        return False
    print(f"  Created {icns_path.name}")
    return True


# ── macOS .app bundle ─────────────────────────────────────────────────────────

INFO_PLIST = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>{app_name}</string>
    <key>CFBundleIconFile</key>
    <string>AppIcon</string>
    <key>CFBundleIdentifier</key>
    <string>ai.legalperigee.app</string>
    <key>CFBundleName</key>
    <string>{app_name}</string>
    <key>CFBundleDisplayName</key>
    <string>{app_name}</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>{version}</string>
    <key>CFBundleVersion</key>
    <string>{build}</string>
    <key>LSMinimumSystemVersion</key>
    <string>12.0</string>
    <key>NSHighResolutionCapable</key>
    <true/>
    <key>LSUIElement</key>
    <false/>
</dict>
</plist>
"""

LAUNCHER_SCRIPT = """\
#!/bin/bash
# LegalPerigee — Smart Launcher with conflict detection
PROJECT_DIR="{project_dir}"
VENV_DIR="$PROJECT_DIR/.venv"
LOG_FILE="$HOME/Library/Logs/LegalPerigee.log"
CHECKER="$PROJECT_DIR/installers/macos/first_run_check.sh"
WINDOW_SCRIPT="$PROJECT_DIR/window.py"

# ── Verify project folder ─────────────────────────────────────────────────────
cd "$PROJECT_DIR" 2>/dev/null || {{
    osascript -e 'display alert "LegalPerigee" message "Project folder not found:\\n{project_dir}\\n\\nMove the LegalPerigee folder back to its original location." as critical'
    exit 1
}}

# ── Run conflict + health checker ─────────────────────────────────────────────
if [ -f "$CHECKER" ]; then
    chmod +x "$CHECKER"
    bash "$CHECKER" "$PROJECT_DIR"
    CHECK_EXIT=$?
    if [ $CHECK_EXIT -ne 0 ]; then
        # Checker already showed the error dialog — just exit
        exit $CHECK_EXIT
    fi
fi

# ── Verify venv after checker ─────────────────────────────────────────────────
PYTHON="$VENV_DIR/bin/python3"
if [ ! -x "$PYTHON" ]; then
    osascript -e 'display alert "LegalPerigee" message "Setup incomplete.\\n\\nOpen Terminal and run:\\n\\n  bash {project_dir}/setup.sh" as critical'
    exit 1
fi

# ── Launch native window ──────────────────────────────────────────────────────
exec arch -arm64 "$PYTHON" "$WINDOW_SCRIPT"
"""


def build_app_bundle(app_path: Path, icns_path: Path) -> None:
    # Clean existing bundle
    if app_path.exists():
        shutil.rmtree(app_path)

    macos_dir     = app_path / "Contents" / "MacOS"
    resources_dir = app_path / "Contents" / "Resources"
    macos_dir.mkdir(parents=True)
    resources_dir.mkdir(parents=True)

    # Info.plist — version/build read from CHANGELOG.md so the regenerated
    # bundle always matches the latest release (the "final build").
    version, build = detect_version()
    (app_path / "Contents" / "Info.plist").write_text(
        INFO_PLIST.format(app_name=APP_NAME, version=version, build=build)
    )
    print(f"  Info.plist → v{version} (build {build})")

    # Icon
    if icns_path.exists():
        shutil.copy(icns_path, resources_dir / "AppIcon.icns")

    # Executable launcher
    exe_path = macos_dir / APP_NAME
    exe_path.write_text(
        LAUNCHER_SCRIPT.format(project_dir=str(PROJECT_DIR))
    )
    exe_path.chmod(0o755)

    print(f"  Built {app_path}")


def set_app_icon_via_applescript(app_path: Path, icns_path: Path) -> None:
    """Use AppleScript + Finder to set the custom dock/Finder icon."""
    script = f"""
    tell application "Finder"
        set f to (POSIX file "{app_path}") as alias
        set icon of f to (POSIX file "{icns_path}") as alias
    end tell
    """
    result = subprocess.run(["osascript", "-e", script], capture_output=True, text=True)
    if result.returncode == 0:
        print("  Finder icon applied.")
    else:
        # Non-fatal — the .icns in the bundle is enough for Spotlight/Dock
        print(f"  Note: AppleScript icon set skipped ({result.stderr.strip()[:80]})")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    print("\n⚖️  LegalPerigee — Desktop Icon Creator\n")

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path    = Path(tmp)
        iconset_dir = tmp_path / "AppIcon.iconset"
        icns_path   = PROJECT_DIR / "AppIcon.icns"
        app_path    = DESKTOP / f"{APP_NAME}.app"

        # 1 — Draw icons
        print("1/4  Drawing icon artwork…")
        build_iconset(iconset_dir)

        # 2 — Convert to .icns
        print("2/4  Converting to .icns…")
        ok = build_icns(iconset_dir, icns_path)
        if not ok:
            # Fallback: copy the largest PNG as the icon
            largest = iconset_dir / "icon_512x512@2x.png"
            if largest.exists():
                shutil.copy(largest, PROJECT_DIR / "AppIcon.png")
                print("  Saved AppIcon.png (iconutil unavailable).")

        # 3 — Build .app bundle
        print("3/4  Building LegalPerigee.app…")
        build_app_bundle(app_path, icns_path)

        # 4 — Touch Finder to refresh icon cache
        print("4/4  Refreshing Finder icon cache…")
        set_app_icon_via_applescript(app_path, icns_path)
        subprocess.run(["touch", str(app_path)], check=False)
        subprocess.run(
            ["killall", "Dock"],
            capture_output=True, check=False,
        )

    print(f"""
✅  Done!

   {DESKTOP / (APP_NAME + '.app')}

Double-click it to launch LegalPerigee in your browser.
Logs → ~/Library/Logs/LegalPerigee.log
""")


if __name__ == "__main__":
    main()
