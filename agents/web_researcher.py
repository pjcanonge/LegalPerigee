"""
Web Research Sub-Agent

Searches news archives, legal blogs, and regulatory press releases for
ALL case types — fraud, civil rights, criminal, consumer harm, regulatory
enforcement, and more. No topic restrictions.
"""

import json
from typing import Optional

import anthropic

from tools.search_tools import WEB_SCRAPE_TOOL_SCHEMA, execute_search_tool
from utils.retry import call_with_retry
from utils.json_extract import extract_json

WEB_RESEARCHER_SYSTEM = """You are an investigative legal researcher covering ALL civil and criminal cases.

You cover every case type: fraud, consumer harm, civil rights, discrimination, criminal,
regulatory enforcement, environmental, medical malpractice, product liability, and more.
No topic restrictions — follow the query wherever it leads.

Priority sources: FTC, SEC, CFPB, DOJ, EEOC, HUD, State AGs, Reuters Legal, Law360,
Bloomberg Law, court press releases, legal news archives. Documented facts only — no rumors.

CRITICAL: Your ENTIRE response must be a single raw JSON object — no prose, no markdown
fences, no explanation. Start with { and end with }.

Output this exact structure:
{"findings":[{"title":"...","source_name":"FTC|SEC|DOJ|news|blog","source_url":"...","date":"...","actor":"...","victim_description":"...","practice_alleged":"...","verifiable_harm":"...","status":"...","excerpt":"..."}],"total_found":0,"sources_searched":[],"coverage_notes":"..."}"""


def run_web_researcher(
    query: str,
    client: Optional[anthropic.Anthropic] = None,
) -> dict:
    """Run the web research sub-agent. Returns structured web findings."""
    if client is None:
        api_key = __import__("os").environ.get("ANTHROPIC_API_KEY", "").strip()
        if not api_key or not api_key.startswith("sk-"):
            return {"results": [], "total_found": 0, "error": "Anthropic API key not configured."}
        client = anthropic.Anthropic(api_key=api_key)

    # M-1: Wrap user query in XML delimiters to resist prompt injection.
    messages = [
        {
            "role": "user",
            "content": (
                f"<user_query>\n{query}\n</user_query>\n\n"
                "Search the web for court cases, enforcement actions, news reports, "
                "and regulatory actions related to this query. "
                "Cover 2-3 different angles. Search for any legal matter — "
                "do NOT restrict to AI or technology cases. "
                "Use FTC, DOJ, SEC, CFPB, state AG sources when relevant. "
                "Return a JSON object with your findings."
            ),
        }
    ]

    tools = [
        {"type": "web_search_20260209", "name": "web_search"},
        WEB_SCRAPE_TOOL_SCHEMA,
    ]

    # Track container_id — web_search_20260209 uses code execution internally
    # for dynamic result filtering; the container_id must be passed on follow-up calls.
    container_id: Optional[str] = None

    while True:
        # Build kwargs fresh each iteration so container_id is current
        create_kwargs: dict = dict(
            model="claude-sonnet-4-6",
            max_tokens=8192,
            system=[
                {
                    "type": "text",
                    "text": WEB_RESEARCHER_SYSTEM,
                    "cache_control": {"type": "ephemeral"},
                }
            ],
            tools=tools,
            messages=messages,
        )
        if container_id:
            create_kwargs["container"] = container_id

        response = call_with_retry(
            lambda: client.messages.create(**create_kwargs),
            label="web_researcher",
        )

        # Capture container for code-execution continuations
        resp_container = getattr(response, "container", None)
        if resp_container and getattr(resp_container, "id", None):
            container_id = resp_container.id

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason in ("end_turn", "stop_sequence", "max_tokens"):
            for block in response.content:
                if block.type == "text" and block.text.strip():
                    parsed = extract_json(block.text)
                    if parsed:
                        return parsed
                    return {"raw_response": block.text, "findings": [], "total_found": 0}
            return {"findings": [], "total_found": 0, "error": "No text in response"}

        # pause_turn — server-side tool hit its iteration limit; re-send to continue
        if response.stop_reason == "pause_turn":
            continue

        if response.stop_reason != "tool_use":
            break

        # Execute client-side tools only (web_scrape); web_search runs server-side
        tool_results = []
        for block in response.content:
            if block.type == "tool_use" and block.name == "web_scrape":
                result = execute_search_tool(block.name, block.input)
                tool_results.append(
                    {"type": "tool_result", "tool_use_id": block.id, "content": result}
                )

        if tool_results:
            messages.append({"role": "user", "content": tool_results})

    return {"findings": [], "total_found": 0, "error": "Agent loop ended unexpectedly"}
