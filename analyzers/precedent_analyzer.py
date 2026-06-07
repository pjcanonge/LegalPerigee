"""
Precedent Comparison Engine

Searches for historical cases and compares them with recent ones to
identify legal precedent, track how standards have evolved, and build
citation chains across judicial eras.

Uses:
  - CourtListener REST API (citations, case clusters)
  - Harvard Caselaw Access Project (historical cases back to 1600s)
  - Claude AI for precedent analysis and legal evolution assessment
"""

import json
import os
import time
from typing import Optional

import httpx

from utils.json_extract import extract_json
from utils.retry import call_with_retry

CL_BASE = "https://www.courtlistener.com/api/rest/v4"
CAP_BASE = "https://api.case.law/v1"
CL_TOKEN = os.getenv("COURTLISTENER_API_TOKEN", "")

CL_HEADERS = {"User-Agent": "LegalPerigee/1.0 (legal research)"}
if CL_TOKEN:
    CL_HEADERS["Authorization"] = f"Token {CL_TOKEN}"

CAP_HEADERS = {"User-Agent": "LegalPerigee/1.0 (legal research)"}
if os.getenv("HARVARD_CAP_TOKEN"):
    CAP_HEADERS["Authorization"] = f"Token {os.getenv('HARVARD_CAP_TOKEN')}"


# ── Case search ───────────────────────────────────────────────────────────────

def search_cases_cl(
    query: str,
    court: Optional[str] = None,
    date_min: Optional[str] = None,
    date_max: Optional[str] = None,
    max_results: int = 10,
) -> list[dict]:
    """Search CourtListener opinions. Returns simplified case dicts."""
    params: dict = {
        "q": query,
        "type": "o",
        "order_by": "score desc",
        "format": "json",
    }
    if court:     params["court"] = court
    if date_min:  params["filed_after"]  = date_min
    if date_max:  params["filed_before"] = date_max

    try:
        r = httpx.get(f"{CL_BASE}/search/", headers=CL_HEADERS,
                      params=params, timeout=20)
        r.raise_for_status()
        results = []
        for hit in r.json().get("results", [])[:max_results]:
            results.append({
                "id":           hit.get("id") or hit.get("cluster_id", ""),
                "case_name":    hit.get("caseName") or hit.get("case_name", ""),
                "court":        hit.get("court", ""),
                "date_decided": hit.get("dateFiled") or hit.get("date_filed", ""),
                "docket_number":hit.get("docketNumber") or "",
                "citation":     hit.get("citation", []),
                "snippet":      hit.get("snippet", "")[:400],
                "url":          f"https://www.courtlistener.com{hit['absolute_url']}"
                                if hit.get("absolute_url") else "",
                "source":       "courtlistener",
            })
        return results
    except Exception:
        return []


def search_cases_cap(
    query: str,
    jurisdiction: Optional[str] = None,
    date_min: Optional[str] = None,
    date_max: Optional[str] = None,
    max_results: int = 10,
) -> list[dict]:
    """
    Harvard Caselaw Access Project — NOTE: Public API retired June 2024.
    Falls back to CourtListener for historical cases.
    """
    # Harvard CAP API was retired — redirect to CourtListener for historical coverage
    return search_cases_cl(query, date_min=date_min, date_max=date_max,
                           max_results=max_results)


def get_citing_cases(cluster_id: str, max_results: int = 20) -> list[dict]:
    """Find cases that CITE a given CourtListener cluster (precedent followers)."""
    try:
        r = httpx.get(
            f"{CL_BASE}/search/",
            headers=CL_HEADERS,
            params={"q": f"cites:{cluster_id}", "type": "o",
                    "order_by": "score desc", "format": "json"},
            timeout=20,
        )
        r.raise_for_status()
        results = []
        for hit in r.json().get("results", [])[:max_results]:
            results.append({
                "case_name":    hit.get("caseName",""),
                "court":        hit.get("court",""),
                "date_decided": hit.get("dateFiled",""),
                "url":          f"https://www.courtlistener.com{hit['absolute_url']}"
                                if hit.get("absolute_url") else "",
            })
        return results
    except Exception:
        return []


def get_cited_cases(cluster_id: str, max_results: int = 20) -> list[dict]:
    """Find cases that a given case CITES (its own precedents)."""
    try:
        r = httpx.get(f"{CL_BASE}/clusters/{cluster_id}/",
                      headers=CL_HEADERS, params={"format": "json"}, timeout=20)
        r.raise_for_status()
        data = r.json()
        # sub_opinions → opinions → citations
        sub_opinions = data.get("sub_opinions", [])
        cited = []
        for op_url in sub_opinions[:3]:
            try:
                op_r = httpx.get(op_url, headers=CL_HEADERS, timeout=15)
                op_data = op_r.json()
                for cite in op_data.get("opinions_cited", [])[:max_results]:
                    cited.append({
                        "case_name": cite.get("case_name",""),
                        "url":       cite.get("absolute_url",""),
                    })
            except Exception:
                pass
        return cited[:max_results]
    except Exception:
        return []


# ── AI comparison ──────────────────────────────────────────────────────────────

COMPARISON_PROMPT = """You are an expert appellate attorney specializing in legal precedent analysis.

Compare these two cases and analyze the legal precedent relationship between them.

CASE A (the reference case):
{case_a}

CASE B (the comparison case):
{case_b}

Analyze thoroughly and return ONLY this JSON object (no prose, no fences):
{{
  "legal_issue": "The core legal question both cases address",
  "case_a_holding": "What Case A decided and the standard it applied",
  "case_b_holding": "What Case B decided and the standard it applied",
  "case_a_era": "Legal/historical context of Case A",
  "case_b_era": "Legal/historical context of Case B",
  "similarities": ["key similarities between the cases"],
  "differences": ["key distinctions — facts, law, outcome, standard"],
  "precedent_relationship": "controlling | persuasive | distinguished | overruled | parallel | unrelated",
  "precedent_explanation": "How Case A relates to Case B as precedent",
  "legal_evolution": "How the law changed or developed between these two cases",
  "key_shift": "The single most important legal shift between the cases (1-2 sentences)",
  "strategic_notes": "How an attorney could use this precedent comparison in argument",
  "citation_value": "HIGH | MEDIUM | LOW | NONE — how useful is citing Case A when arguing Case B's issue"
}}"""

EVOLUTION_PROMPT = """You are an expert legal historian and appellate attorney.

Analyze how courts have ruled on this legal topic across these cases from different eras.
Identify the arc of legal evolution — how standards changed, what drove the changes,
and where the law currently stands.

Topic: {topic}

Cases (chronological order):
{cases}

Return ONLY this JSON object (no prose, no fences):
{{
  "topic": "{topic}",
  "legal_arc_summary": "2-3 sentence overview of how this area of law evolved",
  "key_turning_points": [
    {{
      "case_name": "...",
      "year": "...",
      "shift": "What changed at this point in the law"
    }}
  ],
  "current_standard": "Where the law stands today based on most recent cases",
  "trajectory": "expanding | contracting | stable | contested | fragmented",
  "trajectory_explanation": "Why the law is moving in this direction",
  "practical_implications": "What this evolution means for current cases",
  "notable_tensions": "Any circuit splits or unresolved conflicts",
  "investigator_notes": "Strategic observations for litigators"
}}"""


DISCOVERY_PROMPT = """You are an expert appellate attorney and legal researcher.

A user has described a legal situation. Your job is to:
1. Identify the core legal issues involved
2. Generate precise search queries to find relevant historical precedents
3. Suggest the eras and jurisdictions most likely to have controlling precedent

Situation described by the user:
---
{situation}
---

Return ONLY this JSON object (no prose, no fences):
{{
  "core_legal_issues": ["list of the specific legal issues present"],
  "primary_legal_area": "the main area of law (e.g. Fourth Amendment, Title VII, ECOA)",
  "search_queries": [
    {{
      "query": "precise search terms for CourtListener/Harvard CAP",
      "era": "e.g. 1950-1980 landmark, 1990-2010, recent 2010-present, or all eras",
      "why": "what precedent this query is targeting"
    }}
  ],
  "landmark_cases_to_check": ["case names to search for directly, if you know them"],
  "key_statutes": ["relevant statutes (e.g. 42 U.S.C. § 1983, Title VII)"],
  "investigator_note": "what kind of precedent would be most useful here"
}}"""

RANKING_PROMPT = """You are an expert appellate attorney reviewing a list of cases
to find the most relevant precedents for a specific legal situation.

Legal situation:
---
{situation}
---

Core legal issues: {issues}

Cases found (search results):
---
{cases}
---

Review these cases and return ONLY this JSON array (no prose, no fences).
Include only the cases that are genuinely relevant — skip obviously irrelevant ones:
[
  {{
    "case_name": "exact case name",
    "date_decided": "YYYY or YYYY-MM-DD",
    "court": "court name",
    "url": "url if available",
    "relevance_score": 1-10,
    "relevance_explanation": "exactly why this case matters for the situation described",
    "legal_principle": "the key legal principle this case established",
    "how_to_use": "how an attorney would use this case — supporting or distinguishing",
    "era": "landmark | foundational | recent | current",
    "source": "courtlistener or harvard_cap"
  }}
]"""


def discover_precedents(
    situation: str,
    client=None,
    max_cases_per_query: int = 8,
) -> dict:
    """
    Given a plain-English description of a legal situation, automatically
    find and rank the most relevant historical precedents.

    This is the entry point for users who don't know what cases to search for.

    Returns a dict with:
      - core_legal_issues
      - search_queries used
      - ranked_precedents (list of relevant cases with explanations)
      - investigator_note
    """
    if client is None:
        import anthropic as _ant, os as _os
        _api_key = _os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not _api_key or not _api_key.startswith("sk-"):
            raise ValueError(
                "Anthropic API key not configured. "
                "Enter your key in the app sidebar to use AI features."
            )
        client = _ant.Anthropic(api_key=_api_key)

    # Step 1 — Claude identifies the legal issues and generates search queries
    disco_response = call_with_retry(
        lambda: client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=1024,
            messages=[{"role": "user",
                       "content": DISCOVERY_PROMPT.format(situation=situation)}],
        ),
        label="precedent_discovery",
    )

    plan = {}
    for block in disco_response.content:
        if block.type == "text":
            parsed = extract_json(block.text)
            # Must be a dict — Claude sometimes returns a list by mistake
            if isinstance(parsed, dict):
                plan = parsed
            elif isinstance(parsed, list) and parsed:
                # Unwrap if Claude wrapped the dict in a list
                plan = parsed[0] if isinstance(parsed[0], dict) else {}
            break

    if not plan:
        return {"error": "Could not analyze the legal situation — try rephrasing your description"}

    queries    = plan.get("search_queries", [])
    landmarks  = plan.get("landmark_cases_to_check", [])
    issues_str = ", ".join(plan.get("core_legal_issues", []))

    # Step 2 — Run the generated queries across both sources
    all_cases: list[dict] = []
    seen_names: set = set()

    for q_obj in queries[:3]:  # limit to 3 to stay within rate limits
        query = q_obj.get("query", "")
        era   = q_obj.get("era", "")
        if not query:
            continue

        # Parse era hints into date ranges
        date_min = date_max = None
        if era and "-" in era:
            parts = [p.strip() for p in era.split("-") if p.strip().isdigit()]
            if len(parts) >= 2:
                date_min, date_max = f"{parts[0]}-01-01", f"{parts[-1]}-12-31"

        # CourtListener (federal, recent)
        cl_results = search_cases_cl(query, date_min=date_min,
                                     date_max=date_max, max_results=max_cases_per_query)
        for c in cl_results:
            key = c.get("case_name","").lower()[:40]
            if key not in seen_names:
                seen_names.add(key)
                all_cases.append(c)

        # Harvard CAP (broader historical)
        cap_results = search_cases_cap(query, date_min=date_min,
                                       date_max=date_max, max_results=max_cases_per_query)
        for c in cap_results:
            key = c.get("case_name","").lower()[:40]
            if key not in seen_names:
                seen_names.add(key)
                all_cases.append(c)

        time.sleep(0.2)

    # Also search for any landmark cases Claude named directly
    for lm_name in landmarks[:4]:
        lm_results = search_cases_cl(lm_name, max_results=2)
        if not lm_results:
            lm_results = search_cases_cap(lm_name, max_results=2)
        for c in lm_results:
            key = c.get("case_name","").lower()[:40]
            if key not in seen_names:
                seen_names.add(key)
                all_cases.append(c)

    if not all_cases:
        return {
            "error": "No cases found. Try with different terms.",
            "plan": plan,
        }

    # Step 3 — Claude ranks and explains relevance
    cases_text = "\n".join([
        f"{i+1}. {c.get('case_name','')} | {c.get('date_decided','?')[:4]} | "
        f"{c.get('court','')} | {c.get('snippet','')[:150]} | {c.get('url','')}"
        for i, c in enumerate(all_cases[:30])
    ])

    rank_response = call_with_retry(
        lambda: client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=3000,
            messages=[{"role": "user",
                       "content": RANKING_PROMPT.format(
                           situation=situation,
                           issues=issues_str,
                           cases=cases_text,
                       )}],
        ),
        label="precedent_ranking",
    )

    ranked = []
    for block in rank_response.content:
        if block.type == "text":
            result = extract_json(block.text)
            if isinstance(result, list):
                # Filter to only dicts — Claude occasionally mixes types
                ranked = [r for r in result if isinstance(r, dict)]
            elif isinstance(result, dict) and result.get("cases"):
                # Sometimes Claude wraps the list in {"cases": [...]}
                ranked = [r for r in result["cases"] if isinstance(r, dict)]
            break

    # Fallback: if ranking failed, build basic entries from raw search results
    if not ranked and all_cases:
        ranked = [
            {
                "case_name":            c.get("case_name",""),
                "date_decided":         c.get("date_decided",""),
                "court":                c.get("court",""),
                "url":                  c.get("url",""),
                "relevance_score":      5,
                "relevance_explanation":"Returned by legal search — review manually",
                "legal_principle":      "",
                "how_to_use":           "",
                "era":                  "unknown",
                "source":               c.get("source",""),
            }
            for c in all_cases[:10]
        ]

    # Merge URL/source back from original search results
    case_lookup = {c.get("case_name","").lower()[:40]: c for c in all_cases}
    for r in ranked:
        key = r.get("case_name","").lower()[:40]
        if key in case_lookup and not r.get("url"):
            r["url"] = case_lookup[key].get("url","")
        if not r.get("source"):
            r["source"] = case_lookup.get(key, {}).get("source","")

    # Sort by relevance score
    ranked.sort(key=lambda x: -int(x.get("relevance_score", 0)))

    return {
        "situation":       situation,
        "core_legal_issues": plan.get("core_legal_issues", []),
        "primary_legal_area": plan.get("primary_legal_area",""),
        "key_statutes":    plan.get("key_statutes", []),
        "investigator_note": plan.get("investigator_note",""),
        "search_queries":  [q.get("query","") for q in queries],
        "total_searched":  len(all_cases),
        "ranked_precedents": ranked,
    }


def compare_cases(
    case_a: dict,
    case_b: dict,
    client=None,
) -> dict:
    """
    Use Claude to compare two cases for precedent relationship and legal evolution.

    Args:
        case_a: The older/reference case (dict with case_name, date_decided, snippet, etc.)
        case_b: The newer/comparison case
        client: Anthropic client

    Returns:
        Comparison analysis dict
    """
    if client is None:
        import anthropic as _ant, os as _os
        _api_key = _os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not _api_key or not _api_key.startswith("sk-"):
            raise ValueError(
                "Anthropic API key not configured. "
                "Enter your key in the app sidebar to use AI features."
            )
        client = _ant.Anthropic(api_key=_api_key)

    def _fmt(c: dict) -> str:
        return "\n".join(filter(None, [
            f"Name: {c.get('case_name','')}",
            f"Court: {c.get('court','')}",
            f"Date: {c.get('date_decided','')}",
            f"Citation: {', '.join(c.get('citation',[]) or [])}",
            f"Summary/Snippet: {c.get('snippet','') or c.get('summary','')}",
            f"URL: {c.get('url','')}",
        ]))

    prompt = COMPARISON_PROMPT.format(
        case_a=_fmt(case_a),
        case_b=_fmt(case_b),
    )

    try:
        response = call_with_retry(
            lambda: client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            ),
            label="precedent_comparison",
        )
        for block in response.content:
            if block.type == "text":
                result = extract_json(block.text)
                if result:
                    result["case_a"] = case_a
                    result["case_b"] = case_b
                    return result
    except Exception as e:
        return {"error": str(e)}
    return {"error": "Could not parse comparison response"}


def analyze_legal_evolution(
    topic: str,
    cases: list[dict],
    client=None,
) -> dict:
    """
    Analyze how a legal topic evolved across multiple cases spanning different eras.
    """
    if client is None:
        import anthropic as _ant, os as _os
        _api_key = _os.environ.get("ANTHROPIC_API_KEY", "").strip()
        if not _api_key or not _api_key.startswith("sk-"):
            raise ValueError(
                "Anthropic API key not configured. "
                "Enter your key in the app sidebar to use AI features."
            )
        client = _ant.Anthropic(api_key=_api_key)

    # Sort chronologically
    sorted_cases = sorted(
        [c for c in cases if c.get("date_decided")],
        key=lambda x: x.get("date_decided",""),
    )

    cases_text = "\n\n".join([
        f"{i+1}. {c.get('case_name','')} ({c.get('date_decided','?')[:4]}) "
        f"— {c.get('court','')}\n"
        f"   {c.get('snippet','') or c.get('summary','')[:200]}"
        for i, c in enumerate(sorted_cases[:12])
    ])

    if not cases_text.strip():
        return {"error": "No cases with dates available for evolution analysis"}

    prompt = EVOLUTION_PROMPT.format(topic=topic, cases=cases_text)

    try:
        response = call_with_retry(
            lambda: client.messages.create(
                model="claude-sonnet-4-6",
                max_tokens=2048,
                messages=[{"role": "user", "content": prompt}],
            ),
            label="legal_evolution",
        )
        for block in response.content:
            if block.type == "text":
                result = extract_json(block.text)
                if result:
                    result["cases_analyzed"] = len(sorted_cases)
                    result["date_range"] = (
                        f"{sorted_cases[0].get('date_decided','?')[:4]} – "
                        f"{sorted_cases[-1].get('date_decided','?')[:4]}"
                        if sorted_cases else "Unknown"
                    )
                    return result
    except Exception as e:
        return {"error": str(e)}
    return {"error": "Could not parse evolution response"}
