"""
Shared sync runner — the single source dispatch used by both the GUI's
background auto-sync thread and the headless scheduled sync (launchd/cron).

Keeping the source list and the per-source dispatch here (rather than inline in
gui.py) means the scheduled job and the in-app "Sync now" button run exactly the
same code, so freshness never depends on the app being open.
"""

from typing import Callable, Optional

# "Fast" sources suitable for frequent, incremental syncs. Heavy bulk downloads
# (OFAC, full OpenStates, all-states crawl) are intentionally excluded — run
# those on demand from the Sync Manager, not on the tight schedule.
DEFAULT_SOURCES = [
    "courtlistener", "ftc_sec_cfpb", "eeoc_hud_doj", "federal_register",
    "sec_edgar", "reuters_legal", "scotusblog", "oyez_scotus",
]


def run_sources(
    sources: list,
    progress_cb: Optional[Callable[[str], None]] = None,
    incremental: bool = False,
) -> dict:
    """Run the selected sources and return totals.

    Args:
        sources: source keys from DEFAULT_SOURCES.
        progress_cb: optional progress callback (one line per update).
        incremental: pass through to sources that support delta fetches
            (currently CourtListener), so only items newer than the last
            successful sync are pulled.

    Returns:
        {"added": int, "updated": int, "errors": [str, ...]}
    """
    def _prog(msg: str) -> None:
        if progress_cb:
            progress_cb(msg)

    total_added = total_updated = 0
    errors: list[str] = []

    def _safe(label, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001 — one source must not abort the rest
            _prog(f"  ❌ {label}: {e}")
            errors.append(f"{label}: {e}")
            return {"added": 0, "updated": 0}

    def _safe_ab(label, fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except Exception as e:  # noqa: BLE001
            _prog(f"  ❌ {label}: {e}")
            errors.append(f"{label}: {e}")
            return 0, 0

    if "courtlistener" in sources:
        from aggregator.courtlistener_fetch import run_full_sync
        _prog("Sync: CourtListener…")
        r = _safe("CourtListener", run_full_sync, max_per_query=30,
                  progress_cb=progress_cb, incremental=incremental)
        total_added += r["added"]; total_updated += r["updated"]

    if "ftc_sec_cfpb" in sources:
        from aggregator.regulatory_fetch import run_regulatory_sync
        _prog("Sync: FTC + SEC + CFPB…")
        r = _safe("FTC/SEC/CFPB", run_regulatory_sync, progress_cb=progress_cb)
        total_added += r["added"]; total_updated += r["updated"]

    if "eeoc_hud_doj" in sources:
        from aggregator.civil_rights_fetch import run_civil_rights_sync
        _prog("Sync: EEOC + HUD + DOJ…")
        r = _safe("EEOC/HUD/DOJ", run_civil_rights_sync, progress_cb=progress_cb)
        total_added += r["added"]; total_updated += r["updated"]

    if "federal_register" in sources:
        from aggregator.federal_register_fetch import run_federal_register_sync
        _prog("Sync: Federal Register…")
        r = _safe("Federal Register", run_federal_register_sync, progress_cb=progress_cb)
        total_added += r["added"]; total_updated += r["updated"]

    if "sec_edgar" in sources:
        from aggregator.edgar_fetch import run_edgar_sync
        _prog("Sync: SEC EDGAR…")
        r = _safe("SEC EDGAR", run_edgar_sync, progress_cb=progress_cb)
        total_added += r["added"]; total_updated += r["updated"]

    if "reuters_legal" in sources:
        from aggregator.legal_news_fetch import fetch_reuters_legal
        _prog("Sync: Reuters Legal…")
        a, u = _safe_ab("Reuters Legal", fetch_reuters_legal, progress_cb=progress_cb)
        total_added += a; total_updated += u

    if "scotusblog" in sources:
        from aggregator.scotus_fetch import fetch_scotusblog
        _prog("Sync: SCOTUSblog…")
        a, u = _safe_ab("SCOTUSblog", fetch_scotusblog, progress_cb=progress_cb)
        total_added += a; total_updated += u

    if "oyez_scotus" in sources:
        from aggregator.scotus_fetch import fetch_oyez
        _prog("Sync: Oyez SCOTUS…")
        a, u = _safe_ab("Oyez", fetch_oyez, progress_cb=progress_cb)
        total_added += a; total_updated += u

    return {"added": total_added, "updated": total_updated, "errors": errors}
