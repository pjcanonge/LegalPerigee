"""
Tests for database/db.py

Covers:
- _fts_query() prefix expansion and quote pass-through
- search_cases() BM25 path and column-only path (in-memory SQLite via temp DB_PATH)
- upsert_case() insert + update semantics
- count_cases() with and without source filter
"""

import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture()
def temp_db(tmp_path, monkeypatch):
    """Redirect DB_PATH to a fresh temp file for each test."""
    db_file = tmp_path / "test_cases.db"
    import database.db as db_module
    monkeypatch.setattr(db_module, "DB_PATH", db_file)
    db_module.init_db()
    yield db_module


def _make_case(id: str, name: str, summary: str = "", source: str = "test") -> dict:
    return {
        "id": id,
        "source": source,
        "case_name": name,
        "summary": summary,
        "court": "SDNY",
        "filing_date": "2024-01-01",
        "case_type": "civil rights",
    }


# ── _fts_query() ──────────────────────────────────────────────────────────────

def test_fts_query_single_word():
    from database.db import _fts_query
    result = _fts_query("discrimination")
    assert result == '"discrimination"*'


def test_fts_query_two_words():
    from database.db import _fts_query
    result = _fts_query("wrongful termination")
    assert result == '"wrongful"* "termination"*'


def test_fts_query_quoted_phrase_passthrough():
    from database.db import _fts_query
    result = _fts_query('"exact phrase"')
    assert result == '"exact phrase"'


def test_fts_query_mixed():
    from database.db import _fts_query
    result = _fts_query('"civil rights" discrimination')
    assert result == '"civil rights" "discrimination"*'


def test_fts_query_strips_leading_trailing():
    from database.db import _fts_query
    result = _fts_query("  housing  ")
    assert result == '"housing"*'


# ── upsert_case() ─────────────────────────────────────────────────────────────

def test_upsert_insert_returns_true(temp_db):
    case = _make_case("case-001", "Smith v. Jones")
    result = temp_db.upsert_case(case)
    assert result is True  # new row


def test_upsert_update_returns_false(temp_db):
    case = _make_case("case-001", "Smith v. Jones")
    temp_db.upsert_case(case)
    case["summary"] = "Updated summary"
    result = temp_db.upsert_case(case)
    assert result is False  # existing row


def test_upsert_persists_data(temp_db):
    case = _make_case("case-002", "Doe v. Corp", summary="Fraud case")
    temp_db.upsert_case(case)
    retrieved = temp_db.get_case("case-002")
    assert retrieved is not None
    assert retrieved["case_name"] == "Doe v. Corp"
    assert retrieved["summary"] == "Fraud case"


# ── count_cases() ─────────────────────────────────────────────────────────────

def test_count_cases_empty(temp_db):
    assert temp_db.count_cases() == 0


def test_count_cases_total(temp_db):
    temp_db.upsert_case(_make_case("c1", "Case A", source="courtlistener"))
    temp_db.upsert_case(_make_case("c2", "Case B", source="sec"))
    assert temp_db.count_cases() == 2


def test_count_cases_by_source(temp_db):
    temp_db.upsert_case(_make_case("c1", "Case A", source="courtlistener"))
    temp_db.upsert_case(_make_case("c2", "Case B", source="sec"))
    assert temp_db.count_cases(source="courtlistener") == 1
    assert temp_db.count_cases(source="sec") == 1
    assert temp_db.count_cases(source="missing") == 0


# ── search_cases() ────────────────────────────────────────────────────────────

def test_search_cases_no_query_returns_all(temp_db):
    temp_db.upsert_case(_make_case("c1", "Alpha Case"))
    temp_db.upsert_case(_make_case("c2", "Beta Case"))
    results = temp_db.search_cases()
    assert len(results) == 2


def test_search_cases_fts_match(temp_db):
    temp_db.upsert_case(_make_case("c1", "Housing Discrimination", summary="Fair housing violation"))
    temp_db.upsert_case(_make_case("c2", "Wire Fraud Scheme", summary="Securities fraud"))
    results = temp_db.search_cases(q="housing")
    assert len(results) == 1
    assert results[0]["id"] == "c1"


def test_search_cases_fts_no_match(temp_db):
    temp_db.upsert_case(_make_case("c1", "Housing Discrimination"))
    results = temp_db.search_cases(q="cybercrime")
    assert len(results) == 0


def test_search_cases_column_filter(temp_db):
    temp_db.upsert_case(_make_case("c1", "Case A", source="courtlistener"))
    temp_db.upsert_case(_make_case("c2", "Case B", source="sec"))
    results = temp_db.search_cases(source="sec")
    assert len(results) == 1
    assert results[0]["id"] == "c2"


def test_search_cases_limit(temp_db):
    for i in range(10):
        temp_db.upsert_case(_make_case(f"c{i}", f"Case {i}"))
    results = temp_db.search_cases(limit=3)
    assert len(results) == 3


def test_search_cases_fts_with_column_filter(temp_db):
    temp_db.upsert_case(_make_case("c1", "Housing Discrimination", source="courtlistener"))
    temp_db.upsert_case(_make_case("c2", "Housing Issue", source="sec"))
    results = temp_db.search_cases(q="housing", source="sec")
    assert len(results) == 1
    assert results[0]["id"] == "c2"


def test_search_cases_malformed_fts_falls_back(temp_db):
    """A malformed FTS query must not raise — it should fall back to column search."""
    temp_db.upsert_case(_make_case("c1", "Test Case"))
    # Bare * is invalid FTS5 syntax; should gracefully fall back
    results = temp_db.search_cases(q="*")
    # Result may be 0 or 1 — the important thing is no exception
    assert isinstance(results, list)
