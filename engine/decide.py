"""Modules 6+7 — Sector transmission + sizing. ALL OUTPUT IS PAPER / FOR REVIEW (no confirmed edge in backtests)."""
from __future__ import annotations
from datetime import date, timedelta
from engine import logic, sectors
from engine.common import indicators_for, snapshot, update

CHECK_BACK_DAYS = 30


def run(conn, run_id):
    ind = indicators_for(conn, run_id)
    s = snapshot(conn, run_id)
    d = s["detail"]
    dials = {k: (float(s[f"{k}_score"]) if s[f"{k}_score"] is not None else None)
             for k in ("growth", "inflation", "liquidity", "vote", "fragility")}
    changes, null_log = sectors.regime_changes(ind, dials)
    ranked = sectors.rank(changes)
    frag = dials["fragility"]
    fragility_level = None if frag is None else max(0.0, -frag)  # 0..1, higher = more fragile
    gap_conv = logic.GAP_CONVICTION.get(d.get("conviction"), 0.0)
    pos = logic.size_position(s["stage"] or 0, gap_conv, fragility_level, d.get("gap_type"))
    if any(x["status"] == "triggered" for x in s["invalidation_conditions"] or []):
        pos = {**pos, "action": "wait", "size": 0.0, "reason": "invalidation triggered"}
    sleeve_view = logic.decide(d.get("sleeve"), d.get("conviction"), d.get("confirmation"), frag, d.get("coverage", 0))
    label = "PAPER / FOR REVIEW — not a live trade instruction (backtests showed no confirmed edge)."
    d.update(regime_changes=changes, driver_nulls=null_log, sectors=ranked, position=pos, sleeve_view=sleeve_view,
             paper_label=label, check_back_date=(date.today() + timedelta(days=CHECK_BACK_DAYS)).isoformat(),
             fragility_level=fragility_level, gap_conviction=gap_conv)
    txt = f"[PAPER] {pos['action'].upper()} size {pos['size']:.2f} ({pos['reason']}); sleeve: {sleeve_view['text']}"
    update(conn, run_id, sizing_recommendation=txt, detail=d)
