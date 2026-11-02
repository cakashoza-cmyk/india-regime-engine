"""Rating-actions signal layer, Gujarat first (refresh + scoring).

Source: CRISIL Ratings public rating-rationale listing and the rationale documents themselves (official agency
press releases). Every action carries agency, date, entity, city (if stated), industry, action and the rationale URL.
Nothing is inferred numerically. DeepSeek (deepseek-flash) is used ONLY to map an entity to an industry from its
'About the Company' text when keyword rules cannot, in small batches; the call count is logged.

Scoring (per industry, 12-month window, 3-month recent count shown):
  counted = upgrades + downgrades + defaults + watch/outlook changes + reaffirmations + new ratings
  negative = downgrades + defaults + negative watch/outlook
  Issuer Not Cooperating (INC) moves are recorded and shown separately, not scored: CRISIL's headline says the rating
  was 'revised'/'migrated' without stating direction, and INC is endemic in the rated MSME book (it would swamp every
  industry). An explicit downgrade or a 'Crisil D' under INC is still counted as a downgrade/default.
  net ratio = (negative - upgrades) / counted;  minimum 5 counted actions else 'insufficient' (grey).
  'Rating continues in INC' reviews and withdrawals are recorded but not counted: they are not new information.
  Signal: ratio >= RED -> 'negative' (OK becomes Caution); ratio >= WATCH -> 'watch' (flag only). It never upgrades.
"""
from __future__ import annotations
import html, json, os, re, sys, time, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "ratings_gj.json"
SEEN = ROOT / "data" / "cache" / "ratings_seen.json"
LIST_URL = ("https://www.crisilratings.com/bin/crisil/listing/rating_sme_listing_service.json?cmd=RR&resourcePath="
            "/content/crisilratings/en/home/our-business/ratings/rating-rationale/jcr:content/wrapper_100_par/ratingresultlisting")
DOC_URL = "https://www.crisilratings.com/mnt/winshare/Ratings/RatingList/RatingDocs/"
UA = {"User-Agent": "Mozilla/5.0 (LendingRadar research; weekly)"}
MIN_ACTIONS, WATCH, RED = 5, 0.15, 0.30
WINDOW_DAYS, RECENT_DAYS = 365, 92
MAX_FETCH = 1200  # per run, newest first; CRISIL rate-limits (~2 docs/s), the rest is back-filled on later runs

# Gujarat industries asked for, mapped to engine keys (industry ids or parent sectors) where they exist
INDUSTRIES = {
    "mmf_textiles": {"label": "Surat MMF: weaving, processing, embroidery", "engine": ["mmf_textiles", "textile_processing", "manmade_fibres", "textile_trading"],
                     "kw": ["polyester", "synthetic", "man-made", "manmade", "viscose", "nylon", "embroider", "weaving", "processing house", "dyeing and printing", "printed fabric", "grey fabric", "art silk", "sarees", "dress material"]},
    "diamonds": {"label": "Diamonds & jewellery", "engine": ["diamonds", "diamond_trading", "gold_jewellery"], "kw": ["diamond", "jewellery", "jewelry", "gems"]},
    "ceramics": {"label": "Morbi ceramics, tiles, sanitaryware", "engine": ["ceramics"], "kw": ["ceramic", "tiles", "vitrified", "sanitaryware", "sanitary ware", "porcelain"]},
    "chemicals_dyes": {"label": "Chemicals & dyes (Vapi, Ankleshwar, Bharuch)", "engine": ["chemicals_dyes", "specialty_chemicals", "agrochemicals", "petrochem"],
                       "kw": ["chemical", "dyes", "dyestuff", "pigment", "intermediates", "agrochemical", "pesticide", "solvent", "resin"]},
    "pharma": {"label": "Pharma (Ahmedabad, Vadodara)", "engine": ["pharma", "api_bulk_drugs", "formulations"], "kw": ["pharma", "drug", "formulation", "api ", "active pharmaceutical", "medicine"]},
    "plastics": {"label": "Plastics & polymers", "engine": ["plastics", "plastic_packaging", "pvc_pipes"], "kw": ["plastic", "polymer", "pvc", "hdpe", "pp woven", "polypropylene", "polyethylene", "masterbatch", "packaging film"]},
    "engineering": {"label": "Engineering (Rajkot)", "engine": ["engineering", "castings_forgings", "pumps_valves", "machine_tools"], "kw": ["engineering", "casting", "forging", "pump", "valve", "machine", "machinery", "fabrication"]},
    "auto_components": {"label": "Auto components", "engine": ["auto_components", "vehicle_oem"], "kw": ["auto component", "automobile component", "auto part", "automotive"]},
    "nonferrous_brass": {"label": "Brass parts (Jamnagar)", "engine": ["nonferrous_brass", "fasteners_hardware"], "kw": ["brass", "copper", "non-ferrous"]},
    "salt": {"label": "Salt", "engine": [], "kw": ["salt pan", "salt manufactur", "common salt", "industrial salt", "edible salt", "refined salt", "salt works", "producer of salt", "manufactures salt"]},
    "edible_oil": {"label": "Edible oil", "engine": ["edible_oil"], "kw": ["edible oil", "groundnut oil", "cottonseed oil", "soybean oil", "castor oil", "oil mill", "solvent extraction", "refined oil", "oilseed"]},
    "cotton_textiles": {"label": "Cotton: ginning, spinning", "engine": ["cotton_textiles", "cotton_ginning"], "kw": ["ginning", "cotton bales", "cotton yarn", "spinning", "cotton seed", "cotton"]},
    "shipbreaking": {"label": "Shipbreaking (Alang)", "engine": ["shipbuilding"], "kw": ["ship breaking", "ship-breaking", "shipbreaking", "ship recycling"]},
    "cement": {"label": "Cement", "engine": ["cement"], "kw": ["cement", "clinker"]},
    "ports_logistics": {"label": "Logistics & ports (Kandla, Mundra)", "engine": ["ports", "logistics_warehousing", "transport_ops"], "kw": ["port", "ports", "logistics", "warehousing", "freight", "container freight", "shipping agency", "transporter", "transportation services", "road transport"]},
}
ORDER = ["shipbreaking", "diamonds", "ceramics", "salt", "pharma", "edible_oil", "cement", "mmf_textiles", "cotton_textiles", "nonferrous_brass",
         "auto_components", "plastics", "chemicals_dyes", "ports_logistics", "engineering"]  # most specific first
CITIES = ["Surat", "Ahmedabad", "Vadodara", "Baroda", "Rajkot", "Morbi", "Morvi", "Jamnagar", "Bharuch", "Ankleshwar", "Vapi", "Bhavnagar", "Alang",
          "Gandhidham", "Kandla", "Mundra", "Gondal", "Mehsana", "Anand", "Gandhinagar", "Valsad", "Navsari", "Junagadh", "Porbandar", "Kutch", "Bhuj",
          "Dahej", "Halol", "Sanand", "Unjha", "Wankaner", "Himmatnagar", "Palanpur", "Amreli", "Botad", "Kadi", "Kalol", "Nadiad", "Surendranagar", "Dhrangadhra", "Godhra", "Veraval"]


def classify_action(heading, text=""):
    """From the agency's own headline (and the rationale table for INC revisions). Returns (action, counted, negative)."""
    h = heading.split(":", 1)[-1].lower() if ":" in heading else heading.lower()
    inc = "not cooperating" in h
    if re.search(r"crisil d\b|crisil d[ /']|\bdefault", h):
        return "default", True, True
    if "downgraded" in h:
        return ("downgrade_inc" if inc else "downgrade"), True, True
    if "upgraded" in h:
        return "upgrade", True, False
    if "watch" in h and "negative" in h:
        return "watch_negative", True, True
    if "watch" in h and ("positive" in h or "developing" in h):
        return "watch_positive" if "positive" in h else "watch_developing", True, False
    if "outlook revised" in h:
        m = re.search(r"outlook revised to[^;]*?(negative|positive|stable)", h)
        d = m.group(1) if m else ""
        return ("outlook_" + (d or "changed")), True, d == "negative"
    if inc and "continue" in h:
        return "inc_continues", False, False
    if inc and ("migrated" in h or "revised" in h):
        return "inc_new", False, False  # issuer stopped sharing information: recorded, not scored (see module doc)
    if "migrated" in h and "not cooperating" in text[:3000].lower():
        return "inc_new", False, False
    if "withdrawn" in h:
        return "withdrawn", False, False
    if "reaffirmed" in h:
        return "reaffirm", True, False
    if "assigned" in h:
        return "assigned", True, False
    return "other", False, False


def _text(u):
    for a in range(6):
        try:
            t = urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=60).read().decode("utf-8", "ignore")
            break
        except Exception as e:  # noqa: BLE001
            if "429" in str(e) and a < 5:
                time.sleep(5 * (a + 1)); continue
            return None
    t = re.sub(r"<(script|style).*?</\1>", " ", t, flags=re.S | re.I)
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t)))


def extract(doc):
    """Gujarat test: 'Gujarat' (or a Gujarat city) must appear in the company's own 'About the Company' paragraph."""
    u = DOC_URL + urllib.parse.quote(doc["ratingFileName"])
    t = _text(u)
    if t is None:
        return {"prId": doc["prId"], "err": True}
    i = t.find("About the Company")
    i = i if i >= 0 else t.find("About the")
    about = t[i:i + 900] if i >= 0 else ""
    time.sleep(1.5)  # polite: CRISIL throttles bursts (HTTP 429)
    r = {"prId": doc["prId"], "url": u, "gj": "Gujarat" in about}
    if r["gj"]:
        r["about"], r["head"] = about, t[:1500]
    return r


def city_of(about):
    for c in CITIES:
        if re.search(r"\b" + c + r"\b", about):
            return {"Baroda": "Vadodara", "Morvi": "Morbi"}.get(c, c)
    return None


def industry_kw(about):
    a = about.lower()
    if re.search(r"\b(colleges?|schools?|university|universities|educational|charitable trust|hospitals?)\b", a):
        return None  # institutions: left to the classifier, never keyword-matched to an industry
    for k in ORDER:
        if any(re.search(r"\b" + re.escape(w.strip()) + (r"\b" if k == "ports_logistics" else ""), a) for w in INDUSTRIES[k]["kw"]):
            return k
    return None


def industry_llm(batch, log):
    """Small batches; returns {prId: key or 'other'}. Only language classification, never numbers."""
    if not os.environ.get("DEEPSEEK_API_KEY") or not batch:
        return {}
    from engine.search_adapter import chat_json
    keys = list(INDUSTRIES) + ["other"]
    sysm = ("Classify each company into exactly one industry key from this list, using only the description given: " + ", ".join(keys) +
            ". Use 'other' if none fits. Return JSON {\"m\": {id: key}}.")
    out = {}
    for j in range(0, len(batch), 40):
        part = batch[j:j + 40]
        try:
            r = chat_json(sysm, json.dumps({b["prId"]: b["about"][:400] for b in part}), max_tokens=900)
            log["deepseek_calls"] += 1
            out.update({k: v for k, v in (r.get("m") or {}).items() if v in keys})
        except Exception as e:  # noqa: BLE001
            log["deepseek_calls"] += 1; log["errors"].append(f"deepseek: {e}"[:120])
    return out


def fetch_list(stop_before):
    docs, s = [], 0
    while True:
        u = f"{LIST_URL}&start={s}&limit={s + 1000}"
        for a in range(6):
            try:
                d = json.load(urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=120)).get("docs") or []
                break
            except Exception as e:  # noqa: BLE001
                if "429" in str(e) and a < 5:
                    time.sleep(20 * (a + 1)); continue
                raise
        if not d:
            break
        docs += d; s += 1000
        if datetime.strptime(d[-1]["ratingDate"], "%b %d, %Y").date() < stop_before:
            break
        time.sleep(1)
    return docs


def score(actions, today):
    res = {}
    for k, meta in INDUSTRIES.items():
        a12 = [a for a in actions if a["industry"] == k and (today - date.fromisoformat(a["date"])).days <= WINDOW_DAYS]
        cnt = [a for a in a12 if a["counted"]]
        up = sum(a["action"] == "upgrade" for a in cnt)
        dn = sum(a["action"] in ("downgrade", "downgrade_inc") for a in cnt)
        df = sum(a["action"] == "default" for a in cnt)
        inc = sum(a["action"] == "inc_new" for a in a12)
        neg = sum(a["negative"] for a in cnt)
        ratio = round((neg - up) / len(cnt), 2) if cnt else None
        sig = "insufficient" if len(cnt) < MIN_ACTIONS else ("negative" if ratio >= RED else "watch" if ratio >= WATCH else "neutral")
        rec = sorted(a12, key=lambda a: a["date"], reverse=True)
        samples = [a for a in rec if a["negative"]][:3] or rec[:3]
        res[k] = {"label": meta["label"], "engine": meta["engine"], "actions": len(cnt), "recorded": len(a12),
                  "upgrades": up, "downgrades": dn, "defaults": df, "inc_new": inc, "inc_continues": sum(a["action"] == "inc_continues" for a in a12),
                  "negative": neg, "recent_3m": sum(1 for a in cnt if (today - date.fromisoformat(a["date"])).days <= RECENT_DAYS),
                  "net_ratio": ratio, "signal": sig,
                  "samples": [{f: s[f] for f in ("agency", "date", "entity", "city", "action", "url")} for s in samples]}
    return res


def apply_to_calls(calls, sig, state="GJ"):
    """Rating actions can only make a call more cautious: OK -> Caution on a 'negative' signal. Never upgrades."""
    changed = []
    for k, s in (sig or {}).items():
        if s["signal"] != "negative":
            continue
        for e in s["engine"]:
            key = f"{state}|{e}"
            c = calls.get(key)
            if c and c[0] == "ok":
                c[0] = "caution"; changed.append(key)
    return changed


def refresh(today=None, workers=1, docs_cache=None, max_fetch=MAX_FETCH, list_cache=None):
    today = today or date.today()
    log = {"deepseek_calls": 0, "errors": [], "fetched": 0}
    seen = json.loads(SEEN.read_text()) if SEEN.exists() else {"non_gj": [], "gj": {}}
    prev = json.loads(OUT.read_text()) if OUT.exists() else {"actions": []}
    known = set(seen["non_gj"]) | set(seen["gj"])
    lst = json.loads(Path(list_cache).read_text()) if list_cache else fetch_list(today - timedelta(days=WINDOW_DAYS + 7))
    todo = [d for d in lst if d["prId"] not in known]
    cache = {}
    if docs_cache:  # optional pre-fetched extracts (same format as extract())
        for l in open(docs_cache):
            r = json.loads(l)
            if "err" not in r: cache[r["prId"]] = r
    need_fetch = [d for d in todo if d["prId"] not in cache and classify_action(d["heading"])[0] != "inc_continues"][:max_fetch]
    with ThreadPoolExecutor(workers) as ex:
        for r in ex.map(extract, need_fetch):
            log["fetched"] += 1
            if not r.get("err"): cache[r["prId"]] = r
    byid = {d["prId"]: d for d in lst}
    acts = {a["prId"]: a for a in prev.get("actions", [])}
    new_gj = []
    for d in todo:
        r = cache.get(d["prId"])
        if r is None:
            continue  # not fetched (INC continuation or fetch error): retried next run
        if not (r.get("gj") and "Gujarat" in r.get("about", "")):
            seen["non_gj"].append(d["prId"]); continue
        act, counted, neg = classify_action(d["heading"], r.get("head", ""))
        a = {"prId": d["prId"], "agency": "CRISIL", "date": datetime.strptime(d["ratingDate"], "%b %d, %Y").date().isoformat(),
             "entity": d["companyName"], "city": city_of(r["about"]), "industry": industry_kw(r["about"]), "industry_by": "keywords",
             "action": act, "counted": counted, "negative": neg, "headline": d["heading"].split(":", 1)[-1].strip()[:200], "url": r["url"]}
        if a["industry"] is None:
            new_gj.append((a, r))
        acts[a["prId"]] = a
        seen["gj"][d["prId"]] = 1
    llm = industry_llm([{"prId": a["prId"], "about": r["about"]} for a, r in new_gj], log)
    for a, _ in new_gj:
        k = llm.get(a["prId"])
        a["industry"], a["industry_by"] = (k if k and k != "other" else None), ("deepseek" if k else "unmapped")
    done = set(seen["non_gj"]) | set(seen["gj"])
    pend = [d for d in lst if d["prId"] not in done and classify_action(d["heading"])[0] != "inc_continues"]
    dts = sorted(datetime.strptime(d["ratingDate"], "%b %d, %Y").date() for d in lst if d["prId"] in done)
    # coverage: contiguous from today back to just after the newest not-yet-read rationale
    newest_pending = max((datetime.strptime(d["ratingDate"], "%b %d, %Y").date() for d in pend), default=None)
    coverage_from = (newest_pending + timedelta(days=1)).isoformat() if newest_pending else (dts[0].isoformat() if dts else None)
    log["pending_backfill"] = len(pend)
    cutoff = (today - timedelta(days=WINDOW_DAYS)).isoformat()
    actions = sorted([a for a in acts.values() if a["date"] >= cutoff], key=lambda a: a["date"], reverse=True)
    out = {"generated": today.isoformat(), "coverage_from": coverage_from, "window_days": WINDOW_DAYS, "recent_days": RECENT_DAYS, "min_actions": MIN_ACTIONS,
           "thresholds": {"watch": WATCH, "negative": RED},
           "agencies": {"CRISIL": {"status": "covered", "source": "crisilratings.com rating-rationale listing + rationale documents"},
                        "ICRA": {"status": "not covered", "why": "rating list is JavaScript/session-driven; no public feed found in this pass"},
                        "CARE": {"status": "not covered", "why": "press-release listing URL returned 404 to a plain fetch"},
                        "India Ratings": {"status": "not covered", "why": "listing is client-rendered; no public feed found in this pass"},
                        "Acuité": {"status": "not covered", "why": "press-release listing URL returned 404"},
                        "Infomerics": {"status": "not covered", "why": "press-release listing URL returned 404"},
                        "Brickwork": {"status": "not covered", "why": "public list has ratings but no action dates or locations"}},
           "method": __doc__.split("Scoring", 1)[1].strip(), "log": {**log, "listed": len(lst), "new": len(todo)},
           "industries": score(actions, today), "actions": actions}
    OUT.write_text(json.dumps(out, indent=1, ensure_ascii=False))
    SEEN.write_text(json.dumps(seen))
    print(f"ratings_gj: {len(actions)} Gujarat actions, deepseek calls {log['deepseek_calls']}, fetched {log['fetched']}")
    return out


def load():
    return json.loads(OUT.read_text()) if OUT.exists() else None


if __name__ == "__main__":
    a = sys.argv[1:]
    refresh(docs_cache=a[a.index("--cache") + 1] if "--cache" in a else None,
            max_fetch=int(a[a.index("--max-fetch") + 1]) if "--max-fetch" in a else MAX_FETCH,
            list_cache=a[a.index("--list") + 1] if "--list" in a else None)
