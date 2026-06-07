#!/usr/bin/env python3
"""
LegalPerigee — Real Moon Photo Icon
Uses a NASA/Wikipedia full moon photograph as the background,
scales of justice in gold overlay. No text — pure visual.
"""

import math, os, shutil, subprocess, sys, tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

try:
    from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageEnhance
except ImportError:
    subprocess.check_call([sys.executable, "-m", "pip", "install", "Pillow"])
    from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageEnhance

PROJECT_DIR = Path(__file__).parent.parent
DESKTOP     = Path.home() / "Desktop"
APP_NAME    = "LegalPerigee"
MOON_PHOTO  = PROJECT_DIR / "data" / "moon_photo.jpg"

GOLD   = (201, 168, 76)
GOLD_L = (228, 200, 120)
GOLD_D = (140, 108, 40)
NAVY   = (12,  22,  44)


def draw_icon(size: int) -> Image.Image:
    S  = size * 4       # 4× super-sample for anti-aliasing
    cx = cy = S // 2
    r  = S // 5         # corner radius

    # ── Background: real moon photo ───────────────────────────────────────────
    moon = Image.open(MOON_PHOTO).convert("RGBA")

    # Crop moon photo to a square (centered)
    w, h = moon.size
    side = min(w, h)
    moon = moon.crop(((w-side)//2, (h-side)//2, (w+side)//2, (h+side)//2))

    # Resize to icon canvas size, then slightly enlarge so moon fills the frame
    fill_size = int(S * 1.02)
    moon = moon.resize((fill_size, fill_size), Image.LANCZOS)
    # Center-crop back to S×S
    off = (fill_size - S) // 2
    moon = moon.crop((off, off, off+S, off+S))

    # Slightly enhance contrast and cool the tone for a dramatic night feel
    moon = ImageEnhance.Contrast(moon).enhance(1.15)
    moon = ImageEnhance.Brightness(moon).enhance(0.88)
    # Cool color shift — blue-ish night tint
    r_ch, g_ch, b_ch, a_ch = moon.split()
    r_ch = ImageEnhance.Brightness(r_ch.convert("RGB")).enhance(0.92).split()[0]
    b_ch = ImageEnhance.Brightness(b_ch.convert("RGB")).enhance(1.08).split()[0]
    moon = Image.merge("RGBA", (r_ch, g_ch, b_ch, a_ch))

    # ── Compose onto rounded-square canvas ────────────────────────────────────
    canvas = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # Rounded-square mask
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, S-1, S-1], radius=r, fill=255)

    # Paste moon through mask
    canvas.paste(moon, (0, 0), mask)
    draw = ImageDraw.Draw(canvas)

    # Subtle dark vignette around the edges (makes it feel cinematic)
    vig = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    vd  = ImageDraw.Draw(vig)
    for i in range(S//10, 0, -1):
        alpha = int(120 * (1 - i/(S//10))**2.5)
        vd.rounded_rectangle([i, i, S-1-i, S-1-i], radius=max(4, r-i//2),
                             outline=(0, 0, 0, alpha), width=2)
    canvas = Image.alpha_composite(canvas, vig)
    draw = ImageDraw.Draw(canvas)

    # Thin gold border
    draw.rounded_rectangle([2, 2, S-3, S-3], radius=r,
                           outline=(*GOLD_D, 90), width=max(3, S//120))

    # ── Scales of Justice overlay ─────────────────────────────────────────────
    top_y  = int(S * 0.185)
    base_y = int(S * 0.800)
    beam_y = int(S * 0.295)
    barm   = int(S * 0.295)
    tilt   = int(S * 0.014)
    pw     = max(3, S // 52)

    lx = cx - barm;  ly = beam_y + tilt
    rx = cx + barm;  ry = beam_y - tilt

    def shadow_offset(dx=3, dy=3):
        return dx, dy

    # Drop shadow helper
    def ds(x, y, size=3): return x+size, y+size

    # Pillar
    draw.rectangle([cx-pw+3, top_y+3, cx+pw+3, base_y+3], fill=(*GOLD_D, 180))
    draw.rectangle([cx-pw, top_y, cx+pw, base_y], fill=GOLD)

    # Base trapezoid
    bw    = int(S * 0.20)
    bh    = max(5, S // 20)
    slant = bh // 3
    pts_s = [(cx-bw+3,base_y+3),(cx+bw+3,base_y+3),(cx+bw-slant+3,base_y+bh+3),(cx-bw+slant+3,base_y+bh+3)]
    pts   = [(cx-bw,base_y),(cx+bw,base_y),(cx+bw-slant,base_y+bh),(cx-bw+slant,base_y+bh)]
    draw.polygon(pts_s, fill=(*GOLD_D, 180))
    draw.polygon(pts,   fill=GOLD)
    draw.line([(cx-bw, base_y),(cx+bw, base_y)], fill=GOLD_L, width=max(2, S//90))

    # Beam
    bth = max(3, S//48)
    beam_shadow = [(lx+3,ly-bth+3),(rx+3,ry-bth+3),(rx+3,ry+bth+3),(lx+3,ly+bth+3)]
    beam_pts    = [(lx,ly-bth),(rx,ry-bth),(rx,ry+bth),(lx,ly+bth)]
    draw.polygon(beam_shadow, fill=(*GOLD_D, 180))
    draw.polygon(beam_pts,    fill=GOLD)
    draw.line([(lx,ly-bth),(rx,ry-bth)], fill=GOLD_L, width=max(2, S//100))

    # Pivot knob
    kn = max(6, S // 28)
    draw.ellipse([cx-kn+3, beam_y-kn+3, cx+kn+3, beam_y+kn+3], fill=(*GOLD_D,180))
    draw.ellipse([cx-kn, beam_y-kn, cx+kn, beam_y+kn], fill=GOLD)
    if kn > 8:
        draw.ellipse([cx-kn+4, beam_y-kn+4, cx+kn-4, beam_y+kn-4], fill=GOLD_L)

    # Chains
    def draw_chain(x1,y1,x2,y2):
        length = math.hypot(x2-x1,y2-y1)
        segs   = max(4, int(length/(S//28)))
        lr     = max(2, S//90)
        for i in range(segs+1):
            t  = i/max(1,segs)
            px = x1+(x2-x1)*t; py=y1+(y2-y1)*t
            draw.ellipse([px-lr,py-lr,px+lr,py+lr], fill=GOLD)

    drop  = int(S * 0.225)
    lpc   = ly + drop
    rpc   = ry + drop - int(S * 0.028)
    draw_chain(lx, ly, lx, lpc)
    draw_chain(rx, ry, rx, rpc)

    # Pans
    prx = int(S * 0.095)
    pry = max(4, S // 42)

    def draw_pan(pcx, pcy):
        draw.ellipse([pcx-prx, pcy, pcx+prx, pcy+pry*2], fill=(10,15,30,200))
        draw.ellipse([pcx-prx, pcy-pry, pcx+prx, pcy+pry], fill=GOLD)
        inner = max(2, prx-S//55)
        draw.ellipse([pcx-inner, pcy-pry+3, pcx+inner, pcy-pry+6], fill=GOLD_L)

    draw_pan(lx, lpc - pry)
    draw_pan(rx, rpc - pry)

    # ── Downscale with LANCZOS ─────────────────────────────────────────────────
    return canvas.resize((size, size), Image.LANCZOS)


# ── Build iconset + apply ─────────────────────────────────────────────────────

SIZES = [
    (16,"icon_16x16"),(32,"icon_16x16@2x"),(32,"icon_32x32"),
    (64,"icon_32x32@2x"),(128,"icon_128x128"),(256,"icon_128x128@2x"),
    (256,"icon_256x256"),(512,"icon_256x256@2x"),(512,"icon_512x512"),
    (1024,"icon_512x512@2x"),
]


def main():
    print("\n🌕  LegalPerigee — Real Moon Icon\n")

    if not MOON_PHOTO.exists():
        print("❌  Moon photo not found. Run this first:")
        print("    python3 -c \"import httpx,pathlib; pathlib.Path('data/moon_photo.jpg').write_bytes(httpx.get('https://upload.wikimedia.org/wikipedia/commons/e/e1/FullMoon2010.jpg',headers={'User-Agent':'LegalPerigee/2.0'},follow_redirects=True).content)\"")
        return

    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "AppIcon.iconset"
        iconset.mkdir()

        cache: dict[int, Image.Image] = {}
        for size, name in SIZES:
            if size not in cache:
                print(f"  Rendering {size}×{size}…")
                cache[size] = draw_icon(size)
            cache[size].save(iconset / f"{name}.png")

        # Build .icns
        icns_path = PROJECT_DIR / "AppIcon.icns"
        result = subprocess.run(
            ["iconutil", "-c", "icns", str(iconset), "-o", str(icns_path)],
            capture_output=True,
        )
        if result.returncode != 0:
            print(f"  ⚠️  iconutil: {result.stderr.decode()}")
        else:
            print("  ✅  AppIcon.icns created")

        # Save preview + v2 logo
        preview = PROJECT_DIR / "data" / "logo.png"
        cache[512].save(preview)
        print(f"  ✅  logo.png saved")

        v2_logo = PROJECT_DIR.parent / "LegalPerigee-v2" / "public" / "logo.png"
        if v2_logo.parent.exists():
            cache[512].save(v2_logo)
            print(f"  ✅  v2 logo.png updated")

        # Patch Desktop .app
        app_path = DESKTOP / f"{APP_NAME}.app"
        if app_path.exists():
            shutil.copy(icns_path, app_path / "Contents" / "Resources" / "AppIcon.icns")
            subprocess.run(["touch", str(app_path)], check=False)
            subprocess.run(["killall", "Dock"], capture_output=True)
            print("  ✅  Desktop app icon updated")

    print("\n🌕  Done — relaunch LegalPerigee to see the new icon.\n")


if __name__ == "__main__":
    main()
