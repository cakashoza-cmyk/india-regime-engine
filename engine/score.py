"""Module 2 — Scoring. raw_ingest -> indicators (one row per indicator per run)."""
from __future__ import annotations
from datetime import datetime, timezone
from engine import db
from engine.config import INDICATORS


def direction(value, prior, kind="generic", eps=0.0015):
    """+1 rising, -1 falling, 0 flat/unknown."""
    if value is None or prior is None:
        return 0
    if kind == "rate":
        return 1 if value > prior + 1e-9 else (-1 if value < prior - 1e-9 else 0)
    if prior == 0:
        return 1 if value > 0 else (-1 if value < 0 else 0)
    chg = (value - prior) / abs(prior)
    return 1 if chg > eps else (-1 if chg < -eps else 0)


def score_indicator(value, prior, indicator_type):
    """Spec Module 2 (rate/inflation as pasted; others = documented assumptions). +1 = favourable."""
    if indicator_type in ("rate", "inflation"):
        d = direction(value, prior, "rate" if indicator_type == "rate" else "generic")
        return -d
    if indicator_type in ("growth", "vote"):
        return direction(value, prior)
    if indicator_type == "fragility":
        return -direction(value, prior)
    if indicator_type == "flow":  # AUDIT_LOGIC: FII > +500 expanding, < -500 contracting
        if value is None:
            return 0
        return 1 if value > 500 else (-1 if value < -500 else 0)
    return 0  # display


def _latest(conn, key):
    rows = db.q(conn, "SELECT id, payload, fetched_at, ok, source FROM raw_ingest WHERE indicator=? AND (is_verified OR NOT ok) ORDER BY id DESC LIMIT 50", (key,))
    if not rows:
        return None, None, None
    oks = [r for r in rows if r["ok"]]
    # prefer the most recent reference period (manual official print beats older DBIE vintage)
    good = max(oks, key=lambda r: ((db.jload(r["payload"]).get("as_of") or ""), r["id"])) if oks else None
    stale_since = None
    if not rows[0]["ok"]:
        # first failure after the last good pull
        fails = [r for r in rows if not r["ok"] and (good is None or r["id"] > good["id"])]
        stale_since = fails[-1]["fetched_at"] if fails else rows[0]["fetched_at"]
    return good, stale_since, rows


def _prior_from_history(rows, good, value):
    for r in rows:
        if r["ok"] and r["id"] < good["id"]:
            v = db.jload(r["payload"]).get("value")
            if v is not None and v != value:
                return v
    return None


MAX_AGE_DAYS = {"monthly": 75, "quarterly": 140, "daily": 7, "event": 400}
CADENCE = {"gdp_yoy": "quarterly", "iip_yoy": "monthly", "gst_yoy": "monthly", "cpi_headline": "monthly",
           "cpi_core": "monthly", "food_inflation": "monthly", "credit_growth": "monthly",
           "capacity_util": "quarterly", "repo_rate": "event"}


def too_old(key, as_of, today=None):
    from datetime import date
    if not as_of:
        return True
    today = today or date.today()
    try:
        age = (today - date.fromisoformat(str(as_of)[:10])).days
    except ValueError:
        return True
    return age > MAX_AGE_DAYS[CADENCE.get(key, "daily")]


def run(conn, run_id: str) -> list[dict]:
    out = []
    now = datetime.now(timezone.utc).isoformat()
    for key, meta in INDICATORS.items():
        good, stale_since, rows = _latest(conn, key)
        if good is None:
            continue  # never had a value: absent, not zero
        p = db.jload(good["payload"])
        value = p.get("value")
        prior = p.get("prior")
        if prior is None:
            prior = _prior_from_history(rows, good, value)
        kind = "rate" if meta["type"] == "rate" else "generic"
        d = direction(value, prior, kind)
        s = score_indicator(value, prior, meta["type"])
        aged = too_old(key, p.get("as_of"))
        if aged and stale_since is None:
            stale_since = "vintage:" + str(p.get("as_of"))
        rec = dict(run_id=run_id, indicator=key, dial=meta["dial"], value=value, prior_value=prior,
                   direction=d, score=s, weight=meta["weight"], as_of=p.get("as_of") or now[:10],
                   is_stale=stale_since is not None, stale_since=stale_since, source_raw_id=good["id"],
                   source=good["source"], source_url=p.get("source_url"))
        db.q(conn, "INSERT INTO indicators (run_id, indicator, dial, value, prior_value, direction, score, weight, as_of, is_stale, stale_since, source_raw_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
             (run_id, key, rec["dial"], value, prior, d, s, rec["weight"], rec["as_of"], rec["is_stale"], stale_since, good["id"]))
        out.append(rec)
    conn.commit()
    return out
