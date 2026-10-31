"""Module 4 — Gap + Stage + flip watchlist."""
from __future__ import annotations
from datetime import datetime, timezone
from engine import db, logic
from engine.common import indicators_for, snapshot, update
from engine.config import FLIP_LEVELS


def run(conn, run_id):
    ind = indicators_for(conn, run_id)
    s = snapshot(conn, run_id)
    st, trail = logic.stage(ind)
    vote = float(s["vote_score"]) if s["vote_score"] is not None else None
    gap_type, gap_text = logic.gap(s["regime_label"], vote)
    fl = logic.flips(ind, FLIP_LEVELS)
    now = datetime.now(timezone.utc).isoformat()
    for f in fl:
        db.q(conn, "DELETE FROM flip_levels WHERE indicator=?", (f["indicator"],))
        db.q(conn, "INSERT INTO flip_levels (indicator, current_value, flip_level, flip_direction, is_flipped, tier, last_checked) VALUES (?,?,?,?,?,?,?)",
             (f["indicator"], f["current_value"], f["flip_level"], f["flip_direction"], f["is_flipped"], f["tier"], now))
    t1 = sum(1 for f in fl if f["tier"] == 1 and f["is_flipped"])
    t2 = [f for f in fl if f["tier"] == 2 and f["is_flipped"] is not None]
    t2_conf = bool(t2) and sum(1 for f in t2 if f["is_flipped"]) / len(t2) >= 0.6
    d = s["detail"]; d.update(stage_trail=trail, gap_type=gap_type, flips=fl)
    update(conn, run_id, stage=st, gap_description=gap_text, tier1_flips=t1, tier2_confirmed=t2_conf, detail=d,
           invalidation_conditions=logic.invalidations(ind))
