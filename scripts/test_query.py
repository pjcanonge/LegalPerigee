#!/usr/bin/env python3
"""Run a live end-to-end query test and print results."""
import os, sys, json, time, traceback
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

with open(os.path.join(os.path.dirname(os.path.dirname(__file__)), '.env')) as f:
    for line in f:
        line = line.strip()
        if line and not line.startswith('#') and '=' in line:
            k, _, v = line.partition('=')
            if v.strip(): os.environ[k.strip()] = v.strip()

import anthropic
client = anthropic.Anthropic(api_key=os.environ['ANTHROPIC_API_KEY'])

# 1. API ping
print("=== 1. API PING ===", flush=True)
try:
    r = client.messages.create(
        model="claude-haiku-4-5", max_tokens=10,
        messages=[{"role":"user","content":"Say OK"}]
    )
    print(f"  ✅ {r.content[0].text!r}", flush=True)
except Exception as e:
    print(f"  ❌ {e}", flush=True); sys.exit(1)

# 2. CourtListener direct
print("\n=== 2. COURTLISTENER DIRECT ===", flush=True)
try:
    import httpx
    from tools.court_tools import _cl_headers
    resp = httpx.get(
        "https://www.courtlistener.com/api/rest/v4/search/",
        params={"q":"AI fraud discrimination","type":"o","order_by":"score desc","format":"json"},
        headers=_cl_headers(), timeout=15
    )
    data = resp.json()
    count = len(data.get("results", []))
    print(f"  HTTP {resp.status_code} — {count} results", flush=True)
    if count:
        hit = data["results"][0]
        print(f"  First: {hit.get('caseName','?')[:70]}", flush=True)
        print(f"  Court: {hit.get('court','?')}  Date: {hit.get('dateFiled','?')}", flush=True)
except Exception as e:
    print(f"  ❌ {e}", flush=True)

# 3. Court researcher
print("\n=== 3. COURT RESEARCHER ===", flush=True)
try:
    from agents.court_researcher import run_court_researcher
    r = run_court_researcher("FTC artificial intelligence consumer fraud", client=client)
    print(f"  total_found={r.get('total_found',0)}  cases={len(r.get('cases',[]))}", flush=True)
    if r.get('error'):      print(f"  error: {r['error']}", flush=True)
    if r.get('raw_response'): print(f"  raw (300): {r['raw_response'][:300]}", flush=True)
    for i, c in enumerate(r.get('cases',[])[:2],1):
        print(f"  Case {i}: {c.get('case_name','?')[:60]}", flush=True)
    if r.get('search_queries_used'):
        print(f"  Queries used: {r['search_queries_used']}", flush=True)
except Exception as e:
    print(f"  ❌ {e}", flush=True); traceback.print_exc()

print("\nPausing 8s...", flush=True)
time.sleep(8)

# 4. Web researcher
print("\n=== 4. WEB RESEARCHER ===", flush=True)
try:
    from agents.web_researcher import run_web_researcher
    r = run_web_researcher("FTC enforcement AI fraud 2024", client=client)
    print(f"  total_found={r.get('total_found',0)}  findings={len(r.get('findings',[]))}", flush=True)
    if r.get('error'):      print(f"  error: {r['error']}", flush=True)
    if r.get('raw_response'): print(f"  raw (300): {r['raw_response'][:300]}", flush=True)
    for i, f in enumerate(r.get('findings',[])[:2],1):
        print(f"  Finding {i}: {f.get('title','?')[:60]}", flush=True)
except Exception as e:
    print(f"  ❌ {e}", flush=True); traceback.print_exc()

print("\n=== DONE ===", flush=True)
