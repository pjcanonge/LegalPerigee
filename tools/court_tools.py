"""
Court research tool wrappers.

CourtListener — implemented via direct REST API calls to courtlistener.com/api/rest/v4/
(the public API that the CourtListener MCP server wraps). No API key required for reads.

Descrybe Legal Engine — implemented via the Anthropic SDK `mcp_servers` parameter.
Set DESCRYBE_MCP_URL in your .env to enable. When unset, Descrybe searches are skipped
and the agent works CourtListener-only.

  DESCRYBE_MCP_URL=https://<your-descrybe-mcp-endpoint>

The Descrybe MCP server is also available inside Claude Code sessions via MCP id
97977779-aa48-4ab7-96eb-13e0171b9ad3 — contact Descrybe for the self-hosted URL.
"""

import json
import os
from typing import Optional

import httpx

# ---------------------------------------------------------------------------
# CourtListener REST API
# ---------------------------------------------------------------------------

_CL_BASE = "https://www.courtlistener.com/api/rest/v4"
_CL_TIMEOUT = 20


def _cl_headers() -> dict:
    """Build request headers fresh on every call so tokens set after import are picked up."""
    headers = {
        "User-Agent": "LegalPerigee/1.0 (legal research; contact admin@legalperigee.ai)",
    }
    token = os.getenv("COURTLISTENER_API_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Token {token}"
    return headers


def _cl_get(path: str, params: dict) -> dict:
    """Make a GET request to the CourtListener REST API."""
    url = f"{_CL_BASE}{path}"
    with httpx.Client(timeout=_CL_TIMEOUT, headers=_cl_headers()) as client:
        resp = client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


def search_courtlistener(
    query: str,
    max_results: int = 10,
    court: Optional[str] = None,
    filed_after: Optional[str] = None,
    filed_before: Optional[str] = None,
    nature_of_suit: Optional[str] = None,
) -> str:
    """
    Search CourtListener opinions and dockets.

    Args:
        query: Full-text search query
        max_results: Max results per search type (capped at 20)
        court: CourtListener court code, e.g. 'ca9', 'nysd', 'scotus'
        filed_after: ISO date string YYYY-MM-DD
        filed_before: ISO date string YYYY-MM-DD
        nature_of_suit: Nature of suit filter (dockets only)
    """
    max_results = min(max_results, 20)
    results = []

    def _base_params(search_type: str) -> dict:
        p: dict = {"q": query, "type": search_type, "order_by": "score desc", "format": "json"}
        if court:
            p["court"] = court
        if filed_after:
            p["filed_after"] = filed_after
        if filed_before:
            p["filed_before"] = filed_before
        return p

    # Search opinions
    try:
        data = _cl_get("/search/", _base_params("o"))
        for hit in data.get("results", [])[:max_results]:
            results.append({
                "type": "opinion",
                "case_name": hit.get("caseName") or hit.get("case_name", ""),
                "court": hit.get("court", ""),
                "date_filed": hit.get("dateFiled") or hit.get("date_filed", ""),
                "docket_number": hit.get("docketNumber") or hit.get("docket_number", ""),
                "citation": hit.get("citation", []),
                "snippet": hit.get("snippet", ""),
                "url": (
                    f"https://www.courtlistener.com{hit['absolute_url']}"
                    if hit.get("absolute_url") else None
                ),
                "cluster_id": hit.get("cluster_id"),
                "status": hit.get("status", ""),
            })
    except Exception as e:
        results.append({"error": f"Opinion search failed: {e}", "type": "opinion"})

    # Search dockets (PACER/RECAP)
    try:
        docket_params = _base_params("d")
        if nature_of_suit:
            docket_params["nature_of_suit"] = nature_of_suit
        data = _cl_get("/search/", docket_params)
        for hit in data.get("results", [])[:max_results]:
            results.append({
                "type": "docket",
                "case_name": hit.get("caseName") or hit.get("case_name", ""),
                "court": hit.get("court", ""),
                "date_filed": hit.get("dateFiled") or hit.get("date_filed", ""),
                "docket_number": hit.get("docketNumber") or hit.get("docket_number", ""),
                "cause": hit.get("cause", ""),
                "nature_of_suit": hit.get("suitNature") or hit.get("nature_of_suit", ""),
                "party_names": hit.get("party", []),
                "assigned_to": hit.get("assignedTo") or hit.get("assigned_to", ""),
                "url": (
                    f"https://www.courtlistener.com{hit['absolute_url']}"
                    if hit.get("absolute_url") else None
                ),
                "docket_id": hit.get("docket_id"),
            })
    except Exception as e:
        results.append({"error": f"Docket search failed: {e}", "type": "docket"})

    return json.dumps({
        "source": "courtlistener",
        "query": query,
        "filters": {
            "court": court,
            "filed_after": filed_after,
            "filed_before": filed_before,
            "nature_of_suit": nature_of_suit,
        },
        "total_found": len([r for r in results if "error" not in r]),
        "results": results,
    })


def get_case_details_courtlistener(docket_id: str) -> str:
    """
    Retrieve full docket details for a specific CourtListener docket by numeric ID.
    """
    try:
        data = _cl_get(f"/dockets/{docket_id}/", {"format": "json"})
        # Trim large nested lists to avoid blowing context
        for field in ("parties", "attorneys"):
            if isinstance(data.get(field), list) and len(data[field]) > 10:
                data[field] = data[field][:10]
        return json.dumps({
            "source": "courtlistener",
            "docket_id": docket_id,
            "data": data,
        })
    except httpx.HTTPStatusError as e:
        return json.dumps({"error": f"HTTP {e.response.status_code}", "docket_id": docket_id})
    except Exception as e:
        return json.dumps({"error": str(e), "docket_id": docket_id})


def analyze_citations(opinion_id: str) -> str:
    """
    Retrieve citation info for a CourtListener opinion cluster.

    Uses the clusters endpoint to get citing-document counts and related citations.
    """
    try:
        data = _cl_get(f"/clusters/{opinion_id}/", {"format": "json"})
        return json.dumps({
            "source": "courtlistener",
            "opinion_id": opinion_id,
            "case_name": data.get("case_name", ""),
            "date_filed": data.get("date_filed", ""),
            "citation_count": data.get("citation_count", 0),
            "citations": data.get("citations", []),
            "sub_opinions": data.get("sub_opinions", []),
            "url": f"https://www.courtlistener.com{data['absolute_url']}" if data.get("absolute_url") else None,
        })
    except httpx.HTTPStatusError as e:
        return json.dumps({"error": f"HTTP {e.response.status_code}", "opinion_id": opinion_id})
    except Exception as e:
        return json.dumps({"error": str(e), "opinion_id": opinion_id})


# ---------------------------------------------------------------------------
# Descrybe — MCP via Anthropic SDK mcp_servers parameter
# ---------------------------------------------------------------------------

# The Descrybe MCP is a cloud-hosted server. Set DESCRYBE_MCP_URL to enable.
# In Claude Code sessions it's also accessible as MCP id:
#   97977779-aa48-4ab7-96eb-13e0171b9ad3
DESCRYBE_MCP_URL: Optional[str] = os.getenv("DESCRYBE_MCP_URL")


def search_descrybe(query: str, max_results: int = 10) -> str:
    """
    Search Descrybe Legal Engine for authority-ranked U.S. case law by legal concept.

    When DESCRYBE_MCP_URL is set, makes a focused Claude API call with Descrybe
    configured as an mcp_server — Claude calls search_cases_by_concept directly
    and returns the results.

    When DESCRYBE_MCP_URL is unset, returns a clear notice so the orchestrator
    knows to rely on CourtListener only.
    """
    if not DESCRYBE_MCP_URL:
        return json.dumps({
            "source": "descrybe",
            "available": False,
            "message": (
                "Descrybe MCP not configured. Set DESCRYBE_MCP_URL in .env to enable. "
                "Falling back to CourtListener only."
            ),
            "query": query,
            "results": [],
        })

    # Make a single-turn Claude API call with Descrybe as an MCP server.
    # Claude calls search_cases_by_concept and returns structured results.
    import anthropic  # local import to avoid circular

    client = anthropic.Anthropic()
    try:
        response = client.beta.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=2048,
            betas=["mcp-client-2025-11-20"],
            mcp_servers=[
                {
                    "type": "url",
                    "name": "descrybe",
                    "url": DESCRYBE_MCP_URL,
                }
            ],
            system=(
                "You are a legal research tool. Search Descrybe for the given query "
                "using the search_cases_by_concept tool. Return ONLY a JSON object "
                "with a 'results' list. Each result should include: case_id, case_name, "
                "court, date, citation, summary, jurisdiction. No preamble."
            ),
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Search for: {query}\n"
                        f"Return up to {max_results} results as a JSON object."
                    ),
                }
            ],
        )
        raw = ""
        for block in response.content:
            if block.type == "text":
                raw = block.text.strip()
                break
        try:
            parsed = json.loads(raw)
            parsed["source"] = "descrybe"
            parsed["query"] = query
            parsed["available"] = True
            return json.dumps(parsed)
        except json.JSONDecodeError:
            return json.dumps({
                "source": "descrybe",
                "available": True,
                "query": query,
                "raw_response": raw,
                "results": [],
            })
    except Exception as e:
        return json.dumps({
            "source": "descrybe",
            "available": True,
            "error": str(e),
            "query": query,
            "results": [],
        })


# ---------------------------------------------------------------------------
# Tool schemas (unchanged — court_researcher.py uses these to define Claude tools)
# ---------------------------------------------------------------------------

COURT_TOOL_SCHEMAS = [
    {
        "name": "search_courtlistener",
        "description": (
            "Search CourtListener federal court database for opinions and PACER dockets. "
            "Supports filtering by court code, date range, and nature of suit. "
            "Returns case names, filing dates, court, docket numbers, and URLs."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Full-text search — keywords, party names, legal concepts, demographic terms",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Max results per search type (default 10, max 20)",
                    "default": 10,
                },
                "court": {
                    "type": "string",
                    "description": (
                        "CourtListener court code to restrict results. Examples: "
                        "scotus, ca1–ca11, cadc, cafc (circuits); "
                        "nysd, nyed, cand, casd, dcd, ilnd, txsd (district courts)"
                    ),
                },
                "filed_after": {
                    "type": "string",
                    "description": "Return cases filed on or after this date (YYYY-MM-DD)",
                },
                "filed_before": {
                    "type": "string",
                    "description": "Return cases filed on or before this date (YYYY-MM-DD)",
                },
                "nature_of_suit": {
                    "type": "string",
                    "description": "Nature of suit filter for dockets, e.g. 'Civil Rights', 'Employment', 'Fraud'",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "search_descrybe",
        "description": (
            "Search the Descrybe Legal Engine for authority-ranked U.S. case law by legal "
            "concept, citation, or fact pattern. Best for finding strong precedents, "
            "statutes, and regulations relevant to AI fraud and consumer protection. "
            "Requires DESCRYBE_MCP_URL to be configured — check results for 'available' field."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Legal concept, citation (e.g. '15 U.S.C. § 45'), or case name",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum results to return (default 10)",
                    "default": 10,
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_case_details_courtlistener",
        "description": (
            "Retrieve full docket details for a specific CourtListener case by numeric docket ID. "
            "Use after search_courtlistener returns a docket_id you want to explore further."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "docket_id": {
                    "type": "string",
                    "description": "CourtListener numeric docket ID (from search results)",
                },
            },
            "required": ["docket_id"],
        },
    },
    {
        "name": "analyze_citations",
        "description": (
            "Retrieve citation count and related citation data for a CourtListener opinion "
            "cluster. Use the cluster_id returned by search_courtlistener."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "opinion_id": {
                    "type": "string",
                    "description": "CourtListener opinion cluster ID",
                },
            },
            "required": ["opinion_id"],
        },
    },
]


def execute_court_tool(tool_name: str, tool_input: dict) -> str:
    """Dispatch a court tool call by name."""
    dispatch = {
        "search_courtlistener": lambda i: search_courtlistener(
            i["query"],
            max_results=i.get("max_results", 10),
            court=i.get("court"),
            filed_after=i.get("filed_after"),
            filed_before=i.get("filed_before"),
            nature_of_suit=i.get("nature_of_suit"),
        ),
        "search_descrybe": lambda i: search_descrybe(
            i["query"], i.get("max_results", 10)
        ),
        "get_case_details_courtlistener": lambda i: get_case_details_courtlistener(
            i["docket_id"]
        ),
        "analyze_citations": lambda i: analyze_citations(i["opinion_id"]),
    }
    fn = dispatch.get(tool_name)
    if fn is None:
        return json.dumps({"error": f"Unknown court tool: {tool_name}"})
    return fn(tool_input)
