"""
Offline tests for the legislative fixes — no network required.

Covers the pure logic that the live-source bugs hid behind:
  - GovInfo BILLSTATUS XML parsing, keyword filter, row mapping
  - Congress.gov local title keyword filter (the /bill `query` is ignored upstream)
  - OpenStates no longer capping at the first 10 jurisdictions
"""

import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from aggregator import govinfo_fetch as gi
from aggregator import congress_fetch as cg


# A representative BILLSTATUS document (current GovInfo schema).
BILLSTATUS_XML = """<?xml version="1.0" encoding="UTF-8"?>
<billStatus>
  <bill>
    <number>1234</number>
    <type>HR</type>
    <congress>119</congress>
    <introducedDate>2026-01-15</introducedDate>
    <title>To protect voting rights and prohibit discrimination in elections.</title>
    <policyArea><name>Civil Rights and Liberties, Minority Issues</name></policyArea>
    <sponsors>
      <item><fullName>Rep. Doe, Jane [D-CA-1]</fullName><lastName>Doe</lastName></item>
    </sponsors>
    <latestAction>
      <actionDate>2026-02-01</actionDate>
      <text>Referred to the Committee on the Judiciary.</text>
    </latestAction>
    <summaries>
      <summary>
        <actionDate>2026-01-20</actionDate>
        <text><![CDATA[<p>This bill protects <b>voting rights</b> and bans discrimination.</p>]]></text>
      </summary>
    </summaries>
    <subjects>
      <legislativeSubjects>
        <item><name>Voting rights</name></item>
        <item><name>Civil rights</name></item>
      </legislativeSubjects>
    </subjects>
  </bill>
</billStatus>
"""

POST_OFFICE_XML = BILLSTATUS_XML.replace(
    "To protect voting rights and prohibit discrimination in elections.",
    "To designate a postal facility in Smalltown.",
).replace("<text><![CDATA[<p>This bill protects <b>voting rights</b> and bans discrimination.</p>]]></text>",
          "<text><![CDATA[<p>Names a post office.</p>]]></text>") \
 .replace("<item><name>Voting rights</name></item>", "<item><name>Postal service</name></item>") \
 .replace("<item><name>Civil rights</name></item>", "") \
 .replace("Civil Rights and Liberties, Minority Issues", "Government Operations and Politics")


def test_parse_billstatus_extracts_fields():
    p = gi.parse_billstatus_xml(BILLSTATUS_XML)
    assert p is not None
    assert p["number"] == "1234"
    assert p["type"] == "HR"
    assert p["congress"] == "119"
    assert p["introduced_date"] == "2026-01-15"
    assert "voting rights" in p["title"].lower()
    assert p["sponsor"].startswith("Rep. Doe")
    assert p["latest_action_text"].startswith("Referred")
    assert p["policy_area"].startswith("Civil Rights")
    assert "Voting rights" in p["subjects"]
    # Summary HTML is stripped to text.
    assert "voting rights" in p["summary"].lower()
    assert "<" not in p["summary"]


def test_parse_billstatus_bad_xml_returns_none():
    assert gi.parse_billstatus_xml("not xml <<<") is None
    assert gi.parse_billstatus_xml("<billStatus></billStatus>") is None  # no number/type


def test_bill_matches_keyword_filter():
    civil = gi.parse_billstatus_xml(BILLSTATUS_XML)
    postal = gi.parse_billstatus_xml(POST_OFFICE_XML)
    assert gi.bill_matches(civil) is True
    assert gi.bill_matches(postal) is False


def test_bill_to_row_mapping():
    row = gi.bill_to_row(gi.parse_billstatus_xml(BILLSTATUS_XML))
    assert row["id"] == "govinfo_119_hr1234"
    assert row["source"] == "govinfo"
    assert row["case_type"] == "Federal Legislation"
    assert row["court"] == "U.S. Congress — House"
    assert row["jurisdiction"] == "Federal"
    assert "Voting rights" in row["allegations"]
    assert "congress.gov/bill/119th-congress/house-bill/1234" in row["document_url"]


def test_billnum_sort_key():
    assert gi._billnum("BILLSTATUS-119hr1234.xml") == 1234
    assert gi._billnum("BILLSTATUS-119s5.xml") == 5
    assert gi._billnum("garbage") == 0
    # Sorting descending surfaces the highest (most recent) number first.
    names = ["BILLSTATUS-119hr2.xml", "BILLSTATUS-119hr100.xml", "BILLSTATUS-119hr10.xml"]
    names.sort(key=gi._billnum, reverse=True)
    assert names[0] == "BILLSTATUS-119hr100.xml"


def test_congress_title_matches():
    assert cg.title_matches("Voting Rights Advancement Act") is True
    assert cg.title_matches("A bill to name a federal building") is False


def test_congress_bill_row_mapping():
    item = {
        "congress": 119, "type": "HR", "number": 1234,
        "title": "Voting Rights Advancement Act",
        "latestAction": {"text": "Referred to committee"},
    }
    row = cg._bill_row(item)
    assert row["id"] == "congress_119_HR1234"
    assert row["case_type"] == "Legislation"
    assert "Voting Rights" in row["case_name"]


def test_openstates_queries_all_jurisdictions(monkeypatch):
    """Regression: fetch_bills must hit every jurisdiction, not just the first 10."""
    os.environ["OPENSTATES_API_KEY"] = "test-key"
    os.environ["OPENSTATES_RATE_DELAY"] = "0"
    from aggregator import openstates_fetch as ops

    seen = []

    class _Resp:
        status_code = 200
        headers: dict = {}
        def raise_for_status(self): pass
        def json(self): return {"results": []}

    def _fake_get(url, headers=None, timeout=None, params=None):
        seen.append(params["jurisdiction"])
        return _Resp()

    monkeypatch.setattr(ops.httpx, "get", _fake_get)
    monkeypatch.setattr(ops.time, "sleep", lambda *_: None)

    jur = [f"s{i}" for i in range(15)]  # 15 > the old cap of 10
    ops.fetch_bills("civil rights", jurisdictions=jur)
    assert seen == jur  # all 15 queried, in order


def test_openstates_respects_max_jurisdictions(monkeypatch):
    os.environ["OPENSTATES_API_KEY"] = "test-key"
    os.environ["OPENSTATES_RATE_DELAY"] = "0"
    from aggregator import openstates_fetch as ops

    seen = []

    class _Resp:
        status_code = 200
        headers: dict = {}
        def raise_for_status(self): pass
        def json(self): return {"results": []}

    monkeypatch.setattr(ops.httpx, "get",
                        lambda url, headers=None, timeout=None, params=None: (seen.append(params["jurisdiction"]) or _Resp()))
    monkeypatch.setattr(ops.time, "sleep", lambda *_: None)

    ops.fetch_bills("x", jurisdictions=[f"s{i}" for i in range(15)], max_jurisdictions=5)
    assert len(seen) == 5
