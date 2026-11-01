"""Official / exchange-published scrapers (no keys). Each returns a payload dict with
value, prior, as_of, source_url — or {"error": ...}. Never invents a value."""
from __future__ import annotations
import csv, html, io, json, re, sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import refresh_data as rd  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36"}
MONTH_CODE = "FGHJKMNQUVXZ"


def _get(url):
    raw, err, _ = rd.http_get(url, headers=UA)
    return (raw.decode("utf-8", "ignore") if raw else None), err


def _text(h):
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h)))


def last_business_day(d: date) -> date:
    while d.weekday() >= 5:
        d -= timedelta(days=1)
    return d


def rbi_ref_rate_date(now: datetime | None = None) -> str:
    """FBIL/RBI USD-INR reference rate is published ~13:30 IST on business days; the homepage
    shows the latest one. Before 13:30 (or on weekends) it is the previous business day's rate."""
    now = now or datetime.now(IST)
    d = now.date()
    if d.weekday() >= 5 or (now.hour, now.minute) < (13, 30):
        d = last_business_day(d - timedelta(days=1) if d.weekday() < 5 else d)
    return d.isoformat()


# ---------- Brent: explicit ICE contract (fixes BZ=F roll splicing) ----------
def brent_expiry(year: int, month: int) -> date:
    """ICE Brent month M expires on the last business day of month M-2."""
    m, y = month - 2, year
    if m <= 0:
        m += 12; y -= 1
    nxt = date(y + (m == 12), (m % 12) + 1, 1)
    return last_business_day(nxt - timedelta(days=1))


def brent_active_symbol(today: date) -> tuple[str, date]:
    """First contract whose expiry is strictly after `today` (on expiry day the next month is the
    active, liquid contract)."""
    y, m = today.year, today.month
    for _ in range(6):
        if brent_expiry(y, m) > today:
            return f"BZ{MONTH_CODE[m-1]}{str(y)[2:]}.NYM", brent_expiry(y, m)
        m += 1
        if m > 12:
            m = 1; y += 1
    raise RuntimeError("no brent contract")


def brent_active(today: date | None = None) -> dict:
    today = today or datetime.now(IST).date()
    sym, exp = brent_active_symbol(today)
    r = rd.yahoo_chart(sym, "1mo")
    r.update(contract=sym, contract_expiry=exp.isoformat(),
             note="ICE Brent active contract (value and prior from the same contract)")
    return r


# ---------- NSE official index closing file ----------
NSE_NAMES = {"nifty": "Nifty 50", "nifty_bank": "Nifty Bank", "nifty_auto": "Nifty Auto",
             "nifty_metal": "Nifty Metal", "india_vix": "India VIX"}


def nse_close_all(today: date | None = None) -> dict:
    """Parse NSE ind_close_all_DDMMYYYY.csv for the latest available business day."""
    d = last_business_day(today or datetime.now(IST).date())
    for _ in range(6):
        url = f"https://nsearchives.nseindia.com/content/indices/ind_close_all_{d:%d%m%Y}.csv"
        t, err = _get(url)
        if t and "Index Name" in t:
            out = {}
            for row in csv.DictReader(io.StringIO(t)):
                name = (row.get("Index Name") or "").strip()
                for key, nm in NSE_NAMES.items():
                    if name.lower() == nm.lower():
                        try:
                            close = float(row["Closing Index Value"])
                            chg = float(row.get("Points Change") or 0)
                            out[key] = {"value": close, "prior": round(close - chg, 4), "as_of": d.isoformat(),
                                        "source_url": url, "note": "NSE official index close file"}
                        except (KeyError, ValueError):
                            pass
            return out
        d = last_business_day(d - timedelta(days=1))
    return {}


# ---------- US Treasury par yield curve ----------
def treasury_10y(today: date | None = None) -> dict:
    y = (today or date.today()).year
    url = ("https://home.treasury.gov/resource-center/data-chart-center/interest-rates/daily-treasury-rates.csv/"
           f"{y}/all?type=daily_treasury_yield_curve&field_tdr_date_value={y}&page&_format=csv")
    t, err = _get(url)
    if not t:
        return {"error": err or "no data", "source_url": url}
    rows = [r for r in csv.DictReader(io.StringIO(t)) if r.get("10 Yr")]
    if not rows:
        return {"error": "10 Yr column missing", "source_url": url}
    rows.sort(key=lambda r: datetime.strptime(r["Date"], "%m/%d/%Y"))
    a = rows[-1]; b = rows[-2] if len(rows) > 1 else None
    return {"value": float(a["10 Yr"]), "prior": float(b["10 Yr"]) if b else None,
            "as_of": datetime.strptime(a["Date"], "%m/%d/%Y").date().isoformat(),
            "source_url": url, "note": "US Treasury daily par yield curve, 10 Yr"}


# ---------- RBI Scheduled Banks' Statement of Position (fortnightly) ----------
RBI_PR_LIST = "https://rbi.org.in/scripts/FS_PressRelease.aspx?fn=2"


def _credit_from_statement(url):
    t, err = _get(url)
    if not t:
        return None, err
    s = _text(t)
    m = re.search(r"BANK CREDIT \(Excluding Inter-Bank Advances\)?\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)", s)
    d = re.search(r"Statement of Position in India as on (\w+ \d{1,2}, \d{4})", s)
    if not m:
        return None, "BANK CREDIT row not found"
    yago, _, cur = (float(x) for x in m.groups())
    as_of = datetime.strptime(d.group(1), "%B %d, %Y").date().isoformat() if d else None
    return {"yoy": round((cur / yago - 1) * 100, 2), "as_of": as_of, "level_cr": cur, "year_ago_cr": yago}, None


def rbi_credit_growth() -> dict:
    t, err = _get(RBI_PR_LIST)
    if not t:
        return {"error": err or "RBI press list unavailable", "source_url": RBI_PR_LIST}
    links = re.findall(r"href=['\"]?(FS_PressRelease\.aspx\?prid=\d+&(?:amp;)?fn=2)['\"]?>Scheduled Banks.{0,3}Statement of Position", t)
    if not links:
        return {"error": "no Statement of Position link on RBI press list", "source_url": RBI_PR_LIST}
    urls = ["https://rbi.org.in/scripts/" + html.unescape(x) for x in links[:2]]
    cur, e = _credit_from_statement(urls[0])
    if not cur:
        return {"error": e, "source_url": urls[0]}
    prev = _credit_from_statement(urls[1])[0] if len(urls) > 1 else None
    return {"value": cur["yoy"], "prior": prev["yoy"] if prev else None, "as_of": cur["as_of"],
            "source_url": urls[0], "note": "SCB bank credit YoY (excl. inter-bank), computed from RBI statement columns",
            "extra": cur}


# ---------- Breadth: % of Nifty 50 constituents above their 200-DMA ----------
def breadth_nifty50() -> dict:
    src = "https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv"
    t, err = _get(src)
    if not t:
        return {"error": err or "constituent list unavailable", "source_url": src}
    syms = [r["Symbol"].strip() for r in csv.DictReader(io.StringIO(t)) if r.get("Symbol")]
    above = n = 0; as_of = None; missing = []
    for s in syms:
        raw, e, _ = rd.http_get(f"https://query1.finance.yahoo.com/v8/finance/chart/{s}.NS?range=1y&interval=1d")
        try:
            r0 = json.loads(raw)["chart"]["result"][0]
            closes = [c for c in r0["indicators"]["quote"][0]["close"] if c is not None]
            if len(closes) < 200:
                raise ValueError("short history")
            n += 1; above += closes[-1] > sum(closes[-200:]) / 200
            as_of = datetime.fromtimestamp(r0["timestamp"][-1], tz=IST).date().isoformat()
        except Exception:  # noqa: BLE001
            missing.append(s)
    if n < 40:
        return {"error": f"only {n}/{len(syms)} constituents priced", "source_url": src}
    return {"value": round(100 * above / n, 1), "prior": None, "as_of": as_of, "source_url": src,
            "note": f"% of Nifty 50 above 200-DMA ({above}/{n}); constituents NSE, prices Yahoo",
            "missing": missing}


# ---------- RBI OBICUS (capacity utilisation), official publication page ----------
OBICUS_SEED_ID = 24087  # discovery start (publication id of the Oct-2026 release); not a value
RBI_PUB = "https://www.rbi.org.in/scripts/PublicationsView.aspx?id={}"


def parse_obicus(text):
    i = text.find("Table 1: Capacity Utilisation")
    if i < 0:
        raise ValueError("Table 1 not found")
    seg = text[i:i + 1500].split("Note:")[0]
    rows = re.findall(r"Q([1-4]):(\d{4})-(\d{2})\s+\d+\s+(\d+\.\d)\s+(\d+\.\d)", seg)
    if not rows:
        raise ValueError("no quarter rows")
    q, y1, y2, cu, cusa = rows[-1]
    prior = float(rows[-2][3]) if len(rows) > 1 else None
    fy_end = int(y1) + 1
    qend = {1: (int(y1), 6), 2: (int(y1), 9), 3: (int(y1), 12), 4: (fy_end, 3)}[int(q)]
    last = (date(qend[0], qend[1] % 12 + 1, 1) if qend[1] < 12 else date(qend[0] + 1, 1, 1)) - timedelta(days=1)
    return {"value": float(cu), "prior": prior, "cu_sa": float(cusa), "survey_quarter": f"Q{q}FY{str(fy_end)[2:]}",
            "as_of": last.isoformat()}


def expected_obicus_quarter(today: date) -> str:
    """Latest quarter whose OBICUS result should be out: quarter end + ~100 days (RBI releases
    Q4FY26 on 5 Aug, Q1FY27 on 7 Oct 2026)."""
    y, m = today.year, today.month
    ends = []
    for yy in (y - 1, y):
        for mm in (3, 6, 9, 12):
            d = date(yy, mm, 30 if mm in (6, 9) else 31)
            if d + timedelta(days=100) <= today:
                ends.append(d)
    d = max(ends)
    q = {6: 1, 9: 2, 12: 3, 3: 4}[d.month]
    fy = d.year + 1 if d.month > 3 else d.year
    return f"Q{q}FY{str(fy)[2:]}"


def rbi_obicus(start_id: int | None = None, span: int = 60) -> dict:
    """Probe RBI publication ids from the last known OBICUS release forward; keep the newest match."""
    best, last_id = None, None
    sid = start_id or OBICUS_SEED_ID
    misses = 0
    for pid in range(sid, sid + span):
        t, err = _get(RBI_PUB.format(pid))
        if not t or "PublicationsView" not in t and "Reserve Bank" not in t:
            misses += 1
            if misses > 15:
                break
            continue
        misses = 0
        s = _text(t)
        if "Capacity Utilisation Survey on the Manufacturing sector" in s and "Table 1: Capacity Utilisation" in s:
            try:
                best, last_id = parse_obicus(s), pid
            except ValueError:
                pass
    if not best:
        return {"error": "no OBICUS publication found from id %d" % sid}
    return {**best, "source_url": RBI_PUB.format(last_id), "publication_id": last_id,
            "note": f"RBI OBICUS capacity utilisation {best['survey_quarter']} (CU-SA {best['cu_sa']})"}


# ---------- NSE FII/DII API (cookie warm-up) ----------
def nse_fii_dii() -> dict:
    import http.cookiejar, urllib.request
    cj = http.cookiejar.CookieJar()
    op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
    h = {**UA, "Accept": "application/json, text/plain, */*", "Referer": "https://www.nseindia.com/reports/fii-dii"}
    try:
        op.open(urllib.request.Request("https://www.nseindia.com/", headers=UA), timeout=20).read()
    except Exception:  # noqa: BLE001  (warm-up often returns 403 but still sets cookies)
        pass
    url = "https://www.nseindia.com/api/fiidiiTradeReact"
    raw = op.open(urllib.request.Request(url, headers=h), timeout=20).read()
    out = {}
    for r in json.loads(raw):
        key = "fii_net" if r["category"].upper().startswith("FII") else "dii_net" if r["category"].upper() == "DII" else None
        if key:
            out[key] = {"value": float(r["netValue"]), "prior": None,
                        "as_of": datetime.strptime(r["date"], "%d-%b-%Y").date().isoformat(), "source_url": url,
                        "note": f"NSE provisional cash market {r['category']} net (buy {r['buyValue']} / sell {r['sellValue']} cr)"}
    return out


# ---------- NSE trading holidays (for release rollover) ----------
def nse_holidays() -> set[str]:
    import http.cookiejar, urllib.request
    try:
        cj = http.cookiejar.CookieJar()
        op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))
        try:
            op.open(urllib.request.Request("https://www.nseindia.com/", headers=UA), timeout=15).read()
        except Exception:  # noqa: BLE001
            pass
        raw = op.open(urllib.request.Request("https://www.nseindia.com/api/holiday-master?type=trading",
                                             headers={**UA, "Referer": "https://www.nseindia.com/"}), timeout=15).read()
        return {datetime.strptime(h["tradingDate"], "%d-%b-%Y").date().isoformat() for h in json.loads(raw).get("CM", [])}
    except Exception:  # noqa: BLE001
        return set()
