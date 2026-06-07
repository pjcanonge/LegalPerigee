"""
Legislative Trend Analyzer

Queries the local case database to surface:
  - Topic surge detection (keywords spiking across states)
  - Wave detection (same bill introduced in 3+ states within 60 days)
  - Pre-emption pattern identification
  - Velocity tracking (bills advancing unusually fast)
  - Geographic spread mapping
"""

import json
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Optional

from database.db import get_conn

# ── Topic categories to track ─────────────────────────────────────────────────
TOPIC_KEYWORDS = {
    "Voting Rights":        ["voting", "voter id", "ballot", "election", "poll"],
    "Housing":              ["housing", "eviction", "tenant", "rent", "zoning", "mortgage"],
    "Civil Rights":         ["civil rights", "discrimination", "equal", "protected class"],
    "Criminal Justice":     ["police", "prison", "sentencing", "bail", "criminal justice"],
    "Environmental":        ["environmental", "climate", "pollution", "water", "air quality"],
    "Healthcare":           ["healthcare", "medicaid", "abortion", "reproductive", "mental health"],
    "Labor & Employment":   ["minimum wage", "labor", "worker", "union", "employment"],
    "Education":            ["education", "school", "curriculum", "student", "teacher"],
    "Surveillance & Privacy":["surveillance", "facial recognition", "biometric", "privacy", "data"],
    "Technology & AI":      ["artificial intelligence", "algorithm", "deepfake", "automated"],
    "Immigration":          ["immigration", "immigrant", "asylum", "deportation", "border"],
    "Financial":            ["predatory lending", "payday loan", "debt", "financial fraud", "banking"],
    "Pre-emption":          ["preempt", "pre-empt", "nullify", "supersede", "override local"],
    "LGBTQ+ Rights":        ["lgbtq", "transgender", "gender", "sexual orientation", "same-sex"],
    "Disability Rights":    ["disability", "ada", "accessibility", "accommodation"],
    "Voting Access":        ["voter suppression", "gerrymandering", "redistricting", "purge"],
}

LEGISLATIVE_SOURCES = {
    "congress", "govtrack", "openstates",
    "ny_ag", "ca_ag", "tx_ag", "fl_ag", "wa_ag", "il_ag",
    "ma_ag", "co_ag", "nj_ag", "pa_ag", "oh_ag", "mi_ag",
}

PREEMPTION_KEYWORDS = [
    "preempt", "pre-empt", "nullify", "void", "supersede",
    "prohibit local", "prevent municipality", "override city",
    "state shall preempt", "local government may not",
]


def _text_for_bill(bill: dict) -> str:
    return " ".join(filter(None, [
        bill.get("case_name", ""),
        bill.get("summary", ""),
        bill.get("allegations", ""),
        bill.get("status", ""),
    ])).lower()


def _classify_topics(text: str) -> list[str]:
    found = []
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            found.append(topic)
    return found


def get_legislative_bills(days_back: int = 365) -> list[dict]:
    """Fetch all legislative bills from the DB within the lookback window."""
    cutoff = (datetime.now() - timedelta(days=days_back)).strftime("%Y-%m-%d")
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT * FROM cases
               WHERE (case_type LIKE '%legislat%'
                   OR case_type LIKE '%bill%'
                   OR case_type LIKE '%vote%'
                   OR source IN ('congress','govtrack','openstates'))
               AND (filing_date >= ? OR filing_date = '')
               ORDER BY filing_date DESC
               LIMIT 10000""",
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]


# ── Trend analysis ─────────────────────────────────────────────────────────────

def topic_trends(days_back: int = 365) -> dict:
    """
    Count bills per topic per month.
    Returns: {topic: {YYYY-MM: count}}
    """
    bills  = get_legislative_bills(days_back)
    trends: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for bill in bills:
        text    = _text_for_bill(bill)
        topics  = _classify_topics(text)
        date    = bill.get("filing_date", "")[:7]  # YYYY-MM
        if not date:
            continue
        for topic in topics:
            trends[topic][date] += 1

    return {t: dict(sorted(m.items())) for t, m in trends.items()}


def geographic_spread(days_back: int = 90) -> dict:
    """
    For each topic, which states have active bills?
    Returns: {topic: {state: count}}
    """
    bills = get_legislative_bills(days_back)
    spread: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))

    for bill in bills:
        text  = _text_for_bill(bill)
        state = bill.get("jurisdiction", "") or bill.get("court", "")
        if not state or state in ("Federal", "National", "Academic"):
            continue
        for topic in _classify_topics(text):
            spread[topic][state] += 1

    return {t: dict(sorted(s.items(), key=lambda x: -x[1])) for t, s in spread.items()}


# ── Wave detection ─────────────────────────────────────────────────────────────

def detect_waves(days_back: int = 90, min_states: int = 3) -> list[dict]:
    """
    Detect coordinated legislative waves: same topic appearing in 3+ states
    within the lookback window.

    Returns list of wave dicts sorted by number of states affected.
    """
    bills = get_legislative_bills(days_back)
    topic_state_bills: dict[str, dict[str, list]] = defaultdict(lambda: defaultdict(list))

    for bill in bills:
        text  = _text_for_bill(bill)
        state = bill.get("jurisdiction", "") or ""
        if not state or state in ("Federal", "National", "Academic", ""):
            continue
        for topic in _classify_topics(text):
            topic_state_bills[topic][state].append(bill)

    waves = []
    for topic, state_map in topic_state_bills.items():
        if len(state_map) >= min_states:
            total_bills = sum(len(v) for v in state_map.values())
            states = sorted(state_map.keys())
            # Sample bills across states for display
            sample = []
            for bills_in_state in list(state_map.values())[:3]:
                if bills_in_state:
                    sample.append(bills_in_state[0])
            waves.append({
                "topic":        topic,
                "states":       states,
                "state_count":  len(states),
                "total_bills":  total_bills,
                "sample_bills": sample,
                "severity":     "HIGH" if len(states) >= 8 else "MEDIUM" if len(states) >= 5 else "WATCH",
            })

    return sorted(waves, key=lambda x: -x["state_count"])


# ── Pre-emption tracker ────────────────────────────────────────────────────────

def detect_preemption_bills(days_back: int = 180) -> list[dict]:
    """
    Identify bills that pre-empt local government authority.
    These are often the most dangerous for communities.
    """
    bills = get_legislative_bills(days_back)
    preemption = []

    for bill in bills:
        text = _text_for_bill(bill)
        if any(kw in text for kw in PREEMPTION_KEYWORDS):
            topics  = _classify_topics(text)
            state   = bill.get("jurisdiction", "") or ""
            preemption.append({
                "case_name":   bill.get("case_name", ""),
                "state":       state,
                "filing_date": bill.get("filing_date", ""),
                "status":      bill.get("status", ""),
                "topics":      topics,
                "document_url":bill.get("document_url", ""),
                "summary":     bill.get("summary", "")[:200],
                "source_id":   bill.get("id", ""),
            })

    return sorted(preemption, key=lambda x: x.get("filing_date",""), reverse=True)


# ── Velocity (fast-advancing bills) ───────────────────────────────────────────

def fast_advancing_bills(days_back: int = 30) -> list[dict]:
    """
    Bills whose status has changed to committee, floor, or passed within
    the last 30 days — indicating fast movement that requires rapid response.
    """
    advancing_keywords = [
        "committee", "passed", "signed", "enacted", "floor vote",
        "third reading", "concurred", "chaptered", "approved",
    ]
    bills = get_legislative_bills(days_back)
    fast = []

    for bill in bills:
        status = (bill.get("status", "") or "").lower()
        if any(kw in status for kw in advancing_keywords):
            fast.append({
                "case_name":    bill.get("case_name", ""),
                "state":        bill.get("jurisdiction", ""),
                "status":       bill.get("status", ""),
                "filing_date":  bill.get("filing_date", ""),
                "topics":       _classify_topics(_text_for_bill(bill)),
                "document_url": bill.get("document_url", ""),
                "source_id":    bill.get("id", ""),
            })

    return sorted(fast, key=lambda x: x.get("filing_date",""), reverse=True)[:50]


# ── Similarity detection (coordinated model legislation) ──────────────────────

def find_similar_bills(min_similarity: float = 0.6) -> list[dict]:
    """
    Find bills with very similar titles/summaries across different states.
    High similarity = likely model legislation from a single source.
    """
    bills = [b for b in get_legislative_bills(180)
             if b.get("jurisdiction") not in ("Federal", "National", "")]

    # Simple token overlap similarity
    def tokens(text: str) -> set:
        return set(re.sub(r"[^a-z\s]", "", text.lower()).split()) - {
            "the","a","an","of","in","to","and","or","for","that","this",
            "with","be","is","are","was","were","will","shall","may","act",
            "bill","state","local","government","law","section","any","all",
        }

    def similarity(a: str, b: str) -> float:
        ta, tb = tokens(a), tokens(b)
        if not ta or not tb:
            return 0.0
        return len(ta & tb) / len(ta | tb)

    clusters = []
    matched  = set()

    for i, bill_a in enumerate(bills):
        if bill_a["id"] in matched:
            continue
        text_a  = bill_a.get("case_name","") + " " + bill_a.get("summary","")
        group   = [bill_a]
        states  = {bill_a.get("jurisdiction","")}

        for j, bill_b in enumerate(bills):
            if i == j or bill_b["id"] in matched:
                continue
            if bill_b.get("jurisdiction","") == bill_a.get("jurisdiction",""):
                continue  # skip same state
            text_b = bill_b.get("case_name","") + " " + bill_b.get("summary","")
            if similarity(text_a, text_b) >= min_similarity:
                group.append(bill_b)
                states.add(bill_b.get("jurisdiction",""))

        if len(group) >= 2 and len(states) >= 2:
            for b in group:
                matched.add(b["id"])
            clusters.append({
                "lead_bill":   bill_a.get("case_name","")[:120],
                "states":      sorted(states),
                "state_count": len(states),
                "bill_count":  len(group),
                "topics":      _classify_topics(_text_for_bill(bill_a)),
                "bills":       group[:6],
                "warning":     "Possible model legislation — similar text in multiple states",
            })

    return sorted(clusters, key=lambda x: -x["state_count"])[:20]
