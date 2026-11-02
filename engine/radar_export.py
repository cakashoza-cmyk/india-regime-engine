"""Compact export for the v3 Lending Radar page: data/radar.json (+ data/radar_briefs.json).
Verdicts here are copied from the verified-data engine (lending.py); briefs are display-only text."""
from __future__ import annotations
import json, pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _strip_src(t):
    return t


def export(out, news):
    inds = json.loads((ROOT / "engine" / "industries.json").read_text())["industries"]
    cities = json.loads((ROOT / "engine" / "cities.json").read_text())["cities"]
    lens = json.loads((ROOT / "engine" / "credit_lens.json").read_text())
    R, Ri = [], {}

    def rid(r):
        k = (r["text"], r.get("source_url"))
        if k not in Ri:
            Ri[k] = len(R); R.append([r["text"], r.get("sign"), r.get("source_url"), r.get("kind")])
        return Ri[k]

    calls = {}
    for c in out["combos"]:
        if c["geo_type"] != "state":
            continue
        calls[f"{c['state']}|{c['sector']}"] = [c.get("data_call", c.get("call")), c.get("score"), c.get("national_score"), c.get("local_score"),
                                                  c.get("insufficient"), [rid(r) for r in c.get("reasons", [])]]
    from engine import ratings_gj
    rg = ratings_gj.load()
    rg_changed = ratings_gj.apply_to_calls(calls, rg["industries"]) if rg else []
    ratings_view = rg and {k: rg[k] for k in ("generated", "coverage_from", "window_days", "recent_days", "min_actions", "thresholds", "agencies", "industries")}
    if ratings_view:
        ratings_view["changed_calls"] = rg_changed
    sectors = {}
    for s in out["sectors"]:
        sectors[s["id"]] = {"name": s["name"], "score": s.get("score"), "verdict": s["verdict"], "group": s.get("group"),
                            "credit": s.get("credit"), "gnpa": s.get("gnpa"), "trend": s.get("credit_trend"),
                            "drivers": [{"t": v["text"], "s": v.get("score"), "st": v.get("status"), "d": v.get("as_of"), "u": v.get("source_url"), "r": v.get("reason")} for v in s["drivers"].values()],
                            "checks": (lens.get(s["id"]) or {}).get("checks", []), "change": (s.get("plain") or {}).get("change_mind"),
                            "what": (lens.get(s["id"]) or {}).get("what"),
                            "misfit": s.get("series_misfit"), "pc": s.get("price_controlled"),
                            "stress": s.get("stress") and {k: v["delta"] for k, v in s["stress"].items()}, "wrong_if": s.get("wrong_if"),
                            "capped_by": s.get("capped_by") or None,
                            "sens": s.get("sensitivity") and {k: s["sensitivity"][k] for k in ("rate", "crude", "inr", "demand", "cyclical", "why")}}
    states = {k: {"name": v["name"], "signals": {sk: {f: sv.get(f) for f in ("value", "india", "month_yoy_pct", "as_of", "source_url", "source_name", "verified")}
                                                     for sk, sv in (v.get("signals") or {}).items() if sv}} for k, v in out["states"].items()}
    briefs = {}
    for k, it in (news.get("items") or {}).items():
        b = it.get("brief") or {}
        if it.get("prompt_version", 0) < 3 or not b.get("local_flavour"):
            continue
        briefs[k] = {"f": b["local_flavour"], "c": b.get("borrower_checks"), "x": b.get("change_the_call"), "o": it.get("outlook_vs_macro"),
                     "w": it.get("why"), "s": it.get("sources") or [], "t": it.get("scanned_ist")}
    from engine.regime_overlay import band, SHOCKS
    flips = {k: [] for k in SHOCKS}
    for key, c in calls.items():
        st_, sid = key.split("|")
        sc, ss = c[1], (sectors.get(sid) or {}).get("stress")
        if sc is None or not ss:
            continue
        for k, d in ss.items():
            n = max(0, min(100, round(sc + d)))
            if band(n) != band(sc):
                flips[k].append([st_, sid, sc, n])
    stress_summary = {k: {"label": SHOCKS[k], "flips": len(v), "to_avoid": sum(band(x[3]) == "avoid" for x in v),
                          "from_ok": sum(band(x[2]) == "ok" for x in v), "pairs": v} for k, v in flips.items()}
    radar = {"generated_at_ist": out["generated_at_ist"], "fy": out["fy"], "disclaimer": out["disclaimer"], "units": out["units"],
             "geo": out["geo_config"], "reasons": R, "calls": calls, "sectors": sectors, "states": states, "cities": cities,
             "industries": [{k: i.get(k) for k in ("id", "name", "group", "parent", "mapping", "nic", "focus", "series_misfit")} for i in inds],
             "local_news_status": out.get("local_news_status"),
             "credit_regime": out.get("credit_regime"), "wpi": out.get("wpi"), "stress_summary": stress_summary, "ratings_gj": ratings_view, "gnpa_editions": out.get("gnpa_editions")}
    (ROOT / "data" / "radar.json").write_text(json.dumps(radar, separators=(",", ":"), ensure_ascii=False, default=str))
    (ROOT / "data" / "radar_briefs.json").write_text(json.dumps(briefs, separators=(",", ":"), ensure_ascii=False))
    return radar, briefs
