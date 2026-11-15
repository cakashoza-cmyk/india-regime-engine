"""Check that every quote in engine/expert_kb.py is still present in its public source.

  python3 engine/expert_sources.py            # re-fetch sources marked verify='fetch', check quotes
  EXPERT_SRC_CACHE=/path python3 ...          # also use cached plain-text copies (<source_id>.txt)

Writes data/expert/source_check.json. No AI, no network other than the source URLs themselves.
A source that cannot be fetched keeps its last result (never silently turned into a pass)."""
import json, os, re, sys, html, subprocess, tempfile, datetime as dt, urllib.request, ssl
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from engine import expert_kb as K

ROOT = os.path.join(os.path.dirname(__file__), "..")
OUT = os.path.join(ROOT, "data", "expert", "source_check.json")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120 Safari/537.36"


def norm(t):
    t = html.unescape(t)
    for a, b in (("\u2019", "'"), ("\u2018", "'"), ("\u201c", '"'), ("\u201d", '"'), ("\u2013", "-"), ("\u2014", "-"),
                 ("\xa0", " "), ("\u00ad", ""), ("\ufb03", "ffi"), ("\ufb01", "fi"), ("\ufb02", "fl"), ("\ufb00", "ff")):
        t = t.replace(a, b)
    return re.sub(r"\s+", " ", t).strip().lower()


def to_text(raw):
    if raw[:5] == b"%PDF-":
        with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
            f.write(raw); f.flush()
            return subprocess.run(["pdftotext", f.name, "-"], capture_output=True).stdout.decode("utf8", "ignore")
    t = raw.decode("utf8", "ignore")
    t = re.sub(r"(?s)<(script|style).*?</\1>", " ", t)
    return re.sub(r"<[^>]+>", " ", t)


def fetch(url):
    ctx = ssl.create_default_context(); ctx.check_hostname = False; ctx.verify_mode = ssl.CERT_NONE  # public docs; several gov hosts ship broken chains
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return to_text(urllib.request.urlopen(req, timeout=60, context=ctx).read())


def check(text, quotes):
    n = norm(text)
    return [q for q in quotes if norm(q) not in n]


def main():
    cache = os.environ.get("EXPERT_SRC_CACHE")
    old = json.load(open(OUT)) if os.path.exists(OUT) else {"sources": {}}
    today = dt.date.today().isoformat()
    by_src = {}
    for f in K.FACTS:
        by_src.setdefault(f["src"], []).append(f)
    res = {}
    for sid, facts in by_src.items():
        s = K.SOURCES[sid]
        quotes = [q for f in facts for q in f["quotes"]]
        text, method = None, None
        if s["verify"] == "fetch":
            try:
                text, method = fetch(s["url"]), "fetched"
            except Exception as e:
                print(sid, "fetch failed:", str(e)[:80])
        if text is None and cache and os.path.exists(os.path.join(cache, sid + ".txt")):
            text, method = open(os.path.join(cache, sid + ".txt"), errors="ignore").read(), "cached copy"
        if text is None:
            prev = old["sources"].get(sid)
            res[sid] = prev or {"status": "unchecked", "checked": None, "method": None, "missing": quotes}
            print(sid, "kept previous result:", res[sid]["status"]); continue
        miss = check(text, quotes)
        res[sid] = {"status": "ok" if not miss else "quote_missing", "checked": today, "method": method, "missing": miss,
                    "facts": [f["id"] for f in facts]}
        print(sid, res[sid]["status"], method, miss[:2])
    json.dump({"generated": today, "sources": res}, open(OUT, "w"), indent=1, ensure_ascii=False)
    bad = [k for k, v in res.items() if v["status"] != "ok"]
    print("SUMMARY", len(res), "sources,", len(bad), "not ok:", bad)


if __name__ == "__main__":
    main()
