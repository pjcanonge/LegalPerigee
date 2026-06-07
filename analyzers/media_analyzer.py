"""
LegalPerigee Media Forensics Analyzer

Uses Claude Vision to detect signs of AI manipulation in:
  - Images (deepfakes, face swaps, generative AI, photo editing)
  - Video  (frame-by-frame deepfake detection via ffmpeg)
  - Text   (AI-generated content detection)

NOTE: This provides investigative leads, not courtroom-grade forensics.
Results should be verified with certified digital forensics tools for legal proceedings.
"""

import base64
import io
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

import anthropic
from PIL import Image, ExifTags

# Register HEIC/HEIF support (Apple photos from iPhone/Mac)
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
    _HEIC_SUPPORTED = True
except ImportError:
    _HEIC_SUPPORTED = False

from utils.json_extract import extract_json
from utils.retry import call_with_retry

# ── Prompts ───────────────────────────────────────────────────────────────────

IMAGE_ANALYSIS_PROMPT = """You are a digital forensics expert specializing in detecting
AI-manipulated and fraudulently altered media. Analyze this image carefully for ALL of
the following manipulation indicators:

DEEPFAKE / FACE SWAP INDICATORS:
- Facial boundary artifacts: unnatural blur, halo, or color fringing around face edges
- Skin texture: over-smoothed, plastic-looking, or inconsistently lit skin
- Eye anomalies: unnatural reflections, asymmetry, or blank/dead appearance
- Hair boundary: hair unnaturally merging with or detached from background
- Teeth/mouth: distorted geometry, unnatural whiteness, or blurring
- Ear/hairline: blurred, distorted, or asymmetric boundaries
- Neck/chin: inconsistent shadow or color transition at jawline

AI GENERATION INDICATORS (GAN/Diffusion):
- Background distortions: wavy, melted, or incoherent elements near face
- Text in image: garbled, malformed, or nonsensical letters
- Fingers/hands: extra fingers, merged digits, or unnatural proportions
- Symmetry: unnaturally perfect or imperfect facial symmetry
- Periodic artifacts: grid-like or repeating patterns (GAN fingerprint)
- Lighting: multiple contradictory light sources or impossible shadows

PHOTO EDITING INDICATORS:
- Clone stamp: repeated texture patterns suggesting copy-paste
- Splice lines: sharp color/texture boundaries where elements were inserted
- Compression artifacts: inconsistent JPEG blocking in different regions
- Color grading: unnatural saturation or hue shifts in specific areas
- Shadow direction: objects casting shadows in different directions
- Perspective: objects at impossible angles relative to camera

Respond ONLY with this JSON (no markdown, no prose before or after):
{
  "verdict": "LIKELY_MANIPULATED | POSSIBLY_MANIPULATED | LIKELY_AUTHENTIC | INCONCLUSIVE",
  "confidence": 0-100,
  "manipulation_type": "deepfake | face_swap | generative_ai | photo_edit | composite | unknown | none",
  "risk_level": "HIGH | MEDIUM | LOW | NONE",
  "artifacts_found": ["list of specific artifacts detected"],
  "authentic_indicators": ["list of features suggesting authenticity"],
  "forensic_notes": "detailed analysis for investigators",
  "legal_recommendation": "what further forensic steps to take",
  "summary": "one sentence plain English verdict"
}"""

VIDEO_FRAME_PROMPT = """You are analyzing a video frame extracted from a suspect video for deepfake
and AI manipulation artifacts. This is frame {frame_num} of {total_frames} (timestamp: {timestamp}).

Look specifically for:
1. Facial boundary artifacts typical of deepfake face-swap technology
2. Temporal inconsistencies (note: compare to other frames — does this face look pasted?)
3. Lip-sync artifacts: mouth movements that don't match expected speech patterns
4. Blinking patterns: unnatural, absent, or robotic blinking
5. All image manipulation indicators (same as static image analysis)

Respond ONLY with this JSON:
{
  "frame": {frame_num},
  "timestamp": "{timestamp}",
  "verdict": "LIKELY_MANIPULATED | POSSIBLY_MANIPULATED | LIKELY_AUTHENTIC | INCONCLUSIVE",
  "confidence": 0-100,
  "artifacts_found": ["specific artifacts in this frame"],
  "forensic_notes": "brief note for this frame"
}"""

TEXT_ANALYSIS_PROMPT = """You are a forensic linguist specializing in detecting AI-generated text
used in fraud, scams, and deceptive communications.

Analyze the following text for signs of AI generation and deceptive intent:

AI GENERATION MARKERS:
- Unnaturally consistent sentence length (LLMs avoid variation)
- Hedge phrases: "It's worth noting", "It's important to understand", "Certainly"
- Formulaic structure: intro → body → conclusion without natural tangents
- Lack of personal specificity: no names, dates, places, typos, or idiosyncratic style
- Perfect grammar with no contractions or natural speech patterns
- Overuse of transition words and formal connectors
- Absence of genuine emotional texture or lived experience
- Generic examples that could apply to anyone
- "AI tell" phrases: "As an AI...", "I cannot", "delve", "tapestry", "testament"

SCAM/FRAUD INDICATORS:
- Urgency manufactured without logical basis
- Vague promises of financial gain
- Requests for personal information embedded in seemingly helpful text
- Impersonation patterns (mimicking official language)
- Emotional manipulation tactics
- Pressure language: "limited time", "act now", "exclusive"

Text to analyze:
---
{text}
---

Respond ONLY with this JSON:
{
  "verdict": "LIKELY_AI_GENERATED | POSSIBLY_AI_GENERATED | LIKELY_HUMAN | INCONCLUSIVE",
  "ai_probability": 0-100,
  "scam_probability": 0-100,
  "risk_level": "HIGH | MEDIUM | LOW | NONE",
  "ai_markers_found": ["specific AI generation patterns detected"],
  "scam_markers_found": ["specific fraud/scam patterns detected"],
  "authentic_indicators": ["features suggesting human authorship"],
  "forensic_notes": "detailed analysis",
  "legal_recommendation": "recommended next steps for investigation",
  "summary": "one sentence plain English verdict"
}"""


# ── Image metadata extraction ─────────────────────────────────────────────────

def extract_image_metadata(image_bytes: bytes) -> dict:
    """Extract EXIF metadata and basic image properties."""
    meta = {}
    try:
        img = Image.open(io.BytesIO(image_bytes))
        meta["format"] = img.format
        meta["mode"] = img.mode
        meta["size"] = f"{img.width}×{img.height}"

        exif_data = img._getexif() if hasattr(img, "_getexif") else None
        if exif_data:
            exif = {}
            for tag_id, value in exif_data.items():
                tag = ExifTags.TAGS.get(tag_id, str(tag_id))
                if isinstance(value, bytes):
                    try:
                        value = value.decode("utf-8", errors="replace")
                    except Exception:
                        value = str(value)
                exif[tag] = str(value)[:200]
            meta["exif"] = exif
            meta["has_exif"] = True
            meta["software"] = exif.get("Software", "Not found")
            meta["camera"] = exif.get("Make", "") + " " + exif.get("Model", "")
            meta["date_taken"] = exif.get("DateTime", "Not found")
        else:
            meta["has_exif"] = False
            meta["exif_note"] = "No EXIF data — may have been stripped (suspicious for authentic photos)"
    except Exception as e:
        meta["error"] = str(e)
    return meta


# ── Image analysis ────────────────────────────────────────────────────────────

def analyze_image(
    image_bytes: bytes,
    filename: str,
    client: Optional[anthropic.Anthropic] = None,
) -> dict:
    """Analyze an image for AI manipulation artifacts using Claude Vision."""
    if client is None:
        api_key = __import__("os").environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key or not api_key.startswith("sk-"):
            return {"error": "Anthropic API key not configured.", "verdict": "INCONCLUSIVE",
                    "risk_level": "NONE", "confidence": 0, "manipulation_type": "N/A",
                    "indicators": [], "summary": "API key required for analysis."}
        client = anthropic.Anthropic(api_key=api_key)

    ext = Path(filename).suffix.lower()
    mime_map = {
        ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".png": "image/png", ".gif": "image/gif", ".webp": "image/webp",
        ".heic": "image/jpeg", ".heif": "image/jpeg",  # converted below
        ".bmp": "image/png", ".tiff": "image/jpeg", ".tif": "image/jpeg",
    }
    media_type = mime_map.get(ext, "image/jpeg")

    # Convert and/or resize — HEIC/HEIF and large images all get normalized to JPEG
    try:
        img = Image.open(io.BytesIO(image_bytes))
        # Convert to RGB so JPEG save works (handles HEIC, RGBA PNG, etc.)
        if img.mode not in ("RGB", "L"):
            img = img.convert("RGB")
        needs_save = (
            ext in (".heic", ".heif", ".bmp", ".tiff", ".tif")
            or img.width > 2000 or img.height > 2000
        )
        if needs_save:
            img.thumbnail((2000, 2000), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=88)
            image_bytes = buf.getvalue()
            media_type = "image/jpeg"
    except Exception:
        pass

    b64 = base64.standard_b64encode(image_bytes).decode()
    metadata = extract_image_metadata(image_bytes)

    response = call_with_retry(
        lambda: client.messages.create(
            model="claude-opus-4-8",
            max_tokens=2048,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
                    {"type": "text", "text": IMAGE_ANALYSIS_PROMPT},
                ],
            }],
        ),
        label="image_analysis",
    )

    result = {}
    for block in response.content:
        if block.type == "text":
            result = extract_json(block.text) or {"raw": block.text}
            break

    result["metadata"] = metadata
    result["filename"] = filename
    result["file_size"] = f"{len(image_bytes) / 1024:.1f} KB"
    return result


# ── Video analysis ────────────────────────────────────────────────────────────

FFMPEG = shutil.which("ffmpeg") or "/opt/homebrew/bin/ffmpeg"


def extract_video_frames(
    video_bytes: bytes,
    filename: str,
    num_frames: int = 8,
) -> list[tuple[str, str, bytes]]:
    """
    Extract evenly-spaced frames from a video using ffmpeg.
    Returns list of (frame_label, timestamp, jpeg_bytes).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        video_path = Path(tmpdir) / filename
        video_path.write_bytes(video_bytes)

        # Get duration
        probe = subprocess.run(
            [FFMPEG, "-i", str(video_path)],
            capture_output=True, text=True,
        )
        duration = 0.0
        for line in probe.stderr.splitlines():
            if "Duration:" in line:
                parts = line.split("Duration:")[1].split(",")[0].strip().split(":")
                try:
                    duration = float(parts[0]) * 3600 + float(parts[1]) * 60 + float(parts[2])
                except Exception:
                    pass

        if duration == 0:
            duration = 30.0  # fallback

        frames = []
        interval = duration / (num_frames + 1)

        for i in range(num_frames):
            ts = interval * (i + 1)
            out_path = Path(tmpdir) / f"frame_{i:03d}.jpg"
            result = subprocess.run(
                [
                    FFMPEG, "-ss", str(ts), "-i", str(video_path),
                    "-vframes", "1", "-q:v", "3",
                    "-vf", "scale=800:-1",
                    str(out_path), "-y",
                ],
                capture_output=True,
            )
            if out_path.exists():
                ts_label = f"{int(ts//60):02d}:{int(ts%60):02d}"
                frames.append((f"Frame {i+1}", ts_label, out_path.read_bytes()))

        return frames


def analyze_video(
    video_bytes: bytes,
    filename: str,
    num_frames: int = 6,
    client: Optional[anthropic.Anthropic] = None,
) -> dict:
    """Analyze a video for deepfake manipulation by examining key frames."""
    if client is None:
        api_key = __import__("os").environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key or not api_key.startswith("sk-"):
            return {"error": "Anthropic API key not configured.", "verdict": "INCONCLUSIVE",
                    "risk_level": "NONE", "confidence": 0}
        client = anthropic.Anthropic(api_key=api_key)

    if not FFMPEG or not Path(FFMPEG).exists():
        return {"error": "ffmpeg not found. Install with: brew install ffmpeg"}

    try:
        frames = extract_video_frames(video_bytes, filename, num_frames)
    except Exception as e:
        return {"error": f"Frame extraction failed: {e}"}

    if not frames:
        return {"error": "Could not extract frames from video"}

    frame_results = []
    manipulated_count = 0

    for i, (label, timestamp, frame_bytes) in enumerate(frames):
        b64 = base64.standard_b64encode(frame_bytes).decode()
        prompt = VIDEO_FRAME_PROMPT.format(
            frame_num=i + 1, total_frames=len(frames), timestamp=timestamp
        )

        try:
            response = call_with_retry(
                lambda: client.messages.create(
                    model="claude-opus-4-8",
                    max_tokens=1024,
                    messages=[{
                        "role": "user",
                        "content": [
                            {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}},
                            {"type": "text", "text": prompt},
                        ],
                    }],
                ),
                label=f"video_frame_{i+1}",
            )
            for block in response.content:
                if block.type == "text":
                    fr = extract_json(block.text) or {}
                    frame_results.append(fr)
                    if fr.get("verdict", "").startswith("LIKELY_MANIPULATED"):
                        manipulated_count += 1
                    break
        except Exception as e:
            frame_results.append({"frame": i + 1, "error": str(e)})

    # Overall verdict
    manip_ratio = manipulated_count / len(frame_results) if frame_results else 0
    if manip_ratio >= 0.5:
        overall = "LIKELY_MANIPULATED"
        risk = "HIGH"
    elif manip_ratio >= 0.25:
        overall = "POSSIBLY_MANIPULATED"
        risk = "MEDIUM"
    else:
        overall = "LIKELY_AUTHENTIC"
        risk = "LOW"

    all_artifacts = []
    for fr in frame_results:
        all_artifacts.extend(fr.get("artifacts_found", []))

    return {
        "filename": filename,
        "frames_analyzed": len(frame_results),
        "manipulated_frames": manipulated_count,
        "overall_verdict": overall,
        "risk_level": risk,
        "confidence": int(manip_ratio * 100),
        "all_artifacts": list(set(all_artifacts)),
        "frame_results": frame_results,
        "summary": (
            f"{manipulated_count}/{len(frame_results)} frames show manipulation indicators. "
            f"Overall: {overall}."
        ),
    }


# ── Text analysis ─────────────────────────────────────────────────────────────

def analyze_text(
    text: str,
    client: Optional[anthropic.Anthropic] = None,
) -> dict:
    """Analyze text for AI generation and scam/fraud indicators."""
    if client is None:
        api_key = __import__("os").environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key or not api_key.startswith("sk-"):
            return {"error": "Anthropic API key not configured.", "verdict": "INCONCLUSIVE",
                    "risk_level": "NONE", "confidence": 0}
        client = anthropic.Anthropic(api_key=api_key)

    if len(text.strip()) < 50:
        return {"error": "Text too short for reliable analysis (minimum 50 characters)"}

    # Truncate very long texts
    analysis_text = text[:8000] if len(text) > 8000 else text
    prompt = TEXT_ANALYSIS_PROMPT.format(text=analysis_text)

    response = call_with_retry(
        lambda: client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            messages=[{"role": "user", "content": prompt}],
        ),
        label="text_analysis",
    )

    result = {}
    for block in response.content:
        if block.type == "text":
            result = extract_json(block.text) or {"raw": block.text}
            break

    result["char_count"] = len(text)
    result["word_count"] = len(text.split())
    result["truncated"] = len(text) > 8000
    return result
