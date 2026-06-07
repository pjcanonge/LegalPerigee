"""
LegalPerigee Document Viewer — format-specific rendering helpers.

Handles: PDF, DOCX, XLSX/XLS, CSV, PPTX, images, TXT, MD, JSON,
         HTML, XML, HEIC, video, and common code files.

Each document gets an action bar with three buttons:
  ⧉ Open   — writes to a temp file and opens in the OS native app
              (macOS Preview / Word / Numbers / QuickLook).  That app
              has its own full-fidelity Print dialog.
  🖨 Print  — generates a clean HTML print page, opens it in the
              default browser, and auto-fires the browser Print dialog.
  ⬇ Download — saves to the user's chosen location.
"""

from __future__ import annotations

import atexit
import base64
import io
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

import streamlit as st
import streamlit.components.v1 as components

# M-7: Register a one-time atexit handler to clean up our temp directory
_TMP_DOC_DIR = Path(tempfile.gettempdir()) / "LegalPerigee_docs"

def _cleanup_tmp_docs() -> None:
    """Remove the session temp directory when the process exits."""
    try:
        if _TMP_DOC_DIR.exists():
            shutil.rmtree(_TMP_DOC_DIR, ignore_errors=True)
    except Exception:
        pass

atexit.register(_cleanup_tmp_docs)

# ── Format metadata ───────────────────────────────────────────────────────────

MIME_MAP: dict[str, str] = {
    ".pdf":      "application/pdf",
    ".docx":     "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".doc":      "application/msword",
    ".xlsx":     "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xls":      "application/vnd.ms-excel",
    ".csv":      "text/csv",
    ".pptx":     "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    ".ppt":      "application/vnd.ms-powerpoint",
    ".png":      "image/png",
    ".jpg":      "image/jpeg",
    ".jpeg":     "image/jpeg",
    ".gif":      "image/gif",
    ".webp":     "image/webp",
    ".bmp":      "image/bmp",
    ".svg":      "image/svg+xml",
    ".heic":     "image/heic",
    ".heif":     "image/heif",
    ".tiff":     "image/tiff",
    ".tif":      "image/tiff",
    ".mov":      "video/quicktime",
    ".qt":       "video/quicktime",
    ".mp4":      "video/mp4",
    ".m4v":      "video/mp4",
    ".avi":      "video/x-msvideo",
    ".mkv":      "video/x-matroska",
    ".webm":     "video/webm",
    ".txt":      "text/plain",
    ".md":       "text/markdown",
    ".markdown": "text/markdown",
    ".json":     "application/json",
    ".html":     "text/html",
    ".htm":      "text/html",
    ".xml":      "application/xml",
    ".py":       "text/x-python",
    ".js":       "text/javascript",
    ".ts":       "text/typescript",
    ".css":      "text/css",
    ".yaml":     "text/yaml",
    ".yml":      "text/yaml",
    ".toml":     "application/toml",
    ".rtf":      "application/rtf",
    ".odt":      "application/vnd.oasis.opendocument.text",
}

TYPE_ICONS: dict[str, str] = {
    ".pdf": "📄", ".docx": "📝", ".doc": "📝",
    ".xlsx": "📊", ".xls": "📊", ".csv": "📊",
    ".pptx": "📊", ".ppt": "📊",
    ".png": "🖼️", ".jpg": "🖼️", ".jpeg": "🖼️",
    ".gif": "🖼️", ".webp": "🖼️", ".bmp": "🖼️", ".svg": "🖼️",
    ".heic": "🖼️", ".heif": "🖼️", ".tiff": "🖼️", ".tif": "🖼️",
    ".mov": "🎬", ".qt": "🎬", ".mp4": "🎬", ".m4v": "🎬",
    ".avi": "🎬", ".mkv": "🎬", ".webm": "🎬",
    ".txt": "📃", ".md": "📃", ".markdown": "📃", ".rtf": "📃",
    ".json": "{ }", ".html": "🌐", ".htm": "🌐", ".xml": "📃",
    ".py": "🐍", ".js": "📜", ".ts": "📜", ".css": "🎨",
    ".yaml": "📃", ".yml": "📃", ".toml": "📃",
}

CODE_LANGS: dict[str, str] = {
    ".py": "python", ".js": "javascript", ".ts": "typescript",
    ".css": "css", ".html": "html", ".htm": "html",
    ".xml": "xml", ".json": "json",
    ".yaml": "yaml", ".yml": "yaml", ".toml": "toml",
    ".md": "markdown", ".markdown": "markdown",
    ".txt": "text",
}

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg",
              ".heic", ".heif", ".tiff", ".tif"}
VIDEO_EXTS = {".mp4", ".mov", ".qt", ".m4v", ".avi", ".mkv", ".webm", ".3gp"}


def ext(name: str) -> str:
    return Path(name).suffix.lower()

def mime_for(name: str) -> str:
    return MIME_MAP.get(ext(name), "application/octet-stream")

def icon_for(name: str) -> str:
    return TYPE_ICONS.get(ext(name), "📁")

def fmt_size(n: int) -> str:
    if n < 1024:         return f"{n} B"
    if n < 1024 ** 2:    return f"{n/1024:.1f} KB"
    if n < 1024 ** 3:    return f"{n/1024**2:.1f} MB"
    return f"{n/1024**3:.1f} GB"


# ── OS integration ────────────────────────────────────────────────────────────

def _open_in_system(name: str, data: bytes) -> None:
    """Write data to a temp file and open it in the OS default app.

    macOS:   open file  → Preview (PDF), Word/Pages (DOCX), etc.
    Windows: os.startfile → associated app.
    Temp file is placed in a LegalPerigee temp folder so it can be
    found later; OS cleans up temp dirs on reboot.
    """
    tmp_dir = Path(tempfile.gettempdir()) / "LegalPerigee_docs"
    tmp_dir.mkdir(exist_ok=True)
    # Use the original name so the app knows what format it is
    safe_name = Path(name).name
    tmp_path = tmp_dir / safe_name
    try:
        tmp_path.write_bytes(data)
    except Exception as e:
        st.error(f"Could not write temp file: {e}")
        return

    try:
        sys_name = platform.system()
        if sys_name == "Darwin":
            subprocess.Popen(["open", str(tmp_path)])
        elif sys_name == "Windows":
            os.startfile(str(tmp_path))           # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(tmp_path)])
        st.success(f"Opening **{safe_name}** in system viewer…", icon="⧉")
    except Exception as e:
        st.error(f"Could not open in system app: {e}")


def _open_print_view(name: str, html_body: str) -> None:
    """Write an HTML print page to a temp file and open it in the browser.
    The page auto-triggers the browser Print dialog on load.
    """
    print_html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Print — {name}</title>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: Georgia, "Times New Roman", serif;
    font-size: 12pt;
    line-height: 1.7;
    color: #111;
    background: #fff;
    padding: 1in;
    max-width: 8.5in;
    margin: 0 auto;
  }}
  h1 {{ font-size: 18pt; margin-bottom: .5em; }}
  h2 {{ font-size: 15pt; margin: 1em 0 .4em; }}
  h3 {{ font-size: 13pt; margin: .8em 0 .3em; }}
  p  {{ margin-bottom: .8em; }}
  table {{ border-collapse: collapse; width: 100%; margin-bottom: 1em; font-size: 10pt; }}
  th, td {{ border: 1px solid #bbb; padding: .25rem .5rem; text-align: left; }}
  th {{ background: #eef; font-weight: bold; }}
  pre, code {{ font-family: "Courier New", monospace; font-size: 10pt;
               background: #f5f5f5; padding: .1rem .3rem; }}
  pre {{ padding: .8rem; overflow-x: auto; white-space: pre-wrap; word-break: break-all; }}
  img {{ max-width: 100%; height: auto; display: block; margin: .5rem auto; }}
  .page-break {{ page-break-after: always; border-top: 1px dashed #ccc;
                 margin: 1.5rem 0; padding-top: 1rem; }}
  .doc-header {{ border-bottom: 2px solid #222; padding-bottom: .5rem; margin-bottom: 1.5rem; }}
  .doc-header h1 {{ font-size: 20pt; }}
  .doc-header .meta {{ font-size: 10pt; color: #555; margin-top: .3rem; }}
  /* No-print toolbar */
  .toolbar {{
    position: fixed; top: 0; left: 0; right: 0;
    background: #1a2744; color: #fff; padding: .5rem 1rem;
    display: flex; gap: .5rem; align-items: center; z-index: 9999;
    font-family: -apple-system, sans-serif; font-size: 13px;
  }}
  .toolbar span {{ flex: 1; font-weight: 600; }}
  .toolbar button {{
    padding: .35rem .9rem; border: none; border-radius: 4px; cursor: pointer;
    font-size: 13px; font-weight: 500;
  }}
  .btn-print {{ background: #3d6fd4; color: #fff; }}
  .btn-close {{ background: #444; color: #fff; }}
  .spacer {{ height: 40px; }}
  @media print {{
    .toolbar {{ display: none !important; }}
    .spacer  {{ display: none !important; }}
    body {{ padding: 0; }}
  }}
</style>
</head>
<body>
<div class="toolbar">
  <span>⚖️ LegalPerigee — {name}</span>
  <button class="btn-print" onclick="window.print()">🖨️ Print</button>
  <button class="btn-close" onclick="window.close()">✕ Close</button>
</div>
<div class="spacer"></div>

<div class="doc-header">
  <h1>{name}</h1>
  <div class="meta">LegalPerigee · Legal Case Intelligence Platform</div>
</div>

{html_body}

<script>
// Auto-open print dialog after a short delay (lets content paint first)
window.addEventListener('load', function() {{
  setTimeout(function() {{ window.print(); }}, 600);
}});
</script>
</body>
</html>"""

    # M-7: Use a restricted-permission temp directory; register cleanup on exit
    tmp_dir = Path(tempfile.gettempdir()) / "LegalPerigee_docs"
    tmp_dir.mkdir(mode=0o700, exist_ok=True)
    try:
        import stat as _stat
        tmp_dir.chmod(0o700)  # owner-only, in case it already existed
    except Exception:
        pass

    import time
    tmp_path = tmp_dir / f"print_{Path(name).stem}_{int(time.time())}.html"
    try:
        tmp_path.write_text(print_html, encoding="utf-8")
        tmp_path.chmod(0o600)  # owner read/write only
    except Exception as e:
        st.error(f"Could not write print file: {e}")
        return

    try:
        sys_name = platform.system()
        if sys_name == "Darwin":
            subprocess.Popen(["open", str(tmp_path)])
        elif sys_name == "Windows":
            os.startfile(str(tmp_path))           # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(tmp_path)])
        st.info("Print dialog opening in your browser…", icon="🖨️")
    except Exception as e:
        st.error(f"Could not open print view: {e}")


# ── Action bar (replaces download bar) ───────────────────────────────────────

def _action_bar(
    name: str,
    data: bytes,
    html_for_print: Optional[str] = None,
    open_label: str = "⧉ Open",
) -> None:
    """Top action bar: file info · Open · Print · Download."""
    # HTML and PDF get a wider open button (primary type) since it gives the
    # best full-fidelity view; other types use the normal secondary style.
    _suffix = ext(name)
    _open_is_primary = _suffix in (".html", ".htm", ".pdf")
    # Give the Open button more space for HTML/PDF where it matters most
    if _open_is_primary:
        info_col, open_col, print_col, dl_col = st.columns([3, 2, 1, 1])
    else:
        info_col, open_col, print_col, dl_col = st.columns([4, 1, 1, 1])

    with info_col:
        st.markdown(
            f'<div style="background:#f0f4ff;border:1px solid #c5d0e8;border-radius:6px;'
            f'padding:.4rem .8rem;font-size:.85rem;">'
            f'{icon_for(name)} &nbsp;<strong>{name}</strong>'
            f'&nbsp;·&nbsp;{fmt_size(len(data))}'
            f'&nbsp;·&nbsp;<code style="font-size:.8rem;">{_suffix}</code>'
            f'</div>',
            unsafe_allow_html=True,
        )

    with open_col:
        if st.button(
            open_label,
            key=f"open_{name}_{len(data)}",
            use_container_width=True,
            type="primary" if _open_is_primary else "secondary",
            help=(
                "Opens in Safari / default browser with full rendering and print support"
                if _suffix in (".html", ".htm")
                else "Opens in macOS Preview — full zoom, print, and annotation support"
                if _suffix == ".pdf"
                else "Open in system viewer (Preview, Word, etc.) — has full Print support"
            ),
        ):
            _open_in_system(name, data)

    with print_col:
        if html_for_print is not None:
            if st.button(
                "🖨️ Print",
                key=f"print_{name}_{len(data)}",
                use_container_width=True,
                help="Open print-ready view in browser and show print dialog",
            ):
                _open_print_view(name, html_for_print)
        else:
            # Fallback: just open in system (which has print)
            if st.button(
                "🖨️ Print",
                key=f"print_{name}_{len(data)}",
                use_container_width=True,
                help="Opens in system viewer — use File → Print from there",
            ):
                _open_in_system(name, data)

    with dl_col:
        st.download_button(
            "⬇️ Save",
            data=data,
            file_name=name,
            mime=mime_for(name),
            use_container_width=True,
            key=f"dl_{name}_{len(data)}",
        )


# ── PDF ───────────────────────────────────────────────────────────────────────

def render_pdf(name: str, data: bytes) -> None:
    # Build print HTML from extracted text
    print_html = _pdf_to_print_html(data)
    _action_bar(name, data, html_for_print=print_html, open_label="⧉ Open PDF")

    tab_text, tab_embedded = st.tabs(["📃 Extracted Text", "🖥️ Embedded Viewer"])

    with tab_text:
        _render_pdf_text(data)

    with tab_embedded:
        st.caption("Embedded viewer (WKWebView may limit large files — use ⧉ Open for full fidelity).")
        try:
            if len(data) <= 20 * 1024 * 1024:
                b64 = base64.b64encode(data).decode()
                obj_html = (
                    f'<object data="data:application/pdf;base64,{b64}" '
                    f'type="application/pdf" width="100%" height="850px" '
                    f'style="border:none;border-radius:8px;">'
                    f'<p>PDF cannot be displayed inline. '
                    f'<a href="data:application/pdf;base64,{b64}" '
                    f'download="{name}">Download {name}</a></p>'
                    f'</object>'
                )
                components.html(obj_html, height=860, scrolling=False)
            else:
                st.info("File too large for inline preview (>20 MB). Use **⧉ Open PDF** above.", icon="📄")
        except Exception as e:
            st.warning(f"Embedded viewer unavailable: {e}. Use ⧉ Open PDF.", icon="⚠️")


def _pdf_to_print_html(data: bytes) -> str:
    """Extract PDF text and format as print-ready HTML."""
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            parts = []
            for i, page in enumerate(pdf.pages, 1):
                text = (page.extract_text() or "").strip()
                text_html = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                text_html = "<br>".join(text_html.splitlines())
                divider = '<div class="page-break"></div>' if i > 1 else ""
                parts.append(f'{divider}<p><em style="color:#888;font-size:10pt;">— Page {i} —</em></p><p>{text_html}</p>')
            return "\n".join(parts) if parts else "<p>(No extractable text)</p>"
    except Exception:
        return "<p>(Could not extract PDF text for print — use ⧉ Open PDF for full fidelity)</p>"


def _render_pdf_text(data: bytes) -> None:
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            if not pdf.pages:
                st.info("PDF has no extractable text pages.")
                return
            st.caption(f"📄 {len(pdf.pages)} pages")
            search_term = st.text_input(
                "Search within document",
                placeholder="Enter text to find...",
                key=f"pdf_search_{len(data)}",
            )
            all_text_pages = [(i, page.extract_text() or "") for i, page in enumerate(pdf.pages, 1)]
            if search_term:
                matches = [(i, t) for i, t in all_text_pages if search_term.lower() in t.lower()]
                st.success(f"Found '{search_term}' on {len(matches)} page(s)")
                pages_to_show = matches
            else:
                pages_to_show = all_text_pages
            for page_num, text in pages_to_show:
                with st.expander(f"Page {page_num}", expanded=(len(pages_to_show) <= 3)):
                    if text.strip():
                        if search_term:
                            st.markdown(text.replace(search_term, f"**{search_term}**"))
                        else:
                            st.text(text)
                    else:
                        st.caption("(No extractable text on this page — may be a scanned image)")
    except ImportError:
        st.warning("pdfplumber not installed. Use ⧉ Open PDF to view.", icon="⚠️")
    except Exception as e:
        st.error(f"Could not extract PDF text: {e}")


# ── DOCX ──────────────────────────────────────────────────────────────────────

def render_docx(name: str, data: bytes) -> None:
    try:
        from docx import Document
        from docx.table import Table
        from docx.text.paragraph import Paragraph
    except ImportError:
        st.error("python-docx not installed.")
        return
    try:
        doc = Document(io.BytesIO(data))
    except Exception as e:
        st.error(f"Could not open DOCX: {e}")
        return

    print_html = _docx_to_print_html(doc)
    _action_bar(name, data, html_for_print=print_html, open_label="⧉ Open DOCX")

    tab_rendered, tab_raw = st.tabs(["📄 Rendered", "📃 Raw Text"])

    with tab_rendered:
        for block in doc.element.body:
            tag = block.tag.split("}")[-1]
            if tag == "p":
                try:
                    para = Paragraph(block, doc)
                    text = para.text
                    if not text.strip():
                        continue
                    style = para.style.name if para.style else ""
                    if style.startswith("Heading 1"):
                        st.markdown(f"# {text}")
                    elif style.startswith("Heading 2"):
                        st.markdown(f"## {text}")
                    elif style.startswith("Heading 3"):
                        st.markdown(f"### {text}")
                    else:
                        st.write(text)
                except Exception:
                    pass
            elif tag == "tbl":
                try:
                    tbl = Table(block, doc)
                    rows = [[cell.text for cell in row.cells] for row in tbl.rows]
                    if rows:
                        import pandas as pd
                        df = pd.DataFrame(rows[1:], columns=rows[0]) if len(rows) > 1 else pd.DataFrame(rows)
                        st.dataframe(df, use_container_width=True)
                except Exception:
                    pass

    with tab_raw:
        full_text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        st.text_area("Full text", full_text, height=600, label_visibility="collapsed")


def _docx_to_print_html(doc) -> str:
    """Convert a python-docx Document to print-ready HTML."""
    try:
        from docx.table import Table
        from docx.text.paragraph import Paragraph
        parts = []
        for block in doc.element.body:
            tag = block.tag.split("}")[-1]
            if tag == "p":
                try:
                    para = Paragraph(block, doc)
                    text = para.text.strip()
                    if not text:
                        continue
                    style = para.style.name if para.style else ""
                    esc = text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                    if style.startswith("Heading 1"):
                        parts.append(f"<h1>{esc}</h1>")
                    elif style.startswith("Heading 2"):
                        parts.append(f"<h2>{esc}</h2>")
                    elif style.startswith("Heading 3"):
                        parts.append(f"<h3>{esc}</h3>")
                    else:
                        parts.append(f"<p>{esc}</p>")
                except Exception:
                    pass
            elif tag == "tbl":
                try:
                    tbl = Table(block, doc)
                    rows = [[cell.text for cell in row.cells] for row in tbl.rows]
                    if rows:
                        th_row = "".join(f"<th>{c.replace('&','&amp;').replace('<','&lt;')}</th>" for c in rows[0])
                        body_rows = "".join(
                            "<tr>" + "".join(f"<td>{c.replace('&','&amp;').replace('<','&lt;')}</td>" for c in r) + "</tr>"
                            for r in rows[1:]
                        )
                        parts.append(f"<table><thead><tr>{th_row}</tr></thead><tbody>{body_rows}</tbody></table>")
                except Exception:
                    pass
        return "\n".join(parts) or "<p>(Empty document)</p>"
    except Exception as e:
        return f"<p>(Could not format DOCX for print: {e})</p>"


# ── XLSX / XLS ────────────────────────────────────────────────────────────────

def render_xlsx(name: str, data: bytes) -> None:
    try:
        import pandas as pd
    except ImportError:
        st.error("pandas not installed.")
        return
    try:
        engine = "openpyxl" if name.lower().endswith(".xlsx") else "xlrd"
        sheets = pd.read_excel(io.BytesIO(data), sheet_name=None, engine=engine)
    except Exception as e:
        st.error(f"Could not open workbook: {e}")
        return

    print_html = _df_dict_to_print_html(sheets)
    _action_bar(name, data, html_for_print=print_html, open_label="⧉ Open Sheet")

    if not sheets:
        st.info("Workbook is empty.")
        return

    sheet_names = list(sheets.keys())
    if len(sheet_names) == 1:
        df = sheets[sheet_names[0]]
        st.caption(f"Sheet: {sheet_names[0]} · {len(df):,} rows × {len(df.columns):,} columns")
        st.dataframe(df, use_container_width=True, height=520)
    else:
        tabs = st.tabs([f"📋 {s}" for s in sheet_names])
        for tab, sname in zip(tabs, sheet_names):
            with tab:
                df = sheets[sname]
                st.caption(f"{len(df):,} rows × {len(df.columns):,} columns")
                st.dataframe(df, use_container_width=True, height=520)


def _df_dict_to_print_html(sheets: dict) -> str:
    parts = []
    for sname, df in sheets.items():
        parts.append(f"<h2>{sname}</h2>")
        parts.append(df.to_html(index=False, border=0, classes=""))
    return "\n".join(parts) or "<p>(Empty workbook)</p>"


# ── CSV ───────────────────────────────────────────────────────────────────────

def render_csv(name: str, data: bytes) -> None:
    try:
        import pandas as pd
        df = pd.read_csv(io.BytesIO(data))
    except Exception as e:
        st.error(f"Could not parse CSV: {e}")
        return

    print_html = df.to_html(index=False, border=0)
    _action_bar(name, data, html_for_print=print_html, open_label="⧉ Open CSV")

    st.caption(f"{len(df):,} rows × {len(df.columns):,} columns")
    fc, fs = st.columns([3, 2])
    with fc:
        search = st.text_input("Filter rows", placeholder="Any column contains...",
                               key=f"csv_f_{len(data)}")
    with fs:
        sort_col = st.selectbox("Sort by", ["— none —"] + list(df.columns),
                                key=f"csv_s_{len(data)}")
    if search:
        mask = df.apply(lambda c: c.astype(str).str.contains(search, case=False, na=False)).any(axis=1)
        df = df[mask]
    if sort_col != "— none —":
        df = df.sort_values(sort_col)
    st.dataframe(df, use_container_width=True, height=520)


# ── PPTX ──────────────────────────────────────────────────────────────────────

def render_pptx(name: str, data: bytes) -> None:
    try:
        from pptx import Presentation
    except ImportError:
        st.error("python-pptx not installed.")
        return
    try:
        prs = Presentation(io.BytesIO(data))
    except Exception as e:
        st.error(f"Could not open PPTX: {e}")
        return

    slides = prs.slides
    total  = len(slides)

    print_html = _pptx_to_print_html(prs)
    _action_bar(name, data, html_for_print=print_html, open_label="⧉ Open Slides")

    if total == 0:
        st.info("Presentation has no slides.")
        return

    st.caption(f"{total} slides")
    slide_num = st.slider("Slide", 1, total, 1, key=f"pptx_{len(data)}")
    slide = slides[slide_num - 1]

    with st.container():
        st.markdown(
            '<div style="background:#fff;border:1px solid #dde3ee;border-radius:8px;'
            'padding:1.5rem 2rem;min-height:320px;">',
            unsafe_allow_html=True,
        )
        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            for para in shape.text_frame.paragraphs:
                text = para.text.strip()
                if not text:
                    continue
                try:
                    pts = para.runs[0].font.size.pt if para.runs and para.runs[0].font.size else 0
                except Exception:
                    pts = 0
                if pts >= 24:
                    st.markdown(f"## {text}")
                elif pts >= 18:
                    st.markdown(f"### {text}")
                else:
                    st.write(text)
        st.markdown("</div>", unsafe_allow_html=True)

    with st.expander("All slides — text"):
        for i, sl in enumerate(slides, 1):
            texts = [s.text_frame.text.strip() for s in sl.shapes if s.has_text_frame]
            st.markdown(f"**Slide {i}**")
            st.text("\n".join(t for t in texts if t) or "(no text)")
            st.divider()


def _pptx_to_print_html(prs) -> str:
    parts = []
    for i, slide in enumerate(prs.slides, 1):
        divider = '<div class="page-break"></div>' if i > 1 else ""
        parts.append(f'{divider}<h2>Slide {i}</h2>')
        for shape in slide.shapes:
            if shape.has_text_frame:
                for para in shape.text_frame.paragraphs:
                    text = para.text.strip()
                    if text:
                        esc = text.replace("&", "&amp;").replace("<", "&lt;")
                        parts.append(f"<p>{esc}</p>")
    return "\n".join(parts) or "<p>(No text in presentation)</p>"


# ── Images ────────────────────────────────────────────────────────────────────

def render_image(name: str, data: bytes) -> None:
    suffix = ext(name)

    # Build print HTML with inline image
    if suffix in (".heic", ".heif"):
        # Convert for print HTML
        try:
            from pillow_heif import register_heif_opener
            register_heif_opener()
            from PIL import Image as _PIL
            img = _PIL.open(io.BytesIO(data)).convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=85)
            img_b64 = base64.b64encode(buf.getvalue()).decode()
            img_mime = "image/jpeg"
        except Exception:
            img_b64 = base64.b64encode(data).decode()
            img_mime = "image/heic"
    elif suffix == ".svg":
        img_b64 = base64.b64encode(data).decode()
        img_mime = "image/svg+xml"
    else:
        img_b64 = base64.b64encode(data).decode()
        img_mime = mime_for(name)

    print_html = (
        f'<figure style="text-align:center;">'
        f'<img src="data:{img_mime};base64,{img_b64}" '
        f'style="max-width:100%;max-height:9in;" />'
        f'<figcaption style="font-size:10pt;color:#555;margin-top:.5rem;">{name}</figcaption>'
        f'</figure>'
    )
    _action_bar(name, data, html_for_print=print_html, open_label="⧉ Open Image")

    if suffix == ".svg":
        b64 = base64.b64encode(data).decode()
        st.markdown(
            f'<img src="data:image/svg+xml;base64,{b64}" '
            f'style="max-width:100%;border-radius:8px;" />',
            unsafe_allow_html=True,
        )
    elif suffix in (".heic", ".heif"):
        try:
            from pillow_heif import register_heif_opener
            register_heif_opener()
            from PIL import Image as _PIL
            img = _PIL.open(io.BytesIO(data)).convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=90)
            st.image(buf.getvalue(), use_container_width=True,
                     caption=f"{name} (HEIC→JPEG)")
        except Exception as e:
            st.error(f"Could not display HEIC: {e}")
    elif suffix in (".tiff", ".tif"):
        try:
            from PIL import Image as _PIL
            img = _PIL.open(io.BytesIO(data)).convert("RGB")
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=90)
            st.image(buf.getvalue(), use_container_width=True)
        except Exception as e:
            st.error(f"Could not display TIFF: {e}")
    else:
        st.image(data, use_container_width=True)
    st.caption(fmt_size(len(data)))


def render_video(name: str, data: bytes) -> None:
    _action_bar(name, data, html_for_print=None, open_label="⧉ Open Video")
    try:
        st.video(data)
    except Exception as e:
        st.info(f"Inline preview unavailable ({e}). Use ⧉ Open Video.", icon="🎬")


# ── Markdown ──────────────────────────────────────────────────────────────────

def render_markdown(name: str, data: bytes) -> None:
    text = data.decode("utf-8", errors="replace")
    # Simple markdown → HTML for print (headings, paragraphs)
    import re
    html_lines = []
    for line in text.splitlines():
        if line.startswith("### "):
            html_lines.append(f"<h3>{line[4:]}</h3>")
        elif line.startswith("## "):
            html_lines.append(f"<h2>{line[3:]}</h2>")
        elif line.startswith("# "):
            html_lines.append(f"<h1>{line[2:]}</h1>")
        elif line.strip() == "":
            html_lines.append("<br>")
        else:
            esc = line.replace("&","&amp;").replace("<","&lt;")
            html_lines.append(f"<p>{esc}</p>")
    print_html = "\n".join(html_lines)
    _action_bar(name, data, html_for_print=print_html)

    tab_r, tab_raw = st.tabs(["📄 Rendered", "📃 Raw"])
    with tab_r:
        st.markdown(text)
    with tab_raw:
        st.code(text, language="markdown")


# ── JSON ──────────────────────────────────────────────────────────────────────

def render_json(name: str, data: bytes) -> None:
    text = data.decode("utf-8", errors="replace")
    try:
        parsed = json.loads(text)
        pretty = json.dumps(parsed, indent=2, ensure_ascii=False)
    except json.JSONDecodeError:
        pretty = text

    esc = pretty.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    print_html = f"<pre>{esc}</pre>"
    _action_bar(name, data, html_for_print=print_html)

    try:
        tab_p, tab_r = st.tabs(["📄 Pretty", "📃 Raw"])
        with tab_p:
            st.code(pretty, language="json")
        with tab_r:
            st.code(text, language="json")
        if isinstance(parsed, dict):
            st.caption(f"Keys: {', '.join(str(k) for k in list(parsed.keys())[:20])}")
        elif isinstance(parsed, list):
            st.caption(f"Array with {len(parsed):,} items")
    except Exception:
        st.code(text, language="text")


# ── HTML ──────────────────────────────────────────────────────────────────────

# H-4: Safe HTML tags and attributes — strips <script>, <iframe>, event handlers
_HTML_ALLOWED_TAGS = {
    "a", "abbr", "b", "blockquote", "br", "caption", "cite", "code",
    "col", "colgroup", "dd", "del", "dfn", "div", "dl", "dt", "em",
    "figure", "figcaption", "h1", "h2", "h3", "h4", "h5", "h6",
    "hr", "i", "img", "ins", "kbd", "li", "mark", "ol", "p", "pre",
    "q", "s", "samp", "section", "small", "span", "strong", "sub",
    "sup", "table", "tbody", "td", "tfoot", "th", "thead", "time",
    "tr", "u", "ul", "var",
}
_HTML_ALLOWED_ATTRS: dict = {
    "a":   ["href", "title", "target"],
    "img": ["src", "alt", "title", "width", "height"],
    "td":  ["colspan", "rowspan", "align"],
    "th":  ["colspan", "rowspan", "align"],
    "*":   ["class", "style"],
}


def _sanitize_html(raw: str) -> str:
    """
    Strip scripts, iframes, and event-handler attributes from HTML.
    Uses bleach if available; falls back to a simple regex scrub.
    """
    try:
        import bleach  # type: ignore
        return bleach.clean(
            raw,
            tags=_HTML_ALLOWED_TAGS,
            attributes=_HTML_ALLOWED_ATTRS,
            strip=True,
            strip_comments=True,
        )
    except ImportError:
        # Fallback: remove <script>, <iframe>, and on* attributes
        import re as _re
        cleaned = _re.sub(r'<(script|iframe|object|embed|form)[^>]*>.*?</\1>',
                          '', raw, flags=_re.DOTALL | _re.IGNORECASE)
        cleaned = _re.sub(r'\bon\w+\s*=\s*["\'][^"\']*["\']', '', cleaned,
                          flags=_re.IGNORECASE)
        return cleaned


def render_html(name: str, data: bytes) -> None:
    html_str = data.decode("utf-8", errors="replace")
    _action_bar(name, data, html_for_print=html_str, open_label="⧉ Open in Browser")
    tab_p, tab_s = st.tabs(["🌐 Preview", "📃 Source"])
    with tab_p:
        # H-4: Sanitize before rendering — strips <script> and event handlers
        safe_html = _sanitize_html(html_str)
        st.caption(
            "⚠️ Scripts and iframes stripped for security. "
            "Click **⧉ Open in Browser** above for full rendering.",
        )
        # Wrap in a white-background shell so documents designed for light
        # backgrounds are readable regardless of the app's dark theme.
        # The wrapper also resets the font to a clean readable stack.
        white_shell = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
  html, body {{
    background: #ffffff !important;
    color: #111111 !important;
    font-family: Georgia, "Times New Roman", serif;
    font-size: 14px;
    line-height: 1.6;
    margin: 0;
    padding: 16px 24px;
  }}
  /* Let the document's own colours show through where explicitly set,
     but default everything else to readable dark-on-white. */
  * {{ box-sizing: border-box; }}
  a {{ color: #1a56a0; }}
  table {{ border-collapse: collapse; width: 100%; }}
  td, th {{ border: 1px solid #ddd; padding: 4px 8px; vertical-align: top; }}
  th {{ background: #f0f4ff; font-weight: bold; }}
  img {{ max-width: 100%; height: auto; }}
  pre, code {{ background: #f5f5f5; padding: 2px 4px; border-radius: 3px; font-size: 13px; }}
</style>
</head>
<body>
{safe_html}
</body>
</html>"""
        components.html(white_shell, height=750, scrolling=True)
    with tab_s:
        st.code(html_str, language="html")


# ── Plain text / code ─────────────────────────────────────────────────────────

def render_text(name: str, data: bytes) -> None:
    text = data.decode("utf-8", errors="replace")
    esc = text.replace("&","&amp;").replace("<","&lt;").replace(">","&gt;")
    print_html = f"<pre>{esc}</pre>"
    _action_bar(name, data, html_for_print=print_html)
    lang = CODE_LANGS.get(ext(name), "text")
    st.code(text, language=lang)


# ── Main dispatcher ───────────────────────────────────────────────────────────

def render_file(name: str, data: bytes) -> None:
    """Route a file to the correct viewer based on its extension."""
    if not data:
        st.warning(f"File '{name}' is empty.")
        return

    suffix = ext(name)

    try:
        if suffix == ".pdf":
            render_pdf(name, data)
        elif suffix in (".docx", ".doc", ".odt"):
            render_docx(name, data)
        elif suffix in (".xlsx", ".xls"):
            render_xlsx(name, data)
        elif suffix == ".csv":
            render_csv(name, data)
        elif suffix in (".pptx", ".ppt"):
            render_pptx(name, data)
        elif suffix in IMAGE_EXTS:
            render_image(name, data)
        elif suffix in VIDEO_EXTS:
            render_video(name, data)
        elif suffix in (".md", ".markdown"):
            render_markdown(name, data)
        elif suffix == ".json":
            render_json(name, data)
        elif suffix in (".html", ".htm"):
            render_html(name, data)
        else:
            render_text(name, data)
    except Exception as e:
        st.error(f"Error rendering '{name}': {e}")
        _action_bar(name, data, html_for_print=None, open_label="⧉ Open")
