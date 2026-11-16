"""Fetch quarterly result XBRL filings from NSE (official exchange archive) and parse them.
No values are invented: absent tags stay null with a reason."""
import json, os, re, sys, time, datetime as dt, hashlib
import urllib.request, urllib.parse, http.cookiejar
import xml.etree.ElementTree as ET
sys.path.insert(0, os.path.dirname(__file__))
from universe import UNIVERSE, LENDERS

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
RAW = os.path.join(ROOT, "data", "detective", "raw")
CACHE = os.environ.get("DETECTIVE_CACHE", "/workspace/cache/xbrl")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
START = dt.date(2017, 4, 1)

cj = http.cookiejar.CookieJar()
op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
def get(url, tries=3):
    for i in range(tries):
        try:
            r = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://www.nseindia.com/", "Accept": "*/*"})
            return op.open(r, timeout=40).read()
        except Exception as e:
            err = e; time.sleep(2 + 3 * i)
            if i == 1: warm()
    raise err
def warm():
    try: op.open(urllib.request.Request("https://www.nseindia.com/", headers={"User-Agent": UA}), timeout=30).read()
    except Exception: pass

def pdate(s):
    for f in ("%d-%b-%Y", "%d-%B-%Y", "%Y-%m-%d"):
        try: return dt.datetime.strptime(s.strip().title(), f).date()
        except Exception: pass
    return None

def listing(sym):
    out = []
    q = urllib.parse.quote(sym)
    try:
        d = json.loads(get(f"https://www.nseindia.com/api/corporates-financial-results?index=equities&symbol={q}&period=Quarterly"))
        for x in d:
            if x.get("cumulative") == "Cumulative": continue
            u = x.get("xbrl") or ""
            if not u.endswith(".xml"): continue
            out.append({"end": str(pdate(x["toDate"])), "cons": x["consolidated"] == "Consolidated", "xbrl": u,
                        "filed": x.get("filingDate"), "audited": x.get("audited"), "src": "NSE corporates-financial-results"})
    except Exception as e: print(sym, "legacy list fail", e)
    try:
        d = json.loads(get(f"https://www.nseindia.com/api/integrated-filing-results?index=equities&symbol={q}&period_ended=all&type=Integrated%20Filing-%20Financials"))
        for x in d.get("data", []):
            u = x.get("xbrl") or ""
            if not u.endswith(".xml"): continue
            out.append({"end": str(pdate(x["qe_Date"])), "cons": x["consolidated"] == "Consolidated", "xbrl": u,
                        "filed": x.get("broadcast_Date"), "audited": x.get("audited"), "src": "NSE integrated-filing-results"})
    except Exception as e: print(sym, "integrated list fail", e)
    return out

def xml_for(url):
    fn = os.path.join(CACHE, hashlib.md5(url.encode()).hexdigest() + ".xml")
    if os.path.exists(fn) and os.path.getsize(fn) > 500: return open(fn, "rb").read()
    b = get(url); open(fn, "wb").write(b); time.sleep(0.35); return b

def parse(b, qend):
    root = ET.fromstring(b)
    ctx = {}
    for c in root.iter():
        if not c.tag.endswith("}context"): continue
        dim = any(e.tag.endswith(("}segment", "}scenario")) for e in c.iter())
        st = en = ins = None
        for e in c.iter():
            t = e.tag.split("}")[-1]
            if t == "startDate": st = pdate(e.text)
            elif t == "endDate": en = pdate(e.text)
            elif t == "instant": ins = pdate(e.text)
        ctx[c.get("id")] = (dim, st, en, ins)
    q, ytd, inst = {}, {}, {}
    for e in root.iter():
        cr = e.get("contextRef")
        if not cr: continue
        name = e.tag.split("}")[-1]
        try: v = float(e.text)
        except Exception: continue
        # Exchange taxonomy convention: OneD = current quarter, OneI = instant at quarter end,
        # FourD = year-to-date (some files omit or mis-date these contexts, so the id wins).
        if cr == "OneD": q[name] = v; continue
        if cr == "OneI": inst[name] = v; continue
        if cr == "FourD": ytd[name] = v; continue
        if cr not in ctx or ctx[cr][0]: continue
        _, st, en, ins = ctx[cr]
        if ins == qend: inst.setdefault(name, v)
        elif en == qend and st:
            days = (en - st).days
            if 80 <= days <= 95: q.setdefault(name, v)
            if st.month == 4 and st.day == 1: ytd.setdefault(name, v)
    if qend.month == 6:  # Q1: YTD == quarter
        for k, v in q.items(): ytd.setdefault(k, v)
    return q, ytd, inst

def first(d, *names):
    for n in names:
        if n in d: return d[n]
    return None
CR = 1e7
def extract(q, ytd, inst):
    c = lambda v: None if v is None else round(v / CR, 2)
    rev = first(q, "RevenueFromOperations", "TotalRevenueFromOperations")
    oi = first(q, "OtherIncome")
    pbt_pre = first(q, "ProfitBeforeExceptionalItemsAndTax", "ProfitBeforeTax")
    fin = first(q, "FinanceCosts")
    dep = first(q, "DepreciationDepletionAndAmortisationExpense", "DepreciationAndAmortisationExpense")
    ebitda = None
    if None not in (pbt_pre, fin, dep): ebitda = pbt_pre + fin + dep - (oi or 0)
    mat = sum(x for x in [first(q, "CostOfMaterialsConsumed"), first(q, "PurchasesOfStockInTrade"),
               first(q, "ChangesInInventoriesOfFinishedGoodsWorkInProgressAndStockInTrade")] if x is not None) if first(q, "CostOfMaterialsConsumed") is not None else None
    def pair(a, b):
        x, y = first(inst, a), first(inst, b)
        return None if x is None and y is None else (x or 0) + (y or 0)
    return {
        "revenue": c(rev), "other_income": c(oi), "ebitda": c(ebitda), "pat": c(first(q, "ProfitLossForPeriod")),
        "finance_cost": c(fin), "depreciation": c(dep), "material_cost": c(mat),
        "impairment": c(first(q, "ImpairmentOnFinancialInstruments")),
        "interest_income": c(first(q, "InterestIncome")),
        "inventory": c(first(inst, "Inventories")),
        "receivables": c(pair("TradeReceivablesCurrent", "TradeReceivablesNoncurrent")),
        "payables": c(pair("TradePayablesCurrent", "TradePayablesNoncurrent")),
        "debt": c(pair("BorrowingsCurrent", "BorrowingsNoncurrent") if first(inst, "BorrowingsCurrent", "BorrowingsNoncurrent") is not None else first(inst, "Borrowings", "DebtSecurities")),
        "loans": c(first(inst, "Loans")),
        "ocf_ytd": c(first(ytd, "CashFlowsFromUsedInOperatingActivities", "NetCashFlowsFromUsedInOperatingActivities")
                      or first(q, "CashFlowsFromUsedInOperatingActivities", "NetCashFlowsFromUsedInOperatingActivities")),
        "revenue_ytd": c(first(ytd, "RevenueFromOperations")),
        "volume": None,
    }

def run(syms=None, incremental=False):
    """incremental=True: keep every quarter already parsed (last-known-good) and only download
    filings for quarter-ends not yet present. Any per-company failure leaves the old file untouched."""
    os.makedirs(RAW, exist_ok=True); os.makedirs(CACHE, exist_ok=True); warm()
    stats = {"ok": 0, "failed": [], "new_quarters": 0}
    for row in UNIVERSE:
        sym = row[0]
        if syms and sym not in syms: continue
        fn = os.path.join(RAW, sym + ".json")
        old = json.load(open(fn)) if os.path.exists(fn) else None
        try:
            L = [x for x in listing(sym) if x["end"] != "None" and dt.date.fromisoformat(x["end"]) >= START]
            if not L: raise RuntimeError("empty listing (blocked or no filings)")
            if incremental and old and old.get("quarters"):
                basis = old["basis"]
            else:
                nc = len({x["end"] for x in L if x["cons"]}); ns = len({x["end"] for x in L if not x["cons"]})
                basis = "consolidated" if nc >= max(ns - 4, 1) and nc > 0 else "standalone"
            L = [x for x in L if x["cons"] == (basis == "consolidated")]
            byq = {}
            for x in sorted(L, key=lambda x: x["filed"] or ""):  # later filings (revisions) overwrite
                byq[x["end"]] = x
            out = {"symbol": sym, "basis": basis, "fetched": dt.datetime.now().isoformat(timespec="seconds"), "quarters": {}}
            keep = (old or {}).get("quarters", {}) if incremental else {}
            for end, x in sorted(byq.items()):
                if end in keep and keep[end].get("m"):
                    out["quarters"][end] = keep[end]; continue
                try:
                    q, ytd, inst = parse(xml_for(x["xbrl"]), dt.date.fromisoformat(end))
                    out["quarters"][end] = {"m": extract(q, ytd, inst), "src": x["xbrl"], "filed": x["filed"], "feed": x["src"], "audited": x["audited"]}
                    stats["new_quarters"] += 1
                except Exception as e:
                    if end in keep: out["quarters"][end] = keep[end]
                    else: out["quarters"][end] = {"m": None, "src": x["xbrl"], "error": str(e)[:120]}
            for end, v in keep.items(): out["quarters"].setdefault(end, v)  # never drop known-good quarters
            if old and len([v for v in out["quarters"].values() if v.get("m")]) < len([v for v in old["quarters"].values() if v.get("m")]):
                raise RuntimeError("fewer good quarters than last-known-good; keeping old file")
            json.dump(out, open(fn, "w"), indent=0); stats["ok"] += 1
            print(sym, basis, len(out["quarters"]), flush=True)
        except Exception as e:
            stats["failed"].append(sym); print(sym, "FAILED (kept last-known-good):", str(e)[:100], flush=True)
    return stats

if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    st = run(set(args) or None, incremental="--incremental" in sys.argv)
    print("SUMMARY", json.dumps(st))
