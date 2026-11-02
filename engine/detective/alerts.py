"""Working-capital stress alerts (research only; does NOT feed Lending Radar calls; no AI calls).
Compares the latest half-year (Sep or Mar balance sheet) with the SAME half a year earlier."""
import json, os, sys, datetime as dt
sys.path.insert(0, os.path.dirname(__file__))
from universe import UNIVERSE, LENDERS
from build import shift, fy_label, pfiled

CLUSTER = {
 "ARVIND": "Textiles - Ahmedabad", "WELSPUNLIV": "Home textiles - Kutch (Anjar)", "FILATEX": "MMF/polyester - Dahej -> Surat weavers",
 "ATUL": "Chemicals - Valsad/Vapi", "DEEPAKNTR": "Chemicals - Vadodara/Dahej", "AARTIIND": "Chemicals - Vapi/Bharuch-Ankleshwar",
 "NAVINFLUOR": "Chemicals - Surat/Dahej", "KAJARIACER": "Ceramics - Morbi", "SOMANYCERA": "Ceramics - Morbi", "ASIANTILES": "Ceramics - Himmatnagar/Morbi",
 "PETRONET": "Gas/LNG - Dahej (Morbi fuel)", "ULTRACEMCO": "Cement - Gujarat (Saurashtra/Kutch)", "AMBUJACEM": "Cement - Kodinar (Saurashtra)",
 "JKLAKSHMI": "Cement - Kalol/Surat", "ASTRAL": "Pipes/plastics - Ahmedabad", "PIDILITIND": "Chemicals - Vapi/Bharuch", "ASIANPAINT": "Paints - Ankleshwar",
 "MARUTI": "Auto - Hansalpur/Becharaji", "ASHOKLEY": "Auto - CV (national)", "MOTHERSON": "Auto components - Sanand/Becharaji", "BHARATFORG": "Auto components - Sanand supply chain",
 "LT": "Capital goods - Hazira (Surat)", "ELECON": "Capital goods - Vallabh Vidyanagar (Anand)", "THERMAX": "Capital goods - Gujarat projects",
 "CONCOR": "Logistics - Gujarat port hinterland", "GPPL": "Ports - Pipavav (Amreli)", "ADANIPORTS": "Ports - Mundra (Kutch)",
}
THRESH_PP = 10.0

def g(a, b): return (a / b - 1) * 100 if a is not None and b not in (None, 0) and b > 0 else None
def ytd_sum(Q, q, key):
    n = {9: 2, 3: 4}[dt.date.fromisoformat(q).month]
    vals = [(Q.get(shift(q, -k), {}).get("m") or {}).get(key) for k in range(n)]
    return None if any(v is None for v in vals) else sum(vals)

NOTES = {"ASHOKLEY": "Consolidated figures include its lending subsidiary (Hinduja Leyland Finance); loan-book growth depresses OCF - not a pure WC signal.", "PETRONET": "Revenue moves with LNG prices (pass-through), so revenue-vs-inventory gaps are price-driven."}
def company_alert(sym, j):
    Q = {k: v for k, v in j["quarters"].items() if v.get("m")}
    halves = sorted(q for q in Q if dt.date.fromisoformat(q).month in (3, 9) and Q[q]["m"].get("receivables") is not None)
    if not halves: return None
    q = halves[-1]; p = shift(q, -4)
    if p not in Q: return None
    m, pm = Q[q]["m"], Q[p]["m"]
    rev_g = g(m.get("revenue_ytd"), pm.get("revenue_ytd"))
    rec_g = g(m.get("receivables"), pm.get("receivables"))
    inv_g = g(m.get("inventory"), pm.get("inventory"))
    pat, ppat = ytd_sum(Q, q, "pat"), ytd_sum(Q, p, "pat")
    ocf, pocf = m.get("ocf_ytd"), pm.get("ocf_ytd")
    triggers = []
    if rev_g is not None and rec_g is not None and rec_g > 0 and rec_g - rev_g > THRESH_PP:
        triggers.append(f"Receivables {rec_g:+.1f}% vs revenue {rev_g:+.1f}% (gap {rec_g-rev_g:.1f}pp)")
    if rev_g is not None and inv_g is not None and inv_g > 0 and inv_g - rev_g > THRESH_PP:
        triggers.append(f"Inventory {inv_g:+.1f}% vs revenue {rev_g:+.1f}% (gap {inv_g-rev_g:.1f}pp)")
    if None not in (pat, ppat, ocf, pocf) and ppat > 0 and pat >= ppat * 1.10 and ocf < pocf - 0.15 * abs(pocf):
        triggers.append(f"Operating cash flow fell ({pocf:.0f} -> {ocf:.0f} cr) while profit rose ({ppat:.0f} -> {pat:.0f} cr)")
    metrics = dict(revenue_ytd_growth_pct=rev_g, receivables_growth_pct=rec_g, inventory_growth_pct=inv_g,
                   pat_ytd=pat, pat_ytd_prior=ppat, ocf_ytd=ocf, ocf_ytd_prior=pocf)
    metrics = {k: (None if v is None else round(v, 2)) for k, v in metrics.items()}
    return dict(company=sym, period=q, fq=fy_label(q), compared_with=fy_label(p), cluster=CLUSTER.get(sym, "-"),
                triggers=triggers, alert=bool(triggers), note=NOTES.get(sym), metrics=metrics,
                sources=[dict(period=fy_label(q), url=Q[q]["src"], filed=pfiled(Q[q].get("filed") or "", q)),
                         dict(period=fy_label(p), url=Q[p]["src"], filed=pfiled(Q[p].get("filed") or "", p))])

def build_alerts(raw):
    meta = {r[0]: r for r in UNIVERSE}
    rows = []
    for sym, j in sorted(raw.items()):
        if sym in LENDERS: continue  # lender balance sheets have no trade receivables/inventory
        a = company_alert(sym, j)
        if a: a["name"] = meta[sym][1]; rows.append(a)
    return dict(generated=dt.datetime.now(dt.timezone(dt.timedelta(hours=5, minutes=30))).isoformat(timespec="seconds"), research_only=True, ai_calls=0,
                rule=f"Same half-year YoY: receivables or inventory growth exceeds revenue (YTD) growth by >{THRESH_PP:.0f}pp, or YTD operating cash flow falls >15% while YTD profit rises >=10%. Growth in receivables/inventory must itself be positive. Lenders excluded.",
                alerts=[r for r in rows if r["alert"]], checked=len(rows), clear=[r["company"] for r in rows if not r["alert"]])
