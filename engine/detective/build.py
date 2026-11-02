"""Economic Detective Engine - phase 1 (research only, does NOT feed Lending Radar calls).
Three record types, strictly separated:
  EVIDENCE   - facts computed directly from exchange XBRL filings (with source URL + filing date)
  MODEL      - rule-based company-level inferences that cite evidence ids (never reused as evidence)
  HYPOTHESIS - economy-wide claims needing >=3 independent channels, with alternatives,
               a 'wrong if' test and a check date.
No AI calls are made here (ai_calls logged as 0)."""
import json, os, sys, glob, datetime as dt, statistics as st
sys.path.insert(0, os.path.dirname(__file__))
from universe import UNIVERSE, LENDERS

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
D = os.path.join(ROOT, "data", "detective")
META = {r[0]: dict(sym=r[0], name=r[1], sector=r[2], channel=r[3], factor=r[4], gujarat=r[5], rel=r[6]) for r in UNIVERSE}
LAG_DAYS = 50  # fallback availability lag if a filing date is missing

def qkey(d): return d if isinstance(d, str) else d.isoformat()
def shift(q, n):
    d = dt.date.fromisoformat(q); m = d.month + 3 * n; y = d.year + (m - 1) // 12; m = (m - 1) % 12 + 1
    last = {3: 31, 6: 30, 9: 30, 12: 31}[m]; return dt.date(y, m, last).isoformat()
def fy_label(q):
    d = dt.date.fromisoformat(q); fy = d.year + (1 if d.month > 3 else 0); qn = {6: 1, 9: 2, 12: 3, 3: 4}[d.month]
    return f"Q{qn}FY{str(fy)[2:]}"
def pfiled(s, q):
    for f in ("%d-%b-%Y %H:%M", "%d-%b-%Y %H:%M:%S", "%d-%b-%Y"):
        try: return dt.datetime.strptime(s.strip(), f).date().isoformat()
        except Exception: pass
    return (dt.date.fromisoformat(q) + dt.timedelta(days=LAG_DAYS)).isoformat()
def pct(hist, v):
    """Percentile of v versus the company's OWN prior history (expanding window, no look-ahead)."""
    h = [x for x in hist if x is not None]
    if len(h) < 4 or v is None: return None
    return round(100 * sum(1 for x in h if x <= v) / len(h))

def load():
    out = {}
    for fn in sorted(glob.glob(os.path.join(D, "raw", "*.json"))):
        j = json.load(open(fn)); out[j["symbol"]] = j
    return out

def build(raw, asof=None):
    ev, models, gaps = [], [], {}
    eid = 0
    def add(sym, q, metric, value, prior, hist, unit, rec, extra_src=None):
        nonlocal eid
        if value is None: return None
        eid += 1
        p = pct(hist, value)
        e = dict(id=f"E{eid:05d}", company=sym, period=q, fq=fy_label(q), metric=metric, value=round(value, 2),
                 prior=None if prior is None else round(prior, 2), percentile=p, unit=unit,
                 direction=None if prior is None else ("up" if value > prior else "down" if value < prior else "flat"),
                 source=rec["src"], filed=pfiled(rec.get("filed") or "", q), feed=rec.get("feed"))
        ev.append(e); return e
    for sym, j in raw.items():
        Q = {k: v for k, v in j["quarters"].items() if v.get("m")}
        qs = sorted(Q)
        gaps[sym] = {"basis": j["basis"], "quarters": len(qs), "first": qs[0] if qs else None, "last": qs[-1] if qs else None,
                     "missing_quarters": [], "balance_sheet_points": 0, "ocf_points": 0,
                     "volume": "not in exchange XBRL; disclosed only in investor presentations (not parsed in phase 1)"}
        if qs:
            q = qs[0]
            while q <= qs[-1]:
                if q not in Q: gaps[sym]["missing_quarters"].append(q)
                q = shift(q, 1)
        hist = {k: [] for k in ["rev_yoy", "margin", "margin_chg", "mat_ratio_chg", "accel", "rec_days", "inv_days", "cash_conv", "cost_ratio", "icr"]}
        lender = sym in LENDERS
        cc_prev = {}
        for q in qs:
            if asof and q > asof: break
            rec = Q[q]; m = rec["m"]; py = Q.get(shift(q, -4), {}).get("m")
            row = {"q": q, "filed": pfiled(rec.get("filed") or "", q), "ev": {}}
            def A(metric, val, prior, unit, hk):
                e = add(sym, q, metric, val, prior, hist[hk] if hk else [], unit, rec)
                if e: row["ev"][metric] = e
                if hk and val is not None: hist[hk].append(val)
                return e
            rev, prev = m.get("revenue"), (py or {}).get("revenue")
            yoy = (rev / prev - 1) * 100 if rev and prev and prev > 0 else None
            A("revenue_yoy_pct", yoy, None, "%", "rev_yoy")
            # acceleration: change in YoY growth vs two quarters earlier
            p2 = Q.get(shift(q, -2), {}).get("m"); p6 = Q.get(shift(q, -6), {}).get("m")
            yoy2 = (p2["revenue"] / p6["revenue"] - 1) * 100 if p2 and p6 and p2.get("revenue") and p6.get("revenue") and p6["revenue"] > 0 else None
            if yoy is not None and yoy2 is not None: A("revenue_growth_accel_pp", yoy - yoy2, yoy2, "pp", "accel")
            if lender:
                ii, imp, loans = m.get("revenue"), m.get("impairment"), m.get("loans")
                if ii and imp is not None:
                    cr = imp / ii * 100; pcr = (py["impairment"] / py["revenue"] * 100) if py and py.get("impairment") is not None and py.get("revenue") else None
                    A("credit_cost_pct_of_revenue", cr, pcr, "%", "cost_ratio")
            else:
                if rev and m.get("ebitda") is not None:
                    mg = m["ebitda"] / rev * 100
                    pmg = py["ebitda"] / py["revenue"] * 100 if py and py.get("ebitda") is not None and py.get("revenue") else None
                    A("ebitda_margin_pct", mg, pmg, "%", "margin")
                    if pmg is not None: A("ebitda_margin_yoy_bp", (mg - pmg) * 100, None, "bp", "margin_chg")
                if rev and m.get("material_cost") is not None and py and py.get("material_cost") is not None and py.get("revenue"):
                    A("material_cost_ratio_yoy_pp", m["material_cost"] / rev * 100 - py["material_cost"] / py["revenue"] * 100, None, "pp", "mat_ratio_chg")
                if m.get("ebitda") is not None and m.get("finance_cost"):
                    A("interest_cover_x", m["ebitda"] / m["finance_cost"], None, "x", "icr")
                ry = m.get("revenue_ytd"); days = {9: 183, 3: 365}.get(dt.date.fromisoformat(q).month)
                if ry and days:
                    pm = py or {}; pdays = days
                    def dd(k):
                        return pm[k] / pm["revenue_ytd"] * pdays if pm.get(k) is not None and pm.get("revenue_ytd") else None
                    # compared with the SAME half-year a year earlier (Sep vs Sep, Mar vs Mar) to avoid seasonality
                    if m.get("receivables") is not None:
                        gaps[sym]["balance_sheet_points"] += 1
                        A("receivable_days", m["receivables"] / ry * days, dd("receivables"), "days", "rec_days")
                    if m.get("inventory") is not None:
                        A("inventory_days_on_sales", m["inventory"] / ry * days, dd("inventory"), "days", "inv_days")
                    if m.get("ocf_ytd") is not None:
                        eb = [Q.get(shift(q, -k), {}).get("m", {}) or {} for k in range({9: 2, 3: 4}[dt.date.fromisoformat(q).month])]
                        if all(x.get("ebitda") is not None for x in eb):
                            ey = sum(x["ebitda"] for x in eb)
                            if ey > 0:
                                gaps[sym]["ocf_points"] += 1
                                e = A("cash_conversion_ocf_to_ebitda", m["ocf_ytd"] / ey, cc_prev.get((dt.date.fromisoformat(q).month, dt.date.fromisoformat(q).year - 1)), "x", "cash_conv")
                                cc_prev[(dt.date.fromisoformat(q).month, dt.date.fromisoformat(q).year)] = m["ocf_ytd"] / ey
            models.extend(infer(sym, row))
    return ev, models, gaps

def infer(sym, row):
    """Rule-based company inferences. Each cites evidence ids. Polarity: stress or strength."""
    E = row["ev"]; out = []; meta = META[sym]
    def M(rule, polarity, family, cites, text):
        out.append(dict(id=f"M-{sym}-{row['q']}-{rule}", company=sym, period=row["q"], fq=fy_label(row["q"]), available=max(c["filed"] for c in cites),
                        rule=rule, polarity=polarity, family=family, channel=meta["channel"], factor=meta["factor"],
                        evidence=[c["id"] for c in cites], text=text))
    g, a = E.get("revenue_yoy_pct"), E.get("revenue_growth_accel_pp")
    if g and a and g["percentile"] is not None and g["percentile"] <= 25 and a["value"] <= -8:
        M("demand_deceleration", "stress", "demand", [g, a], f"Revenue growth {g['value']:.1f}% YoY, bottom quartile of own history, slowing {a['value']:.1f}pp")
    if g and a and g["percentile"] is not None and g["percentile"] >= 75 and a["value"] >= 8:
        M("demand_acceleration", "strength", "recovery", [g, a], f"Revenue growth {g['value']:.1f}% YoY, top quartile of own history, accelerating {a['value']:.1f}pp")
    mc, mr = E.get("ebitda_margin_yoy_bp"), E.get("material_cost_ratio_yoy_pp")
    if mc and mc["value"] <= -200 and mr and mr["value"] >= 1.5:
        M("input_cost_margin_squeeze", "stress", "input_cost", [mc, mr], f"EBITDA margin {mc['value']:.0f}bp YoY with material cost ratio +{mr['value']:.1f}pp")
    elif mc and mc["value"] <= -300 and g and g["value"] < 5:
        M("operating_deleverage", "stress", "demand", [mc, g], f"EBITDA margin {mc['value']:.0f}bp YoY on weak revenue ({g['value']:.1f}%)")
    rd, idd, cc = E.get("receivable_days"), E.get("inventory_days_on_sales"), E.get("cash_conversion_ocf_to_ebitda")
    if rd and rd["prior"] is not None and rd["value"] - rd["prior"] >= 10:
        M("receivable_stretch", "stress", "liquidity", [rd], f"Receivable days {rd['value']:.0f} vs {rd['prior']:.0f} a year earlier (same half)")
    if idd and idd["prior"] is not None and idd["value"] - idd["prior"] >= 15:
        M("inventory_build", "stress", "demand", [idd], f"Inventory days {idd['value']:.0f} vs {idd['prior']:.0f} a year earlier (same half)")
    if cc and cc["value"] < 0.5 and cc["prior"] is not None and cc["value"] < cc["prior"] - 0.2:
        M("profit_not_cash", "stress", "liquidity", [cc] + ([g] if g else []), f"OCF only {cc['value']:.2f}x of EBITDA (YTD) vs {cc['prior']:.2f}x a year earlier")
    cr = E.get("credit_cost_pct_of_revenue")
    if cr and cr["percentile"] is not None and cr["percentile"] >= 80 and cr["prior"] is not None and cr["value"] > cr["prior"] * 1.25:
        M("lender_credit_cost_spike", "stress", "liquidity", [cr], f"Credit cost {cr['value']:.1f}% of revenue vs {cr['prior']:.1f}% a year ago")
    return out

FAMILIES = {
 "demand": "Broad demand slowdown is under way before official data confirms it",
 "input_cost": "An input-cost squeeze is compressing margins across independent industries",
 "liquidity": "Working-capital and credit stress is building (profits not turning into cash)",
 "recovery": "A broad demand recovery is under way",
}
ALTS = {
 "demand": ["High base effect from a strong prior year", "Company-specific market-share loss", "Price deflation (volumes may be fine; volume data not parsed)"],
 "input_cost": ["Commodity spike that will pass through with a lag (temporary)", "Inventory-valuation timing", "Mix change toward lower-margin products"],
 "liquidity": ["Seasonal year-end receivable build", "Deliberate channel financing to gain share", "Acquisition consolidating a higher-receivable business"],
 "recovery": ["Low base effect from a weak prior year", "Price inflation rather than volume", "Pre-buying ahead of a price increase or policy change"],
}
WRONG_IF = {
 "demand": "Revenue growth re-accelerates (>= +8pp) at a majority of flagged companies within 2 quarters",
 "input_cost": "Material-cost ratios fall back and margins recover >= 150bp YoY within 2 quarters",
 "liquidity": "Receivable days and OCF/EBITDA normalise to below the 60th percentile at the next half-year",
 "recovery": "YoY growth falls back below the own-history median at most flagged companies within 2 quarters",
}

def stage_for(ms, universe_size_by_factor):
    """Breadth with common-factor discount: a factor group counts as ONE clue, and only if
    at least half of its members (min 1) are flagged. Stage 1-5."""
    by_f = {}
    for m in ms: by_f.setdefault(m["factor"], set()).add(m["company"])
    groups = [f for f, s in by_f.items() if len(s) >= max(1, universe_size_by_factor.get(f, 1) / 2)]
    raw_groups = list(by_f)
    chans = {next(m["channel"] for m in ms if m["factor"] == f) for f in groups}
    n, c = len(groups), len(chans)
    if n == 0: s = 1 if raw_groups else 0
    elif n == 1: s = 1
    elif n == 2 or c < 2: s = 2
    elif c < 3: s = 3
    else: s = 4
    return s, groups, sorted(chans)

def timeline(models, quarters, uni):
    rows = {}
    for fam in FAMILIES:
        prev = 0; rows[fam] = []
        for q in quarters:
            ms = [m for m in models if m["family"] == fam and m["period"] == q]
            s, groups, chans = stage_for(ms, uni)
            if s == 4 and prev >= 4: s = 5  # sustained across 2 consecutive quarters
            avail = max([m["available"] for m in ms], default=None)
            rows[fam].append(dict(q=q, fq=fy_label(q), stage=s, groups=groups, channels=chans, companies=sorted({m["company"] for m in ms}), available=avail, models=[m["id"] for m in ms]))
            prev = s
    return rows

EVENTS = [
 dict(id="FY20_slowdown", name="FY19-20 slowdown / IL&FS", family=["demand", "liquidity"], window=("2018-09-30", "2020-03-31"),
      consensus="2019-08-30", consensus_note="Q1FY20 GDP print of 5.0% (MoSPI, 30 Aug 2019) made the slowdown consensus; IL&FS defaulted Sep 2018"),
 dict(id="COVID", name="COVID shock Q1FY21", family=["demand"], window=("2020-03-31", "2020-09-30"),
      consensus="2020-03-24", consensus_note="National lockdown announced 24 Mar 2020 (exogenous - no lead expected)"),
 dict(id="FY22_recovery", name="FY22 recovery", family=["recovery"], window=("2021-03-31", "2022-03-31"),
      consensus="2021-08-31", consensus_note="Q1FY22 GDP print (+20.1%, MoSPI 31 Aug 2021) - base-effect-laden"),
 dict(id="FY23_input_cost", name="FY23 input-cost squeeze", family=["input_cost"], window=("2021-12-31", "2023-03-31"),
      consensus="2022-06-14", consensus_note="WPI peaked at 15.9% for May 2022 (OEA release 14 Jun 2022)"),
]

MISS_REASON = {"FY20_slowdown": "Structural data miss: NSE XBRL quarterly P&L starts Q4FY18, so YoY growth exists only from Q4FY19 and the own-history percentile needs 4 more points (first usable ~Q3FY20). Balance-sheet and cash-flow XBRL start only around FY21-FY23, so the liquidity detectors could not see IL&FS-era stress at all."}
def backtest(tl):
    res, falses = [], []
    for ev in EVENTS:
        best = None
        for fam in ev["family"]:
            for r in tl[fam]:
                if ev["window"][0] <= r["q"] <= ev["window"][1] and r["stage"] >= 3 and r["available"]:
                    if best is None or r["available"] < best["available"]: best = dict(r, family=fam)
        if best:
            lead = (dt.date.fromisoformat(ev["consensus"]) - dt.date.fromisoformat(best["available"])).days
            res.append(dict(event=ev["id"], name=ev["name"], hit=True, family=best["family"], first_signal_quarter=best["fq"], signal_available=best["available"],
                            stage=best["stage"], consensus=ev["consensus"], consensus_note=ev["consensus_note"], lead_days=lead,
                            verdict="lead" if lead > 0 else "lag"))
        else:
            res.append(dict(event=ev["id"], name=ev["name"], hit=False, consensus=ev["consensus"], consensus_note=ev["consensus_note"], verdict="miss",
                            reason=MISS_REASON.get(ev["id"], "No family reached stage 3 inside the window")))
    for fam in FAMILIES:
        for r in tl[fam]:
            if r["stage"] < 3: continue
            inside = any(fam in e["family"] and e["window"][0] <= r["q"] <= e["window"][1] for e in EVENTS)
            if not inside:
                note = "Stage>=3 outside every pre-registered event window - counted as a false alarm"
                if fam == "demand" and "2024-06-30" <= r["q"] <= "2025-03-31":
                    note += "; coincides with the FY25 H1 slowdown (Q2FY25 GDP 5.4%, MoSPI 29 Nov 2024), which was not in the pre-registered event list"
                if fam == "input_cost" and r["q"] == "2021-09-30":
                    note += "; one quarter before the pre-registered FY23 squeeze window (arguably early, still counted as false)"
                falses.append(dict(family=fam, quarter=r["fq"], q=r["q"], stage=r["stage"], channels=r["channels"], companies=r["companies"], note=note))
    return res, falses

def hypotheses(tl, models_by_id, ev_by_id, asof_q):
    hs = []
    for fam, rows in tl.items():
        r = next((x for x in rows if x["q"] == asof_q), None)
        if not r or r["stage"] < 1: continue
        ms = [models_by_id[i] for i in r["models"]]
        cites = []
        for m in ms:
            for e in m["evidence"]: cites.append(e)
        contra = [m for m in models_by_id.values() if m["period"] == asof_q and m["family"] != fam and (
            (fam in ("demand", "liquidity", "input_cost") and m["polarity"] == "strength") or (fam == "recovery" and m["polarity"] == "stress"))]
        check = shift(asof_q, 2)
        hs.append(dict(id=f"H-{fam}-{asof_q}", family=fam, statement=FAMILIES[fam], as_of=r["fq"], stage=r["stage"],
                       is_hypothesis=r["stage"] >= 4, label="Hypothesis (>=3 independent channels)" if r["stage"] >= 4 else "Lead only - fewer than 3 independent channels",
                       channels=r["channels"], counted_groups=r["groups"], companies=r["companies"], models=r["models"], evidence=cites,
                       contradictions=[c["id"] for c in contra], alternatives=ALTS[fam], wrong_if=WRONG_IF[fam],
                       check_after=f"results for {fy_label(check)} (period ending {check}, filed ~{(dt.date.fromisoformat(check)+dt.timedelta(days=50)).isoformat()})"))
    return hs

def failed_log(tl):
    """Every stage>=3 lead is a dated prediction. If, two quarters later, the same family has
    dropped to stage<=1 and the event was not a labelled episode, it is logged as failed."""
    log = []
    for fam, rows in tl.items():
        for i, r in enumerate(rows):
            if r["stage"] >= 3 and i + 2 < len(rows):
                later = rows[i + 2]
                inside = any(fam in e["family"] and e["window"][0] <= r["q"] <= e["window"][1] for e in EVENTS)
                if later["stage"] <= 1 and not inside:
                    log.append(dict(family=fam, raised=r["fq"], stage=r["stage"], checked=later["fq"], outcome="failed - signal faded within 2 quarters, no labelled episode"))
    return log

def main():
    raw = load()
    ev, models, gaps = build(raw)
    quarters = sorted({m["period"] for m in models} | {e["period"] for e in ev})
    uni = {}
    for s in raw: uni[META[s]["factor"]] = uni.get(META[s]["factor"], 0) + 1
    tl = timeline(models, quarters, uni)
    bt, falses = backtest(tl)
    # latest quarter with broad reporting (>= 60% of companies filed)
    cnt = {q: len({e["company"] for e in ev if e["period"] == q}) for q in quarters}
    asof_q = max(q for q in quarters if cnt[q] >= 0.6 * len(raw))
    mb = {m["id"]: m for m in models}; eb = {e["id"]: e for e in ev}
    hs = hypotheses(tl, mb, eb, asof_q)
    used_e = {e for h in hs for e in h["evidence"]}; used_m = {m for h in hs for m in h["models"]} | {c for h in hs for c in h["contradictions"]}
    for m in models:
        if m["id"] in used_m: used_e.update(m["evidence"])
    out = dict(generated=dt.datetime.now(dt.timezone(dt.timedelta(hours=5, minutes=30))).isoformat(timespec="seconds"), as_of_quarter=asof_q, as_of_fq=fy_label(asof_q), ai_calls=0,
               research_only=True, universe=list(META.values()), coverage=gaps, hypotheses=hs, timeline=tl, backtest=bt,
               false_alarms=falses, failed_predictions=failed_log(tl),
               models_current=[m for m in models if m["id"] in used_m],
               evidence_cited={i: eb[i] for i in sorted(used_e)},
               counts=dict(evidence=len(ev), models=len(models), companies=len(raw)))
    json.dump(out, open(os.path.join(D, "briefing.json"), "w"), separators=(",", ":"))
    from alerts import build_alerts
    al = build_alerts(raw); out["wc_alerts"] = al
    json.dump(al, open(os.path.join(D, "alerts.json"), "w"), indent=1)
    json.dump(out, open(os.path.join(D, "briefing.json"), "w"), separators=(",", ":"))
    json.dump(ev, open(os.path.join(D, "evidence.json"), "w"), separators=(",", ":"))
    json.dump(models, open(os.path.join(D, "models.json"), "w"), separators=(",", ":"))
    print(json.dumps(dict(asof=fy_label(asof_q), counts=out["counts"], bt=bt, falses=len(falses), failed=len(out["failed_predictions"]),
                          hyps=[(h["family"], h["stage"], h["channels"]) for h in hs]), indent=1))

if __name__ == "__main__":
    main()
