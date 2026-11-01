"""Geography layer: state indicators, sector x geography verdicts, Avoid list, highlights,
plain-language summaries, GNPA (RBI FSR), audit rows and the accuracy gate. Pure functions; numbers only
from verified official datasets."""
from engine import lending_sources as ls

UNKNOWN = "Unknown — collect"
LABEL = {"ok": "OK to lend", "caution": "Caution", "avoid": "Avoid"}


def _match(rows, st):
    if not rows:
        return None
    keys = {ls.norm_state(st["name"])} | {ls.norm_state(a) for a in st.get("aliases", [])}
    for k, v in rows.items():
        if ls.norm_state(k) in keys:
            return k, v
    return None


def state_indicators(cfg, data, meta):
    gst, pw, rs = data.get("gst_state") or {}, data.get("power_state") or {}, data.get("rbi_state") or {}
    ig, ip = gst.get("India") or {}, pw.get("India") or {}
    out = {}
    for st in cfg["states"]:
        rec = {"code": st["code"], "name": st["name"], "region": st.get("region"), "signals": {}}
        g = _match(gst, st)
        if g and g[1].get("fytd_pct") is not None:
            v = g[1]
            rec["signals"]["gst"] = {"value": v["fytd_pct"], "india": ig.get("fytd_pct"), "fytd_cr": v.get("fytd_cr"),
                                     "month_yoy_pct": v.get("month_yoy_pct"), "verified": bool(v.get("fytd_check_ok") and v.get("check_ok", True)),
                                     "as_of": (meta.get("gst_state") or {}).get("period"), "source_url": (meta.get("gst_state") or {}).get("url"),
                                     "source_name": "GSTN state-wise GST collections", "label": "GST collections, Apr-to-date growth", "row": g[0]}
        p = _match(pw, st)
        if p and p[1].get("fytd_pct") is not None:
            v = p[1]
            rec["signals"]["power"] = {"value": v["fytd_pct"], "india": ip.get("fytd_pct"), "month_yoy_pct": v.get("month_yoy_pct"),
                                       "verified": bool(v.get("check_ok")), "as_of": (meta.get("power_state") or {}).get("period"),
                                       "source_url": (meta.get("power_state") or {}).get("report_url") or (meta.get("power_state") or {}).get("url"),
                                       "source_name": "CEA Power Supply Position", "label": "Electricity demand, Apr-to-date growth", "row": p[0]}
        r = _match(rs, st)
        if r:
            v = r[1]
            rec["credit"] = {**{k: v.get(k) for k in ("credit_cr", "credit_yoy_pct", "cd_ratio_pct", "industry_credit_cr", "industry_credit_yoy_pct")},
                             "verified": bool(v.get("check_ok")), "as_of": (meta.get("rbi_state") or {}).get("period"),
                             "source_url": (meta.get("rbi_state") or {}).get("url"), "source_name": "RBI Handbook of Statistics on Indian States"}
        out[st["code"]] = rec
    return out


def local_score(si, g):
    """Each verified state signal vs all-India: > +gap pp -> +1, < -gap pp or negative growth -> -1, else 0."""
    parts = []
    for k in ("gst", "power"):
        s = si["signals"].get(k)
        if not s or not s["verified"] or s.get("india") is None:
            continue
        d = round(s["value"] - s["india"], 1)
        sc = -1 if (s["value"] < 0 or d < -g["local_gap_pp"]) else (1 if d > g["local_gap_pp"] else 0)
        parts.append((k, sc, d, s))
    if len(parts) < g["min_local_signals"]:
        return None, parts
    return round(50 + 50 * sum(p[1] for p in parts) / len(parts)), parts


SRC = {"iip_yoy": "IIP, MoSPI", "iip_fytd": "IIP, MoSPI", "export_fytd_usd": "Dept of Commerce", "credit_vs_output": "RBI bank credit vs output",
       "activity_proxy": "official activity proxy", "energy_overlay": "Brent, macro engine", "rate_overlay": "RBI policy, macro engine"}


def _mon(iso):
    import calendar
    try:
        y, m = int(iso[:4]), int(iso[5:7]); return f"{calendar.month_abbr[m]}-{y}"
    except Exception:  # noqa: BLE001
        return iso


def _band(score, g):
    return "ok" if score >= g["ok_at_or_above"] else ("avoid" if score < g["avoid_below"] else "caution")


def _local_text(k, sc, d, s, sname):
    what = "GST collections" if k == "gst" else "electricity demand"
    rel = "faster than" if d > 0 else ("slower than" if d < 0 else "in line with")
    tail = {1: "a local tailwind", -1: "a local stress signal", 0: "neutral"}[sc]
    return (f"{sname}: {what} {s['value']:+.1f}% Apr-to-date vs India {s['india']:+.1f}% "
            f"({abs(d):.1f} pp {rel} India) — {tail}. [{s['source_name']}, data to {_mon(s['as_of'])}]")


def geo_verdict(sector, si, g, geo_name):
    nat = sector.get("score")
    nat_label = sector["verdict"]
    res = {"sector": sector["id"], "geo": geo_name, "national_score": nat, "national_verdict": nat_label}
    if nat is None:
        res.update(call=None, label="Not enough sector data", insufficient="sector",
                   message=f"Not enough verified national data for {sector['name']} — {UNKNOWN}.", reasons=[], score=None)
        return res
    ls_, parts = local_score(si, g)
    nat_call = _band(nat, g)
    reasons = []
    for k, v in sector["drivers"].items():
        if v.get("score") is None:
            continue
        w = (0.2 if k.endswith("overlay") else 1.0) * g["weight_national"]
        reasons.append({"weight": w * (1 if v["score"] else 0.3), "sign": v["score"], "kind": "national", "source_url": v.get("source_url"),
                        "text": f"India-wide: {v['text'][0].upper() + v['text'][1:]}. [{SRC.get(k, k)}, data to {_mon(v.get('as_of'))}]"})
    for k, sc, d, s in parts:
        reasons.append({"weight": g["weight_local"] * 1.5 * (1 if sc else 0.3), "sign": sc, "text": _local_text(k, sc, d, s, si["name"]),
                        "kind": "local", "source_url": s.get("source_url")})
    ls_score = ls_
    final = nat_call if ls_score is None else _band(round(g["weight_national"] * nat + g["weight_local"] * ls_score), g)
    pref = {"ok": 1, "avoid": -1}.get(final)
    reasons.sort(key=lambda r: (-(pref is not None and r["sign"] == pref), -r["weight"]))
    if ls_ is None:
        res.update(call=nat_call, label=LABEL[nat_call], insufficient="local", score=nat,
                   message=f"Not enough local data for {si['name']}. National view: {LABEL[nat_call]} (score {nat}).",
                   local_score=None, reasons=reasons[:4])
        return res
    score = round(g["weight_national"] * nat + g["weight_local"] * ls_)
    call = _band(score, g)
    res.update(call=call, label=LABEL[call], score=score, local_score=ls_, insufficient=None,
               message=f"{LABEL[call]}: national {nat} x {g['weight_national']} + local {ls_} x {g['weight_local']} = {score}.",
               reasons=reasons[:4])
    return res


def build_geo(cfg, sectors, states):
    g = cfg["geo"]
    by = {s["id"]: s for s in sectors}
    combos = []
    for code, si in states.items():
        for s in sectors:
            v = geo_verdict(s, si, g, si["name"])
            v.update(geo_type="state", geo_id=code, state=code)
            combos.append(v)
    for cl in cfg["clusters"]:
        si = states.get(cl["state"])
        if not si:
            continue
        for sid in cl["sectors"]:
            if sid not in by:
                continue
            v = geo_verdict(by[sid], si, g, si["name"])
            v.update(geo_type="cluster", geo_id=cl["id"], state=cl["state"], cluster_name=cl["name"], signals=cl.get("signals"))
            if v.get("message"):
                v["message"] = v["message"].replace(f"for {si['name']}", f"for {cl['name']} ({si['name']})")
            combos.append(v)
    # Avoid list: every cluster x sector Avoid, plus state x sector Avoid where local signals confirm stress (local score < 50)
    avoid = sorted([c for c in combos if c.get("call") == "avoid" and not c.get("insufficient")
                    and (c["geo_type"] == "cluster" or (c.get("local_score") is not None and c["local_score"] < 50))],
                   key=lambda c: (c["score"], c.get("local_score") or 0))
    for i, c in enumerate(avoid, 1):
        c["severity_rank"] = i
    return combos, avoid


def highlights(cfg, sectors, states, combos):
    th, out = cfg["highlight_thresholds"], []
    by = {s["id"]: s for s in sectors}
    def sig(code, k):
        s = (states.get(code) or {}).get("signals", {}).get(k)
        return s if s and s["verified"] else None
    for cl in cfg["clusters"]:
        g, p = sig(cl["state"], "gst"), sig(cl["state"], "power")
        vs = [by[x]["verdict"] for x in cl["sectors"] if x in by]
        if g and "Avoid" in vs and g["value"] < g["india"]:
            out.append({"rule": "stress_cluster", "kind": "stress", "geo": cl["name"],
                        "text": f"{cl['name']}: a sector here is Avoid nationally and {states[cl['state']]['name']} GST is {g['value']:+.1f}% vs India {g['india']:+.1f}% (Apr-to-date)."})
        if g and p and vs and all(v == "Lend" for v in vs) and g["value"] > g["india"] and p["value"] > p["india"]:
            out.append({"rule": "opp_cluster", "kind": "opportunity", "geo": cl["name"],
                        "text": f"{cl['name']}: all sectors Lend nationally; state GST {g['value']:+.1f}% and power {p['value']:+.1f}% both ahead of India."})
        for x in cl["sectors"]:
            d = (by.get(x) or {}).get("drivers", {}).get("credit_vs_output")
            if d and d.get("status") == "verified" and d["value"] > th["credit_heat_pp"]:
                out.append({"rule": "credit_heat", "kind": "stress", "geo": cl["name"],
                            "text": f"{cl['name']} / {by[x]['name']}: bank credit growing {d['value']:+.1f} pp faster than output (India-wide)."})
    for code, si in states.items():
        g, p = sig(code, "gst"), sig(code, "power")
        if g and p and g["value"] < th["state_gst_neg"] and p["value"] < th["state_power_low"]:
            out.append({"rule": "stress_state", "kind": "stress", "geo": si["name"],
                        "text": f"{si['name']}: GST {g['value']:+.1f}% and electricity demand {p['value']:+.1f}% Apr-to-date."})
        if g and p and g["value"] >= th["opp_gst"] and p["value"] >= th["opp_power"]:
            out.append({"rule": "opp_state", "kind": "opportunity", "geo": si["name"],
                        "text": f"{si['name']}: GST {g['value']:+.1f}% and electricity demand {p['value']:+.1f}% Apr-to-date."})
    seen, uniq = set(), []
    for h in out:
        if h["text"] not in seen:
            seen.add(h["text"]); uniq.append(h)
    return uniq


_LENS = None


def _lens(sid):
    global _LENS
    if _LENS is None:
        import json, pathlib
        _LENS = json.loads((pathlib.Path(__file__).with_name("credit_lens.json")).read_text())
    return _LENS.get(sid) or {}


def plain_summary(s, th=None):
    """Deterministic. Numbers are copied from verified drivers; repayment drivers/checks come from the credit lens (analytical framing, not data)."""
    th = th or {}
    L = _lens(s["id"])
    what = L.get("what") or s.get("plain_what") or f"{s['name']}."
    dv = {k: v for k, v in s["drivers"].items() if v.get("status") == "verified" and v.get("value") is not None}
    facts = [f"{v['text']} (data to {_mon(v.get('as_of'))})" for v in dv.values()][:3]
    if s.get("credit"):
        facts.append(f"Bank credit outstanding Rs {s['credit']['outstanding_cr']:,.0f} Cr, {s['credit']['yoy_pct']:+.1f}% YoY (RBI, {_mon(s['credit'].get('as_of'))})")
    facts = facts[:4]
    v, sc = s["verdict"], s.get("score")
    vt = th.get("verdict", {"lend_at_or_above": 65, "avoid_below": 45})
    neg = [x["text"] for x in dv.values() if x.get("score") == -1]
    pos = [x["text"] for x in dv.values() if x.get("score") == 1]
    if v == UNKNOWN:
        why = "Fewer than two checked official series are available, so no call is made."
    else:
        why = (f"Score {sc} (OK to lend at {vt['lend_at_or_above']}+, Avoid below {vt['avoid_below']}). "
               + (f"Supporting: {'; '.join(pos[:2])}. " if pos else "") + (f"Against: {'; '.join(neg[:2])}." if neg else ""))
    flips = []
    rule = {"iip_yoy": ("IIP output YoY", "iip_yoy"), "iip_fytd": ("output Apr-to-date", "iip_fytd"), "export_fytd_usd": ("exports Apr-to-date (USD)", "export_fytd_usd"), "activity_proxy": ("activity proxy", "activity_proxy")}
    for k, x in dv.items():
        if k in rule:
            nm, tk = rule[k]
            t = th.get(tk, {})
            if x.get("score") == -1 and "neg_below" in t:
                flips.append(f"{nm} back above {t['neg_below']:g}% (now {x['value']:+.1f}%)")
            elif x.get("score") == 1 and "pos_above" in t:
                flips.append(f"{nm} falling below {t['pos_above']:g}% (now {x['value']:+.1f}%)")
        if k == "credit_vs_output":
            t = th.get("credit_vs_output_gap_pp", {})
            if x.get("score") == -1 and "neg_above" in t:
                flips.append(f"credit-output gap narrowing below {t['neg_above']:g} pp (now {x['value']:+.1f} pp)")
            elif "pos_below" in t:
                flips.append(f"credit-output gap widening past {t['pos_below']:g} pp (now {x['value']:+.1f} pp)")
    change = ("Thresholds that move the score: " + "; ".join(flips[:3]) + ".") if flips else "Once two official series are checked, a call will be made."
    return {"what": what, "facts": facts, "why": why.strip(), "change_mind": change,
            "watch": L.get("stress", [])[:3], "checks": L.get("checks", [])[:3], "lens_label": "Sector lens: analytical framing, not data"}


def gnpa_for(cfg, gnpa_series, sector_id):
    k = cfg.get("fsr_sector_map", {}).get(sector_id)
    if not k:
        return {"status": UNKNOWN, "points": []}
    pts = [{"period": p["period"], "value": p["gnpa"][k], "edition": p["edition"], "source_url": p["url"]}
           for p in gnpa_series if k in p["gnpa"]]
    return {"fsr_category": k, "points": pts, "tier": "official_primary",
            "status": "verified (RBI FSR chart data label)" if pts else UNKNOWN,
            "note": "RBI FSR 'GNPA ratios of industrial sub-sectors' (%). Half-yearly; one value per edition. Display only — not used in verdicts."}


def accuracy_checks(data):
    """Second-source checks per dataset. Returns {dataset: (ok, detail)}."""
    res = {}
    sib = data.get("rbi_sibc")
    if sib:
        nf = sib.get("2")
        rows = [v for k, v in sib.items() if isinstance(v, dict) and "check_ok" in v]
        share = sum(bool(v["check_ok"]) for v in rows) / max(1, len(rows))
        res["rbi_sibc"] = (bool(nf and nf.get("check_ok")) and share >= 0.9, f"non-food credit YoY recomputed from Rs Cr levels; {share:.0%} rows match")
    for ds, label in (("iip_nic2", "IIP index YoY recomputed from index levels"), ("exports_qe", "exports FYTD totals re-added")):
        d = data.get(ds)
        if d:
            rows = [v for v in d.values() if isinstance(v, dict) and "check_ok" in v]
            share = sum(bool(v["check_ok"]) for v in rows) / max(1, len(rows))
            res[ds] = (share >= 0.8, f"{label}; {share:.0%} rows match")
    g = data.get("gst_state")
    if g:
        rows = [v for k, v in g.items() if k != "India"]
        share = sum(bool(v.get("fytd_check_ok")) for v in rows) / max(1, len(rows))
        res["gst_state"] = (share >= 0.8, f"Table 4 SGST vs Table 2 SGST (independent table); {share:.0%} states match")
    p = data.get("power_state")
    if p:
        rows = [v for k, v in p.items() if k != "India"]
        share = sum(bool(v.get("check_ok")) for v in rows) / max(1, len(rows))
        res["power_state"] = (share >= 0.8, f"requirement − supplied = shortfall identity; {share:.0%} states match")
    r = data.get("rbi_state")
    if r:
        ok = all(v.get("check_ok") for v in r.values())
        res["rbi_state"] = (ok, "sum of states within 2% of All-India total")
    return res


def attach_local(combos, news):
    """Local credit view (news_llm). Rule: 'Worse' can only turn OK-to-lend into Caution; it never creates or removes Avoid,
    and 'Better' never upgrades a call. All hard calls stay data-based."""
    items = (news or {}).get("items", {})
    for c in combos:
        it = items.get(f"{c['geo_id']}|{c['sector']}") if c["geo_type"] == "cluster" else None
        it = it or items.get(f"{c['state']}|{c['sector']}") or items.get(f"{c['state']}|*")
        c["local_view"] = it and {k: it.get(k) for k in ("brief", "analysis", "outlook_vs_macro", "why", "sources", "scanned_ist", "geo_type", "geo_id", "attempts")}
        if it and not it.get("brief") and it.get("prompt_version", 1) >= 2:
            c["local_view"]["outlook_vs_macro"] = None  # rejected by post-check: no tag, no nudge
        c["data_call"] = c.get("call")
        if it and it.get("outlook_vs_macro") == "Worse" and c.get("call") == "ok":
            c["call"], c["label"], c["nudged_by"] = "caution", LABEL["caution"], "local_news"
    return combos
