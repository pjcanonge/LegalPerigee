"""
Secure API key storage using macOS Keychain / Windows Credential Manager
via the `keyring` library.

All sensitive credentials are stored encrypted in the OS Keychain.
They are NEVER written to .env, source files, or log files.

Managed keys:
  ANTHROPIC_API_KEY       — Claude AI (required)
  COURTLISTENER_API_TOKEN — CourtListener REST API (optional, raises rate limits)
  CONGRESS_API_KEY        — Congress.gov (optional, for Legislative Watch)
  OPENSTATES_API_KEY      — OpenStates 50-state legislatures (optional)
  REGULATIONS_GOV_KEY     — Regulations.gov dockets (optional)
  ALERT_EMAIL_FROM        — SMTP sender address for email alerts (optional)
  ALERT_EMAIL_PASSWORD    — SMTP app password (optional, sensitive)
"""

import os

SERVICE = "LegalPerigee"

# All keys managed by this module — order controls sidebar display
ALL_KEYS = [
    "ANTHROPIC_API_KEY",
    "COURTLISTENER_API_TOKEN",
    "CONGRESS_API_KEY",
    "OPENSTATES_API_KEY",
    "REGULATIONS_GOV_KEY",
    "ALERT_EMAIL_FROM",
    "ALERT_EMAIL_PASSWORD",
]

try:
    import keyring as _kr
    _KEYRING_AVAILABLE = True
except ImportError:
    _KEYRING_AVAILABLE = False


def save_key(name: str, value: str) -> bool:
    """Store a credential in macOS Keychain / Windows Credential Manager.
    Returns True on success."""
    if not _KEYRING_AVAILABLE or not value:
        return False
    try:
        _kr.set_password(SERVICE, name, value.strip())
        return True
    except Exception:
        return False


def load_key(name: str) -> str:
    """Retrieve a credential from Keychain. Returns '' if not found."""
    if not _KEYRING_AVAILABLE:
        return ""
    try:
        val = _kr.get_password(SERVICE, name)
        return val.strip() if val else ""
    except Exception:
        return ""


def delete_key(name: str) -> None:
    """Remove a credential from Keychain."""
    if not _KEYRING_AVAILABLE:
        return
    try:
        _kr.delete_password(SERVICE, name)
    except Exception:
        pass


def load_all_keys() -> dict:
    """Load ALL managed keys from Keychain into os.environ.

    Call this once at app startup so every module can use os.getenv()
    as normal — no module needs to know about Keychain directly.

    Returns a dict of {key_name: True/False} indicating which keys
    were found and injected.
    """
    status = {}
    for name in ALL_KEYS:
        val = load_key(name)
        if val:
            os.environ[name] = val
            status[name] = True
        else:
            status[name] = False
    return status


def keyring_available() -> bool:
    return _KEYRING_AVAILABLE


def list_stored_keys() -> list[str]:
    """Return names of keys that are currently stored in Keychain."""
    return [k for k in ALL_KEYS if load_key(k)]
