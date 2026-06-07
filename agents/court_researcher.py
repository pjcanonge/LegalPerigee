"""
Court Research Sub-Agent

Queries CourtListener and Descrybe Legal Engine for ALL case types —
civil, criminal, regulatory, constitutional, consumer, civil rights, and more.
No topic restrictions.
"""

import json
from typing import Optional

import anthropic

from tools.court_tools import COURT_TOOL_SCHEMAS, execute_court_tool
from utils.retry import call_with_retry
from utils.json_extract import extract_json

COURT_RESEARCHER_SYSTEM = """You are a specialist legal researcher covering ALL civil and criminal cases.

You handle every case type: fraud, consumer protection, civil rights, discrimination,
criminal, regulatory, contract, tort, constitutional, environmental, IP, and more.
No restrictions on topic or case type — follow the query wherever it leads.

Search CourtListener using 2-3 targeted queries with precise legal terms:
party names, statutes, nature of suit codes, cause of action codes.

CRITICAL: Your ENTIRE response must be a single raw JSON object — no prose, no markdown
fences, no explanation before or after. Start your response with { and end with }.

Output this exact structure:
{"cases":[{"case_name":"...","court":"...","docket_number":"...","filing_date":"...","parties":{"plaintiff":"...","defendant":"..."},"allegations":"...","harm_alleged":"...","legal_status":"...","source":"courtlistener","source_url":"..."}],"total_found":0,"search_queries_used":[],"coverage_notes":"..."}"""


def run_court_researcher(
    query: str,
    court_code: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    client: Optional[anthropic.Anthropic] = None,
) -> dict:
    """Run the court research sub-agent. Returns structured court findings."""
    if client is None:
        api_key = __import__("os").environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key or not api_key.startswith("sk-"):
            return {"cases": [], "total_found": 0, "error": "Anthropic API key not configured."}
        client = anthropic.Anthropic(api_key=api_key)

    filter_hint = ""
    if court_code:
        filter_hint += f"\nRestrict searches to court code: '{court_code}'."
    if date_from or date_to:
        filter_hint += f"\nDate range: filed_after={date_from or 'any'}, filed_before={date_to or 'any'}."

    # M-1: Wrap user query in XML delimiters to resist prompt injection.
    # The model sees the query as data, not instructions.
    messages = [
        {
            "role": "user",
            "content": (
                f"<user_query>\n{query}\n</user_query>\n"
                f"{filter_hint}\n\n"
                "Run 2 targeted CourtListener searches with max_results=5 each. "
                "Return the top 5 most relevant cases total as a compact JSON object. "
                "Be brief in each field — one sentence max per field."
            ),
        }
    ]

    tools = COURT_TOOL_SCHEMAS

    while True:
        response = call_with_retry(
            lambda: client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=8192,
                system=[
                    {
                        "type": "text",
                        "text": COURT_RESEARCHER_SYSTEM,
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                tools=tools,
                messages=messages,
            ),
            label="court_researcher",
        )

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason in ("end_turn", "stop_sequence", "max_tokens"):
            for block in response.content:
                if block.type == "text" and block.text.strip():
                    parsed = extract_json(block.text)
                    if parsed:
                        return parsed
                    return {"raw_response": block.text, "cases": [], "total_found": 0}
            return {"cases": [], "total_found": 0, "error": "No text in response"}

        if response.stop_reason not in ("tool_use", "pause_turn"):
            break

        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                result = execute_court_tool(block.name, block.input)
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": result}
                )

        if tool_results:
            messages.append({"role": "user", "content": tool_results})

    return {"cases": [], "total_found": 0, "error": "Agent loop ended unexpectedly"}
