"""Run the cascade: ingest -> score -> classify -> stage/gap -> decide -> alert -> export JSON."""
from __future__ import annotations
import argparse, json, sys, uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine import db, ingest, score, classify, stage_gap, decide, alert  # noqa: E402
from engine.common import snapshot  # noqa: E402
from engine import release_calendar as cal  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
OUT = ROOT / "data"


def _missing(ind_rows, log):
    """Indicators with no usable value, with the reason (never a fabricated number)."""
    from engine.config import INDICATORS
    from engine.ingest import MANUAL
    have = {r["indicator"] for r in ind_rows}
    man = json.loads(MANUAL.read_text()) if MANUAL.exists() else {}
    errs = {}
    for k, src, ok, e in log:
        if not ok and e:
            errs.setdefault(k, f"{src}: {e}")
    return [{"indicator": k, "reason": (man.get(k) or {}).get("reason") or errs.get(k) or "no source returned a value"}
            for k in INDICATORS if k not in have]


def flip_level_warnings(today=None):
    from datetime import date
    from engine.config import FLIP_LEVELS, FLIP_STALE_DAYS
    today = today or date.today()
    out = []
    for k, lv in FLIP_LEVELS.items():
        age = (today - date.fromisoformat(lv["last_calibrated"])).days
        if age > FLIP_STALE_DAYS:
            out.append(f"FLIP_LEVEL_STALE: {k} last calibrated {lv['last_calibrated']} ({age} days)")
    for w in out:
        print("WARNING", w)
    return out


def export(conn, snap, ind_rows, log, alert_res, ingest_failed=None, mpc_check=None):
    latest = {
        "generated_at_ist": datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"),
        "run_id": snap["run_id"], "snapshot_date": snap["snapshot_date"],
        "regime_label": snap["regime_label"], "sub_label": snap["sub_label"], "stage": snap["stage"],
        "scores": {k: snap[f"{k}_score"] for k in ("growth", "inflation", "liquidity", "vote", "fragility")},
        "tier1_flips": snap["tier1_flips"], "tier2_confirmed": bool(snap["tier2_confirmed"]),
        "gap_description": snap["gap_description"], "sizing_recommendation": snap["sizing_recommendation"],
        "invalidation_conditions": snap["invalidation_conditions"], "detail": snap["detail"],
        "indicators": [{k: r.get(k) for k in ("indicator", "dial", "value", "prior_value", "direction", "score", "weight",
                        "as_of", "is_stale", "stale_since", "source", "source_url", "status", "checks", "note", "source_tier", "data_period", "survey_quarter", "diagnostics", "stale_reason", "release_date")} for r in ind_rows],
        "missing": _missing(ind_rows, log),
        "warnings": flip_level_warnings() + [f"INGEST_FAILED:{k}" for k in (ingest_failed or {}).get("failed", [])],
        "release_calendar": {"mpc_dates_check": mpc_check, "today_due": cal.is_release_day(datetime.now(IST).date()), **cal.RELEASE_CALENDAR},
        "source_log": [{"indicator": k, "source": s, "ok": ok, "error": e} for k, s, ok, e in log],
        "alert": alert_res,
    }
    OUT.mkdir(exist_ok=True)
    (OUT / "regime_latest.json").write_text(json.dumps(latest, indent=2, default=str))
    hist_p = OUT / "regime_history.json"
    hist = json.loads(hist_p.read_text()) if hist_p.exists() else []
    key = lambda h: (h.get("regime_label"), h.get("sub_label"), h.get("stage"), json.dumps(h.get("scores"), sort_keys=True))  # noqa: E731
    if not hist or key(hist[-1]) != key(latest):
      hist.append({k: latest[k] for k in ("generated_at_ist", "run_id", "regime_label", "sub_label", "stage", "scores")}
                | {"position": snap["detail"].get("position"), "check_back_date": snap["detail"].get("check_back_date"),
                   "outcome": None})
    hist_p.write_text(json.dumps(hist[-500:], indent=2, default=str))
    return latest


def run(force_language=False, skip_ingest=False):
    conn = db.connect(); db.init(conn)
    flip_level_warnings()  # startup check (spec 3.3)
    run_id = datetime.now(IST).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    scraped = [] if skip_ingest else cal.scrape_mpc_dates()
    mpc_check = ("verified vs rbi.org.in" if set(cal.MPC_DATES) <= set(scraped) else f"MPC_DATES_UNVERIFIED: scraped {scraped}")
    log = [] if skip_ingest else ingest.run(conn, force_language)
    ingest_failed = ingest.ingest_with_fallback_failures(conn, log) if log else {"failed": []}
    ind_rows = score.run(conn, run_id)
    classify.run(conn, run_id)
    stage_gap.run(conn, run_id)
    decide.run(conn, run_id)
    snap = snapshot(conn, run_id)
    failures = sorted({k for k, s, ok, e in log if not ok and s not in ("manual", "stub") and "not set" not in str(e)})
    alert_res = alert.run(snap, failures)
    return export(conn, snap, ind_rows, log, alert_res, ingest_failed, mpc_check)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--force-language", action="store_true")
    ap.add_argument("--skip-ingest", action="store_true")
    a = ap.parse_args()
    out = run(a.force_language, a.skip_ingest)
    print(json.dumps({k: out[k] for k in ("regime_label", "sub_label", "stage", "scores", "gap_description", "sizing_recommendation")}, indent=2, default=str))
