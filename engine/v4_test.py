"""v4 QUALITY TEST: deep local-news brief for exactly 3 cards. Manual run only (workflow v4-test.yml).
News = news_llm (unverified). Numbers in the brief must trace to a fetched article, the data pack, or the market table.
News can only nudge OK -> Caution, never upgrade."""
from __future__ import annotations
import json, re, sys, time
from datetime import datetime, timedelta, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine import search_adapter as sa  # noqa: E402
IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime.now(IST)
CUTOFF = (NOW - timedelta(days=95)).strftime("%Y-%m-%d")
CALLS = {"search": 0, "fetch": 0, "chat": 0, "fetch_fallback_plain": 0}
CARDS = [
 {"key": "gj_surat|mmf_textiles", "state": "GJ", "city": "Surat", "label": "Surat - MMF / polyester weaving & processing", "call_key": "GJ|mmf_textiles", "mkt": "mmf",
  "q": ["Surat weavers powerloom polyester yarn price payment 2026", "Surat textile processing dyeing mills GPCB closure effluent",
        "SGCCI FOGWA Surat weaving industry demand", "Surat textile market traders payment dues fraud weavers",
        "સુરત વિવિંગ ઉદ્યોગ મંદી યાર્ન", "સુરત ડાઇંગ મિલ પ્રોસેસિંગ હાઉસ", "सूरत कपड़ा उद्योग बुनकर मंदी",
        "timesofindia Surat textile weavers", "Surat textile exports US tariff orders powerloom units shut"]},
 {"key": "gj_morbi|ceramics", "state": "GJ", "city": "Morbi", "label": "Morbi - ceramic tiles & sanitaryware", "call_key": "GJ|ceramics", "mkt": "ceramics",
  "q": ["Morbi ceramic industry gas price units shut 2026", "Morbi Ceramic Association exports tiles demand", "Morbi ceramic plants shutdown production cut",
        "મોરબી સિરામિક ઉદ્યોગ ગેસ ભાવ", "મોરબી સિરામિક એકમો બંધ", "मोरबी सिरेमिक उद्योग मंदी",
        "timesofindia Rajkot Morbi ceramic", "Morbi ceramic GPCB NGT pollution coal gasifier", "Morbi tiles export anti-dumping Gulf US orders"]},
 {"key": "gj_vapi|chemicals_dyes", "state": "GJ", "city": "Vapi", "label": "Vapi - chemicals, dyes & intermediates", "call_key": "GJ|chemicals_dyes", "mkt": "chem",
  "q": ["Vapi GIDC chemical units GPCB closure notice 2026", "Vapi Industries Association VIA chemical industry", "Vapi CETP NGT pollution chemical",
        "Vapi dyes intermediates China prices exports demand", "વાપી જીઆઇડીસી કેમિકલ ઉદ્યોગ", "વાપી કેમિકલ એકમ ક્લોઝર નોટિસ",
        "वापी केमिकल उद्योग", "timesofindia Vapi chemical units", "Gujarat dye intermediates industry crisis 2026"]},
]
BANNED = ["monitor closely", "macro headwinds", "exercise caution", "going forward", "challenging environment", "remains to be seen",
          "headwinds", "robust", "cautious optimism", "mixed bag", "evolving situation", "stay vigilant"]
SYSTEM = ("You are a senior credit officer at a bank branch in the named city, writing for fellow bankers in plain language a 10-year-old can follow. "
 "You get: DATA PACK (verified official figures and the data-based call), MARKET TABLE (listed peers' share price changes vs Nifty), and FULL LOCAL ARTICLES "
 "numbered [n] with dates. Rules: (1) Every local claim must name a specific event, place, unit, association, order or figure from the articles and cite [n] with the "
 "article date. (2) Use ONLY numbers that appear verbatim in the articles, data pack or market table; never compute or estimate. (3) If the articles contain nothing "
 "specific and local for this industry, write exactly 'No local signal found.' for local_story. (4) Banned: generic filler such as 'monitor closely', 'headwinds', "
 "'exercise caution', 'going forward', 'challenging environment', 'robust'. (5) Do not repeat the same fact twice. "
 'Return JSON: {"local_story":"90-150 words: what is actually happening in this cluster now, with [n] citations and dates",'
 '"repayment_impact":"40-80 words: what it means for borrowers\' cash flow and repayment here, specific to this cluster\'s business model",'
 '"market_read":"1-2 sentences reading the market table plainly (only its numbers)",'
 '"borrower_checks":["exactly 3 checks specific to this cluster, each with a metric and a benchmark, tied to a local risk named in the articles"],'
 '"change_the_call":"1-2 sentences: what concrete local or data event would move the call, naming the score bands given",'
 '"news_direction":"Worse|In line|Better","news_direction_why":"<=20 words","sources_used":[article indexes]}')


def post_search(q):
    CALLS["search"] += 1
    try:
        return sa.search(q[:128], 10)
    except Exception as e:  # noqa: BLE001
        print("search fail", q, e); return []


def date_of(r):
    for k in ("published_date", "published", "date", "publish_time", "time", "publishedDate"):
        v = r.get(k)
        if v:
            m = re.search(r"(20\d\d)-(\d\d)-(\d\d)", str(v))
            if m:
                return m.group(0)
    return None


def fetch(url):
    CALLS["fetch"] += 1
    try:
        r = sa._post("/v1/tools/fetch", {"url": url})
        return r.get("content") or "", r.get("published_date") or r.get("date"), "deepseek"
    except Exception:  # noqa: BLE001
        CALLS["fetch_fallback_plain"] += 1
        try:
            return sa.plain_fetch(url).get("content", ""), None, "plain-http"
        except Exception:  # noqa: BLE001
            return "", None, "failed"


def nums(t):
    return [n.rstrip(".,") for n in re.findall(r"\d[\d,.]*", t) if re.search(r"\d", n.rstrip(".,"))]


def check(out, corpus):
    txt = " ".join([out.get("local_story", ""), out.get("repayment_impact", ""), out.get("market_read", ""), out.get("change_the_call", "")] + list(out.get("borrower_checks") or []))
    probs = [f"banned phrase '{b}'" for b in BANNED if b in txt.lower()]
    plain = re.sub(r"\[\d+(?:[,\s]*\d+)*\]", "", txt)
    bad = [n for n in nums(plain) if n not in corpus and n.replace(",", "") not in corpus]
    if bad:
        probs.append("numbers not found in sources: " + ", ".join(sorted(set(bad))[:15]))
    if len(out.get("borrower_checks") or []) != 3:
        probs.append("need exactly 3 borrower_checks")
    return probs


def run(card, radar, mkt):
    e = radar["calls"][card["call_key"]]
    geo = radar["geo"]
    base, score, nat, loc = e[0], e[1], e[2], e[3]
    reasons = [radar["reasons"][i][0] for i in e[5]]
    pack = [f"Data-based call: {base.upper()} score {score} (national {nat} x 0.6 + Gujarat {loc} x 0.4). Bands: OK to lend at or above {geo['ok_at_or_above']}, Avoid below {geo['avoid_below']}, Caution in between."] + reasons
    peers = {k: v for k, v in mkt.items() if v.get("group") == card["mkt"] and "r1m" in v}
    nifty = mkt["^NSEI"]
    mt = [f"Nifty 50: 1M {nifty['r1m']}%, 3M {nifty['r3m']}%, 12M {nifty['r12m']}% (to {nifty['asof']})"] + \
         [f"{k}: 1M {v['r1m']}%, 3M {v['r3m']}%, 12M {v['r12m']}%" for k, v in peers.items()]
    # search
    hits, seen = [], set()
    for q in card["q"]:
        for r in post_search(q):
            u = r.get("url")
            if not u or u in seen:
                continue
            seen.add(u)
            hits.append({"url": u, "title": r.get("title", ""), "date": date_of(r), "snippet": (r.get("summary") or r.get("snippet") or "")[:300], "q": q,
                         "score": (r.get("rerank_score") or 0)})
    city = card["city"].lower(); gcity = {"surat": "સુરત", "morbi": "મોરબી", "vapi": "વાપી"}[city]
    def rel(h):
        t = (h["title"] + " " + h["snippet"] + " " + h["url"]).lower()
        return (city in t or gcity in t, h["date"] or "")
    recent = [h for h in hits if h["date"] and h["date"] >= CUTOFF]
    undated = [h for h in hits if not h["date"]]
    cand = sorted(recent, key=rel, reverse=True) + sorted(undated, key=rel, reverse=True)
    docs = []
    for h in cand:
        if len(docs) >= 8 or CALLS["fetch"] > 40 * (CARDS.index(card) + 1):
            break
        if not rel(h)[0]:
            continue
        content, d2, via = fetch(h["url"])
        content = re.sub(r"\s+", " ", content)
        dt = h["date"] or (re.search(r"(20\d\d)-(\d\d)-(\d\d)", str(d2 or "")) or [None])[0]
        if len(content) < 400 or (city not in content.lower() and gcity not in content):
            continue
        if not dt or dt < CUTOFF:
            continue  # require a verifiable date in the 90-day window
        docs.append({**h, "date": dt, "via": via, "content": content[:6000]})
    arts = "\n\n".join(f"[{i}] {d['title']} (published {d['date']}) {d['url']}\n{d['content']}" for i, d in enumerate(docs)) or "(no dated local articles found in the last 90 days)"
    corpus = " ".join(d["content"] + " " + d["title"] + " " + d["date"] for d in docs) + " ".join(pack + mt) + " 90 3 1 12"
    user = f"CARD: {card['label']}\nToday: {NOW:%Y-%m-%d}\n\nDATA PACK:\n" + "\n".join("- " + x for x in pack) + "\n\nMARKET TABLE (share price change):\n" + "\n".join("- " + x for x in mt) + f"\n\nFULL LOCAL ARTICLES:\n{arts}"
    out, probs = {}, []
    for _ in range(3):
        CALLS["chat"] += 1
        out = sa.chat_json(SYSTEM, user if not probs else user + "\n\nPREVIOUS ANSWER REJECTED: " + "; ".join(probs) + ". Fix them.")
        probs = check(out, corpus)
        if not probs:
            break
    call = base
    nudged = base == "ok" and out.get("news_direction") == "Worse"
    if nudged:
        call = "caution"
    return {"key": card["key"], "label": card["label"], "base_call": base, "call": call, "nudged_by_news": nudged, "score": score, "pack": pack,
            "market": {"peers": peers, "nifty": nifty, "source": "Yahoo Finance public chart API (NSE prices), daily close"},
            "brief": out, "post_check_problems": probs, "articles": [{k: d[k] for k in ("url", "title", "date", "via")} for d in docs],
            "search_hits": len(hits), "dated_recent_hits": len(recent), "generated_ist": NOW.strftime("%Y-%m-%d %H:%M IST"), "tier": "news_llm (unverified)"}


def main():
    radar = json.loads((ROOT / "data/radar.json").read_text())
    mkt = json.loads((ROOT / "data/v4_market.json").read_text())
    res = {"cards": {}, "calls": CALLS, "cutoff": CUTOFF}
    for c in CARDS:
        try:
            r = run(c, radar, mkt)
        except Exception as e:  # noqa: BLE001
            r = {"key": c["key"], "error": str(e)}
        res["cards"][c["key"]] = r
        print(json.dumps(r, ensure_ascii=False)[:1500])
    (ROOT / "data/v4_test.json").write_text(json.dumps(res, ensure_ascii=False, indent=1))
    print("CALLS", CALLS)


if __name__ == "__main__":
    main()
