"""
Documentation Sub-Agent

Synthesizes raw research findings from court and web researchers into
a structured CaseIntelReport. Covers ALL case types — no AI restriction.
"""

import json
from typing import Optional

import anthropic

from models.case_report import CaseIntelReport, SearchFilters
from utils.retry import call_with_retry
from utils.json_extract import extract_json

DOCUMENTOR_SYSTEM = """You are a legal documentation specialist. Synthesize research findings
into a structured case intelligence report for ANY legal matter.

CRITICAL RULES:
1. You MUST return a JSON object — no exceptions, no prose, no markdown fences.
2. Even if findings are empty or the query is vague, return the JSON structure with
   empty findings array and a summary explaining what was found.
3. Start your response with { and end with }. Nothing before or after.
4. Use "other" for harm_types if the case doesn't fit standard categories.
5. Use "unknown" for severity if there is insufficient information.

Severity rubric:
  high    → loss > $1M, > 1000 victims, criminal conviction, or regulatory penalty imposed
  medium  → loss < $1M, < 1000 victims, active litigation or prosecution
  low     → allegations only, no documented figures, or case dismissed
  unknown → insufficient information

Return exactly this JSON structure:
{"query":"...","findings":[{"case_name":"...","jurisdiction":"...","court_name":"...","filing_date":"...","harm_types":["other"],"severity":"unknown","ai_actor":"...","victim_description":"...","deceptive_practice":"...","verifiable_harm":"...","legal_status":"...","protected_classes":[],"sources":[{"source_type":"court_filing","title":"...","url":"...","date":"...","excerpt":"..."}]}],"total_cases_found":0,"high_severity_count":0,"summary":"...","investigator_notes":"...","sources_searched":[]}"""


# Max chars of combined research to send — prevents token overflow
_MAX_RESEARCH_CHARS = 12_000


def run_documentor(
    query: str,
    court_findings: dict,
    web_findings: dict,
    filters: Optional["SearchFilters"] = None,
    client: Optional[anthropic.Anthropic] = None,
) -> CaseIntelReport:
    if client is None:
        api_key = __import__("os").environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key or not api_key.startswith("sk-"):
            raise ValueError("Anthropic API key not configured.")
        client = anthropic.Anthropic(api_key=api_key)

    # Truncate large research blobs to stay within token budget
    combined_raw = json.dumps(
        {"court_research": court_findings, "web_research": web_findings},
        indent=2,
    )
    if len(combined_raw) > _MAX_RESEARCH_CHARS:
        combined_raw = combined_raw[:_MAX_RESEARCH_CHARS] + "\n... [truncated for length]"

    # M-1: Wrap user query in XML delimiters to resist prompt injection.
    user_msg = (
        f"<user_query>\n{query}\n</user_query>\n\n"
        f"Research findings:\n{combined_raw}\n\n"
        "Synthesize into a CaseIntelReport JSON object. "
        "De-duplicate cases appearing in both sources. "
        "Return ONLY the JSON — no prose, no fences."
    )

    response = call_with_retry(
        lambda: client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=4096,
            system=[{
                "type": "text",
                "text": DOCUMENTOR_SYSTEM,
                "cache_control": {"type": "ephemeral"},
            }],
            messages=[{"role": "user", "content": user_msg}],
        ),
        label="documentor",
    )

    raw_text = ""
    for block in response.content:
        if block.type == "text" and block.text.strip():
            raw_text = block.text
            data = extract_json(block.text)
            # Claude occasionally wraps the dict in a list — unwrap it
            if isinstance(data, list) and data:
                data = data[0] if isinstance(data[0], dict) else None
            if isinstance(data, dict):
                try:
                    data["query"] = query
                    if filters:
                        data["filters_applied"] = filters.model_dump()
                    findings = data.get("findings", [])
                    data["total_cases_found"] = len(findings)
                    data["high_severity_count"] = sum(
                        1 for f in findings if f.get("severity") == "high"
                    )
                    return CaseIntelReport.model_validate(data)
                except Exception as e:
                    # Validation failed — return what we have with debug notes
                    return CaseIntelReport(
                        query=query,
                        summary=data.get("summary", "Report generated with validation warnings."),
                        investigator_notes=(
                            data.get("investigator_notes", "") +
                            f"\n\n[Validation note: {e}]"
                        ),
                        sources_searched=data.get("sources_searched", []),
                    )
            break  # had text but no JSON — fall through to fallback

    # Fallback: build a minimal report from raw researcher data directly
    court_cases  = court_findings.get("cases", [])
    web_findings_list = web_findings.get("findings", [])
    total = len(court_cases) + len(web_findings_list)

    summary = (
        f"Research found {len(court_cases)} court case(s) and "
        f"{len(web_findings_list)} web finding(s) for query: '{query}'. "
        "The documentation agent could not produce a structured report — "
        "raw findings are available in the investigator notes."
    )
    if raw_text:
        summary = f"Partial results for '{query}'. " + summary

    notes = "RAW COURT FINDINGS:\n"
    for c in court_cases[:5]:
        notes += f"• {c.get('case_name','?')} — {c.get('court','?')} ({c.get('filing_date','?')})\n"
    notes += "\nRAW WEB FINDINGS:\n"
    for w in web_findings_list[:5]:
        notes += f"• {w.get('title','?')} — {w.get('source_name','?')} ({w.get('date','?')})\n"
    if raw_text:
        notes += f"\nDOCUMENTOR RAW OUTPUT (first 800 chars):\n{raw_text[:800]}"

    return CaseIntelReport(
        query=query,
        total_cases_found=total,
        summary=summary,
        investigator_notes=notes,
        sources_searched=["court_researcher", "web_researcher"],
    )
