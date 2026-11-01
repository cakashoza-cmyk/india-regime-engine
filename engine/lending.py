"""Lending radar: sector Lend / Selective / Avoid from verified, fresh official data.
Decision aid for credit judgment - not a replacement for it.
Run: python engine/lending.py  -> data/lending_latest.json (+ source_health table in regime.db)"""
from __future__ import annotations
import json, sys, uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine import lending_sources as ls
from engine import lending_geo as geo  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
OUT = ROOT / "data" / "lending_latest.json"
UNKNOWN = "Unknown — collect"
SENS = {"energy": {"very_high": 1.0, "high": 1.0, "medium": 0.5}, "wc": {"very_high": 1.0, "high": 1.0}}


def fy_label(d: date) -> str:
    y = d.year if d.month >= 4 else d.year - 1
    return f"FY{str(y + 1)[2:]} (Apr {y}–Mar {y + 1})"


def band(v, pos_above=None, neg_below=None, pos_below=None, neg_above=None):
    if v is None:
        return None
    if pos_above is not None:
        return 1 if v > pos_above else (-1 if v < neg_below else 0)
    return 1 if v < pos_below else (-1 if v > neg_above else 0)


def is_fresh(period_iso, max_age_days, today):
    if not period_iso:
        return False, "no data period"
    age = (today - date.fromisoformat(period_iso)).days
    return (age <= max_age_days), (None if age <= max_age_days else f"stale: period {period_iso} is {age} days old (max {max_age_days})")


def macro_inputs(path=ROOT / "data" / "regime_latest.json"):
    """Only verified, non-stale indicators from the regime engine."""
    if not path.exists():
        return {}
    d = json.loads(path.read_text())
    out = {}
    for i in d.get("indicators", []):
        out[i["indicator"]] = {**{k: i.get(k) for k in ("value", "prior_value", "as_of", "source_url", "status", "is_stale", "source_tier", "note")},
                               "usable": i.get("status") == "verified" and not i.get("is_stale") and i.get("source_tier") in ("official_primary", "market_data")}
    out["_regime"] = {"label": (d.get("detail") or {}).get("full_label") or d.get("regime_label"), "generated": d.get("generated_at_ist")}
    return out


def overlays(sector, macro, th):
    """Macro overlays apply only to sensitive sectors; only from usable (verified+fresh) inputs."""
    res = {}
    e = SENS["energy"].get(sector.get("energy"))
    b = macro.get("brent") or {}
    if e:
        if b.get("usable") and b.get("value") is not None:
            v = b["value"]
            s = -1 if v > th["brent_usd_high"] else (1 if v < th["brent_usd_low"] else 0)
            res["energy_overlay"] = {"score": s * e, "value": round(v, 1), "unit": "USD/bbl", "as_of": b["as_of"], "source_url": b["source_url"], "status": "verified",
                                     "text": f"Brent ${v:.0f}/bbl {'above' if s < 0 else 'below' if s > 0 else 'within'} the ${th['brent_usd_low']:.0f}–{th['brent_usd_high']:.0f} band"}
        else:
            res["energy_overlay"] = {"score": None, "status": "excluded", "text": "Brent not verified/fresh"}
    w = SENS["wc"].get(sector.get("wc_intensity"))
    st, rp = macro.get("rbi_stance_score") or {}, macro.get("repo_rate") or {}
    if w:
        if st.get("usable") and rp.get("usable"):
            rising = rp.get("prior_value") is not None and rp["value"] > rp["prior_value"]
            s = -1 if (st["value"] < 0 and rising) else (1 if st["value"] > 0 else 0)
            res["rate_overlay"] = {"score": s * w, "value": rp["value"], "unit": "% repo", "as_of": rp["as_of"], "source_url": st["source_url"], "status": "verified",
                                   "text": f"Repo {rp['value']}% ({'raised from ' + str(rp['prior_value']) + '%' if rising else 'unchanged/lower'}), RBI stance {'tightening' if st['value'] < 0 else 'easing' if st['value'] > 0 else 'neutral'}"}
        else:
            res["rate_overlay"] = {"score": None, "status": "excluded", "text": "RBI stance/repo not verified"}
    return res


def score_sector(sector, data, macro, cfg, today):
    th, wt = cfg["thresholds"], cfg["weights"]
    srcs = cfg["sources"]
    drivers, excluded = {}, []

    def add(key, val, unit, ds, rec, text):
        ok, why = is_fresh(rec.get("_period"), srcs[ds]["max_age_days"], today)
        if not rec.get("check_ok"):
            ok, why = False, "excluded: failed arithmetic cross-check"
        if val is None:
            ok, why = False, "missing value"
        s = band(val, **({"pos_below": th["credit_vs_output_gap_pp"]["pos_below"], "neg_above": th["credit_vs_output_gap_pp"]["neg_above"]} if key == "credit_vs_output" else th[key])) if ok else None
        drivers[key] = {"score": s, "value": val, "unit": unit, "as_of": rec.get("_period"), "source_url": rec.get("_url"), "dataset": ds,
                        "status": "verified" if ok else ("stale" if why and why.startswith("stale") else "excluded"), "reason": why, "text": text}
        if not ok:
            excluded.append(f"{key}: {why}")

    iip = (data.get("iip_nic2") or {}).get(sector.get("iip_nic") or "")
    exp = (data.get("exports_qe") or {}).get(sector.get("export_row") or -1)
    cr = (data.get("rbi_sibc") or {}).get(sector.get("rbi_row") or "")
    if iip:
        add("iip_yoy", iip["yoy_pct"], "% YoY", "iip_nic2", iip, f"IIP NIC {sector['iip_nic']} output {iip['yoy_pct']:+.1f}% YoY")
        add("iip_fytd", iip["fytd_pct"], "% FYTD", "iip_nic2", iip, f"output {iip['fytd_pct']:+.1f}% Apr-to-date")
    if exp:
        add("export_fytd_usd", exp["usd_fytd_pct"], "% FYTD (USD)", "exports_qe", exp, f"exports {exp['usd_fytd_pct']:+.1f}% Apr-to-date in USD (Rs {exp['inr_fytd_cr']:,.0f} Cr FYTD)")
    act = sector.get("activity")
    arec = ((data.get(act["dataset"]) or {}).get(act["key"]) if act else None)
    if act and arec and arec.get(act["field"]) is not None:
        arec2 = {**arec, "check_ok": arec.get("check_ok", True) and arec.get("fytd_check_ok", True)}
        add("activity_proxy", arec[act["field"]], "% FYTD", act["dataset"], arec2, f"{act['label']} {arec[act['field']]:+.1f}%")
    pc = sector.get("price_controlled")
    if pc:
        excluded.append("credit_vs_output: not used (price-controlled/subsidised sector)")
    if pc:
        pass
    elif cr and iip:
        gap = round(cr["yoy_pct"] - iip["fytd_pct"], 1)
        rec = {**cr, "check_ok": cr["check_ok"] and iip["check_ok"], "_period": min(cr["_period"], iip["_period"])}
        add("credit_vs_output", gap, "pp", "rbi_sibc", rec, f"bank credit {cr['yoy_pct']:+.1f}% YoY vs output {iip['fytd_pct']:+.1f}% (gap {gap:+.1f} pp)")
    elif cr and act and arec and arec.get(act["field"]) is not None:
        gap = round(cr["yoy_pct"] - arec[act["field"]], 1)
        rec = {**cr, "check_ok": cr["check_ok"] and arec.get("check_ok", True), "_period": min(cr["_period"], arec["_period"])}
        add("credit_vs_output", gap, "pp", "rbi_sibc", rec, f"bank credit {cr['yoy_pct']:+.1f}% YoY vs activity {arec[act['field']]:+.1f}% (gap {gap:+.1f} pp)")
    gp = sector.get("_gnpa_points") or []
    if len(gp) >= 2:
        last = gp[-1]
        prev = next((p for p in reversed(gp[:-1]) if p["period"][:3] == last["period"][:3]), gp[0])  # same half-year a year earlier
        mon = {"Mar": "03-31", "Sep": "09-30"}.get(last["period"][:3], "03-31")
        iso = f"20{last['period'][-2:]}-{mon}"
        d = round(last["value"] - prev["value"], 1)
        fresh = (today - date.fromisoformat(iso)).days <= 400
        sc = (-1 if (d >= 0.3 or last["value"] >= 5.0) else (1 if (d <= -0.3 and last["value"] < 3.0) else 0)) if fresh else None
        drivers["gnpa_trend"] = {"score": sc, "value": d, "unit": "pp", "as_of": iso, "source_url": last.get("source_url"), "dataset": "fsr_gnpa",
                                 "status": "verified" if fresh else "stale", "reason": None if fresh else "stale: FSR edition older than 13 months",
                                 "text": f"bank GNPA ratio ({sector.get('_gnpa_cat')}) {last['value']:.1f}% in {last['period']} vs {prev['value']:.1f}% in {prev['period']} ({d:+.1f} pp), RBI FSR"}
        if not fresh:
            excluded.append("gnpa_trend: stale")
    cv = drivers.get("credit_vs_output")
    if cv and cv["score"] is not None and cr and cr.get("yoy_pct") is not None and cr["yoy_pct"] < 0:
        cv["score"] = -1
        cv["text"] += " — bank credit is shrinking: a warning (banks may be exiting), not a positive"
    core = [k for k, v in drivers.items() if v["score"] is not None]
    drivers.update(overlays(sector, macro, th))
    num = sum(wt[k] * drivers[k]["score"] for k in core)
    den = sum(wt[k] for k in core)
    ov = [wt[k] * v["score"] for k, v in drivers.items() if k not in core and v.get("score") is not None]
    ovw = sum(wt[k] for k, v in drivers.items() if k not in core and v.get("score") is not None)
    adj = round(th["overlay_max_points"] * sum(ov) / ovw, 1) if ovw else 0.0
    core_score = round(50 + 50 * num / den) if den else None
    if len(core) < th["min_verified_drivers"] or not den:
        score, verdict = None, UNKNOWN
    else:
        score = max(0, min(100, round(core_score + adj)))
        verdict = "Lend" if score >= th["verdict"]["lend_at_or_above"] else ("Avoid" if score < th["verdict"]["avoid_below"] else "Selective")
    scored = [(k, v) for k, v in drivers.items() if v.get("score") is not None]
    main = max(scored, key=lambda kv: abs(kv[1]["score"] * wt[kv[0]]), default=(None, None))[0]
    return {"id": sector["id"], "name": sector["name"], "cluster": sector["cluster"], "south_gujarat": sector.get("south_gujarat", False),
            "score": score, "core_score": core_score, "overlay_adj": adj, "verdict": verdict, "drivers": drivers, "main_driver": main, "excluded": excluded,
            "why": why_line(verdict, drivers, wt), "credit": cr and {k: cr[k] for k in ("name", "outstanding_cr", "yoy_pct", "fy_pct", "as_of")},
            "rbi_row": sector.get("rbi_row"), "iip_nic": sector.get("iip_nic"), "export_row": sector.get("export_row"),
            "energy": sector.get("energy"), "wc_intensity": sector.get("wc_intensity"), "ews": sector.get("ews"),
            "group": sector.get("group"), "series_misfit": sector.get("series_misfit"), "price_controlled": sector.get("price_controlled"), "guidance": sector.get("guidance", []), "note": sector.get("note"), "commodities": sector.get("commodities", [])}


def why_line(verdict, drivers, wt):
    sc = [(k, v) for k, v in drivers.items() if v.get("score") is not None]
    if verdict == UNKNOWN:
        miss = [k for k, v in drivers.items() if v.get("score") is None and k not in ("energy_overlay", "rate_overlay")]
        return ("Not enough verified, fresh sector data to call it — collect: " + ", ".join(miss) + "." if miss else
                "Only one official sector series (bank credit) is mapped; no output/export series exists for it — collect sector data (e.g. unsold inventory, absorption).")
    pos = [v["text"] for k, v in sorted(sc, key=lambda kv: -kv[1]["score"] * wt[kv[0]]) if v["score"] > 0][:2]
    neg = [v["text"] for k, v in sorted(sc, key=lambda kv: kv[1]["score"] * wt[kv[0]]) if v["score"] < 0][:2]
    head = {"Lend": "Supportive", "Selective": "Mixed", "Avoid": "Weak"}[verdict]
    parts = []
    if pos: parts.append("helped by " + "; ".join(pos))
    if neg: parts.append("held back by " + "; ".join(neg))
    return f"{head}: " + (" — ".join(parts) if parts else "all verified drivers neutral") + "."


def calibration_warnings(cfg, today):
    out = []
    for k in ("weights", "thresholds"):
        lc = cfg[k].get("_last_calibrated")
        if lc and (today - date.fromisoformat(lc)).days > cfg.get("calibration_stale_days", 180):
            out.append(f"CALIBRATION_STALE: {k} last calibrated {lc}")
    return out


def record_health(health, run_id):
    try:
        from engine import db
        c = db.connect()
        db.q(c, "CREATE TABLE IF NOT EXISTS source_health (id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT, ts_ist TEXT, dataset TEXT, source TEXT, ok INTEGER, skipped INTEGER, url TEXT, period TEXT, error TEXT)") if not db.IS_PG else None
        ts = datetime.now(IST).strftime("%Y-%m-%d %H:%M")
        for h in health:
            db.q(c, "INSERT INTO source_health (run_id, ts_ist, dataset, source, ok, skipped, url, period, error) VALUES (?,?,?,?,?,?,?,?,?)",
                 (run_id, ts, h["dataset"], h["source"], int(bool(h["ok"])), int(bool(h.get("skipped"))), h.get("url"), h.get("period"), h.get("error")))
        c.commit()
    except Exception as e:  # noqa: BLE001
        print("WARNING source_health not recorded:", e)


def run(today=None, fetch=True):
    cfg = ls.load_config()
    today = today or datetime.now(IST).date()
    state, health, data, meta = ls.load_state(), [], {}, {}
    validators = {"rbi_sibc": ls.validate_sibc, "iip_nic2": ls.validate_iip, "exports_qe": ls.validate_exports,
                  "gst_state": ls.validate_gst, "power_state": ls.validate_power, "rbi_state": ls.validate_rbi_state}
    accuracy = {}
    for ds, v in validators.items():
        prev = json.loads(json.dumps(state.get(ds))) if state.get(ds) else None
        payload, period, url, sid = ls.discover(ds, cfg, state, health, today, v) if fetch else (
            (state.get(ds) or {}).get("payload"), (state.get(ds) or {}).get("period"), (state.get(ds) or {}).get("url"), "cache")
        if not payload:
            meta[ds] = {"ok": False, "label": cfg["sources"][ds]["label"]}
            continue
        def _rows(payload, period, url):
            src_url = payload.get("release_url") or url
            return src_url, {(int(k) if ds == "exports_qe" else k): {**r, "_period": r.get("as_of") or period, "_url": src_url} for k, r in payload["rows"].items()}
        src_url, rows = _rows(payload, period, url)
        ok, detail = geo.accuracy_checks({ds: rows}).get(ds, (True, "no second-source check defined"))
        accuracy[ds] = {"ok": ok, "detail": detail, "period": period, "kept_last_good": False}
        if not ok:
            if prev and prev.get("payload") and prev.get("period") != period:
                state[ds] = prev
                payload, period, url, sid = prev["payload"], prev["period"], prev["url"], "last_good"
                src_url, rows = _rows(payload, period, url)
                accuracy[ds]["kept_last_good"] = prev["period"]
            else:
                meta[ds] = {"ok": False, "label": cfg["sources"][ds]["label"], "error": "failed accuracy check: " + detail}
                if prev: state[ds] = prev
                continue
        data[ds] = rows
        fresh, why = is_fresh(period, cfg["sources"][ds]["max_age_days"], today)
        meta[ds] = {"ok": True, "label": cfg["sources"][ds]["label"], "period": period, "url": src_url, "via": sid,
                    "fresh": fresh, "stale_reason": why, "file_url": payload.get("xlsx_url"),
                    "tier": cfg["sources"][ds].get("tier"), "report_url": payload.get("report_url"), "year_ago_url": payload.get("year_ago_url"),
                    "checked_ist": (state.get(ds) or {}).get("checked_ist")}
    macro = macro_inputs()
    health.append({"dataset": "macro_engine", "source": "regime_latest", "ok": bool(macro), "error": None if macro else "regime_latest.json missing", "url": "data/regime_latest.json"})
    comms = {}
    if fetch:
        for k, c in cfg["commodities"].items():
            r = ls.yahoo_yoy(c["symbol"])
            health.append({"dataset": "commodities", "source": f"yahoo:{c['symbol']}", "ok": "error" not in r, "error": r.get("error"), "url": r.get("source_url")})
            comms[k] = {**c, **r, "status": "unverified", "source_tier": "market_data", "scored": False}
    else:
        comms = (json.loads(OUT.read_text()).get("commodities") if OUT.exists() else {}) or {}
    # RBI FSR GNPA (display only), parsed once per edition and cached
    fsr_cache = state.setdefault("fsr_gnpa", {})
    for rep in cfg.get("fsr_reports", []):
        if rep["url"] not in fsr_cache and fetch:
            r, err = ls.validate_fsr_gnpa(rep["url"])
            health.append({"dataset": "fsr_gnpa", "source": rep["edition"], "ok": bool(r), "error": err, "url": rep["url"], "period": r and r["period"]})
            if r:
                fsr_cache[rep["url"]] = {**r, "edition": rep["edition"]}
    gnpa_series = sorted([{**v, "url": u} for u, v in fsr_cache.items()], key=lambda x: (int(x["period"][-2:]), x["period"][:3] == "Sep"))
    for s0 in cfg["sectors"]:
        g0 = geo.gnpa_for(cfg, gnpa_series, s0["id"])
        if not s0.get("series_misfit"):
            s0["_gnpa_points"], s0["_gnpa_cat"] = g0.get("points") or [], g0.get("fsr_category")
    sectors = [score_sector(s, data, macro, cfg, today) for s in cfg["sectors"]]
    # monthly credit-growth history (accumulates one point per SIBC release; never back-filled)
    hist = state.setdefault("credit_history", {})
    if data.get("rbi_sibc") and meta.get("rbi_sibc", {}).get("period"):
        hist[meta["rbi_sibc"]["period"]] = {k: v.get("yoy_pct") for k, v in data["rbi_sibc"].items() if isinstance(v, dict) and v.get("check_ok")}
    for s_ in sectors:
        s_["plain"] = geo.plain_summary(s_, cfg["thresholds"])
        s_["gnpa"] = geo.gnpa_for(cfg, gnpa_series, s_["id"])
        row = s_.get("rbi_row")
        s_["credit_trend"] = [{"period": p, "yoy_pct": h.get(row)} for p, h in sorted(hist.items()) if row and h.get(row) is not None][-13:]
    states = geo.state_indicators(cfg, data, meta)
    combos, avoid = geo.build_geo(cfg, sectors, states)
    news_p = ROOT / "data" / "local_news.json"
    news = json.loads(news_p.read_text()) if news_p.exists() else {}
    geo.attach_local(combos, news)
    hl = geo.highlights(cfg, sectors, states, combos)
    run_id = datetime.now(IST).strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex[:6]
    nonfood = (data.get("rbi_sibc") or {})
    out = {
        "generated_at_ist": datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"), "run_id": run_id, "fy": fy_label(today),
        "disclaimer": "Decision aid for credit judgment, not a replacement for it. Internal use only; not loan advice to any outside party.",
        "units": "Rs Cr; Indian FY Apr–Mar; growth % YoY unless stated",
        "regime": macro.get("_regime"),
        "macro": {k: v for k, v in macro.items() if not k.startswith("_") and k in ("cpi_headline", "repo_rate", "rbi_stance_score", "india10y", "credit_growth", "capacity_util", "brent", "usdinr_ref", "iip_yoy", "gst_yoy", "gdp_yoy", "food_inflation")},
        "system_credit": {k: nonfood[k] for k in ("2", "2.1", "2.2", "2.3", "3") if k in nonfood},
        "datasets": meta, "sectors": sectors, "states": states, "clusters": cfg["clusters"], "geo_config": cfg["geo"],
        "combos": combos, "avoid_list": avoid, "highlights": hl, "highlight_rules": cfg["highlight_rules"], "highlight_thresholds": cfg["highlight_thresholds"],
        "accuracy": accuracy, "local_news_status": {k: news.get(k) for k in ("active", "status", "checked_ist", "last_run")}, "gnpa_editions": [{k: g[k] for k in ("edition", "period", "url")} for g in gnpa_series], "commodities": comms,
        "counts": {v: sum(s["verdict"] == v for s in sectors) for v in ("Lend", "Selective", "Avoid", UNKNOWN)},
        "config": {"weights": cfg["weights"], "thresholds": cfg["thresholds"]},
        "missing_sources": cfg["missing_sources"],
        "deepseek": {"enabled": ls.deepseek_available(), "use": "URL discovery and language only; never numbers"},
        "health": health, "warnings": calibration_warnings(cfg, today) + [f"ACCURACY_FAIL: {k}: {a['detail']}" for k, a in accuracy.items() if not a["ok"]] + [f"SOURCE_DOWN: {m['label']}" for m in meta.values() if not m["ok"]],
    }
    for s in out["sectors"]:  # drop internals
        for d in s["drivers"].values():
            d.pop("dataset", None)
    if fetch:
        ls.save_state(state)
        record_health(health, run_id)
    out["avoid_list"] = [{"i": combos.index(c), "rank": c["severity_rank"]} for c in avoid]
    OUT.write_text(json.dumps(out, separators=(",", ":"), default=str, ensure_ascii=False))
    from engine import radar_export
    radar_export.export(out, news)
    return out


if __name__ == "__main__":
    o = run(fetch="--offline" not in sys.argv)
    print(o["counts"], "avoid combos:", len(o["avoid_list"]))
    for s in o["sectors"]:
        print(f"{s['verdict']:<18} {str(s['score']):>4}  {s['name']}  | {s['why']}")
    for w in o["warnings"]:
        print("WARNING", w)
    if any(not a["ok"] for a in o["accuracy"].values()):
        print("ACCURACY GATE FAILED — last good values kept where available")
        sys.exit(2)
