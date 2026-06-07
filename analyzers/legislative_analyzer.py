"""
AI-Powered Legislative Impact Analyzer

Uses Claude to analyze individual bills for:
  - Community impact (who is helped, who is harmed)
  - Protected class implications
  - Constitutional concerns
  - Historical precedents
  - Mobilization recommendations
  - Pre-emption scope
"""

import json
import os
from typing import Optional

import anthropic

from utils.json_extract import extract_json
from utils.retry import call_with_retry

ANALYSIS_PROMPT = """You are a civil rights attorney and legislative policy expert analyzing
a bill for its potential impact on communities — particularly vulnerable, historically
marginalized, or under-resourced populations.

Analyze this bill text thoroughly and return ONLY a JSON object (no prose, no fences):

Bill:
---
{bill_text}
---

Return this exact JSON structure:
{{
  "plain_english_summary": "2-3 sentence explanation anyone can understand",
  "who_benefits": ["list of groups or entities that benefit"],
  "who_is_harmed": ["list of communities or groups that could be harmed"],
  "protected_classes_affected": ["race", "gender", "disability", "etc — only if applicable"],
  "harm_severity": "CRITICAL | HIGH | MEDIUM | LOW | UNCLEAR",
  "harm_types": ["economic", "civil rights", "voting", "housing", "health", "environment", "other"],
  "is_preemption": true/false,
  "preemption_scope": "what local authority this removes (if applicable)",
  "constitutional_concerns": ["list any 1st, 14th amendment, voting rights concerns"],
  "historical_precedents": ["similar laws that passed and their outcomes"],
  "time_sensitivity": "URGENT (days) | HIGH (weeks) | MEDIUM (months) | LOW (already passed)",
  "mobilization_actions": [
    "specific, actionable steps communities can take right now"
  ],
  "contact_targets": ["who specifically to contact — committee chairs, sponsors, governor"],
  "investigator_notes": "key patterns, red flags, or strategic observations"
}}"""


def analyze_bill(
    bill: dict,
    client: Optional[anthropic.Anthropic] = None,
) -> dict:
    """
    Run AI impact analysis on a bill from the database.

    Args:
        bill: A row dict from the cases table
        client: Anthropic client (uses env key if not provided)

    Returns:
        Analysis dict
    """
    if client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return {"error": "No API key configured"}
        client = anthropic.Anthropic(api_key=api_key)

    # Build bill text from available fields
    bill_text = "\n".join(filter(None, [
        f"Title: {bill.get('case_name','')}",
        f"State/Jurisdiction: {bill.get('jurisdiction', bill.get('court',''))}",
        f"Date Introduced: {bill.get('filing_date','')}",
        f"Current Status: {bill.get('status','')}",
        f"Summary: {bill.get('summary','')}",
        f"Allegations/Subjects: {bill.get('allegations','')}",
        f"Sponsors: {bill.get('plaintiffs','')}",
    ]))

    if len(bill_text.strip()) < 30:
        return {"error": "Insufficient bill text for analysis"}

    try:
        response = call_with_retry(
            lambda: client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2048,
                system=[{
                    "type": "text",
                    "text": (
                        "You are a civil rights attorney specializing in legislative impact analysis. "
                        "You analyze bills for community harm with precision and objectivity. "
                        "Return ONLY valid JSON — no prose, no markdown fences."
                    ),
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{
                    "role": "user",
                    "content": ANALYSIS_PROMPT.format(bill_text=bill_text),
                }],
            ),
            label="bill_analysis",
        )

        for block in response.content:
            if block.type == "text":
                result = extract_json(block.text)
                if result:
                    result["bill_id"]   = bill.get("id", "")
                    result["bill_name"] = bill.get("case_name", "")
                    result["analyzed_at"] = __import__("datetime").datetime.utcnow().isoformat() + "Z"
                    return result

        return {"error": "Could not parse analysis response"}

    except Exception as e:
        return {"error": str(e)}


def batch_triage(
    bills: list[dict],
    client: Optional[anthropic.Anthropic] = None,
    max_bills: int = 10,
) -> list[dict]:
    """
    Triage a list of bills — do a fast severity assessment on many bills at once
    to identify which ones need full analysis.
    """
    if client is None:
        api_key = os.environ.get("ANTHROPIC_API_KEY", "")
        if not api_key:
            return []
        client = anthropic.Anthropic(api_key=api_key)

    if not bills:
        return []

    # Build a compact list for triage
    bill_list = "\n".join([
        f"{i+1}. [{b.get('jurisdiction','')}] {b.get('case_name','')[:100]} | {b.get('status','')[:60]}"
        for i, b in enumerate(bills[:max_bills])
    ])

    triage_prompt = f"""You are a civil rights legislative triage analyst.

Review these {len(bills[:max_bills])} bills and quickly assess each for community harm potential.

Bills:
{bill_list}

Return ONLY a JSON array (no prose, no fences):
[
  {{
    "number": 1,
    "harm_severity": "CRITICAL | HIGH | MEDIUM | LOW",
    "one_line_concern": "brief reason for rating",
    "affected_communities": ["brief list"],
    "requires_immediate_action": true/false
  }}
]"""

    try:
        response = call_with_retry(
            lambda: client.messages.create(
                model="claude-haiku-4-5",
                max_tokens=2048,
                messages=[{"role": "user", "content": triage_prompt}],
            ),
            label="bill_triage",
        )
        for block in response.content:
            if block.type == "text":
                result = extract_json(block.text)
                if isinstance(result, list):
                    # Attach back to original bills
                    for item in result:
                        idx = item.get("number", 1) - 1
                        if 0 <= idx < len(bills):
                            bills[idx]["_triage"] = item
                    return bills[:max_bills]
    except Exception:
        pass

    return bills[:max_bills]
