"""
Shared HTTP utility for LegalPerigee aggregators.
Provides safe_get() with automatic 429 retry/backoff and clear 403 reporting.
"""

import time
from typing import Callable, Optional

import httpx

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36 "
        "LegalPerigee/1.1 (legal research; contact admin@legalperigee.ai)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/json,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


def safe_get(
    url: str,
    *,
    headers: Optional[dict] = None,
    params: Optional[dict] = None,
    timeout: int = 20,
    retries: int = 3,
    progress_cb: Optional[Callable[[str], None]] = None,
    source_label: str = "",
) -> Optional[httpx.Response]:
    """
    GET with automatic retry on 429 (exponential backoff) and
    graceful 403 reporting.

    Returns the Response on success, None on failure.
    """
    hdrs = {**DEFAULT_HEADERS, **(headers or {})}
    label = f"[{source_label}] " if source_label else ""

    for attempt in range(1, retries + 1):
        try:
            r = httpx.get(
                url, headers=hdrs, params=params,
                timeout=timeout, follow_redirects=True,
            )

            # ── 429 Too Many Requests ─────────────────────────────────────
            if r.status_code == 429:
                retry_after = int(r.headers.get("Retry-After", 5 * (2 ** attempt)))
                wait = min(retry_after, 60)
                if progress_cb:
                    progress_cb(
                        f"  ⏳ {label}Rate limited (429) — waiting {wait}s "
                        f"(attempt {attempt}/{retries})…"
                    )
                time.sleep(wait)
                continue

            # ── 403 Forbidden ────────────────────────────────────────────
            if r.status_code == 403:
                if progress_cb:
                    progress_cb(
                        f"  🚫 {label}Access blocked (403 Forbidden): {url[:80]}"
                    )
                return None

            # ── Other HTTP errors ─────────────────────────────────────────
            if r.status_code >= 400:
                if progress_cb:
                    progress_cb(
                        f"  ⚠️ {label}HTTP {r.status_code}: {url[:80]}"
                    )
                return None

            return r

        except httpx.TimeoutException:
            if progress_cb:
                progress_cb(
                    f"  ⚠️ {label}Timeout (attempt {attempt}/{retries}): {url[:80]}"
                )
            if attempt < retries:
                time.sleep(2 ** attempt)

        except Exception as exc:
            if progress_cb:
                progress_cb(f"  ⚠️ {label}Request error: {exc}")
            return None

    if progress_cb:
        progress_cb(f"  ❌ {label}Failed after {retries} attempts: {url[:80]}")
    return None


def safe_get_json(
    url: str,
    *,
    headers: Optional[dict] = None,
    params: Optional[dict] = None,
    timeout: int = 20,
    retries: int = 3,
    progress_cb: Optional[Callable[[str], None]] = None,
    source_label: str = "",
) -> Optional[dict]:
    """Convenience wrapper — returns parsed JSON dict or None."""
    r = safe_get(
        url, headers=headers, params=params, timeout=timeout,
        retries=retries, progress_cb=progress_cb, source_label=source_label,
    )
    if r is None:
        return None
    try:
        return r.json()
    except Exception:
        return None


def safe_get_soup(
    url: str,
    *,
    headers: Optional[dict] = None,
    params: Optional[dict] = None,
    timeout: int = 20,
    retries: int = 3,
    progress_cb: Optional[Callable[[str], None]] = None,
    source_label: str = "",
):
    """Convenience wrapper — returns BeautifulSoup or None."""
    from bs4 import BeautifulSoup
    r = safe_get(
        url, headers=headers, params=params, timeout=timeout,
        retries=retries, progress_cb=progress_cb, source_label=source_label,
    )
    if r is None:
        return None
    try:
        return BeautifulSoup(r.text, "html.parser")
    except Exception:
        return None
