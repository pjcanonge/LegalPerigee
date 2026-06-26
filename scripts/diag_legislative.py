#!/usr/bin/env python3
"""
LegalPerigee — legislative sources diagnostic.

Probes each legislative data source and reports, per source: whether a key is
present, how many bills a small probe pulls, any errors, and the resulting DB
row count. Run on a machine WITH network access (the sources are blocked in the
sandbox where this was written):

    python3 scripts/diag_legislative.py

This is the "test" half of the legislative fixes — it turns "feels limited"
into concrete numbers so you can see exactly which sources are working.
"""

import os
import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_DIR))


def _p(msg: str) -> None:
    print(f"   {msg}")


def main() -> int:
    env = PROJECT_DIR / ".env"
    if env.exists():
        try:
            from dotenv import load_dotenv
            load_dotenv(dotenv_path=str(env), override=False)
        except Exception:
            pass

    from database.db import init_db, count_cases
    init_db()

    print("\n⚖️  Legislative sources diagnostic\n" + "━" * 50)

    # ── GovInfo (no key) ──────────────────────────────────────────────────────
    print("\n🏛️  GovInfo (federal bills, no key required)")
    try:
        from aggregator.govinfo_fetch import fetch_govinfo_bills
        a, u = fetch_govinfo_bills(max_bills=20, progress_cb=_p)
        print(f"   → +{a} new, {u} updated (probe of ~20 recent bills/type)")
    except Exception as e:  # noqa: BLE001
        print(f"   ❌ {e}")

    # ── Congress.gov (key) ────────────────────────────────────────────────────
    print("\n🏛️  Congress.gov (needs CONGRESS_API_KEY)")
    if not os.getenv("CONGRESS_API_KEY"):
        print("   ⏭️  no CONGRESS_API_KEY — skipped (free at api.congress.gov)")
    else:
        try:
            from aggregator.congress_fetch import fetch_congress_bills
            a, u = fetch_congress_bills(bill_types=["hr"], max_per_type=100, progress_cb=_p)
            print(f"   → +{a} new, {u} updated (HR only, keyword-filtered)")
        except Exception as e:  # noqa: BLE001
            print(f"   ❌ {e}")

    # ── OpenStates (key) ──────────────────────────────────────────────────────
    print("\n🗺️  OpenStates (needs OPENSTATES_API_KEY)")
    if not os.getenv("OPENSTATES_API_KEY"):
        print("   ⏭️  no OPENSTATES_API_KEY — skipped (free at openstates.org)")
    else:
        try:
            from aggregator.openstates_fetch import fetch_bills
            a, u = fetch_bills("civil rights", jurisdictions=["ca", "tx", "ny"], progress_cb=_p)
            print(f"   → +{a} new, {u} updated (CA/TX/NY probe — all states no longer capped at 10)")
        except Exception as e:  # noqa: BLE001
            print(f"   ❌ {e}")

    # ── DB totals ─────────────────────────────────────────────────────────────
    print("\n📊 Legislative rows in DB by source")
    for src in ("govinfo", "congress", "openstates", "govtrack"):
        print(f"   {src:12s}: {count_cases(src)}")
    print("\nDone.\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
