"""Regime/stage overlay, WPI margin driver, price-adjusted credit gap, stress panel and 'wrong if' triggers.
Code only: official/structured inputs (RBI repo/stance, Brent, USD/INR, OEA WPI/PPI, MoSPI CPI) and a documented
sensitivity table (engine/sector_sensitivity.json). No AI calls. Missing inputs stay missing (driver excluded)."""
from __future__ import annotations
import json
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SENS_P = ROOT / "engine" / "sector_sensitivity.json"
EXTRA_P = ROOT / "data" / "macro_extra.json"
PTS = 2.5            # points per sensitivity notch for an active regime factor
OV_MIN, OV_MAX = -10, 6
CYCLICAL_CAP = 85    # late-cycle ceiling for cyclical sectors
GAP_WATCH, GAP_RED = 15.0, 25.0   # real credit-output gap thresholds (pp)
MARGIN_PP = 2.0      # input-vs-output price change threshold (pp)
OK_AT, AVOID_BELOW = 65, 45
SHOCKS = {"brent_up20": "Brent +20%", "inr_down5": "Rupee −5%", "repo_up50": "Repo +50 bp", "demand_down5": "Demand −5%"}


def sens():
    return json.loads(SENS_P.read_text())["sectors"]


def refresh_extra(today=None):
    """USD/INR 1-year change (market data), cross-checked against the RBI/FBIL reference rate level."""
    from engine import lending_sources as ls
    r = ls.yahoo_yoy("INR=X")
    if "error" not in r:
        r["source_tier"] = "market_data"
        EXTRA_P.write_text(json.dumps({"usdinr_yoy": r}, indent=1))
    return r


def _next_wpi_release(period_ym):
    y, m = map(int, period_ym.split("-"))
    m += 2
    if m > 12:
        y, m = y + 1, m - 12
    d = date(y, m, 14)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


def regime(macro, wpi, today):
    """Current regime from verified macro only. Each factor is on/off with its evidence; unknown inputs leave the factor off."""
    f, ev = {}, []
    rp, st = macro.get("repo_rate") or {}, macro.get("rbi_stance_score") or {}
    if rp.get("usable") and st.get("usable") and rp.get("prior_value") is not None:
        f["tightening"] = rp["value"] > rp["prior_value"] and st["value"] < 0
        f["easing"] = rp["value"] < rp["prior_value"] or st["value"] > 0
        ev.append({"k": "repo", "t": f"Repo {rp['value']}% (from {rp['prior_value']}%), RBI stance {'tightening' if st['value'] < 0 else 'easing' if st['value'] > 0 else 'neutral'}", "d": rp.get("as_of"), "u": st.get("source_url")})
    b = macro.get("brent") or {}
    if b.get("usable") and b.get("value") is not None:
        f["oil_shock"] = b["value"] > 100
        ev.append({"k": "brent", "t": f"Brent ${b['value']:.0f}/bbl (oil shock above $100)", "d": b.get("as_of"), "u": b.get("source_url")})
    ex = json.loads(EXTRA_P.read_text()) if EXTRA_P.exists() else {}
    fx, ref = ex.get("usdinr_yoy") or {}, macro.get("usdinr_ref") or {}
    if fx.get("yoy_pct") is not None and ref.get("usable") and abs(fx["value"] / ref["value"] - 1) < 0.02:
        f["inr_weak"] = fx["yoy_pct"] > 3
        ev.append({"k": "inr", "t": f"Rupee {fx['value']:.2f}/USD, {fx['yoy_pct']:.1f}% weaker than a year ago (USD/INR {fx['yoy_pct']:+.1f}%) (level checked against RBI reference rate {ref['value']:.2f})", "d": fx.get("as_of"), "u": fx.get("source_url")})
    cpi = macro.get("cpi_headline") or {}
    if wpi and not wpi.get("errors") and wpi.get("headline_yoy") is not None and cpi.get("usable"):
        gap = round(wpi["headline_yoy"] - cpi["value"], 2)
        f["cost_push"] = gap > 3
        ev.append({"k": "wpi_cpi", "t": f"WPI {wpi['headline_yoy']:.2f}% vs CPI {cpi['value']:.2f}% ({gap:+.2f} pp: producers' costs rising faster than consumer prices)", "d": wpi.get("period"), "u": wpi.get("source_url")})
    late = bool(f.get("tightening") and (f.get("cost_push") or f.get("oil_shock")))
    stage = ("Late cycle: tightening into a cost-push shock" if late else "Tightening" if f.get("tightening") else
             "Easing" if f.get("easing") else "Neutral / not determined")
    from engine.release_calendar import MPC_DATES
    nxt = next((m for m in MPC_DATES if date.fromisoformat(m) > today), None)
    return {"factors": f, "late_cycle": late, "stage": stage, "evidence": ev, "next_mpc": nxt,
            "next_wpi": _next_wpi_release(wpi["period"]).isoformat() if wpi and wpi.get("period") else None}


def overlay_points(sv, reg):
    """Points added to the core score from regime factors x sector sensitivity, with a per-factor breakdown."""
    f, parts = reg["factors"], []
    if sv is None:
        return None, []
    if f.get("tightening") and sv["rate"]:
        parts.append(("rates", -PTS * sv["rate"]))
    elif f.get("easing") and sv["rate"]:
        parts.append(("rates", PTS * sv["rate"]))
    if f.get("oil_shock") and sv["crude"]:
        parts.append(("crude", PTS * sv["crude"]))
    if f.get("inr_weak") and sv["inr"]:
        parts.append(("rupee", PTS * sv["inr"]))
    tot = max(OV_MIN, min(OV_MAX, sum(p for _, p in parts)))
    return round(tot, 1), parts


def margin_driver(sv, wpi):
    if not sv or not sv.get("wpi_group") or sv.get("margin_scope") == "none":
        return None
    g = sv["wpi_group"]
    ig = "motor vehicles" if g == "other transport equipment" else g  # trial IPPI combines NIC 29+30
    o, i = (wpi.get("oppi") or {}).get(g), (wpi.get("ippi") or {}).get(ig)
    if not o or not i or wpi.get("errors"):
        return {"score": None, "status": "excluded", "reason": "WPI group not in release", "text": f"input vs output prices ({g}): not available"}
    mo = wpi.get("months") or ["", ""]
    oc, ic = round((o[-1] / o[0] - 1) * 100, 1), round((i[-1] / i[0] - 1) * 100, 1)
    spread = round(oc - ic, 1)
    sc = 1 if spread > MARGIN_PP else (-1 if spread < -MARGIN_PP else 0)
    disp = sv.get("margin_scope") == "display"
    txt = (f"input costs {ic:+.1f}% vs selling prices {oc:+.1f}% ({mo[0]}→{mo[-1]}, {g}; spread {spread:+.1f} pp"
           + (", margin squeeze" if sc < 0 else ", margin widening" if sc > 0 else "") + ")")
    return {"score": None if disp else sc, "value": spread, "unit": "pp", "as_of": wpi.get("period") + "-28" if wpi.get("period") else None,
            "source_url": wpi.get("source_url"), "status": "display" if disp else "verified",
            "reason": "group-level only: this sector is a narrow slice of the WPI group, so shown but not scored" if disp else "trial Input PPI (OEA, published since Mar 2026)",
            "text": txt + (" — group level, not scored" if disp else "")}


def deflator(sv, wpi):
    if not sv or not wpi or wpi.get("errors") or not sv.get("deflator"):
        return None, None
    if sv["deflator"] == "ALL":
        return wpi.get("headline_yoy"), "headline WPI"
    v = (wpi.get("wpi_yoy") or {}).get(sv["deflator"])
    return (v[-1], f"WPI {sv['deflator']}") if v else (None, None)


def band(sc):
    return None if sc is None else ("ok" if sc >= OK_AT else "avoid" if sc < AVOID_BELOW else "caution")


def stress_deltas(sv, demand_delta):
    """Score change per shock. Brent/INR/repo shocks use one extra sensitivity notch (repo +50 bp = two 25 bp notches);
    demand -5% re-scores the output drivers with output growth 5 pp lower (computed by the caller)."""
    if sv is None:
        return None
    return {"brent_up20": PTS * sv["crude"], "inr_down5": PTS * sv["inr"], "repo_up50": -2 * PTS * sv["rate"], "demand_down5": demand_delta}


def wrong_if(sector_out, reg, today):
    """'Wrong if' triggers and check-back date, only from drivers that actually moved the call."""
    t, dates = [], []
    d = sector_out["drivers"]
    ro = d.get("regime_overlay") or {}
    if ro.get("points"):
        bits = []
        if any(p[0] == "rates" for p in ro.get("parts", [])):
            bits.append("RBI pauses or cuts" + (f" at the {reg['next_mpc']} MPC" if reg.get("next_mpc") else ""))
            if reg.get("next_mpc"): dates.append(reg["next_mpc"])
        if any(p[0] == "crude" for p in ro.get("parts", [])):
            bits.append("Brent falls back below $100" if ro["points"] < 0 else "Brent falls below $100")
        if any(p[0] == "rupee" for p in ro.get("parts", [])):
            bits.append("the rupee recovers to under 3% weaker than a year ago")
        if bits:
            t.append("regime: " + " or ".join(bits))
    m = d.get("margin")
    if m and m.get("score"):
        t.append(f"margin: the input-vs-output price spread turns {'positive' if m['score'] < 0 else 'negative'} in the next WPI release")
        if reg.get("next_wpi"): dates.append(reg["next_wpi"])
    cv = d.get("credit_vs_output") or {}
    if cv.get("flag"):
        t.append(f"credit gap: real credit growth falls back within {GAP_WATCH:.0f} pp of output growth in the next RBI sector-credit release")
        dates.append(((today.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)).isoformat())  # RBI sector credit: around month-end
    for k in ("iip_fytd", "activity_proxy"):
        v = d.get(k) or {}
        if v.get("score") and v.get("status") == "verified":
            t.append(f"output: {v['text']} {'turns negative' if v['score'] > 0 else 'recovers above +5%'}")
            if k == "iip_fytd":
                from engine.release_calendar import release_date
                rd = release_date("iip_yoy", today.year, today.month)
                if rd <= today:
                    nm = (today.replace(day=28) + timedelta(days=4))
                    rd = release_date("iip_yoy", nm.year, nm.month)
                dates.append(rd.isoformat())
            break
    if not t:
        return None
    return {"triggers": t[:3], "check_back": min(dates) if dates else None}
