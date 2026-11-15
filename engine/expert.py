"""Credit Expert View builder (static, no AI, no network).

Reads the files the site already publishes and assembles, for every city x industry pair on the
Lending Radar, a structured note in seven sections:
  1 verdict  2 how to lend  3 industry economics  4 local knowledge  5 red flags & questions
  6 what would change the view  7 evidence & sources
Writes data/expert/index.json (search + navigation), data/expert/kb.json (facts, sources, practice
guidance) and data/expert/<STATE>.json (one view per pair).

Rules carried over from Lending Radar: the verdict is the same call the Radar and Sense-Check show
(same formula); news and ratings can only make it more cautious; unknowns stay grey; every sourced
fact links to its source; practice guidance is labelled and number-free (engine/expert_kb.py).
"""
import json, os, glob, datetime as dt
from engine import expert_kb as K

ROOT = os.path.join(os.path.dirname(__file__), "..")
D = lambda *p: os.path.join(ROOT, "data", *p)
LBL = {"ok": "OK to lend", "caution": "Caution", "avoid": "Avoid", "proxy": "Proxy, not assessed",
       "dealer": "Selective OK: borrower-specific", None: "Not enough data"}
DEALER = {"fuel_stations", "fertiliser"}
BASIS = {"local": "Local assessment", "hub": "Hub, official data", "proxy": "Proxy, not assessed", "dealer": "Dealer: borrower-specific, not scored"}
STRESS_LBL = {"brent_up20": "Brent crude +20%", "inr_down5": "Rupee 5% weaker", "repo_up50": "Repo rate +0.50 pp", "demand_down5": "Demand shock (-5%)"}
GREY = "not yet known"


def load(p, default=None):
    try:
        return json.load(open(p))
    except Exception:
        return default


def band(score, geo):
    if score is None:
        return None
    return "ok" if score >= geo["ok_at_or_above"] else "avoid" if score < geo["avoid_below"] else "caution"


def family_of(ind):
    f = K.IND_FAMILY.get(ind["id"]) or K.IND_FAMILY.get(ind.get("parent"))
    if f:
        return f
    return "generic_mfg" if ind.get("group") in ("Manufacturing", "MSME", "Agri-processing") else "generic_services"


def stance(R, briefs, st, ct, ind, note, city):
    """Same rule as sensecheck.html stance() and lending.html restate()/basisOf()/confOf()."""
    geo = R["geo"]; parent = ind["parent"]; sec = R["sectors"].get(parent, {})
    e = R["calls"].get(st + "|" + parent) or [None, None, None, None, None, []]
    base0, score, nat, local, ins, rs = (list(e) + [None] * 6)[:6]
    base = (base0 or band(score, geo)) if score is not None else None
    misfit = ind.get("series_misfit") or sec.get("misfit")
    if ind["id"] in DEALER:
        basis = "dealer"
    elif misfit:
        basis = "proxy"
    elif note:
        basis = "local"
    elif ind.get("mapping") != "direct" and ind["id"] not in (city.get("hubs") or []):
        basis = "proxy"
    else:
        basis = "hub"
    br = briefs.get(ct + "|" + ind["id"]) or briefs.get(st + "|*")
    if note:
        nudged = base == "ok" and bool(note.get("nudged_by_news") or note.get("news_direction") == "Worse")
    else:
        nudged = base == "ok" and bool(br and br.get("o") == "Worse")
    call = basis if basis in ("proxy", "dealer") else ("caution" if nudged else base)
    conf = None
    if basis not in ("proxy", "dealer") and score is not None:
        dv = [d for d in sec.get("drivers", []) if d.get("st") == "verified" and d.get("s") is not None
              and not any(x in d.get("t", "") for x in ("Brent", "Repo ")) and not d.get("t", "").startswith("Regime")]
        p, why = 0, []
        p += 2 if len(dv) >= 3 else 1 if len(dv) == 2 else 0
        why.append(f"{len(dv)} verified sector series")
        if basis == "local" or ind.get("mapping") == "direct":
            p += 1
        else:
            why.append("parent-sector data")
        if any(d.get("st") == "stale" for d in sec.get("drivers", [])):
            p -= 1; why.append("some data stale")
        m = min(abs(score - geo["ok_at_or_above"]), abs(score - geo["avoid_below"]))
        if m >= 8:
            p += 1
        else:
            p -= 1; why.append(f"score within {m} of a cut-off")
        why.append("banker feedback not counted in this view")
        conf = {"lv": "high" if p >= 4 else "med" if p >= 2 else "low", "why": "; ".join(why)}
    reasons = [R["reasons"][i] for i in (rs or []) if i < len(R["reasons"])]
    return {"call": call, "base": base, "score": score if basis not in ("proxy", "dealer") else None, "ref_score": score,
            "nat": nat, "local": local, "ins": ins, "basis": basis, "nudged": nudged, "conf": conf, "reasons": reasons, "brief": br}


def one_line(s, sec, ind, city, stname, ratings_cut):
    if s["basis"] == "proxy":
        mis = ind.get("series_misfit") or sec.get("misfit")
        ref = f" Parent-sector score {s['ref_score']} is reference only." if s["ref_score"] is not None else ""
        if mis:
            return f"Not scored for {ind['name']} in {city['name']}: the official series does not fit this industry. {mis}{ref}"
        return (f"Not scored for {ind['name']} in {city['name']}: no local note, not a known hub, and no own data series "
                f"for this industry.{ref}")
    if s["basis"] == "dealer":
        return "Dealer business: judged borrower by borrower on throughput and principal support; not scored."
    if s["score"] is None:
        return "Not enough verified data for a call. Unknown: collect."
    adj = s["score"] - (s["nat"] if s["nat"] is not None else s["score"])
    parts = [f"{LBL[s['call']]} {s['score']}/100: national {sec.get('name', ind['name'])} score {s['nat']}"
             f" ({sec.get('verdict', '')}) {'+' if adj >= 0 else ''}{adj} {stname} adjustment."]
    neg = [d for d in sec.get("drivers", []) if d.get("s") is not None and d["s"] < 0 and d.get("st") == "verified"]
    if neg:
        parts.append("Main drag: " + neg[0]["t"] + ".")
    if s["nudged"]:
        parts.append("Local news is worse than the data, so OK becomes Caution.")
    if ratings_cut:
        parts.append("Recent rating actions already cut the state call from OK to Caution.")
    return " ".join(parts)


def stress_lines(sec, s, geo):
    out = []
    if s["score"] is None:
        return out
    for k, d in (sec.get("stress") or {}).items():
        if not d:
            continue
        new = round(s["score"] + d)
        b0, b1 = band(s["score"], geo), band(new, geo)
        out.append({"shock": STRESS_LBL.get(k, k), "points": d, "new_score": new,
                    "flip": None if b0 == b1 else f"{LBL[b0]} -> {LBL[b1]}"})
    return out


def peers_block(P, ind_id):
    g = (P or {}).get("industry_group", {}).get(ind_id)
    if not g:
        return None
    G, BM = P["groups"][g], P["benchmarks"][g]
    comp = {s: {"name": P["companies"][s]["name"], "gujarat": P["companies"][s].get("gujarat")} for s in G["companies"]}
    metrics = {}
    for m, b in BM.items():
        obs = {s: [{"fq": r["fq"], "value": r["value"], "source": r["source"]} for r in P["observations"][s].get(m, []) if "excluded" not in r]
               for s in G["companies"]}
        metrics[m] = {"label": b["label"], "unit": b["unit"], "median": b["median"], "lo": b["lo"], "hi": b["hi"],
                      "n": b["n_companies"], "per_company": b["per_company"], "obs": obs, "grey": b.get("grey")}
    return {"group": g, "label": G["label"], "fit": G["fit"], "companies": comp, "metrics": metrics,
            "window": [w["fq"] for w in P["window"]], "as_of_fq": P["as_of_fq"], "method": P["method"], "no_benchmark": P["no_benchmark"]}


def facts_for(cluster_id, st, ind_group):
    out = []
    for f in K.FACTS:
        cl = f["clusters"]
        if (cluster_id and cluster_id in cl) or ("*GJ_MFG" in cl and st == "GJ" and ind_group in ("Manufacturing", "MSME", "Agri-processing")):
            out.append(f["id"])
    return out


def build():
    R = load(D("radar.json"))
    L = load(D("lending_latest.json"), {})
    P = load(D("sensecheck_peers.json"))
    RG = load(D("ratings_gj.json"), {}) or {}
    briefs = load(D("radar_briefs.json"), {}) or {}
    check = load(D("expert", "source_check.json"), {"sources": {}})
    geo = R["geo"]
    IND = {i["id"]: i for i in R["industries"]}
    CITY = {c["id"]: c for c in R["cities"]}
    FACT = {f["id"]: f for f in K.FACTS}
    pair_cluster = {(ct, i): cid for cid, c in K.CLUSTERS.items() for ct, i in c["pairs"]}
    notes = {}
    for p in glob.glob(D("notes", "*.json")):
        n = load(p)
        if n and n.get("state") and n.get("city") and n.get("ind"):
            notes[(n["state"], n["city"], n["ind"])] = n
    radar_clusters = L.get("clusters", [])
    datasets = [{"label": v.get("label"), "period": v.get("period"), "fresh": v.get("fresh"), "url": v.get("url"),
                 "stale_reason": v.get("stale_reason")} for v in (L.get("datasets") or {}).values()]
    commodities = L.get("commodities", {})
    rg_ind = RG.get("industries", {})
    rg_actions = RG.get("actions", [])
    pairs = set()
    for c in R["cities"]:
        for i in c.get("hubs", []):
            if i in IND:
                pairs.add((c["state"], c["id"], i))
    for (st, ct, i) in notes:
        if ct in CITY and i in IND:
            pairs.add((st, ct, i))
    states, index, sectors_used, peers_used, ratings_used = {}, [], {}, {}, {}
    for (st, ct, i) in sorted(pairs):
        ind, city = IND[i], CITY[ct]
        sec = R["sectors"].get(ind["parent"], {})
        note = notes.get((st, ct, i))
        s = stance(R, briefs, st, ct, ind, note, city)
        stname = R["states"].get(st, {}).get("name", st)
        fam_id = family_of(ind)
        cid = pair_cluster.get((ct, i))
        depth = "full" if cid else ("partial" if st == "GJ" else "standard")
        ratings_cut = (st + "|" + ind["parent"]) in (RG.get("changed_calls") or [])
        fids = facts_for(cid, st, ind.get("group"))
        econ_f = [x for x in fids if FACT[x]["section"] == "economics"]
        local_f = [x for x in fids if FACT[x]["section"] == "local"]
        pb = peers_block(P, i)
        # data-driven sizing anchors for section 2 (from listed-peer filings only)
        anchors = []
        if pb:
            for m in ("receivable_days", "inventory_days_on_sales", "ebitda_margin_pct"):
                b = pb["metrics"].get(m)
                if b and b["median"] is not None:
                    anchors.append({"metric": m, "label": b["label"], "median": b["median"], "lo": b["lo"], "hi": b["hi"], "unit": b["unit"], "n": b["n"]})
        crude = (sec.get("sens") or {}).get("crude")
        comm = []
        fam = K.FAMILIES[fam_id]
        want = set()
        if crude and crude < 0:
            want.add("brent_fut")
        if fam_id in ("textile_weaving", "yarn") and i in ("cotton_textiles", "cotton_ginning", "home_textiles", "handloom_powerloom"):
            want.add("cotton")
        if fam_id == "ceramics":
            want.add("lng_jkm")
        if fam_id == "shipbreaking" or i in ("castings_forgings", "steel_rerolling"):
            want.add("us_hrc")
        for k in sorted(want):
            c = commodities.get(k)
            if c:
                comm.append({"label": c["label"], "value": c["value"], "unit": c.get("unit"), "yoy_pct": c.get("yoy_pct"), "as_of": c.get("as_of"),
                             "url": c.get("source_url"), "status": c.get("status")})
        margin_drv = [d for d in sec.get("drivers", []) if "input costs" in d.get("t", "")]
        rc = [c for c in radar_clusters if c["state"] == st and (i in c["sectors"] or ind["parent"] in c["sectors"])]
        rgk = next((k for k, v in rg_ind.items() if i in v.get("engine", [])), None) or next((k for k, v in rg_ind.items() if ind["parent"] in v.get("engine", [])), None)
        ratings = None
        if st == "GJ" and rgk:
            v = rg_ind[rgk]
            acts = sorted([a for a in rg_actions if a.get("industry") == rgk], key=lambda a: a.get("date", ""), reverse=True)[:10]
            ratings = {"label": v["label"], "signal": v["signal"], "actions": v["actions"], "upgrades": v["upgrades"], "downgrades": v["downgrades"],
                       "defaults": v["defaults"], "inc_new": v["inc_new"], "net_ratio": v.get("net_ratio"), "min_actions": RG.get("min_actions"),
                       "window": f"{RG.get('coverage_from')} to {RG.get('generated')}", "agencies_covered": [a for a, x in (RG.get("agencies") or {}).items() if x.get("status") == "covered"],
                       "list": [{"date": a.get("date"), "entity": a.get("entity"), "city": a.get("city"), "action": a.get("action"), "url": a.get("url"), "counted": a.get("counted")} for a in acts]}
        news = []
        if note:
            news = [{"title": a.get("title"), "url": a.get("url"), "date": a.get("date")} for a in (note.get("articles") or []) if a.get("used") and a.get("url")][:8]
        elif s["brief"]:
            news = [{"title": a.get("title"), "url": a.get("url"), "date": a.get("date")} for a in (s["brief"].get("s") or [])][:8]
        st_sig = []
        for k, sg in (R["states"].get(st, {}).get("signals") or {}).items():
            if sg and sg.get("value") is not None:
                st_sig.append({"label": {"gst": "GST collections, Apr-to-date", "power": "Electricity demand, Apr-to-date"}.get(k, k), "value": sg["value"],
                               "india": sg.get("india"), "as_of": sg.get("as_of"), "url": sg.get("source_url"), "source": sg.get("source_name")})
        view = {
            "key": f"{st}|{ct}|{i}", "st": st, "state": stname, "ct": ct, "city": city["name"], "ind": i, "industry": ind["name"],
            "parent": ind["parent"], "parent_name": sec.get("name"), "mapping": ind.get("mapping"), "nic": ind.get("nic"),
            "depth": depth, "cluster": cid, "cluster_name": K.CLUSTERS[cid]["name"] if cid else None, "family": fam_id,
            "verdict": {"call": s["call"], "label": LBL.get(s["call"], LBL[None]), "score": s["score"], "ref_score": s["ref_score"], "nat": s["nat"],
                        "nat_verdict": sec.get("verdict"), "basis": s["basis"], "basis_label": BASIS[s["basis"]], "conf": s["conf"],
                        "reason": one_line(s, sec, ind, city, stname, ratings_cut), "nudged": s["nudged"],
                        "news_why": (note or {}).get("news_why") if s["nudged"] else None, "ratings_cut": ratings_cut,
                        "refreshed": R.get("generated_at_ist"), "note_at": (note or {}).get("generated_at"),
                        "thresholds": {"ok": geo["ok_at_or_above"], "avoid": geo["avoid_below"]}},
            "lend": {"anchors": anchors},
            "economics": {"what": sec.get("what"), "facts": econ_f, "peers": pb["group"] if pb else None, "commodities": comm,
                          "margin_driver": [{"t": d["t"], "u": d.get("u"), "d": d.get("d"), "st": d.get("st")} for d in margin_drv],
                          "has_capacity": any(FACT[x]["topic"] == "capacity" for x in fids),
                          "has_seasonality": any(FACT[x]["topic"] == "seasonality" for x in fids)},
            "local": {"facts": local_f, "watch": [{"name": c["name"], "signals": c["signals"]} for c in rc],
                      "news": news, "news_direction": (note or {}).get("news_direction") or ((s["brief"] or {}).get("o") if not note else None),
                      "news_why": (note or {}).get("news_why") or ((s["brief"] or {}).get("w") if not note else None),
                      "state_signals": st_sig},
            "redflags": {"sector_checks": sec.get("checks") or []},
            "triggers": {"wrong_if": (sec.get("wrong_if") or {}).get("triggers") or [], "check_back": (sec.get("wrong_if") or {}).get("check_back"),
                         "change": sec.get("change"), "stress": stress_lines(sec, s, geo),
                         "ratings_signal": ratings["signal"] if ratings else None},
            "evidence": {"sector": ind["parent"], "reasons": [{"t": r[0], "sign": r[1], "u": r[2], "kind": r[3] if len(r) > 3 else None} for r in s["reasons"]],
                         "ratings": rgk if ratings else None,
                         "note": {"generated_at": note.get("generated_at"), "tier": note.get("tier"), "score_then": note.get("score"), "call_then": note.get("call")} if note else None},
            "links": {"sensecheck": f"sensecheck.html?state={st}&city={ct}&ind={i}", "lending": f"lending.html?state={st}&city={ct}&ind={i}",
                      "expert": f"expert.html?state={st}&city={ct}&ind={i}"},
        }
        states.setdefault(st, {})[f"{ct}|{i}"] = view
        if pb:
            peers_used.setdefault(st, {})[pb["group"]] = pb
        if ratings:
            ratings_used.setdefault(st, {})[rgk] = ratings
        sectors_used.setdefault(st, {})[ind["parent"]] = {"name": sec.get("name"), "drivers": sec.get("drivers") or [],
                                                           "credit": sec.get("credit"), "gnpa": sec.get("gnpa")}
        index.append({"k": view["key"], "st": st, "stn": stname, "ct": ct, "ctn": city["name"], "ind": i, "indn": ind["name"],
                      "call": s["call"], "score": s["score"], "depth": depth})
    os.makedirs(D("expert"), exist_ok=True)
    gen = R.get("generated_at_ist")
    for st, pv in states.items():
        json.dump({"generated": gen, "state": st, "sectors": sectors_used[st], "peers": peers_used.get(st, {}),
                   "ratings": ratings_used.get(st, {}), "datasets": datasets, "pairs": pv}, open(D("expert", st + ".json"), "w"), ensure_ascii=False, separators=(",", ":"))
    srcs = {}
    for k, v in K.SOURCES.items():
        srcs[k] = dict(v, check=(check.get("sources") or {}).get(k))
    kb = {"generated": gen, "sources": srcs, "facts": {f["id"]: f for f in K.FACTS}, "families": K.FAMILIES,
          "generic_red": K.GENERIC_RED, "generic_q": K.GENERIC_Q, "clusters": K.CLUSTERS,
          "rules": ["Sourced facts carry a verbatim quote and a link; numbers in a fact appear in its quote.",
                    "Practice guidance is general credit practice, labelled, and contains no numbers.",
                    "The verdict is the Lending Radar call; news and rating actions can only make it more cautious.",
                    "Unknowns are shown grey as 'not yet known'. No AI-generated facts."]}
    json.dump(kb, open(D("expert", "kb.json"), "w"), ensure_ascii=False, indent=0)
    st_list = sorted({(x["st"], x["stn"]) for x in index}, key=lambda t: t[1])
    json.dump({"generated": gen, "states": [{"st": a, "name": b} for a, b in st_list], "pairs": index}, open(D("expert", "index.json"), "w"),
              ensure_ascii=False, separators=(",", ":"))
    return index


if __name__ == "__main__":
    import sys
    sys.path.insert(0, ROOT)
    ix = build()
    from collections import Counter
    print(len(ix), "pairs;", Counter(x["depth"] for x in ix), Counter(x["call"] for x in ix))
