"""On-demand v6 credit-head note for one (state, city, industry). Run: python engine/note_v6.py GJ gj_surat mmf_textiles
DeepSeek: search + fetch (fallback free HTTP) + one synthesis call (one retry). Cap ~25 calls.
Every number in the note must appear in a fetched source text or the official data pack. News never upgrades the stance."""
from __future__ import annotations
import json, re, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from engine import search_adapter as sa  # noqa: E402
from engine.local_news import LOCAL_TERMS  # noqa: E402
IST = timezone(timedelta(hours=5, minutes=30))
NOW = datetime.now(IST)
CAP = 25
CALLS = {"search": 0, "fetch": 0, "chat": 0, "plain_fetch_free": 0}
BANNED = ["monitor closely", "macro headwinds", "headwinds", "exercise caution", "going forward", "challenging environment", "robust",
          "remains to be seen", "cautious optimism", "mixed bag", "evolving situation", "stay vigilant", "navigate", "landscape", "in conclusion"]
RATING = ("icra.in", "careratings.com", "crisil.com", "indiaratings.co.in", "acuite.in", "infomerics.com", "brickworkratings.com")
SYSTEM = """You are a credit head at an Indian bank with 20 years of SME lending, writing a note to a ground-level credit manager about one industry in one city.
Write ONE flowing note, not a form. Build from first principles: what the business physically is and how it turns inputs into cash, where value and cash sit
(cost structure, pricing power, working-capital cycle, capex), what has broken or changed now, where the GROWTH opportunity is (which borrower types to pursue now),
how to grow safely (structure, covenants, what to take every month), and early-warning signs. Put guidance inline exactly where it follows from a fact
("so when a proposal lands, check X; if Y, ask Z"). Plain, confident language; short paragraphs; bold the key line of each paragraph with **...**.
HARD RULES: (1) Use ONLY numbers that appear verbatim in the SOURCES or DATA PACK, and cite each with [n] (source number). Never compute, convert or estimate.
(2) Where a needed figure is missing, write 'collect from customer'. (3) Separate local news from peer results from rating reports, and say when a source is old.
(4) No generic filler; banned: monitor closely, headwinds, exercise caution, going forward, challenging environment, robust, navigate, landscape.
(5) If sources say little about this city, say so plainly and lean on first principles plus peers.
Return JSON: {"verdict":"one line credit-head call","title":"<city> <industry>: a note to the credit manager",
"narrative":["paragraph strings; headers start with '## ' (use about 5-6 headers); bullets start with '- '"],
"watch":[["monitorable (frequency)","trigger -> action"] x 3-5],"news_direction":"Worse|In line|Better","news_why":"<=20 words","sources_used":[n]}"""


class Cap(Exception):
    pass


def _take(kind):
    if sum(CALLS[k] for k in ("search", "fetch", "chat")) >= CAP:
        raise Cap("call cap reached")
    CALLS[kind] += 1


def search(q, n=8):
    _take("search")
    try:
        return sa.search(q[:128], n)
    except Exception as e:  # noqa: BLE001
        print("search fail", q, e)
        return []


def fetch(url):
    via, text, d = "deepseek", "", None
    try:
        _take("fetch")
        r = sa._post("/v1/tools/fetch", {"url": url})
        text, d = r.get("content") or "", r.get("published_date") or r.get("date")
    except Cap:
        raise
    except Exception:  # noqa: BLE001
        text = ""
    if len(text) < 400:
        CALLS["plain_fetch_free"] += 1
        try:
            text, via = sa.plain_fetch(url).get("content", ""), "plain-http"
        except Exception:  # noqa: BLE001
            text, via = "", "failed"
    return re.sub(r"\s+", " ", text), d, via


def date_of(r):
    for k in ("published_date", "published", "date", "publish_time", "time", "publishedDate"):
        m = re.search(r"20\d\d-\d\d-\d\d", str(r.get(k) or ""))
        if m:
            return m.group(0)
    return None


def nums(t):
    out = []
    for n in re.findall(r"\d[\d,]*(?:\.\d+)?", t):
        n = n.replace(",", "")
        out.append(n)
    return out


def number_problems(note, corpus_nums):
    txt = " ".join(note.get("narrative") or []) + " " + note.get("verdict", "") + " " + " ".join(" ".join(w) for w in note.get("watch") or [])
    txt = re.sub(r"\[\d+\]", "", txt)
    bad = sorted({n for n in nums(txt) if n not in corpus_nums and not (n.isdigit() and 1 <= int(n) <= 12)})
    probs = [f"numbers not in any source: {', '.join(bad[:20])}"] if bad else []
    probs += [f"banned phrase '{b}'" for b in BANNED if b in txt.lower()]
    if not 3 <= len(note.get("watch") or []) <= 5:
        probs.append("watch list must have 3-5 items")
    return probs, bad


def strip_bad(note, bad):
    """Last resort after retry: drop sentences that still carry an untraceable number."""
    pat = re.compile(r"(?<![\d.])(" + "|".join(re.escape(b) for b in bad) + r")(?![\d])")
    out = []
    for para in note["narrative"]:
        sents = re.split(r"(?<=[.!?])\s+", para)
        keep = [s for s in sents if not pat.search(s.replace(",", ""))]
        if keep:
            out.append(" ".join(keep))
    note["narrative"] = out
    note["watch"] = [w for w in note.get("watch", []) if not pat.search(" ".join(w).replace(",", ""))]
    return note


def build(state, city_id, ind_id):
    radar = json.loads((ROOT / "data/radar.json").read_text())
    city = next(c for c in radar["cities"] if c["id"] == city_id)
    ind = next(i for i in radar["industries"] if i["id"] == ind_id)
    stname = radar["states"][state]["name"]
    e = radar["calls"].get(f"{state}|{ind['parent']}") or [None, None, None, None, None, []]
    base, score, nat, loc = e[0], e[1], e[2], e[3]
    geo = radar["geo"]
    pack = [f"Data-based call: {(base or 'unknown').upper()} score {score} (national {nat} x {geo['weight_national']} + {stname} {loc} x {geo['weight_local']}). "
            f"OK to lend at or above {geo['ok_at_or_above']}, Avoid below {geo['avoid_below']}."] + [radar["reasons"][i][0] for i in e[5]]
    short = ind["name"].split(" (")[0].replace(" - ", " ").replace("&", "and")
    c = city["name"]
    lt = LOCAL_TERMS.get(state, "उद्योग मंदी भुगतान")
    qs = [("local", f"{c} {short} industry news {NOW:%B %Y}"), ("local", f"{c} {short} units payment orders closure"),
          ("local", f"{c} {lt}"), ("local", f"{c} {short.split()[0]} उद्योग"),
          ("peer", f"{short} listed companies India Q2 FY27 results volume margin"),
          ("peer", f"{short} earnings call concall FY27 management commentary demand raw material"),
          ("rating", f"ICRA rationale {c} {short}"), ("rating", f"CARE ratings rationale {c} {short} working capital"),
          ("cluster", f"{c} {short} cluster profile study cost structure")]
    if ind.get("focus"):
        qs.append(("local", f"{c} {ind['focus']}"[:128]))
    hits, seen = [], set()
    for kind, q in qs:
        for r in search(q):
            u = r.get("url")
            if u and u not in seen:
                seen.add(u)
                hits.append({"kind": kind, "url": u, "title": r.get("title", ""), "date": date_of(r),
                             "snip": (r.get("summary") or r.get("snippet") or "")[:300]})
    cut_news = (NOW - timedelta(days=95)).strftime("%Y-%m-%d")

    def rank(h):
        t = (h["title"] + h["snip"] + h["url"]).lower()
        loc_hit = c.lower() in t
        rec = h["date"] or ""
        if h["kind"] == "local":
            return (2 if loc_hit and rec >= cut_news else 0, rec)
        if h["kind"] == "rating":
            return (2 if any(d in h["url"] for d in RATING) else 0, rec)
        return (1, rec)
    picks = []
    for kind, k in (("local", 5), ("peer", 3), ("rating", 2), ("cluster", 1)):
        picks += sorted([h for h in hits if h["kind"] == kind], key=rank, reverse=True)[:k]
    docs = []
    for h in picks:
        try:
            text, d2, via = fetch(h["url"])
        except Cap:
            break
        if len(text) < 400:
            continue
        if h["kind"] == "local" and c.lower() not in text.lower():
            continue
        dt = h["date"] or (re.search(r"20\d\d-\d\d-\d\d", str(d2 or "")) or [None])[0]
        docs.append({**h, "date": dt or "date unknown", "via": via, "text": text[:6000]})
    srcs = "\n\n".join(f"[{i+1}] ({d['kind']}; {d['date']}) {d['title']} {d['url']}\n{d['text']}" for i, d in enumerate(docs)) or "(no sources fetched)"
    corpus_nums = set(nums(" ".join(d["text"] + " " + d["title"] for d in docs) + " " + " ".join(pack)))
    user = (f"CITY: {c}, {stname}\nINDUSTRY: {ind['name']}\nTODAY: {NOW:%Y-%m-%d}\n\nDATA PACK (official, verified):\n" + "\n".join("- " + x for x in pack) +
            f"\n\nSOURCES:\n{srcs}")
    note, probs, bad, tries = {}, [], [], 0
    for _ in range(2):
        try:
            _take("chat")
        except Cap:
            break
        tries += 1
        note = sa.chat_json(SYSTEM, user if not probs else user + "\n\nYOUR PREVIOUS NOTE WAS REJECTED: " + "; ".join(probs) +
                            ". Remove or replace every listed number with one that appears verbatim in a source, or write 'collect from customer'.")
        probs, bad = number_problems(note, corpus_nums)
        if not probs:
            break
    stripped = False
    if bad:
        note = strip_bad(note, bad)
        stripped = True
        probs, bad = number_problems(note, corpus_nums)
    call = base
    if base == "ok" and note.get("news_direction") == "Worse":
        call = "caution"
    used = set(note.get("sources_used") or [])
    return {"key": f"{city_id}|{ind_id}", "state": state, "city": city_id, "ind": ind_id, "version": "v6",
            "generated_at": NOW.strftime("%Y-%m-%d %H:%M IST"), "call": call, "base_call": base, "score": score,
            "nudged_by_news": call != base, "verdict": note.get("verdict", ""), "title": note.get("title", ""),
            "narrative": note.get("narrative", []), "watch": note.get("watch", []),
            "watch_note": "Trigger levels are policy suggestions (analytical framing), not data.",
            "news_direction": note.get("news_direction"), "news_why": note.get("news_why"),
            "articles": [{"title": d["title"] or d["url"], "url": d["url"], "date": d["date"], "kind": d["kind"], "via": d["via"], "used": (i + 1) in used}
                         for i, d in enumerate(docs)],
            "pack": pack, "trace": {"pass": not probs, "problems": probs, "synthesis_tries": tries, "sentences_stripped": stripped},
            "calls": dict(CALLS), "tier": "news_llm (unverified); numbers traced to fetched sources"}


def main():
    state, city, ind = sys.argv[1:4]
    if not re.fullmatch(r"[A-Z]{2}", state) or not re.fullmatch(r"[a-z0-9_]+", city) or not re.fullmatch(r"[a-z0-9_]+", ind):
        sys.exit("bad input")
    out = build(state, city, ind)
    p = ROOT / "data" / "notes" / f"{state}_{city}_{ind}.json"
    p.parent.mkdir(exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps({k: out[k] for k in ("key", "call", "trace", "calls")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
