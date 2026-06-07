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
    """Full-text + column search. Returns list of dicts."""
    with get_conn() as conn:
        if q and q.strip():
            # FTS query
            safe_q = q.replace('"', '""')
            base_ids = [
                r["id"]
                for r in conn.execute(
                    "SELECT id FROM cases_fts WHERE cases_fts MATCH ? LIMIT 500",
                    (safe_q,),
                ).fetchall()
            ]
            if not base_ids:
                return []
            id_filter = f"AND id IN ({','.join('?'*len(base_ids))})"
            params: list = list(base_ids)
        else:
            id_filter = ""
            params = []

        filters = []
        if source:
            filters.append("source = ?")
            params.append(source)
        if court:
            filters.append("court LIKE ?")
            params.append(f"%{court}%")
        if case_type:
            filters.append("case_type LIKE ?")
            params.append(f"%{case_type}%")
        if date_from:
            filters.append("filing_date >= ?")
            params.append(date_from)
        if date_to:
            filters.append("filing_date <= ?")
            params.append(date_to)
        if harm_type:
            filters.append("harm_types LIKE ?")
            params.append(f"%{harm_type}%")
        if protected_class:
            filters.append("protected_classes LIKE ?")
            params.append(f"%{protected_class}%")

        where = ("WHERE " + " AND ".join(filters)) if filters else ""
        if id_filter:
            where = (where + " " + id_filter).strip() if where else f"WHERE 1=1 {id_filter}"

        sql = f"""
            SELECT * FROM cases {where}
            ORDER BY filing_date DESC
            LIMIT ? OFFSET ?
        """
        params += [limit, offset]
        rows = conn.execute(sql, params).fetchall()
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
