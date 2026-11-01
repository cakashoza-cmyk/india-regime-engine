"""Local credit view: weekly DeepSeek scan of local news per cluster x sector (plus state fallback).
Output is news_llm (unverified, display-only). NEVER affects verdicts. Key lives only in GitHub Actions."""
from __future__ import annotations
import hashlib, json, os, re, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
OUT = ROOT / "data" / "local_news.json"
IST = timezone(timedelta(hours=5, minutes=30))
TOPICS = "payment delays OR layoffs OR power cuts OR orders OR exports OR strike OR closure OR prices"
LOCAL_TERMS = {  # regional-language search terms (payment delay / units closed / orders)
    "GJ": "ઉદ્યોગ મંદી પેમેન્ટ", "TN": "தொழில் நெருக்கடி ஆர்டர்", "UP": "उद्योग मंदी भुगतान", "HR": "उद्योग मंदी भुगतान",
    "RJ": "उद्योग मंदी भुगतान", "MP": "उद्योग मंदी भुगतान", "BR": "उद्योग मंदी भुगतान", "HP": "उद्योग मंदी भुगतान",
    "DL": "उद्योग मंदी भुगतान", "MH": "उद्योग मंदी पेमेंट"}
PROMPT_VERSION = 3
SYSTEM = ("You are a senior credit officer in the given city, writing the local section of a one-card lending brief on one industry. "
          "You get (1) a DATA PACK of verified official figures, including the data-based call and its score bands, (2) a CREDIT LENS for the "
          "industry (analytical framing, not data), and (3) local news extracts. Rules: use ONLY numbers that appear in the data pack or the "
          "articles, copied exactly; never estimate or compute new figures; attribute news points to the news. No generic filler: never write "
          "'monitor closely', 'macro headwinds', 'exercise caution', 'going forward', 'challenging environment' or similar. If the articles are "
          "few, old or off-topic, local_flavour must start with 'Limited local coverage.' "
          'Return JSON: {"local_flavour":"one paragraph of 80-140 words: what is happening locally in this industry and what it means for '
          'borrowers\' cash flow and repayment, blending the news with at least 2 figures from the data pack; no headline list",'
          '"borrower_checks":["exactly 3 concrete diligence items for a borrower here, each with a metric and a benchmark, e.g. debtor days vs 90"],'
          '"change_the_call":"1-2 sentences: which score move would change the call. Use the bands exactly: OK to lend at or above the OK '
          'threshold, Caution between the Avoid threshold and the OK threshold, Avoid below the Avoid threshold. Name the threshold number.",'
          '"outlook_vs_macro":"Worse|In line|Better","why":"<=20 words","sources_used":[article indexes]}.')
MAX_CALLS = int(os.environ.get("LOCAL_NEWS_MAX_CALLS", "3000"))
RESCAN_DAYS = 7
WINDOW_DAYS = 60


class Budget:
    def __init__(self, n):
        import threading
        self.left, self._l = n, threading.Lock()

    def take(self):
        with self._l:
            if self.left <= 0:
                raise RuntimeError("call budget exhausted")
            self.left -= 1


def _retry(fn, budget, *a):
    import time
    err, tries, limited = None, 0, 0
    while tries < 2:  # at most 2 attempts (rate-limit waits are retried separately, max 4)
        budget.take()
        try:
            return fn(*a)
        except RuntimeError:
            raise
        except Exception as e:  # noqa: BLE001
            err = e
            if getattr(e, "code", None) == 429 and limited < 4:
                limited += 1
                time.sleep(10 * limited)
                continue
            tries += 1
    raise err


def _date(r):
    for k in ("published_date", "published", "date", "publish_time", "time"):
        v = r.get(k)
        if v:
            m = re.search(r"(20\d\d)-(\d\d)-(\d\d)", str(v))
            if m:
                return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    return None


def pairs(cfg):
    """City x hub-industry pairs (engine/cities.json) plus one state-level fallback per state."""
    inds = {i["id"]: i for i in json.loads((ROOT / "engine" / "industries.json").read_text())["industries"]}
    cities = json.loads((ROOT / "engine" / "cities.json").read_text())["cities"]
    states = {s["code"]: s for s in cfg["states"]}
    for c in cities:
        for iid in c["hubs"]:
            ind = inds[iid]
            short = ind["name"].split(" (")[0].split(" - ")[-1].split(" & ")[0]
            yield {"key": f"{c['id']}|{iid}", "geo_type": "city", "geo_id": c["id"], "city": c["name"], "state": c["state"], "industry": iid,
                   "sector": ind["parent"], "mapping": ind["mapping"], "focus": ind.get("focus"), "q": f"{c['name']} {short}", "iname": ind["name"]}
    for code, st in states.items():
        yield {"key": f"{code}|*", "geo_type": "state", "geo_id": code, "city": None, "state": code, "industry": "*", "sector": "*",
               "mapping": None, "focus": None, "q": f"{st['name']} industry MSME", "iname": "industry overall"}


def numbers_ok(text, src):
    return all(n in src for n in re.findall(r"\d[\d,.]*", text))


def scan_pair(p, sa, budget, today):
    qs = [f"{p['q']} {TOPICS}"]
    if p["state"] in LOCAL_TERMS:
        qs.append(f"{p['q'].split()[0]} {LOCAL_TERMS[p['state']]}")
    res, seen = [], set()
    cutoff = (today - timedelta(days=WINDOW_DAYS)).isoformat()
    for q in qs:
        for r in _retry(sa.search, budget, q[:128], 8):
            u, d = r.get("url"), _date(r)
            if u and u not in seen and d and d >= cutoff:
                seen.add(u); res.append({"url": u, "title": r.get("title", ""), "date": d})
    res = sorted(res, key=lambda r: r["date"], reverse=True)[:4]
    return res


def fetch_articles(arts, sa, budget):
    docs = []
    for a in arts:
        try:
            c = _retry(sa.fetch, budget, a["url"])
            docs.append({**a, "content": (c.get("content") or "")[:3000]})
        except RuntimeError:
            raise
        except Exception:  # noqa: BLE001
            continue
    return docs


def brief(p, docs, pack, lens, sa, budget, bands):
    from engine import brief_pack as bp
    lens_text = json.dumps(lens or {}, ensure_ascii=False)
    arts = "\n\n".join(f"[{i}] {d['title']} ({d['date']}) {d['url']}\n{d['content']}" for i, d in enumerate(docs)) or "(no local articles found in the last 60 days)"
    user = (f"PLACE / INDUSTRY: {p['label']}\n\nDATA PACK (verified official figures):\n" + "\n".join(f"- {x}" for x in pack) +
            f"\n\nCREDIT LENS (analytical framing, not data):\n{lens_text}\n\nLOCAL NEWS EXTRACTS:\n{arts}")
    corpus = " ".join(d["content"] + " " + d["title"] for d in docs) + f" last {WINDOW_DAYS} days"
    need = 2 if len(bp.nums(" ".join(pack))) >= 6 else 0
    probs, out = [], None
    for attempt in range(3):  # first try + up to 2 corrective retries
        msg = user if not probs else (user + "\n\nYOUR PREVIOUS ANSWER WAS REJECTED. Fix these problems: " + "; ".join(probs) +
                                      ". Delete or replace any listed number; use only figures written in the data pack or the articles.")
        out = _retry(sa.chat_json, budget, SYSTEM, msg)
        if not isinstance(out.get("borrower_checks"), list):
            out["borrower_checks"] = []
        probs = bp.validate_v3(out, pack, corpus, lens_text, bands, need_pack=need)
        if not probs:
            break
    if probs:
        return {"brief": None, "rejected": probs, "attempts": attempt + 1}
    used = [i for i in (out.get("sources_used") or []) if isinstance(i, int) and 0 <= i < len(docs)] or list(range(len(docs)))
    tag = out.get("outlook_vs_macro") if out.get("outlook_vs_macro") in ("Worse", "In line", "Better") else None
    fl = out["local_flavour"].strip()
    if len(docs) < 2 and not fl.lower().startswith("limited local coverage"):
        fl = "Limited local coverage. " + fl
    return {"brief": {"local_flavour": fl, "borrower_checks": [x.strip() for x in out["borrower_checks"]], "change_the_call": out["change_the_call"].strip()},
            "outlook_vs_macro": tag, "why": (out.get("why") or "")[:160] if tag else None, "attempts": attempt + 1,
            "sources": [{"url": docs[i]["url"], "title": docs[i]["title"], "date": docs[i]["date"]} for i in used]}


def main():
    from engine import lending_sources as ls
    cfg = ls.load_config()
    now = datetime.now(IST)
    cache = json.loads(OUT.read_text()) if OUT.exists() else {"items": {}}
    items = cache.setdefault("items", {})
    if not ls.deepseek_available():
        cache.update(active=False, status="Local scan activates once the key is added (GitHub secret DEEPSEEK_API_KEY).",
                     checked_ist=now.strftime("%Y-%m-%d %H:%M IST"))
        OUT.write_text(json.dumps(cache, indent=1, ensure_ascii=False)); print(cache["status"]); return
    from engine import search_adapter as sa
    from engine import brief_pack as bp
    import threading
    from concurrent.futures import ThreadPoolExecutor
    D = json.loads((ROOT / "data" / "lending_latest.json").read_text())
    lens_all = json.loads((ROOT / "engine" / "credit_lens.json").read_text())
    secs = {x["id"]: x for x in D["sectors"]}
    combos = {f"{c['state']}|{c['sector']}": c for c in D["combos"] if c["geo_type"] == "state"}
    bands = {"ok": D["geo_config"]["ok_at_or_above"], "avoid": D["geo_config"]["avoid_below"]}
    budget, lock = Budget(MAX_CALLS), threading.Lock()
    stats = {"scanned": 0, "skipped_fresh": 0, "rejected": 0, "errors": []}
    force = os.environ.get("LOCAL_NEWS_FORCE") == "1"
    plist = list(pairs(cfg))
    keep = {p["key"] for p in plist}
    for k in [k for k in items if k not in keep]:
        items.pop(k)
    todo = sorted(plist, key=lambda p: ((items.get(p["key"]) or {}).get("prompt_version") == PROMPT_VERSION, (items.get(p["key"]) or {}).get("scanned_ist", "")))
    STATE_LENS = {"what": "All industry in the state", "drivers": ["state demand and output", "power availability", "payment cycles"],
                  "stress": ["tax collections and electricity demand lagging India", "unit closures", "delayed payments"],
                  "checks": ["GST turnover vs bank credit summations", "debtor days vs 90", "electricity bills trend vs last year"]}

    def work(p):
        old = items.get(p["key"]) or {}
        fresh = old.get("scanned_ist", "") > (now - timedelta(days=RESCAN_DAYS)).strftime("%Y-%m-%d %H:%M IST")
        if fresh and old.get("prompt_version") == PROMPT_VERSION and old.get("brief") and not force:
            with lock: stats["skipped_fresh"] += 1
            return
        st = D["states"].get(p["state"])
        sec = secs.get(p["sector"])
        combo = combos.get(f"{p['state']}|{p['sector']}") if sec else None
        pack = bp.build_pack(D, combo, sec, st)
        if sec and p["mapping"] != "direct":
            pack.insert(0, f"Industry asked: {p['iname']}. Official series are not published for it separately; figures below are for the nearest parent sector, {sec['name']} (proxy: parent sector).")
        if not any("Bands:" in x for x in pack):
            pack.append(f"Bands: OK to lend >= {bands['ok']}; Caution {bands['avoid']} to {bands['ok'] - 1}; Avoid < {bands['avoid']}.")
        p["label"] = f"{p['iname']} in {p['city']}, {st['name'] if st else p['state']}" if p["city"] else f"Industry overall, {st['name'] if st else p['state']}"
        lens = dict(lens_all.get(p["sector"]) or {}) if sec else STATE_LENS
        if p.get("focus"):
            lens["industry_focus"] = p["focus"]
        try:
            arts = scan_pair(p, sa, budget, now.date())
            docs = fetch_articles(arts, sa, budget)
            r = brief(p, docs, pack, lens, sa, budget, bands)
            rec = {**{k: p[k] for k in ("geo_type", "geo_id", "state", "sector", "industry")}, **r, "queries": p["q"], "pack": pack,
                   "scanned_ist": now.strftime("%Y-%m-%d %H:%M IST"), "tier": "news_llm", "window_days": WINDOW_DAYS, "prompt_version": PROMPT_VERSION}
            with lock:
                items[p["key"]] = rec
                stats["scanned"] += 1
                stats["rejected"] += 0 if r.get("brief") else 1
        except RuntimeError as e:
            with lock: stats["errors"].append(f"{p['key']}: {e}")
        except Exception as e:  # noqa: BLE001
            with lock: stats["errors"].append(f"{p['key']}: {type(e).__name__}: {e}")

    with ThreadPoolExecutor(5) as ex:
        list(ex.map(work, todo))
    errors = stats.pop("errors")
    cache.update(active=True, status="Weekly scan via DeepSeek search (news_llm, unverified; never used in verdicts).",
                 checked_ist=now.strftime("%Y-%m-%d %H:%M IST"),
                 last_run={**stats, "calls_used": MAX_CALLS - budget.left, "call_cap": MAX_CALLS, "errors": errors[:20]})
    OUT.write_text(json.dumps(cache, indent=1, ensure_ascii=False))
    print(cache["last_run"])


if __name__ == "__main__":
    main()
