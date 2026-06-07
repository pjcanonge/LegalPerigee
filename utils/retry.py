"""
Rate-limit-aware retry wrapper for Anthropic API calls.

On a 429 (rate_limit_error) the SDK already retries twice with short backoff,
but 30K TPM limits need a longer wait. This wrapper catches what slips through
and waits up to 90 s before giving up.
"""

import sys
import time
from typing import Callable, TypeVar

import anthropic

T = TypeVar("T")

# Seconds to wait after each rate-limit hit
_BACKOFF = [10, 20, 40, 60, 90]


def call_with_retry(fn: Callable[[], T], label: str = "API call") -> T:
    """
    Call fn(), retrying on 429 rate limit errors with increasing backoff.

    Args:
        fn: Zero-argument callable that makes an Anthropic API call.
        label: Human-readable name shown in retry log messages.

    Returns:
        Whatever fn() returns.

    Raises:
        The last exception if all retries are exhausted.
    """
    last_exc: Exception | None = None
    for attempt, wait in enumerate([0] + _BACKOFF, start=1):
        if wait:
            msg = f"[rate limit] {label} — waiting {wait}s before retry {attempt}/{len(_BACKOFF) + 1}…"
            print(msg, file=sys.stderr, flush=True)
            time.sleep(wait)
        try:
            return fn()
        except anthropic.RateLimitError as exc:
            last_exc = exc
            print(
                f"[rate limit] 429 on {label} (attempt {attempt}): {exc}",
                file=sys.stderr,
                flush=True,
            )
        except anthropic.APIStatusError as exc:
            # Re-raise non-rate-limit API errors immediately
            raise
    raise last_exc  # type: ignore[misc]
