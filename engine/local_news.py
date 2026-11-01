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
SYSTEM = ("You are a local bank credit officer briefing a credit committee. Read the supplied local news articles and write "
          "ONE short paragraph (60-110 words, plain English): the key local issues for this sector in this place, why they matter for "
          "borrowers' repayment capacity and working capital, and whether local conditions look better or worse than the national macro "
          "view given. Use ONLY what the articles say. Do not invent, estimate or compute any figure; a number may appear only if it is "
          "written in an article. No headline, no bullets, no loan advice. If the articles are few, old or off-topic, start with "
          "'Limited local coverage.' and say only what they support. "
          'Return JSON: {"analysis":"<paragraph>","outlook_vs_macro":"Worse|In line|Better","why":"<=20 words","sources_used":[<article indexes>]}.')
MAX_CALLS = int(os.environ.get("LOCAL_NEWS_MAX_CALLS", "300"))
RESCAN_DAYS = 7
WINDOW_DAYS = 60


class Budget:
    def __init__(self, n): self.left = n
    def take(self):
        if self.left <= 0: raise RuntimeError("call budget exhausted")
        self.left -= 1


def _retry(fn, budget, *a):
    err = None
    for _ in range(2):  # at most 2 attempts
        budget.take()
        try:
            return fn(*a)
        except RuntimeError:
            raise
        except Exception as e:  # noqa: BLE001
            err = e
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
    secs = {s["id"]: s for s in cfg["sectors"]}
    states = {s["code"]: s for s in cfg["states"]}
    for cl in cfg["clusters"]:
        place = cl["name"]
        for sid in cl["sectors"]:
            if sid in secs:
                yield {"key": f"{cl['id']}|{sid}", "geo_type": "cluster", "geo_id": cl["id"], "state": cl["state"], "sector": sid,
                       "q": f"{place} {secs[sid]['name'].split(' - ')[0].split('(')[0]}"}
    for code, st in states.items():  # state-level fallback: one general industry scan per state
        yield {"key": f"{code}|*", "geo_type": "state", "geo_id": code, "state": code, "sector": "*", "q": f"{st['name']} industry MSME"}


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


def summarise(arts, sa, budget, macro_ctx=""):
    docs = []
    for a in arts:
        try:
            c = _retry(sa.fetch, budget, a["url"])
            docs.append({**a, "content": (c.get("content") or "")[:3500]})
        except RuntimeError:
            raise
        except Exception:  # noqa: BLE001
            continue
    if not docs:
        return None
    user = (f"Sector and place: {macro_ctx}\n\n" +
            "\n\n".join(f"[{i}] {d['title']} ({d['date']}) {d['url']}\n{d['content']}" for i, d in enumerate(docs)))
    j = _retry(sa.chat_json, budget, SYSTEM, user)
    text = (j.get("analysis") or "").strip()
    corpus = " ".join(d["content"] + " " + d["title"] for d in docs)
    if not text or not numbers_ok(text, corpus):
        return {"analysis": None, "outlook_vs_macro": None, "why": None, "sources": [], "rejected": "empty or contained a figure not in the articles"}
    used = [i for i in (j.get("sources_used") or []) if isinstance(i, int) and 0 <= i < len(docs)] or list(range(len(docs)))
    tag = j.get("outlook_vs_macro") if j.get("outlook_vs_macro") in ("Worse", "In line", "Better") else None
    if len(docs) < 2 and not text.lower().startswith("limited local coverage"):
        text = "Limited local coverage. " + text
    return {"analysis": text, "outlook_vs_macro": tag, "why": (j.get("why") or "")[:140] if tag else None,
            "sources": [{"url": docs[i]["url"], "title": docs[i]["title"], "date": docs[i]["date"]} for i in used], "tier": "news_llm"}

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
    lat = ROOT / "data" / "lending_latest.json"
    macro = {x["id"]: f"{x['verdict']} (score {x['score']})" for x in (json.loads(lat.read_text())["sectors"] if lat.exists() else [])}
    budget, done, skipped, unchanged, errors = Budget(MAX_CALLS), 0, 0, 0, []
    todo = sorted(pairs(cfg), key=lambda p: (items.get(p["key"]) or {}).get("scanned_ist", ""))  # oldest first
    for p in todo:
        old = items.get(p["key"]) or {}
        if old.get("scanned_ist", "") > (now - timedelta(days=RESCAN_DAYS)).strftime("%Y-%m-%d %H:%M IST"):
            skipped += 1; continue
        try:
            arts = scan_pair(p, sa, budget, now.date())
            sig = hashlib.sha1("|".join(a["url"] for a in arts).encode()).hexdigest()
            if old.get("sig") == sig:
                old["scanned_ist"] = now.strftime("%Y-%m-%d %H:%M IST"); unchanged += 1; continue
            empty = {"analysis": "Limited local coverage. No relevant local articles in the last 60 days.", "outlook_vs_macro": None, "why": None, "sources": []}
            s = (summarise(arts, sa, budget, f"{p['q']} | national macro view: {macro.get(p['sector'], 'n/a')}") if arts else None) or empty
            items[p["key"]] = {**{k: p[k] for k in ("geo_type", "geo_id", "state", "sector")}, **s, "sig": sig, "queries": p["q"],
                               "scanned_ist": now.strftime("%Y-%m-%d %H:%M IST"), "tier": "news_llm", "window_days": WINDOW_DAYS}
            done += 1
        except RuntimeError as e:
            if "budget" in str(e):
                break
            errors.append(f"{p['key']}: {e}")
        except Exception as e:  # noqa: BLE001
            errors.append(f"{p['key']}: {e}")
    cache.update(active=True, status="Weekly scan via DeepSeek search (news_llm, unverified; never used in verdicts).",
                 checked_ist=now.strftime("%Y-%m-%d %H:%M IST"),
                 last_run={"scanned": done, "skipped_fresh": skipped, "unchanged": unchanged, "calls_used": MAX_CALLS - budget.left,
                           "call_cap": MAX_CALLS, "errors": errors[:20]})
    OUT.write_text(json.dumps(cache, indent=1, ensure_ascii=False))
    print(cache["last_run"])


if __name__ == "__main__":
    main()
