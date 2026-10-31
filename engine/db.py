"""DB layer: SQLite default (engine/regime.db), Postgres when DATABASE_URL=postgres://..."""
from __future__ import annotations
import json, os, re, sqlite3
from pathlib import Path

HERE = Path(__file__).resolve().parent
URL = os.environ.get("DATABASE_URL", f"sqlite:///{HERE / 'regime.db'}")
IS_PG = URL.startswith("postgres")


def connect():
    if IS_PG:
        import psycopg  # pip install psycopg[binary]
        return psycopg.connect(URL)
    path = URL.replace("sqlite:///", "")
    c = sqlite3.connect(path)
    c.row_factory = sqlite3.Row
    return c


def _sqlite_schema(sql: str) -> str:
    sql = sql.replace("BIGSERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
    sql = re.sub(r"\bJSONB\b", "TEXT", sql)
    sql = sql.replace("TIMESTAMPTZ DEFAULT NOW()", "TEXT DEFAULT CURRENT_TIMESTAMP")
    sql = re.sub(r"\bTIMESTAMPTZ\b", "TEXT", sql)
    return sql


def init(conn) -> None:
    sql = (HERE / "schema.sql").read_text()
    if IS_PG:
        with conn.cursor() as cur:
            cur.execute(sql)
    else:
        conn.executescript(_sqlite_schema(sql))
    conn.commit()


def q(conn, sql: str, params=(), one=False):
    if IS_PG:
        sql = sql.replace("?", "%s")
        if sql.lstrip().upper().startswith("INSERT") and "RETURNING" not in sql.upper():
            sql += " RETURNING id" if "flip_levels" not in sql else ""
    cur = conn.cursor()
    cur.execute(sql, params)
    if sql.lstrip().upper().startswith("INSERT"):
        if IS_PG:
            r = cur.fetchone() if "RETURNING" in sql else None
            return r[0] if r else None
        return cur.lastrowid
    rows = cur.fetchall() if cur.description else []
    if IS_PG:
        cols = [d[0] for d in cur.description] if cur.description else []
        rows = [dict(zip(cols, r)) for r in rows]
    else:
        rows = [dict(r) for r in rows]
    return (rows[0] if rows else None) if one else rows


def jdump(o) -> str:
    return json.dumps(o, default=str)


def jload(s):
    if s is None or isinstance(s, (dict, list)):
        return s
    return json.loads(s)
