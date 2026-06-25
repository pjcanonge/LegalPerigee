#!/usr/bin/env python3
"""
LegalPerigee — headless scheduled sync.

Runs an incremental sync of the fast sources WITHOUT the GUI, so the local
case database stays fresh even when the app is closed. Intended to be driven by
launchd (macOS) or cron every ~20 minutes. See:
    installers/macos/com.legalperigee.sync.plist
    installers/macos/install_scheduled_sync.sh

Run manually:
    python3 scripts/scheduled_sync.py
    python3 scripts/scheduled_sync.py --sources courtlistener,federal_register
    python3 scripts/scheduled_sync.py --full     # ignore incremental window

Exit code is 0 on success, 1 if any source errored (so launchd/cron can log it).
"""

import argparse
import os
import sys
import time
from pathlib import Path

# Make the project importable when launched by launchd/cron with a bare cwd.
PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))

LOG_FILE = Path.home() / "Library" / "Logs" / "LegalPerigee_sync.log"


def _log(msg: str) -> None:
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG_FILE, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
    except OSError:
        pass  # logging is best-effort; never fail the sync over it


def main() -> int:
    parser = argparse.ArgumentParser(description="LegalPerigee headless scheduled sync")
    parser.add_argument(
        "--sources",
        help="Comma-separated source keys (default: all fast sources).",
        default="",
    )
    parser.add_argument(
        "--full",
        action="store_true",
        help="Pull the full default window instead of an incremental delta.",
    )
    args = parser.parse_args()

    # Load .env so API tokens (CourtListener, etc.) are available headlessly.
    env_file = PROJECT_DIR / ".env"
    if env_file.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(dotenv_path=str(env_file), override=False)
        except Exception:
            pass

    from database.db import init_db
    from aggregator.sync_runner import DEFAULT_SOURCES, run_sources

    init_db()

    sources = (
        [s.strip() for s in args.sources.split(",") if s.strip()]
        if args.sources else list(DEFAULT_SOURCES)
    )

    _log(f"Scheduled sync starting — sources={sources} incremental={not args.full}")
    started = time.time()
    result = run_sources(sources, progress_cb=_log, incremental=not args.full)
    elapsed = time.time() - started

    _log(
        f"Done in {elapsed:.0f}s — +{result['added']} new, "
        f"{result['updated']} updated, {len(result['errors'])} error(s)"
    )
    for err in result["errors"]:
        _log(f"  error: {err}")

    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
