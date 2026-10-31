"""Module 3 — Classify. indicators -> regime_snapshots row (dial labels, regime, confirmation)."""
from __future__ import annotations
from datetime import date
from engine import db, logic
from engine.common import indicators_for

ALL_DIALS = ("growth", "inflation", "liquidity", "vote", "fragility")


def latest_stance(conn):
    r = db.q(conn, "SELECT payload FROM raw_ingest WHERE indicator='rbi_stance' AND ok ORDER BY id DESC LIMIT 1", one=True)
    return db.jload(r["payload"]).get("stance") if r else None


def run(conn, run_id):
    ind = indicators_for(conn, run_id)
    stance = latest_stance(conn)
    g = logic.score_growth(ind)
    i = logic.score_inflation(ind)
    l, hard = logic.score_liquidity(ind, stance)
    quad = logic.quadrant(g, i)
    label = logic.regime_label(quad, l, hard)
    slv = logic.sleeve(g, i, l, quad, hard)
    conv = logic.conviction(g, i, l, quad, slv)
    scores = {d: logic.dial_score([r for r in ind.values() if r["dial"] == d]) for d in ALL_DIALS}
    voting = [r for r in ind.values() if r["weight"] and r["dial"] in ALL_DIALS]
    from engine.config import INDICATORS
    expected = [k for k, m in INDICATORS.items() if m["weight"] and m["dial"] in ALL_DIALS]
    coverage = sum(1 for k in expected if k in ind and not ind[k]["is_stale"]) / len(expected)
    prev = db.q(conn, "SELECT regime_label, detail FROM regime_snapshots WHERE run_id<>? ORDER BY id DESC LIMIT 1", (run_id,), one=True)
    prev_label = prev["regime_label"] if prev else None
    status = logic.confirm(prev_label, label)
    sub = "acute" if hard and l == "Contracting" else status
    change = "no change" if prev_label == label else f"{prev_label or 'none'} -> {label}"
    detail = {"dial_labels": {"growth": g, "inflation": i, "liquidity": l, "liquidity_hard": hard},
              "rbi_stance": stance, "quadrant": quad, "sleeve": slv, "conviction": conv,
              "confirmation": status, "coverage": round(coverage, 2), "change": change,
              "liq_signals": logic.liq_signals(ind, stance), "n_indicators": len(voting)}
    db.q(conn, "INSERT INTO regime_snapshots (run_id, snapshot_date, growth_score, inflation_score, liquidity_score, vote_score, fragility_score, regime_label, sub_label, detail) VALUES (?,?,?,?,?,?,?,?,?,?)",
         (run_id, date.today().isoformat(), scores["growth"], scores["inflation"], scores["liquidity"], scores["vote"],
          scores["fragility"], label, sub, db.jdump(detail)))
    conn.commit()
