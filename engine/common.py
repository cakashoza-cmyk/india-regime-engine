from __future__ import annotations
from engine import db


def indicators_for(conn, run_id) -> dict:
    rows = db.q(conn, "SELECT * FROM indicators WHERE run_id=?", (run_id,))
    out = {}
    for r in rows:
        r["is_stale"] = bool(r["is_stale"])
        for k in ("value", "prior_value"):
            r[k] = float(r[k]) if r[k] is not None else None
        out[r["indicator"]] = r
    return out


def snapshot(conn, run_id):
    s = db.q(conn, "SELECT * FROM regime_snapshots WHERE run_id=?", (run_id,), one=True)
    if s:
        s["detail"] = db.jload(s["detail"]) or {}
        s["invalidation_conditions"] = db.jload(s["invalidation_conditions"])
    return s


def update(conn, run_id, **cols):
    for k in ("detail", "invalidation_conditions"):
        if k in cols:
            cols[k] = db.jdump(cols[k])
    sets = ", ".join(f"{k}=?" for k in cols)
    db.q(conn, f"UPDATE regime_snapshots SET {sets} WHERE run_id=?", (*cols.values(), run_id))
    conn.commit()
