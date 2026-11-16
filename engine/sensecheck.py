"""Proposal Sense-Check: listed-peer benchmarks for the static sensecheck.html page.

Builds data/sensecheck_peers.json from files already in the repo:
  data/detective/evidence.json  (NSE XBRL result filings; every value carries its filing URL)
  data/detective/briefing.json  (universe names, as-of quarter)
  data/detective/raw/*.json     (revenue levels, only to spot suspected half-year figures)
No AI, no network, no invented numbers. Where peers are missing the benchmark is grey.

Benchmark = per-company median over the last 4 reported quarters (to the as-of quarter),
then median / min / max ACROSS companies. At least MIN_COMPANIES companies are needed,
otherwise the metric is grey ("no benchmark").
"""
import json, os, statistics, datetime as dt

ROOT = os.path.join(os.path.dirname(__file__), "..")
D = lambda *p: os.path.join(ROOT, "data", *p)
MIN_COMPANIES = 2
WINDOW_Q = 4
METRICS = {  # metric id in evidence.json -> (label, unit, which way is "optimistic" in a projection)
    "revenue_yoy_pct": ("Sales growth", "%", "high"),
    "ebitda_margin_pct": ("EBITDA margin", "%", "high"),
    "receivable_days": ("Debtor days", "days", "low"),
    "inventory_days_on_sales": ("Inventory days", "days", "low"),
    "interest_cover_x": ("Interest cover (EBITDA / finance cost), context only", "x", None),
}
# Which listed witnesses are the nearest peers for each Lending Radar industry id.
# Fit notes are analytical framing, not data. Industries not listed here show grey.
GROUPS = {
    "textile_chain": {
        "label": "Listed textile chain (Gujarat-linked)",
        "companies": ["FILATEX", "ARVIND", "WELSPUNLIV"],
        "fit": "Nearest listed peers for Surat weaving/processing: Filatex (polyester yarn, Dahej, supplies Surat weavers), "
               "Arvind (fabrics, Ahmedabad), Welspun Living (home textiles, Anjar). Large listed firms, not like-for-like with "
               "an SME weaver: they usually have better scale, pricing and collection, so an SME projecting BETTER numbers than them needs proof.",
    },
    "cotton_chain": {
        "label": "Listed cotton textile peers (Gujarat-linked)",
        "companies": ["ARVIND", "WELSPUNLIV"],
        "fit": "Arvind (denim/woven fabric, Ahmedabad) and Welspun Living (cotton home textiles, Anjar). Integrated exporters, "
               "not spinners or ginners: margins and working capital differ from a standalone spinning or ginning unit.",
    },
    "mmf_yarn": {
        "label": "Listed polyester yarn peer",
        "companies": ["FILATEX"],
        "fit": "Only one listed MMF-yarn witness (Filatex) is in the Detective universe, so flags stay grey; figures shown for context.",
    },
}
INDUSTRY_GROUP = {
    "mmf_textiles": "textile_chain",
    "textile_processing": "textile_chain",
    "technical_textiles": "textile_chain",
    "manmade_fibres": "mmf_yarn",
    "cotton_textiles": "cotton_chain",
    "home_textiles": "cotton_chain",
    "handloom_powerloom": "cotton_chain",
}
TEXTILE_INDUSTRIES = ["mmf_textiles", "textile_processing", "manmade_fibres", "cotton_textiles", "handloom_powerloom",
                      "home_textiles", "technical_textiles", "silk_weaving", "textile_trading", "apparel", "cotton_ginning"]


def qshift(q, n):
    d = dt.date.fromisoformat(q); m = d.month - 1 + 3 * n; y = d.year + m // 12; m = m % 12 + 1
    last = (dt.date(y + (m == 12), m % 12 + 1, 1) - dt.timedelta(days=1)).day
    return dt.date(y, m, last).isoformat()


def suspect_quarters(raw_quarters):
    """Quarters whose revenue is >=1.6x the median of the neighbouring quarters (+/-2): typically a
    half-year (YTD) figure picked up as a quarter. Returned so growth built on them can be excluded."""
    rev = {q: (v.get("m") or {}).get("revenue") for q, v in raw_quarters.items()}
    out = set()
    for q, r in rev.items():
        nb = [rev.get(qshift(q, k)) for k in (-2, -1, 1, 2)]
        nb = [x for x in nb if x]
        if r and len(nb) >= 2 and r >= 1.6 * statistics.median(nb):
            out.add(q)
    return out


def med(xs):
    return round(statistics.median(xs), 2) if xs else None


def build(evidence, briefing, raw):
    asof = briefing["as_of_quarter"]
    window = [qshift(asof, -k) for k in range(WINDOW_Q - 1, -1, -1)]
    fq = {e["period"]: e["fq"] for e in evidence}
    names = {u["sym"]: u for u in briefing.get("universe", [])}
    syms = sorted({s for g in GROUPS.values() for s in g["companies"]})
    companies, obs = {}, {}
    for s in syms:
        u = names.get(s, {})
        companies[s] = {"name": u.get("name", s), "sector": u.get("sector"), "gujarat": u.get("gujarat"),
                        "basis": (raw.get(s) or {}).get("basis")}
        sus = suspect_quarters((raw.get(s) or {}).get("quarters", {}))
        obs[s] = {}
        for m in METRICS:
            rows = []
            for e in evidence:
                if e["company"] != s or e["metric"] != m or e["period"] not in window or e.get("value") is None:
                    continue
                r = {"id": e["id"], "period": e["period"], "fq": e["fq"], "value": round(e["value"], 2),
                     "filed": e.get("filed"), "source": e["source"]}
                if m == "revenue_yoy_pct" and (e["period"] in sus or qshift(e["period"], -4) in sus):
                    r["excluded"] = "suspected half-year (YTD) revenue in the filing feed for this quarter or its year-ago quarter; left out of the benchmark"
                elif e["period"] in sus:
                    r["note"] = "suspected half-year (YTD) figures for this quarter"
                rows.append(r)
            obs[s][m] = sorted(rows, key=lambda r: r["period"])
    bench = {}
    for g, cfg in GROUPS.items():
        bench[g] = {}
        for m, (label, unit, way) in METRICS.items():
            per = {}
            for s in cfg["companies"]:
                vals = [r["value"] for r in obs[s][m] if "excluded" not in r]
                if vals:
                    per[s] = med(vals)
            b = {"label": label, "unit": unit, "optimistic": way, "per_company": per,
                 "periods": sorted({r["fq"] for s in per for r in obs[s][m] if "excluded" not in r},
                                   key=lambda x: (x[-2:], x))}
            if len(per) >= MIN_COMPANIES:
                v = list(per.values())
                b.update(median=med(v), lo=min(v), hi=max(v), n_companies=len(v))
            else:
                b.update(median=None, lo=None, hi=None, n_companies=len(per),
                         grey=f"fewer than {MIN_COMPANIES} listed peers with filings in the window")
            bench[g][m] = b
    return {
        "generated": briefing.get("generated"),
        "as_of_quarter": asof, "as_of_fq": fq.get(asof, briefing.get("as_of_fq")),
        "window": [{"period": q, "fq": fq.get(q, q)} for q in window],
        "method": ("Per company: median of its reported values in the last 4 quarters (working-capital days are "
                   "reported half-yearly, so 1-2 points). Peer median / range = median, min and max of those company "
                   f"medians. Needs >= {MIN_COMPANIES} companies, else grey. Source: NSE XBRL result filings via the "
                   "Detective Engine (data/detective/evidence.json). No AI, no estimates."),
        "no_benchmark": {
            "creditor_days": "Creditor (payables) days are not extracted from the filings yet.",
            "capacity_utilisation": "Listed peers do not report capacity utilisation in XBRL results.",
            "dscr": "DSCR needs repayment schedules that results filings do not carry; interest cover is shown as context only, never used to flag.",
        },
        "groups": GROUPS, "industry_group": INDUSTRY_GROUP, "textile_industries": TEXTILE_INDUSTRIES,
        "companies": companies, "observations": obs, "benchmarks": bench,
    }


def main():
    ev = json.load(open(D("detective", "evidence.json")))
    br = json.load(open(D("detective", "briefing.json")))
    raw = {}
    for s in {s for g in GROUPS.values() for s in g["companies"]}:
        p = D("detective", "raw", s + ".json")
        if os.path.exists(p):
            raw[s] = json.load(open(p))
    out = build(ev, br, raw)
    json.dump(out, open(D("sensecheck_peers.json"), "w"), indent=1, ensure_ascii=False)
    for g, b in out["benchmarks"].items():
        print(g, {m: (x["median"], x["lo"], x["hi"], x["n_companies"]) for m, x in b.items()})


if __name__ == "__main__":
    main()
