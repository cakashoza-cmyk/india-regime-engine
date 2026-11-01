"""Automatic macro pulls (no keys). Official first (MOSPI API + PDF, CCIL via headless Chrome, RBI MPC
resolution), Trading Economics meta descriptions as a credible secondary. Never invents: any parse
failure returns {"error": ...}."""
from __future__ import annotations
import calendar, html, json, re, shutil, subprocess, tempfile, urllib.request
from datetime import date, datetime

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"
MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
QEND = {"first": 3, "second": 6, "third": 9, "fourth": 12}


def _req(url, data=None, headers=None, timeout=30):
    h = {"User-Agent": UA, **(headers or {})}
    r = urllib.request.Request(url, data=data, headers=h, method="POST" if data else "GET")
    return urllib.request.urlopen(r, timeout=timeout).read()


def month_end(y, m):
    return date(y, m, calendar.monthrange(y, m)[1]).isoformat()


# ---------------- MOSPI: official latest-release API -> CPI PDF -> pdftotext ----------------
MOSPI_API = "https://www.mospi.gov.in/api/latest-release/get-web-latest-release-list"


def mospi_releases():
    raw = _req(MOSPI_API, data=json.dumps({"page": 1, "pageSize": 50, "lang": "en"}).encode(),
               headers={"Content-Type": "application/json", "Origin": "https://www.mospi.gov.in",
                        "Referer": "https://www.mospi.gov.in/latest-releases"})
    return json.loads(raw)["data"]


def _pdf_text(url):
    if not shutil.which("pdftotext"):
        raise RuntimeError("pdftotext not installed")
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(_req(url, timeout=60)); f.flush()
        return subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, text=True, timeout=60).stdout


def parse_cpi_pdf(text):
    """Key-statistics table: CPI (General) / CFPI rows = prior R U C, current R U C."""
    m = re.search(r"for the month of (\w+),? (\d{4})", text)
    if not m:
        raise ValueError("month not found")
    y, mo = int(m.group(2)), MONTHS[m.group(1).lower()]
    num = r"(-?\d+\.\d+)"
    six = r"\s+".join([num] * 6)
    gen = re.search(r"CPI\s+" + six + r"\s+\(General\)\s+Inflation", text, re.S)
    food = re.search(r"CFPI\s+" + six, text)
    if not gen or not food:
        raise ValueError("inflation table not found")
    g, f = [float(x) for x in gen.groups()], [float(x) for x in food.groups()]
    return {"cpi_headline": {"value": g[5], "prior": g[2]}, "food_inflation": {"value": f[5], "prior": f[2]},
            "as_of": month_end(y, mo)}


def mospi_cpi():
    rel = next((r for r in mospi_releases() if re.search(r"CPI for the month", r.get("title", ""), re.I)), None)
    if not rel:
        return {"error": "no CPI release in MOSPI latest-release list"}
    url = "https://www.mospi.gov.in/" + rel["file_one"]["path"]
    p = parse_cpi_pdf(_pdf_text(url))
    return {k: {**p[k], "as_of": p["as_of"], "release_date": rel["published_year"], "source_url": url,
                "note": "MOSPI CPI press release PDF (base 2024=100), Combined"} for k in ("cpi_headline", "food_inflation")}


# ---------------- Trading Economics (credible secondary; quotes the official print) ----------------
TE_PAGES = {"cpi_headline": "inflation-cpi", "food_inflation": "food-inflation", "iip_yoy": "industrial-production",
            "gdp_yoy": "gdp-growth-annual", "capacity_util": "capacity-utilization", "credit_growth": "loan-growth",
            "india10y": "government-bond-yield"}


def parse_te(desc, today=None):
    today = today or date.today()
    v = re.search(r"(?:to|increased|decreased|expanded|contracted|grew|rose|fell|declined)\s+(-?\d+(?:\.\d+)?)\s*(?:percent|%)", desc)
    if not v:
        raise ValueError("value not found")
    out = {"value": float(v.group(1)), "prior": None}
    pm = re.search(r"from\s+(-?\d+(?:\.\d+)?)\s*(?:percent|%)", desc)
    if pm:
        out["prior"] = float(pm.group(1))
    d = re.search(r"on (\w+ \d{1,2}, \d{4})", desc)
    q = re.search(r"(first|second|third|fourth) quarter of (\d{4})", desc)
    mo = re.search(r"in (January|February|March|April|May|June|July|August|September|October|November|December)(?: of)?(?: (\d{4}))?", desc)
    yr = re.search(r"(\d{4})", desc)
    if d:
        out["as_of"] = datetime.strptime(d.group(1), "%B %d, %Y").date().isoformat()
    elif q:
        out["as_of"] = month_end(int(q.group(2)), QEND[q.group(1)])
    elif mo:
        y = int(mo.group(2) or (yr.group(1) if yr else today.year))
        out["as_of"] = month_end(y, MONTHS[mo.group(1).lower()])
    else:
        raise ValueError("date not found")
    return out


def tradingeconomics(key):
    url = f"https://tradingeconomics.com/india/{TE_PAGES[key]}"
    t = _req(url).decode("utf-8", "ignore")
    m = re.search(r'name="description" content="([^"]*)"', t) or re.search(r'description" content="([^"]*)', t)
    if not m:
        return {"error": "no description meta", "source_url": url}
    desc = html.unescape(m.group(1)).split(" This page provides")[0].split(" This dataset")[0]
    try:
        out = parse_te(desc)
    except ValueError as e:
        return {"error": f"{e}: {desc[:120]}", "source_url": url}
    return {**out, "source_url": url, "note": "Trading Economics: " + desc[:200]}


# ---------------- CCIL tenor-wise indicative yields via headless Chrome ----------------
CCIL = "https://www.ccilindia.com/tenorwise-indicative-yields"


def _chrome():
    for c in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser"):
        if shutil.which(c):
            return c
    return None


def parse_ccil(text):
    m = re.search(r"9Y-10Y\s+(.+?GS \d{4})\s+(\d+\.\d+)\s+(\d{2})-(\d{2})-(\d{4})", text)
    if not m:
        raise ValueError("9Y-10Y row not found")
    return {"value": float(m.group(2)), "as_of": f"{m.group(5)}-{m.group(4)}-{m.group(3)}", "security": m.group(1)}


def ccil_10y():
    c = _chrome()
    if not c:
        return {"error": "no headless Chrome on this runner", "source_url": CCIL}
    dom = subprocess.run(["timeout", "-s", "KILL", "90", c, "--headless=new", "--no-sandbox", "--disable-gpu", "--virtual-time-budget=20000",
                          f"--user-agent={UA}", "--dump-dom", CCIL], capture_output=True, text=True, timeout=150).stdout  # Chrome may hang after printing
    t = re.sub(r"<script.*?</script>|<style.*?</style>", "", dom, flags=re.S)
    s = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t)))
    try:
        p = parse_ccil(s)
    except ValueError as e:
        return {"error": str(e), "source_url": CCIL}
    return {**p, "prior": None, "source_url": CCIL, "note": f"CCIL tenor-wise indicative yield, 9Y-10Y benchmark {p['security']}"}


# ---------------- RBI MPC resolution -> stance language (deterministic regex, not LLM) ----------------
RBI_PR = "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx"
KNOWN_MPC = "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=63742"  # Oct 2026 resolution (fallback URL only)
STANCE_SCORE = {"tightening": -1, "withdrawal of accommodation": -1, "neutral": 0, "accommodative": 1}


def parse_stance(text):
    m = re.search(r"decided to (?:change|retain|continue with|keep|maintain) the (?:monetary policy )?stance (?:to|at|as)?\s*['‘\"]?([a-z ]+?)['’\"]?(?:[.,;]| and )", text, re.I)
    if not m:
        raise ValueError("stance sentence not found")
    phrase = m.group(1).strip().lower()
    kind = "tightening" if ("tighten" in phrase or "withdrawal" in phrase) else "accommodative" if "accommodat" in phrase else "neutral"
    return {"phrase": phrase, "stance": kind, "value": STANCE_SCORE[kind], "quote": m.group(0)[:200]}


def rbi_stance():
    url = KNOWN_MPC
    try:
        lst = _req(RBI_PR).decode("utf-8", "ignore")
        m = re.search(r"prid=(\d+)'?>[^<]*Monetary Policy Statement", lst)
        if m:
            url = f"{RBI_PR}?prid={m.group(1)}"
    except Exception:  # noqa: BLE001
        pass
    t = _req(url).decode("utf-8", "ignore")
    s = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", t)))
    d = re.search(r"Monetary Policy Committee (?:\(MPC\) )?held its \d+\w* meeting from (\w+ \d+) to (\d+), (\d{4})", s)
    as_of = datetime.strptime(f"{d.group(1).split()[0]} {d.group(2)} {d.group(3)}", "%B %d %Y").date().isoformat() if d else None
    return {**parse_stance(s), "as_of": as_of, "source_url": url, "note": "RBI MPC resolution (regex, not LLM)"}
