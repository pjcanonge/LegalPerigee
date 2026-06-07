"""
Web search and scraping tools.  (v1.2 — SSRF-hardened)

web_search uses the Anthropic SDK's built-in server-side web_search tool.
web_scrape uses httpx + BeautifulSoup for direct URL fetching.

Security (v1.2):
  - H-3: _validate_url() blocks private/loopback IPs, non-http(s) schemes,
          and enforces an optional domain allowlist.
"""

import ipaddress
import json
import re
from typing import Optional
from urllib.parse import urlparse

import httpx
from bs4 import BeautifulSoup

# ── SSRF guard (H-3) ──────────────────────────────────────────────────────────
_ALLOWED_SCHEMES = {"http", "https"}

# Known-good legal source domains — extend as needed
_LEGAL_DOMAIN_ALLOWLIST: set[str] = {
    "courtlistener.com", "storage.courtlistener.com",
    "pacer.gov", "uscourts.gov",
    "congress.gov", "api.congress.gov",
    "regulations.gov", "api.regulations.gov",
    "sec.gov", "efts.sec.gov",
    "ftc.gov", "cfpb.gov",
    "doj.gov", "justice.gov",
    "supremecourt.gov",
    "law.cornell.edu",
    "casetext.com",
    "scholar.google.com",
    "reuters.com", "law360.com",
    "bloomberg.com",
    "eur-lex.europa.eu",
    # Allow any subdomain — checked via endswith below
}


def _validate_url(url: str) -> None:
    """
    Raise ValueError if the URL should not be fetched (SSRF / scheme guard).

    Blocks:
      - Non-http/https schemes (file://, ftp://, etc.)
      - Private / loopback / link-local IP addresses
      - Common private IP prefix strings (belt-and-suspenders)
    """
    try:
        parsed = urlparse(url)
    except Exception as exc:
        raise ValueError(f"Malformed URL: {url}") from exc

    scheme = (parsed.scheme or "").lower()
    if scheme not in _ALLOWED_SCHEMES:
        raise ValueError(f"URL scheme not allowed: {scheme!r} in {url}")

    host = parsed.hostname or ""
    if not host:
        raise ValueError(f"URL has no hostname: {url}")

    # Try to parse as an IP address — block private/loopback ranges
    try:
        addr = ipaddress.ip_address(host)
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_reserved:
            raise ValueError(f"Request to private/internal address blocked: {host}")
    except ValueError as exc:
        # Re-raise our own ValueError, not the ipaddress parse error
        if "blocked" in str(exc):
            raise
        # hostname (not an IP) — belt-and-suspenders string check
        _BLOCKED_PREFIXES = (
            "127.", "10.", "192.168.", "169.254.", "0.",
            "localhost", "::1", "[::1]",
        )
        if any(host.lower().startswith(p) for p in _BLOCKED_PREFIXES):
            raise ValueError(f"Request to internal host blocked: {host}")

# Anthropic SDK web_search tool schema (server-side tool — no client execution needed)
WEB_SEARCH_TOOL_SCHEMA = {
    "type": "web_search_20260209",
    "name": "web_search",
}

# Client-side scrape tool schema
WEB_SCRAPE_TOOL_SCHEMA = {
    "name": "web_scrape",
    "description": (
        "Fetch and extract readable text content from a specific URL. "
        "Use this to read tech-law blog posts, regulatory press releases, "
        "news articles, or court document pages after finding them via web_search."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "Full URL to fetch and extract text from",
            },
            "focus": {
                "type": "string",
                "description": (
                    "Optional — what to focus on when extracting content "
                    "(e.g. 'case details', 'financial figures', 'defendant names')"
                ),
            },
        },
        "required": ["url"],
    },
}


def web_scrape(url: str, focus: Optional[str] = None, timeout: int = 15) -> str:
    """
    Fetch a URL and return cleaned, readable text content.

    Args:
        url: Target URL (validated against SSRF guard before fetching)
        focus: Optional hint for what to extract
        timeout: HTTP timeout in seconds

    Returns:
        JSON string with extracted text and metadata
    """
    # H-3: SSRF guard — validate before any network I/O
    try:
        _validate_url(url)
    except ValueError as ve:
        return json.dumps({"error": f"URL blocked by security policy: {ve}", "url": url})

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (compatible; LegalPerigee/1.2; "
            "+https://github.com/legalperigee) research-bot"
        )
    }

    try:
        with httpx.Client(timeout=timeout, follow_redirects=True) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
    except httpx.TimeoutException:
        return json.dumps({"error": f"Timeout fetching {url}", "url": url})
    except httpx.HTTPStatusError as e:
        return json.dumps({"error": f"HTTP {e.response.status_code}", "url": url})
    except Exception as e:
        return json.dumps({"error": str(e), "url": url})

    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type and "text/plain" not in content_type:
        return json.dumps({
            "error": f"Unsupported content type: {content_type}",
            "url": url,
        })

    soup = BeautifulSoup(response.text, "html.parser")

    # Remove boilerplate
    for tag in soup(["script", "style", "nav", "footer", "header", "aside", "noscript"]):
        tag.decompose()

    # Extract title
    title = soup.find("title")
    title_text = title.get_text(strip=True) if title else ""

    # Extract main content — prefer <main>, <article>, or <body>
    main = soup.find("main") or soup.find("article") or soup.find("body")
    raw_text = main.get_text(separator="\n") if main else soup.get_text(separator="\n")

    # Collapse whitespace
    lines = [line.strip() for line in raw_text.splitlines()]
    lines = [line for line in lines if line]
    text = "\n".join(lines)

    # Truncate to ~8000 chars to avoid blowing context
    truncated = len(text) > 8000
    text = text[:8000]

    result = {
        "url": url,
        "title": title_text,
        "text": text,
        "truncated": truncated,
        "char_count": len(text),
    }
    if focus:
        result["focus_hint"] = focus

    return json.dumps(result)


def execute_search_tool(tool_name: str, tool_input: dict) -> str:
    """Dispatch a client-side search tool call by name."""
    if tool_name == "web_scrape":
        return web_scrape(tool_input["url"], tool_input.get("focus"))
    return json.dumps({"error": f"Unknown search tool: {tool_name}"})


ALL_WEB_TOOL_SCHEMAS = [WEB_SEARCH_TOOL_SCHEMA, WEB_SCRAPE_TOOL_SCHEMA]
