"""Lending Radar simple card builder (no network, no AI).

Reads only data the existing refresh jobs already write:
  data/radar.json (calls, reasons, sector drivers, state signals, rating actions, regime evidence),
  data/notes/*.json and data/local_news.json (news, display only: can only make a view more cautious),
  data/detective/raw/*.json (listed-peer NSE filings),
  engine/credit_lens.json + engine/plain_industries.json (descriptive text, no figures).
Writes data/cards/common.json and data/cards/<STATE>.json for lending.html.

Rule enforced here and in engine/tests/test_cards.py: every line that shows a digit carries at least one
source with a URL and a 'data to' date. Descriptive lines carry no digits at all.
"""
import json, re, sys
from datetime import datetime, date, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
OUT = DATA / "cards"
IST = timezone(timedelta(hours=5, minutes=30))
NEWS_STALE_DAYS = 90
METHOD_URL = "methodology.html"
MON = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

# detective (listed-peer filings) -> parent sector; large listed firms, shown for margin direction only
PEERS = {
    "mmf_textiles": ["FILATEX"], "petrochem": ["FILATEX"], "cotton_textiles": ["ARVIND", "WELSPUNLIV"],
    "apparel": ["ARVIND"], "chemicals_dyes": ["ATUL", "AARTIIND"], "ceramics": ["KAJARIACER", "SOMANYCERA"],
    "cement": ["ULTRACEMCO", "AMBUJACEM"], "plastics": ["ASTRAL"], "auto_components": ["MOTHERSON", "BHARATFORG"],
    "engineering": ["ELECON", "THERMAX"], "nbfc": ["CHOLAFIN"],
}
DRIVER_KEYS = [  # (regex on driver text, config weight key, plain label)
    (r"^IIP", "iip_yoy", "the factory-output trend (IIP)"),
    (r"^output .*Apr-to-date", "iip_fytd", "the factory-output trend (IIP)"),
    (r"^exports", "export_fytd_usd", "the export trend"),
    (r"^bank credit", "credit_vs_output", "the bank-credit-versus-output gap"),
    (r"GNPA", "gnpa_trend", "the banks' bad-loan (GNPA) trend for this sector"),
    (r"^input costs", "margin", "the selling-price-versus-input-cost spread (WPI)"),
    (r"GST collections|activity", "activity_proxy", "the activity proxy"),
]
PARTS = {"rates": "repo", "rupee": "inr", "crude": "brent"}
SHOCK = {"brent_up20": "Crude oil (Brent) 20% higher", "inr_down5": "Rupee 5% weaker",
         "repo_up50": "Repo rate up by half a percentage point", "demand_down5": "Output growth five points lower"}
LBL = {"ok": "OK to lend", "caution": "Caution", "avoid": "Avoid", None: "Not scored"}


def jload(p, default=None):
    try:
        return json.loads(Path(p).read_text())
    except Exception:
        return default


def mon_label(iso):
    """'2026-09-30' -> 'Sep 2026'; 'Sep-2026' -> 'Sep 2026'."""
    if not iso:
        return None
    m = re.match(r"(\d{4})-(\d{2})", str(iso))
    if m:
        return f"{MON[int(m.group(2)) - 1]} {m.group(1)}"
    m = re.match(r"([A-Z][a-z]{2})-(\d{4})", str(iso))
    return f"{m.group(1)} {m.group(2)}" if m else str(iso)


def src(name, url, as_of, label=None):
    return {"name": name, "url": url, "as_of": str(as_of) if as_of else None, "label": label or mon_label(as_of)}


def line(t, kind, srcs=None, **kw):
    d = {"t": t, "kind": kind, "src": [s for s in (srcs or []) if s and s.get("url")]}
    d.update(kw)
    return d


def band(sc, th):
    if sc is None:
        return None
    return "ok" if sc >= th["ok"] else ("avoid" if sc < th["avoid"] else "caution")


def plainify(t):
    t = re.sub(r"^India-wide: (.)(.)", lambda m: "India: " + (m.group(1) if m.group(2).isupper() else m.group(1).lower()) + m.group(2), t)
    t = t.replace("Apr-to-date", "so far this financial year").replace(" YoY", " on a year earlier")
    t = re.sub(r"\(Apr-(\d\d)→Sep-(\d\d), ", r"(Apr to Sep 20\2, ", t)
    t = t.replace(" pp ", " percentage points ").replace(" pp)", " percentage points)").replace(" pp,", " percentage points,").replace(" pp;", " percentage points;")
    t = re.sub(r"IIP NIC (\d+) output", r"IIP factory output (industry code \1)", t)
    t = t.replace(" — a local tailwind.", ": helps.").replace(" — a local stress signal.", ": a local stress signal.").replace(" — neutral.", ": neutral.")
    return t


def parse_reason(r):
    """radar.json reason [text, sign, url, scope] -> card line with its own source and date."""
    text, sign, url, scope = (list(r) + [None] * 4)[:4]
    m = re.search(r"\s*\[([^\]]*?)(?:, data to ([A-Za-z]{3}-\d{4}))?\]\s*$", text)
    name, asof, body = (m.group(1), m.group(2), text[: m.start()]) if m else ("source", None, text)
    if name in ("margin",):
        name = "Office of the Economic Adviser, WPI"
    return line(plainify(body.strip()), "data", [src(name, url, asof)], sign=sign, scope=scope)


def strip_digits_clauses(t):
    t = re.sub(r"\s*\([^)]*\d[^)]*\)", "", t or "")
    parts = [p.strip() for p in re.split(r";\s*", t) if p.strip() and not re.search(r"\d", p)]
    s = "; ".join(parts)
    return (s[0].upper() + s[1:] + ("" if s.endswith(".") else ".")) if s else ""


CHECK_FIX = [(r"\s+vs\s+[\d.]+%?(\s*days)?(\s*\(MSME rule\))?", " against your policy limit"),
             (r"top-5", "top five"), (r"top-3", "top three"), (r"next 3 months", "next three months"),
             (r"12-month average", "last year's average"), (r"last 4 quarters", "last four quarters"),
             (r"in the last 12 months", "in the last year"), (r"1-year bucket", "one-year bucket"),
             (r"30\+ dpd", "early-overdue (SMA)"), (r"Form 483 observations", "USFDA inspection observations")]


def plain_check(c):
    for a, b in CHECK_FIX:
        c = re.sub(a, b, c)
    c = c.strip()
    if re.search(r"\d", c):
        return None
    return c[0].upper() + c[1:] + ("" if c.endswith(".") else ".")


# ---------------- listed-peer filings (detective) ----------------
UNIVERSE = {}
try:
    sys.path.insert(0, str(ROOT))
    from engine.detective.universe import UNIVERSE as _U
    UNIVERSE = {u[0]: {"name": u[1], "what": u[2], "link": u[5]} for u in _U}
except Exception:
    pass


def _quarter_vals(q, keys, prev):
    """Quarter values from an NSE XBRL record. A Sep/Mar filing with no YTD figure that is well above the
    previous quarter is a half-year statement: the quarter is that half-year less the previous quarter."""
    m = q["m"]
    vals = {k: m.get(k) for k in keys}
    derived = False
    if prev and m.get("revenue_ytd") is None and m.get("revenue") and prev["m"].get("revenue") \
            and m["revenue"] > 1.6 * prev["m"]["revenue"]:
        vals = {k: (m.get(k) - prev["m"].get(k)) if m.get(k) is not None and prev["m"].get(k) is not None else None for k in keys}
        derived = True
    return vals, derived


def peer_margin(sym):
    d = jload(DATA / "detective" / "raw" / f"{sym}.json")
    if not d or not d.get("quarters"):
        return None
    qs = sorted(d["quarters"])
    def qv(i):
        if i < 0:
            return None
        prev = d["quarters"][qs[i - 1]] if i > 0 else None
        v, der = _quarter_vals(d["quarters"][qs[i]], ["revenue", "ebitda"], prev)
        if not v["revenue"] or v["ebitda"] is None or v["revenue"] <= 0:
            return None
        return {"period": qs[i], "margin": round(100 * v["ebitda"] / v["revenue"], 1), "derived": der,
                "src": d["quarters"][qs[i]].get("src"), "filed": d["quarters"][qs[i]].get("filed")}
    last = qv(len(qs) - 1)
    if not last or not last["src"]:
        return None
    ly = last["period"].replace(last["period"][:4], str(int(last["period"][:4]) - 1), 1)
    prev = qv(qs.index(ly)) if ly in qs else None
    if not prev or not prev["src"]:
        return None
    return {"sym": sym, "last": last, "prev": prev}


def qname(iso):
    y, mth = int(iso[:4]), int(iso[5:7])
    return {3: f"Jan to Mar {y}", 6: f"Apr to Jun {y}", 9: f"Jul to Sep {y}", 12: f"Oct to Dec {y}"}.get(mth, iso)


def filed_date(f):
    try:
        return datetime.strptime(f[:11], "%d-%b-%Y").date().isoformat()
    except Exception:
        return None


def peer_lines(parent):
    out = []
    for sym in PEERS.get(parent, [])[:2]:
        p = peer_margin(sym)
        if not p:
            continue
        u = UNIVERSE.get(sym, {"name": sym, "what": "", "link": ""})
        a, b = p["last"], p["prev"]
        word = "down from" if a["margin"] < b["margin"] else ("up from" if a["margin"] > b["margin"] else "same as")
        der = " (quarter worked out from a half-year filing)" if a["derived"] or b["derived"] else ""
        what = re.sub(r'\s*\(.*?\)', '', u['what']).lower()
        out.append(line(f"Listed peer {u['name']} ({what}): operating margin (EBITDA) {a['margin']}% in {qname(a['period'])}, "
                        f"{word} {b['margin']}% a year earlier{der}. A large listed firm, not an SME: read it for the direction of margins only.",
                        "filing", [src(f"NSE filing, {u['name']}", a["src"], filed_date(a["filed"]) or a["period"], qname(a["period"])),
                                   src(f"NSE filing, {u['name']}", b["src"], filed_date(b["filed"]) or b["period"], qname(b["period"]))]))
    return out


# ---------------- news (display only, can only add caution) ----------------
def _news_items(arts, city_name, state_name, today):
    items = []
    for a in arts or []:
        t, u, dt = a.get("title") or "", a.get("url") or "", a.get("date") or ""
        if not u or not re.match(r"\d{4}-\d{2}-\d{2}$", dt):
            continue
        if a.get("kind") not in (None, "local", "cluster"):
            continue
        if not re.search(re.escape(city_name), t, re.I) and not (state_name and re.search(re.escape(state_name), t, re.I)):
            continue
        age = (today - date.fromisoformat(dt)).days
        items.append({"title": t.split(" | ")[0].strip(), "url": u, "date": dt, "stale": age > NEWS_STALE_DAYS, "age_days": age})
    seen, out = set(), []
    for it in sorted(items, key=lambda x: x["date"], reverse=True):
        if it["url"] in seen:
            continue
        seen.add(it["url"]); out.append(it)
    return out[:4]


def news_for(city, ind_id, state_name, notes, ln, today):
    n = notes.get(f"{city['state']}_{city['id']}_{ind_id}")
    l = ln.get(f"{city['id']}|{ind_id}")
    arts = (n or {}).get("articles", []) + [dict(s, kind="local") for s in (l or {}).get("sources", [])]
    items = _news_items(arts, city["name"], None, today)
    worse = ((n or {}).get("news_direction") == "Worse") or ((l or {}).get("outlook_vs_macro") == "Worse")
    if not items:
        return None
    fresh = [i for i in items if not i["stale"]]
    return {"items": items, "worse": bool(worse), "fresh": bool(fresh),
            "checked": (n or {}).get("generated_at") or (l or {}).get("scanned_ist")}


# ---------------- view per state x parent sector ----------------
def driver_model(sec, wts):
    """Rebuild the national score from the sector drivers (same formula as engine/lending.py)."""
    core, stale, regime = [], [], None
    for dv in sec.get("drivers", []):
        if dv["t"].startswith("Regime"):
            m = re.search(r"= ([+\-]?\d+(?:\.\d+)?) points", dv["t"])
            parts = re.findall(r"(rates|rupee|crude) ([+\-]\d+(?:\.\d+)?)", dv["t"])
            regime = {"pts": float(m.group(1)) if m else 0.0, "parts": [(a, float(b)) for a, b in parts]}
            continue
        key = next(((k, lab) for rx, k, lab in DRIVER_KEYS if re.search(rx, dv["t"])), None)
        if not key:
            continue
        rec = {"key": key[0], "label": key[1], "w": wts.get(key[0], 1.0), "s": dv.get("s"), "d": dv.get("d"), "u": dv.get("u"), "t": dv["t"], "st": dv.get("st")}
        if dv.get("st") == "verified" and dv.get("s") is not None:
            core.append(rec)
        elif dv.get("st") == "stale":
            stale.append(rec)
    return core, stale, regime


def nat_score(core, regime, override=None, extra=None):
    items = [dict(c) for c in core] + list(extra or [])
    for c in items:
        if override and c["key"] == override[0]:
            c["s"] = override[1]
    den = sum(c["w"] for c in items)
    if not den:
        return None
    num = sum(c["w"] * c["s"] for c in items)
    return round(50 + 50 * num / den + (regime["pts"] if regime else 0))


def implied_score(rec, thr):
    m = re.search(r"([+\-]\d+(?:\.\d+)?)%", rec["t"])
    if not m or rec["key"] not in ("iip_yoy", "iip_fytd"):
        return None
    v, t = float(m.group(1)), thr.get(rec["key"], {})
    return 1 if v > t.get("pos_above", 5) else (-1 if v < t.get("neg_below", 0) else 0), v


def evid(R, k):
    e = next((x for x in (R or {}).get("evidence", []) if x.get("k") == k), None)
    return e


def build_view(st_code, st, parent, sec, call, D, cfg, th, updated, ratings):
    base, score, nat, loc, ins, rs = (list(call) + [None] * 6)[:6]
    reasons = [parse_reason(D["reasons"][i]) for i in (rs or []) if i < len(D["reasons"])
               and D["reasons"][i][2] and not re.search(r"\bregime\b", D["reasons"][i][0], re.I)]
    R = D.get("credit_regime") or {}
    view = {"call": base or band(score, th), "score": score, "nat": nat, "adj": (score - nat) if (score is not None and nat is not None) else None,
            "misfit": bool(sec and sec.get("misfit"))}
    eng = src("Lending Radar method", METHOD_URL, updated[:10], f"{int(updated[8:10])} {MON[int(updated[5:7]) - 1]} {updated[:4]} refresh" if re.match(r"\d{4}-\d{2}-\d{2}", updated) else updated)
    if score is None:
        view["why"] = []
        msg = ("The official output series for this group mostly tracks other products, so it does not fit this industry and is not used for a score."
               if view["misfit"] else "Not enough current official data to score this sector. It stays grey until the next releases arrive.")
        view["misfit"] = bool(view["misfit"])
        view["move"] = [line(msg, "engine")]
        view["conf"] = {"level": "none", "text": "No score, so no confidence level."}
        return view
    # ---- why: data lines that moved the score first, then regime, then neutral ones
    why = [r for r in reasons if r.get("sign")]
    core, stale, regime = driver_model(sec, cfg["weights"])
    if regime and regime["pts"]:
        ev = [evid(R, PARTS[n]) for n, _ in regime["parts"] if PARTS.get(n)]
        ev = [e for e in ev if e and e.get("u")]
        what = "; ".join(re.sub(r" \(USD/INR [^)]*\)", "", e["t"].split(" (level")[0]) for e in ev)
        why.append(line(f"Interest rates and the rupee: {what}. For this industry that {'takes' if regime['pts'] < 0 else 'adds'} {abs(regime['pts']):g} points {'off' if regime['pts'] < 0 else 'to'} the score.",
                        "data", [src("RBI" if e["k"] == "repo" else "Market data (checked against RBI reference rate)", e["u"], e["d"]) for e in ev], sign=-1 if regime["pts"] < 0 else 1))
    why += [r for r in reasons if not r.get("sign")]
    if st_code == "GJ" and ratings:
        rv = next((v for v in ratings.get("industries", {}).values() if parent in v.get("engine", [])), None)
        if rv and rv.get("signal") in ("watch", "negative") and rv.get("samples"):
            s0 = rv["samples"][0]
            why.insert(min(2, len(why)), line(
                f"Rating agencies, Gujarat ({rv['label']}): {rv['negative']} of {rv['actions']} rating actions in the last year were negative "
                f"({rv['downgrades']} downgrades, {max(0, rv['negative'] - rv['downgrades'] - rv.get('defaults', 0))} negative outlooks or watches, {rv['upgrades']} upgrades). {'This cuts an OK call to Caution.' if rv['signal'] == 'negative' else 'A watch flag only.'}",
                "rating", [src(f"{s0['agency']} rating rationale, {s0['entity']}", s0["url"], ratings.get("generated"), mon_label(ratings.get("generated")))],
                sign=-1))
    view["why"] = why[:5]
    # ---- confidence from data coverage
    n_nat = len(core); n_state = len([k for k, s in (st.get("signals") or {}).items() if s.get("verified")])
    p = 2 if n_nat >= 3 else (1 if n_nat == 2 else 0)
    if ins == "local" or not n_state:
        p -= 1; cover = f"The figures are national only ({n_nat} current {'series' if n_nat != 1 else 'series'}); there is no usable {st['name']} data"
    else:
        p += 1; cover = f"The figures are national ({n_nat} current series) and {st['name']}-wide ({n_state} series)"
    extra = []
    if stale:
        p -= 1; extra.append(f"{len(stale)} national {'series is' if len(stale) == 1 else 'series are'} out of date")
    gap = min(abs(score - th["ok"]), abs(score - (th["avoid"] - 1)))
    if gap < 5:
        p -= 1; extra.append(f"the score is {gap} {'point' if gap == 1 else 'points'} from a cut-off")
    lvl = "medium" if p >= 3 else "low"   # no city-level official data exists, so never 'high'
    txt = cover + "; there is no {city}-only data for this industry." + (" " + extra[0][0].upper() + extra[0][1:] + (", and " + extra[1] if len(extra) > 1 else "") + "." if extra else "")
    view["conf"] = {"level": lvl, "text": txt, "src": [eng]}
    # ---- what would move the view (computed from the live score, thresholds and drivers)
    b = band(score, th)
    up_need, down_need = th["ok"] - score, score - (th["avoid"] - 1)
    head = (f"Score {score}: " + (f"{up_need} {'point' if up_need == 1 else 'points'} short of OK ({th['ok']} or above), " if b != "ok" else f"{score - th['ok'] + 1} {'point' if score - th['ok'] + 1 == 1 else 'points'} above the OK cut-off ({th['ok']}), ")
            + (f"{down_need} {'point' if down_need == 1 else 'points'} above Avoid (below {th['avoid']})." if b != "avoid" else f"{th['avoid'] - score} {'point' if th['avoid'] - score == 1 else 'points'} below the Avoid cut-off ({th['avoid']})."))
    moves = [line(head, "engine", [eng])]
    adj = view["adj"] or 0
    rebuilt = nat_score(core, regime) if core else None
    cands = []
    if rebuilt is not None and nat is not None and abs(rebuilt - nat) <= 1:
        for c in core:
            for to, verb in ((1, "turns positive"), (-1, "turns negative")):
                if c["s"] == to:
                    continue
                if c["key"] == "gnpa_trend" and to == 1 and not any(o["s"] == 1 for o in core if o is not c):
                    continue  # engine rule: a falling bad-loan ratio alone cannot upgrade a sector
                new = nat_score(core, regime, (c["key"], to)) + adj
                cands.append((new, f"If {c['label']} {verb} (now {'positive' if c['s'] > 0 else 'negative' if c['s'] < 0 else 'neutral'})", [src(c["label"][0].upper() + c["label"][1:], c["u"], c["d"])]))
        back = [(s_, implied_score(s_, cfg["thresholds"])) for s_ in stale]
        back = [(s_, imp) for s_, imp in back if imp and imp[0] != 0]
        if back:
            new = nat_score(core, regime, extra=[dict(s_, s=imp[0]) for s_, imp in back]) + adj
            figs = " and ".join(f"{imp[1]:+g}%" for _, imp in back)
            cands.append((new, f"When the next factory-output (IIP) release is counted (the latest {figs} {'is' if len(back) == 1 else 'are'} out of date, so not scored now) and growth stays this strong",
                          [src("IIP, MoSPI", back[0][0]["u"], back[0][0]["d"])]))
        if regime and regime["pts"] < 0:
            new = nat_score(core, None) + adj
            ev = [evid(R, PARTS[n]) for n, _ in regime["parts"] if PARTS.get(n)]
            cands.append((new, "If RBI pauses or cuts rates and the rupee steadies (removes the rate-and-rupee deduction)",
                          [src("RBI" if e["k"] == "repo" else "Market data", e["u"], e["d"]) for e in ev if e and e.get("u")]))
    for k, dlt in (sec.get("stress") or {}).items():
        dv = dlt["delta"] if isinstance(dlt, dict) else dlt
        if not dv:
            continue
        e = evid(R, {"brent_up20": "brent", "inr_down5": "inr", "repo_up50": "repo"}.get(k, ""))
        cands.append((max(0, min(100, round(score + dv))), f"{SHOCK.get(k, k)}", [src("Today's level", e["u"], e["d"])] if e and e.get("u") else []))
    # prefer moves that change the call, smallest first; otherwise the biggest move that does not
    rank = lambda c: (band(c[0], th) == b, abs(c[0] - score) if band(c[0], th) != b else -abs(c[0] - score))
    ups = sorted([c for c in cands if c[0] > score], key=rank)
    downs = sorted([c for c in cands if c[0] < score], key=rank)
    def fmt(c):
        new, txt, ss = c
        d_ = new - score; nb = band(new, th)
        tail = f"moves to {LBL[nb]}" if nb != b else f"still {LBL[b]}"
        return line(f"{txt}: about {d_:+d} points, to {new}, {tail}.", "engine", ss or [eng], dir="up" if d_ > 0 else "down")
    for grp in (ups, downs):
        for i, c in enumerate(grp[:2]):
            if i == 0 or band(c[0], th) != b:
                moves.append(fmt(c))
    if b == "ok":
        moves.append(line("Fresh local news that conditions are worse would turn OK into Caution. News can never raise a view.", "engine"))
    view["move"] = moves
    return view


def build(today=None, write=True):
    today = today or datetime.now(IST).date()
    D = jload(DATA / "radar.json")
    cfg = jload(ROOT / "engine" / "lending_config.json")
    lens = jload(ROOT / "engine" / "credit_lens.json", {})
    plain = jload(ROOT / "engine" / "plain_industries.json", {"what": {}, "local": {}})
    ln = (jload(DATA / "local_news.json", {}) or {}).get("items", {})
    notes = {}
    for p in (DATA / "notes").glob("*_*.json"):
        if p.name != "index.json":
            n = jload(p)
            if isinstance(n, dict):
                notes[p.stem] = n
    th = {"ok": D["geo"]["ok_at_or_above"], "avoid": D["geo"]["avoid_below"]}
    updated = D.get("generated_at_ist") or ""
    det_fetch = max((jload(p, {}).get("fetched") or "" for p in (DATA / "detective" / "raw").glob("*.json")), default="")
    common = {"updated_ist": updated, "filings_fetched": det_fetch[:10], "built_ist": datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"),
              "thresholds": th, "news_stale_days": NEWS_STALE_DAYS, "industries": {}, "local": {}}
    peers_cache = {}
    for ind in D["industries"]:
        par = ind["parent"]; sec = D["sectors"].get(par, {}); cl = lens.get(par, {})
        if ind["mapping"] == "direct":
            w = cl.get("what") or sec.get("what")
            what = [line(w, "desc")] if w and not re.search(r"\d", w) else []
            drv = [x for x in cl.get("drivers", []) if not re.search(r"\d", x)]
            money = []
            if drv:
                money.append(line(f"Where the margin sits: {drv[0]}." + (f" What decides it: {'; '.join(drv[1:3])}." if len(drv) > 1 else ""), "desc"))
            why = strip_digits_clauses((sec.get("sens") or {}).get("why"))
            if why:
                money.append(line(why, "desc"))
        else:
            w = plain["what"].get(ind["id"])
            what = [line(w, "desc")] if w else []
            foc = strip_digits_clauses(ind.get("focus"))
            money = [line(f"What decides the margin: {foc[0].lower() + foc[1:] if foc[1:2].islower() else foc}", "desc")] if foc else []
            money.append(line(f"Official data covers the wider sector only ({sec.get('name', par)}), not this industry on its own.", "desc"))
        if par not in peers_cache:
            peers_cache[par] = peer_lines(par)
        money += peers_cache[par]
        checks = [c for c in (plain_check(x) for x in (cl.get("checks") or sec.get("checks") or [])) if c]
        common["industries"][ind["id"]] = {"what": what, "money": money, "checks": checks, "proxy": ind["mapping"] != "direct",
                                           "misfit": bool(ind.get("series_misfit") or sec.get("misfit"))}
    for k, v in plain.get("local", {}).items():
        common["local"][k] = {"what": [line(x["t"], x.get("kind", "desc"), x.get("src")) for x in v.get("what", [])],
                              "money": [line(x["t"], x.get("kind", "desc"), x.get("src")) for x in v.get("money", [])],
                              "checks": v.get("checks", [])}
    states = {}
    for st_code, st in D["states"].items():
        cities = [c for c in D["cities"] if c["state"] == st_code]
        if not cities:
            continue
        views = {}
        for par, sec in D["sectors"].items():
            call = D["calls"].get(f"{st_code}|{par}")
            if call is None:
                continue
            views[par] = build_view(st_code, st, par, sec, call, D, cfg, th, updated, D.get("ratings_gj"))
        news = {}
        for c in cities:
            for ind in D["industries"]:
                nw = news_for(c, ind["id"], st["name"], notes, ln, today)
                if nw:
                    news[f"{c['id']}|{ind['id']}"] = nw
        states[st_code] = {"updated_ist": updated, "views": views, "news": news}
    if write:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / "common.json").write_text(json.dumps(common, ensure_ascii=False, separators=(",", ":")))
        for k, v in states.items():
            (OUT / f"{k}.json").write_text(json.dumps(v, ensure_ascii=False, separators=(",", ":")))
    return common, states


if __name__ == "__main__":
    c, s = build()
    print(f"cards: {len(c['industries'])} industries, {len(s)} states, {sum(len(v['views']) for v in s.values())} state-sector views, "
          f"{sum(len(v['news']) for v in s.values())} city-industry news sets; data refresh {c['updated_ist']}")
