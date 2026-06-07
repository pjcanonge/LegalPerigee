"""
LegalPerigee case database — SQLite via Python's built-in sqlite3.

Schema
------
cases       — one row per case from any source
sync_log    — history of every aggregator run
"""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Generator, Optional

DB_PATH = Path(__file__).parent.parent / "data" / "cases.db"


def init_db() -> None:
    """Create tables and indexes if they don't exist."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    # M-5: Restrict file permissions to owner-only before first write
    if not DB_PATH.exists():
        DB_PATH.touch(mode=0o600)
    else:
        try:
            import os as _os
            _os.chmod(DB_PATH, 0o600)
        except Exception:
            pass
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS cases (
            id                TEXT PRIMARY KEY,
            source            TEXT NOT NULL,
            case_name         TEXT,
            court             TEXT,
            jurisdiction      TEXT,
            docket_number     TEXT,
            filing_date       TEXT,
            decision_date     TEXT,
            case_type         TEXT,
            status            TEXT,
            summary           TEXT,
            allegations       TEXT,
            harm_types        TEXT,
            protected_classes TEXT,
            financial_harm    TEXT,
            plaintiffs        TEXT,
            defendants        TEXT,
            judge             TEXT,
            document_url      TEXT,
            opinion_pdf_url   TEXT,
            citation          TEXT,
            last_updated      TEXT DEFAULT (datetime('now')),
            raw_json          TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_cases_source   ON cases(source);
        CREATE INDEX IF NOT EXISTS idx_cases_court    ON cases(court);
        CREATE INDEX IF NOT EXISTS idx_cases_date     ON cases(filing_date);
        CREATE INDEX IF NOT EXISTS idx_cases_type     ON cases(case_type);

        CREATE VIRTUAL TABLE IF NOT EXISTS cases_fts
            USING fts5(
                id UNINDEXED,
                case_name,
                summary,
                allegations,
                plaintiffs,
                defendants,
                content='cases',
                content_rowid='rowid'
            );

        CREATE TRIGGER IF NOT EXISTS cases_ai AFTER INSERT ON cases BEGIN
            INSERT INTO cases_fts(rowid, id, case_name, summary, allegations, plaintiffs, defendants)
            VALUES (new.rowid, new.id, new.case_name, new.summary, new.allegations,
                    new.plaintiffs, new.defendants);
        END;

        CREATE TRIGGER IF NOT EXISTS cases_au AFTER UPDATE ON cases BEGIN
            INSERT INTO cases_fts(cases_fts, rowid, id, case_name, summary, allegations,
                                  plaintiffs, defendants)
            VALUES ('delete', old.rowid, old.id, old.case_name, old.summary, old.allegations,
                    old.plaintiffs, old.defendants);
            INSERT INTO cases_fts(rowid, id, case_name, summary, allegations, plaintiffs, defendants)
            VALUES (new.rowid, new.id, new.case_name, new.summary, new.allegations,
                    new.plaintiffs, new.defendants);
        END;

        CREATE TABLE IF NOT EXISTS sync_log (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            source      TEXT,
            started_at  TEXT DEFAULT (datetime('now')),
            finished_at TEXT,
            cases_added INTEGER DEFAULT 0,
            cases_updated INTEGER DEFAULT 0,
            status      TEXT DEFAULT 'running',
            message     TEXT
        );
        """)


@contextmanager
def get_conn() -> Generator[sqlite3.Connection, None, None]:
    """Context manager yielding a WAL-mode connection with row_factory."""
    conn = sqlite3.connect(str(DB_PATH), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# ── Write helpers ──────────────────────────────────────────────────────────────

def upsert_case(row: dict) -> bool:
    """Insert or update a case. Returns True if new, False if updated."""
    with get_conn() as conn:
        existing = conn.execute(
            "SELECT id FROM cases WHERE id = ?", (row["id"],)
        ).fetchone()

        cols = [k for k in row if k in _CASE_COLS]
        placeholders = ", ".join(f":{c}" for c in cols)
        col_names = ", ".join(cols)
        update_set = ", ".join(f"{c}=:{c}" for c in cols if c != "id")

        if existing:
            conn.execute(
                f"UPDATE cases SET {update_set}, last_updated=datetime('now') WHERE id=:id",
                {c: row.get(c) for c in cols},
            )
            return False
        else:
            conn.execute(
                f"INSERT INTO cases ({col_names}) VALUES ({placeholders})",
                {c: row.get(c) for c in cols},
            )
            return True


def log_sync_start(source: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO sync_log (source) VALUES (?)", (source,)
        )
        return cur.lastrowid


def log_sync_finish(sync_id: int, added: int, updated: int, status: str, msg: str = "") -> None:
    with get_conn() as conn:
        conn.execute(
            """UPDATE sync_log
               SET finished_at=datetime('now'), cases_added=?, cases_updated=?,
                   status=?, message=?
               WHERE id=?""",
            (added, updated, status, msg, sync_id),
        )


# ── Read helpers ───────────────────────────────────────────────────────────────

def count_cases(source: Optional[str] = None) -> int:
    with get_conn() as conn:
        if source:
            return conn.execute(
                "SELECT COUNT(*) FROM cases WHERE source=?", (source,)
            ).fetchone()[0]
        return conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]


def _fts_query(q: str) -> str:
    """
    Convert a plain-text query into an FTS5 query string.

    Uses shlex.split so multi-word quoted phrases (e.g. `"civil rights"`) are
    treated as a single exact-match token rather than two separate prefix tokens.
    Unquoted single words get a trailing `*` for prefix matching.

    Examples
    --------
    "wrongful termination"    →  "wrongful"* "termination"*
    '"exact phrase" foo'      →  "exact phrase" "foo"*
    '"civil rights" discrim'  →  "civil rights" "discrim"*
    """
    import shlex

    try:
        parts = shlex.split(q.strip())
    except ValueError:
        # Unmatched quote — fall back to plain whitespace split
        parts = q.strip().split()

    tokens = []
    for part in parts:
        safe = part.replace('"', '""')
        if " " in part:
            # Was a quoted multi-word phrase — keep as exact match (no wildcard)
            tokens.append(f'"{safe}"')
        else:
            # Single word — add prefix wildcard
            tokens.append(f'"{safe}"*')
    return " ".join(tokens)


def search_cases(
    q: str = "",
    source: Optional[str] = None,
    court: Optional[str] = None,
    case_type: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    harm_type: Optional[str] = None,
    protected_class: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """
    Full-text + column search. Returns list of dicts.

    When a text query is supplied the results are ranked by BM25 relevance
    (most relevant first) rather than by filing date. This means a search for
    "housing discrimination" surfaces the most on-topic cases at the top even
    if a less relevant case was filed more recently.

    When no text query is supplied the results are ordered by filing_date DESC
    (newest first), which is the expected behaviour for browsing.
    """
    with get_conn() as conn:
        col_filters: list[str] = []
        col_params:  list      = []

        if source:
            col_filters.append("source = ?")
            col_params.append(source)
        if court:
            col_filters.append("court LIKE ?")
            col_params.append(f"%{court}%")
        if case_type:
            col_filters.append("case_type LIKE ?")
            col_params.append(f"%{case_type}%")
        if date_from:
            col_filters.append("filing_date >= ?")
            col_params.append(date_from)
        if date_to:
            col_filters.append("filing_date <= ?")
            col_params.append(date_to)
        if harm_type:
            col_filters.append("harm_types LIKE ?")
            col_params.append(f"%{harm_type}%")
        if protected_class:
            col_filters.append("protected_classes LIKE ?")
            col_params.append(f"%{protected_class}%")

        if q and q.strip():
            # ── FTS5 path: relevance-ranked via BM25 ─────────────────────────
            fts_q = _fts_query(q.strip())
            col_where = (" AND " + " AND ".join(col_filters)) if col_filters else ""

            # Join cases_fts with cases so we can apply column filters and BM25
            # bm25() returns negative values; ORDER BY bm25 ASC = most relevant first.
            sql = f"""
                SELECT c.*
                FROM cases c
                JOIN cases_fts f ON f.rowid = c.rowid
                WHERE f.cases_fts MATCH ?{col_where}
                ORDER BY bm25(f.cases_fts)
                LIMIT ? OFFSET ?
            """
            params: list = [fts_q] + col_params + [limit, offset]

            try:
                rows = conn.execute(sql, params).fetchall()
                return [dict(r) for r in rows]
            except Exception:
                # FTS5 MATCH can raise if the query string is malformed (e.g. bare *)
                # Fall back to the column-only path rather than surfacing an error.
                pass

        # ── Column-only path: no text query (or FTS fallback) ────────────────
        where = ("WHERE " + " AND ".join(col_filters)) if col_filters else ""
        sql = f"""
            SELECT * FROM cases {where}
            ORDER BY filing_date DESC
            LIMIT ? OFFSET ?
        """
        col_params += [limit, offset]
        rows = conn.execute(sql, col_params).fetchall()
        return [dict(r) for r in rows]


def get_case(case_id: str) -> Optional[dict]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM cases WHERE id=?", (case_id,)).fetchone()
        return dict(row) if row else None


def get_sync_log(limit: int = 20) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM sync_log ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


def source_stats() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            """SELECT source,
                      COUNT(*) as total,
                      MAX(last_updated) as last_updated
               FROM cases GROUP BY source ORDER BY total DESC"""
        ).fetchall()
        return [dict(r) for r in rows]


_CASE_COLS = {
    "id", "source", "case_name", "court", "jurisdiction", "docket_number",
    "filing_date", "decision_date", "case_type", "status", "summary",
    "allegations", "harm_types", "protected_classes", "financial_harm",
    "plaintiffs", "defendants", "judge", "document_url", "opinion_pdf_url",
    "citation", "raw_json",
}


# ── Alert rules ───────────────────────────────────────────────────────────────

def init_alerts_table() -> None:
    with get_conn() as conn:
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS alert_rules (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            name         TEXT NOT NULL,
            keywords     TEXT,
            courts       TEXT,
            harm_types   TEXT,
            states       TEXT,
            email        TEXT NOT NULL,
            active       INTEGER DEFAULT 1,
            last_checked TEXT,
            created_at   TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS alert_history (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_id    INTEGER,
            case_id    TEXT,
            sent_at    TEXT DEFAULT (datetime('now')),
            UNIQUE(rule_id, case_id)
        );
        """)


def get_alert_rules() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM alert_rules WHERE active=1").fetchall()
        return [dict(r) for r in rows]


def save_alert_rule(rule: dict) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO alert_rules (name, keywords, courts, harm_types, states, email)
               VALUES (:name,:keywords,:courts,:harm_types,:states,:email)""",
            rule,
        )
        return cur.lastrowid


def delete_alert_rule(rule_id: int) -> None:
    with get_conn() as conn:
        conn.execute("DELETE FROM alert_rules WHERE id=?", (rule_id,))


def mark_alert_sent(rule_id: int, case_id: str) -> bool:
    """Returns True if this is a new alert (not already sent)."""
    with get_conn() as conn:
        try:
            conn.execute(
                "INSERT INTO alert_history (rule_id, case_id) VALUES (?,?)",
                (rule_id, case_id),
            )
            return True
        except Exception:
            return False


def touch_alert_rule(rule_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE alert_rules SET last_checked=datetime('now') WHERE id=?",
            (rule_id,),
        )
