"""
LegalPerigee Auto-Repair System  (v1.2 — security-hardened)

Catches exceptions anywhere in the app, sends them to Claude with
the relevant source code context, receives a diagnosis + fix, and
PROPOSES the patch for attorney review — auto-apply requires explicit
human approval via the UI (H-2 fix).

Usage:
    from utils.auto_repair import capture_error, get_pending_errors, apply_fix

    try:
        risky_operation()
    except Exception as e:
        capture_error(e, context="what was being attempted")

Security changes in v1.2:
  - C-1: Path traversal guard — patches may not escape PROJECT_ROOT
  - H-1: Transmission log + credential scrubbing before API sends
  - H-2: apply_fix() is diagnosis-only by default; REQUIRE_HUMAN_APPROVAL=True
"""

import ast
import hashlib
import os
import re
import sys
import textwrap
import traceback
from datetime import datetime
from pathlib import Path
from typing import Optional

# ── In-memory error store (persists for the session) ─────────────────────────
_error_store: list[dict] = []
_MAX_ERRORS = 50
PROJECT_ROOT = Path(__file__).parent.parent

# ── Security constants ────────────────────────────────────────────────────────
# H-2: Set to False to allow auto-apply without human review (NOT recommended)
REQUIRE_HUMAN_APPROVAL = True

# H-1: Patterns to scrub from payloads before sending to Anthropic API
_CREDENTIAL_PATTERNS = [
    re.compile(r'sk-ant-[A-Za-z0-9_\-]{20,}'),          # Anthropic keys
    re.compile(r'Token\s+[A-Za-z0-9]{20,}'),             # CourtListener tokens
    re.compile(r'Bearer\s+[A-Za-z0-9._\-]{20,}'),        # Bearer auth
    re.compile(r'[A-Z_]+(KEY|TOKEN|SECRET|PASSWORD)\s*=\s*\S{8,}'),  # env assignments
]

# Audit log for all API transmissions (H-1)
_TRANSMISSION_LOG_PATH = Path.home() / "Library" / "Logs" / "LegalPerigee_transmissions.log"


def _scrub_credentials(text: str) -> str:
    """Replace any credential patterns with a redacted placeholder."""
    for pattern in _CREDENTIAL_PATTERNS:
        text = pattern.sub("[REDACTED-CREDENTIAL]", text)
    return text


def _log_transmission(action: str, payload_size: int, destination: str) -> None:
    """Append one line to the local transmission audit log (H-1)."""
    try:
        _TRANSMISSION_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        entry = (
            f"{datetime.utcnow().isoformat()}Z  action={action}  "
            f"bytes={payload_size}  dest={destination}\n"
        )
        with open(_TRANSMISSION_LOG_PATH, "a") as f:
            f.write(entry)
    except Exception:
        pass  # never let audit logging crash the app


def _error_id(tb: str) -> str:
    return hashlib.md5(tb.encode()).hexdigest()[:10]


def _read_source_context(filename: str, lineno: int, radius: int = 20) -> str:
    """Read ±radius lines around the error line from a source file."""
    try:
        p = Path(filename)
        if not p.exists() or not p.is_file():
            return ""
        lines = p.read_text().splitlines()
        start = max(0, lineno - radius - 1)
        end   = min(len(lines), lineno + radius)
        numbered = []
        for i, line in enumerate(lines[start:end], start + 1):
            marker = ">>> " if i == lineno else "    "
            numbered.append(f"{marker}{i:4d} | {line}")
        return "\n".join(numbered)
    except Exception:
        return ""


def capture_error(
    exc: Exception,
    context: str = "",
    extra_files: Optional[list[str]] = None,
) -> str:
    """
    Capture an exception and queue it for analysis.

    Args:
        exc: The exception that was caught
        context: Human-readable description of what was being attempted
        extra_files: Additional source files to include for context

    Returns:
        error_id string
    """
    tb_str  = traceback.format_exc()
    err_id  = _error_id(tb_str)

    # Avoid duplicate captures of the same error
    if any(e["id"] == err_id for e in _error_store):
        return err_id

    # Extract file/line from traceback
    frames = traceback.extract_tb(exc.__traceback__) if exc.__traceback__ else []
    primary_file = frames[-1].filename if frames else ""
    primary_line = frames[-1].lineno   if frames else 0

    # Only include project files — skip venv
    project_frames = [
        f for f in frames
        if ".venv" not in f.filename and str(PROJECT_ROOT) in f.filename
    ]

    # Collect source context for all project frames
    source_snippets: dict[str, str] = {}
    for frame in project_frames[-3:]:  # last 3 project frames
        rel = os.path.relpath(frame.filename, PROJECT_ROOT)
        snippet = _read_source_context(frame.filename, frame.lineno)
        if snippet:
            source_snippets[rel] = snippet

    # Extra files the caller wants included
    for ef in (extra_files or []):
        ep = PROJECT_ROOT / ef
        if ep.exists():
            source_snippets[ef] = ep.read_text()[:3000]

    record = {
        "id":             err_id,
        "timestamp":      datetime.utcnow().isoformat() + "Z",
        "exception_type": type(exc).__name__,
        "exception_msg":  str(exc),
        "traceback":      tb_str,
        "context":        context,
        "primary_file":   os.path.relpath(primary_file, PROJECT_ROOT) if primary_file else "",
        "primary_line":   primary_line,
        "source_snippets":source_snippets,
        "diagnosis":      None,   # filled in by analyze()
        "fix":            None,   # filled in by analyze()
        "fixed":          False,
        "status":         "pending",
    }
    _error_store.append(record)
    if len(_error_store) > _MAX_ERRORS:
        _error_store.pop(0)

    return err_id


def get_pending_errors() -> list[dict]:
    return [e for e in _error_store if not e["fixed"]]


def get_all_errors() -> list[dict]:
    return list(_error_store)


def mark_fixed(error_id: str) -> None:
    for e in _error_store:
        if e["id"] == error_id:
            e["fixed"]  = True
            e["status"] = "fixed"


# ── Claude diagnosis ──────────────────────────────────────────────────────────

REPAIR_PROMPT = """You are an expert Python/Streamlit developer maintaining LegalPerigee,
a legal case intelligence platform. An exception has occurred and you must diagnose
and fix it precisely.

## Error Details
Context: {context}
Exception: {exc_type}: {exc_msg}

## Full Traceback
```
{traceback}
```

## Relevant Source Code
{source_context}

## Instructions
1. Diagnose the root cause in 1-2 sentences
2. Provide the exact fix as a SEARCH/REPLACE patch — use the exact existing text
3. The fix must be minimal — change only what is broken
4. If the fix requires multiple files, provide multiple patches

Return ONLY this JSON (no prose, no fences):
{{
  "diagnosis": "Root cause in 1-2 sentences",
  "severity": "critical | high | medium | low",
  "fix_summary": "What the fix does",
  "patches": [
    {{
      "file": "relative/path/from/project/root.py",
      "search": "exact text to find (must be unique in the file)",
      "replace": "replacement text"
    }}
  ],
  "restart_required": true,
  "notes": "Any caveats or follow-up actions"
}}"""


def analyze_error(error_id: str, api_key: Optional[str] = None) -> dict:
    """
    Send an error to Claude for diagnosis and fix.
    Updates the error record in-place and returns the result.
    """
    record = next((e for e in _error_store if e["id"] == error_id), None)
    if not record:
        return {"error": "Error ID not found"}

    key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        return {"error": "No API key available"}

    import anthropic
    from utils.json_extract import extract_json
    from utils.retry import call_with_retry

    client = anthropic.Anthropic(api_key=key)

    # Build source context section
    source_parts = []
    for fname, snippet in record["source_snippets"].items():
        source_parts.append(f"### {fname}\n```python\n{snippet}\n```")
    source_context = "\n\n".join(source_parts) or "(no source available)"

    # H-1: Scrub credentials from every field before transmission
    safe_context   = _scrub_credentials(record["context"] or "No context provided")
    safe_exc_msg   = _scrub_credentials(record["exception_msg"][:500])
    safe_traceback = _scrub_credentials(record["traceback"][-3000:])
    safe_src       = _scrub_credentials(source_context[:6000])

    prompt = REPAIR_PROMPT.format(
        context        = safe_context,
        exc_type       = record["exception_type"],
        exc_msg        = safe_exc_msg,
        traceback      = safe_traceback,
        source_context = safe_src,
    )

    # H-1: Log this transmission to the local audit file
    _log_transmission("analyze_error", len(prompt), "api.anthropic.com")

    try:
        response = call_with_retry(
            lambda: client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            ),
            label="auto_repair",
        )
        result = {}
        for block in response.content:
            if block.type == "text":
                result = extract_json(block.text) or {}
                break

        record["diagnosis"] = result.get("diagnosis","")
        record["fix"]       = result
        record["status"]    = "diagnosed"
        return result

    except Exception as e:
        record["status"] = f"analysis_failed: {e}"
        return {"error": str(e)}


# ── Apply fix ─────────────────────────────────────────────────────────────────

def preview_fix(error_id: str) -> dict:
    """
    Return a human-readable diff of proposed patches WITHOUT writing anything.
    Use this to show the attorney what would change before asking for approval.
    """
    record = next((e for e in _error_store if e["id"] == error_id), None)
    if not record or not record.get("fix"):
        return {"success": False, "error": "No fix available — run analyze first"}

    patches = record["fix"].get("patches", [])
    previews = []
    for patch in patches:
        rel_path = patch.get("file", "")
        search   = patch.get("search", "")
        replace  = patch.get("replace", "")
        previews.append({
            "file":    rel_path,
            "removes": search,
            "adds":    replace,
        })
    return {"success": True, "patches": previews, "count": len(previews)}


def apply_fix(error_id: str, human_approved: bool = False) -> dict:
    """
    Apply the patches from a diagnosed error.

    Args:
        error_id:       ID of the error record
        human_approved: MUST be True — caller confirms the attorney has reviewed
                        the diff shown by preview_fix() and approved the change.

    Returns {"success": True/False, "files_changed": [...], "error": ...}

    Security (v1.2):
      - C-1: Every patch path is resolved and checked to stay inside PROJECT_ROOT.
      - H-2: REQUIRE_HUMAN_APPROVAL enforces that human_approved=True is passed;
             patches are never written silently.
    """
    # H-2: Require explicit human approval
    if REQUIRE_HUMAN_APPROVAL and not human_approved:
        return {
            "success": False,
            "error": (
                "Human approval required. Call preview_fix() first, show the diff "
                "to the attorney, then call apply_fix(error_id, human_approved=True)."
            ),
        }

    record = next((e for e in _error_store if e["id"] == error_id), None)
    if not record or not record.get("fix"):
        return {"success": False, "error": "No fix available — run analyze first"}

    fix     = record["fix"]
    patches = fix.get("patches", [])
    if not patches:
        return {"success": False, "error": "Fix contains no patches"}

    changed = []
    errors  = []
    project_root_resolved = PROJECT_ROOT.resolve()

    for patch in patches:
        rel_path = patch.get("file", "")
        search   = patch.get("search", "")
        replace  = patch.get("replace", "")

        if not rel_path or not search:
            errors.append("Invalid patch — missing file or search text")
            continue

        # ── C-1: Path traversal guard ─────────────────────────────────────────
        # Reject any path that contains '..' before resolving (fast check)
        if ".." in rel_path:
            errors.append(f"Patch rejected — path contains '..': {rel_path}")
            continue

        full_path = (PROJECT_ROOT / rel_path).resolve()

        # Ensure the resolved path is still inside the project root
        if not str(full_path).startswith(str(project_root_resolved) + os.sep):
            errors.append(
                f"Patch rejected — path escapes project root: {rel_path} → {full_path}"
            )
            continue

        if not full_path.exists():
            errors.append(f"File not found: {rel_path}")
            continue

        original = full_path.read_text()
        if search not in original:
            errors.append(f"Search text not found in {rel_path}:\n{search[:100]}…")
            continue

        # Validate the patched file parses before writing
        patched = original.replace(search, replace, 1)
        if rel_path.endswith(".py"):
            try:
                ast.parse(patched)
            except SyntaxError as se:
                errors.append(f"Patch would introduce syntax error in {rel_path}: {se}")
                continue

        # Write backup then apply
        backup = full_path.with_suffix(full_path.suffix + ".repair_backup")
        backup.write_text(original)
        full_path.write_text(patched)
        changed.append(rel_path)
        _log_transmission("apply_patch", len(patched), rel_path)

    if errors:
        return {"success": False, "files_changed": changed, "errors": errors}

    mark_fixed(error_id)
    return {
        "success":          True,
        "files_changed":    changed,
        "restart_required": fix.get("restart_required", True),
    }


def restart_server() -> None:
    """Restart the Streamlit server by killing the current process."""
    import signal
    os.kill(os.getpid(), signal.SIGTERM)
