"""Lending radar data layer: self-discovering, fallback-chained fetchers for sector data.
Numbers only from official structured tables (RBI xlsx, PIB statement table, Commerce QE pdf) or
exchange prices. DeepSeek is used ONLY to discover URLs (site: search), never for numbers."""
from __future__ import annotations
import html, io, json, os, re, subprocess, sys, tempfile, shutil
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import refresh_data as rd  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
CONFIG = Path(__file__).resolve().parent / "lending_config.json"
STATE = ROOT / "data" / "lending_state.json"
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
          "October", "November", "December"]
MON3 = {m[:3].lower(): i + 1 for i, m in enumerate(MONTHS)}


def load_config():
    return json.loads(CONFIG.read_text())


def load_state():
    return json.loads(STATE.read_text()) if STATE.exists() else {}


def save_state(s):
    STATE.write_text(json.dumps(s, indent=1, sort_keys=True))


def _get(url, timeout=40, binary=False, tries=3):
    import time
    err = None
    for i in range(tries):
        b, err, final = rd.http_get(url, timeout=timeout, headers={"Accept": "*/*"} if binary else None)
        if b and not (binary and b.lstrip()[:15].lower().startswith((b"<!doctype", b"<html"))):
            return b, None
        if b:
            err = "bot-challenge HTML instead of file"
        time.sleep(3 * (i + 1))
    return None, err


def _text(h):
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", h)))


def month_end(y, m):
    return (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))


# ------------------------------------------------------------------ parsers (pure, unit-tested)
def parse_sibc_rows(rows):
    """rows: iterable of tuples from the SIBC workbook (both statements). Returns
    {code: {name, outstanding_cr, outstanding_yago_cr, yoy_pct, fy_pct, as_of, check}}."""
    out, dates = {}, None
    for r in rows:
        cells = [c for c in r if c is not None]
        if not cells:
            continue
        if all(isinstance(c, str) for c in cells) and len(cells) >= 5 and re.match(r"\d{1,2}\.\w{3},\d{4}", str(cells[0])):
            dates = cells[:5]
            continue
        lab = str(cells[0]).strip()
        m = re.match(r"^(\d+(?:\.\d+)*)\.\s+(.*)$", lab)
        nums = [c for c in cells[1:] if isinstance(c, (int, float))]
        if not m or len(nums) < 9 or dates is None:
            continue
        code, name = m.group(1), re.sub(r"\s+", " ", m.group(2)).strip()
        yago, cur, yoy, fy = float(nums[2]), float(nums[4]), float(nums[6]), float(nums[8])
        calc = (cur / yago - 1) * 100 if yago else None
        dd, mm, yy = re.match(r"(\d{1,2})\.(\w{3}),(\d{4})", dates[4]).groups()
        out[code] = {"name": name, "outstanding_cr": round(cur), "outstanding_yago_cr": round(yago),
                     "yoy_pct": round(yoy, 2), "fy_pct": round(fy, 2),
                     "as_of": date(int(yy), MON3[mm.lower()], int(dd)).isoformat(),
                     "check_ok": calc is not None and abs(calc - yoy) < 0.1}
    return out


def parse_iip_text(s):
    """PIB IIP statement (NIC 2-digit). Returns ({nic: {...}}, period_iso)."""
    p = re.search(r"Figures for (\w{3})\w* (\d{4}) are Quick Estimates", s)
    period = month_end(int(p.group(2)), MON3[p.group(1)[:3].lower()]).isoformat() if p else None
    out = {}
    num = r"(-?\d+(?:\.\d+)?)"
    pat = re.compile(r"\b(\d{2}) ((?:Manufacture of|Other manufacturing)[^0-9]{0,140}?) " + " ".join([num] * 7))
    for m in pat.finditer(s):
        nic = m.group(1)
        if nic in out:
            continue
        w, a, b, c, d, g, gc = (float(x) for x in m.groups()[2:])
        chk = a and abs((b / a - 1) * 100 - g) < 0.2 and c and abs((d / c - 1) * 100 - gc) < 0.2
        out[nic] = {"name": m.group(2).strip(), "weight": w, "index": b, "index_yago": a, "yoy_pct": g,
                    "fytd_pct": gc, "check_ok": bool(chk)}
    return out, period


def parse_exports_text(t, period_iso=None):
    """Commerce QE pdftotext -layout. Returns {serial: {name, inr_cr, inr_cr_yago, inr_fytd_cr, inr_fytd_pct, usd_pct, usd_fytd_pct}}."""
    def block(unit):
        i = t.find(f"(Values in {unit})")
        if i < 0:
            return {}
        seg = t[i:]
        j = seg.find("(Values in", 20)
        seg = seg[: j if j > 0 else len(seg)]
        rows, prev = {}, ""
        num = r"(-?\d+(?:\.\d+)?)"
        for line in seg.splitlines():
            m = re.match(r"^\s*(\d{1,2})\s+(.*?)\s+" + r"\s+".join([num] * 6) + r"\s*$", line)
            if m:
                n = int(m.group(1))
                if n not in rows:
                    vals = [float(x) for x in m.groups()[2:]]
                    rows[n] = {"name": (prev + " " + m.group(2)).strip() if not re.search(r"[A-Za-z]{3}", m.group(2) or "") or prev else m.group(2), "v": vals}
                prev = ""
            else:
                prev = line.strip() if re.search(r"[A-Za-z]", line) and len(line.strip()) < 45 else ""
        return rows
    inr, usd = block("Rs Crore"), block("Million USD")
    out = {}
    for n, r in inr.items():
        a, c, b, d, g, gc = r["v"]  # m-yago, fytd-yago, m, fytd, %m, %fytd
        u = usd.get(n, {}).get("v")
        chk = a and abs((b / a - 1) * 100 - g) < 0.15
        out[n] = {"name": re.sub(r"\s+", " ", r["name"]), "inr_cr": b, "inr_cr_yago": a, "inr_fytd_cr": d,
                  "inr_pct": g, "inr_fytd_pct": gc, "usd_pct": u[4] if u else None,
                  "usd_fytd_pct": u[5] if u else None, "check_ok": bool(chk), "as_of": period_iso}
    return out


# ------------------------------------------------------------------ discovery
def deepseek_available():
    return bool(os.environ.get("DEEPSEEK_API_KEY"))


def deepseek_urls(query):
    from engine import search_adapter as sa
    return [r.get("url") for r in sa.search(query, count=8) if r.get("url")]


def _target_month(today, lag=1):
    y, m = today.year, today.month - lag
    while m <= 0:
        y, m = y - 1, m + 12
    return y, m


def discover(dataset, cfg, state, health, today=None, validator=None):
    """Walk the source chain; first step returning a URL that the validator accepts wins.
    validator(url) -> (payload, period) or raises. Every attempt is logged to `health`."""
    today = today or datetime.now(IST).date()
    src = cfg["sources"][dataset]
    for step in src["chain"]:
        sid, meth = step["id"], step["method"]
        try:
            cands = []
            if meth == "html_link":
                b, e = _get(step["url"])
                if not b:
                    raise RuntimeError(e)
                t = b.decode("utf-8", "ignore")
                for href, title in re.findall(r"href=['\"]?([^'\" >]+)['\"]?[^>]*>([^<]{0,200})", t):
                    if re.search(step["title_regex"], title, re.I):
                        href = html.unescape(href)
                        if not href.startswith("http"):
                            href = "https://www.rbi.org.in/Scripts/" + href.split("/")[-1]
                        cands.append(href)
                cands = cands[:2]
            elif meth == "rss_scan":
                b, e = _get(step["url"])
                if not b:
                    raise RuntimeError(e)
                t = b.decode("utf-8", "ignore")
                cands = [l for ti, l in re.findall(r"<title>([^<]*)</title>\s*<link>([^<]*)", t) if re.search(step["title_regex"], ti, re.I)]
            elif meth == "deepseek_search":
                if not deepseek_available():
                    health.append({"dataset": dataset, "source": sid, "ok": False, "skipped": True, "error": "DEEPSEEK_API_KEY not set (auto-enables when added)", "url": None})
                    continue
                y, m = _target_month(today)
                cands = deepseek_urls(step["query"].format(month_year=f"{MONTHS[m-1]} {y}"))
            elif meth == "url_pattern":
                for lag in range(1, step.get("lookback_months", 3) + 1):
                    y, m = _target_month(today, lag)
                    ry, rm = (y + (m == 12), m % 12 + 1)
                    cands.append(step["url"].format(rel_yyyy_mm=f"{ry}-{rm:02d}", month_name=MONTHS[m - 1], year=y))
            elif meth == "last_known":
                if state.get(dataset, {}).get("url"):
                    cands = [state[dataset]["url"]]
            elif meth == "cache":
                c = state.get(dataset, {})
                if not c.get("payload"):
                    raise RuntimeError("no cached last-known-good payload")
                health.append({"dataset": dataset, "source": sid, "ok": True, "error": "live sources failed; serving last-known-good (freshness gate decides if stale)", "url": c.get("url"), "period": c.get("period")})
                return c["payload"], c.get("period"), c.get("url"), sid
            elif meth == "static":
                cands = [step["url"]]
            elif meth in ("yahoo", "local_json"):
                cands = [step.get("url", "")]
            if not cands:
                raise RuntimeError("no candidate URL found")
            last_err = None
            for u in cands:
                try:
                    payload, period = validator(u)
                    health.append({"dataset": dataset, "source": sid, "ok": True, "error": None, "url": u, "period": period})
                    prev = state.get(dataset, {})
                    state[dataset] = {"url": u, "period": period, "discovered_by": sid, "payload": payload,
                                      "checked_ist": datetime.now(IST).strftime("%Y-%m-%d %H:%M"),
                                      "first_seen": prev.get("first_seen") if prev.get("url") == u else datetime.now(IST).date().isoformat()}
                    return payload, period, u, sid
                except Exception as e:  # noqa: BLE001
                    last_err = f"{u}: {e}"
            raise RuntimeError(last_err)
        except Exception as e:  # noqa: BLE001
            health.append({"dataset": dataset, "source": sid, "ok": False, "error": str(e)[:300], "url": step.get("url")})
    return None, None, None, None


# ------------------------------------------------------------------ validators (fetch + parse + check)
def _rbi_release_to_xlsx(url, file_regex=r"SIBC\w*\.xlsx"):
    if url.lower().endswith(".xlsx"):
        return url, None
    b, e = _get(url)
    if not b:
        raise RuntimeError(e)
    t = b.decode("utf-8", "ignore")
    links = re.findall(r"href=['\"]?(https?://[^'\" >]+?\.xlsx)", t, re.I)
    links = [l for l in links if re.search(file_regex, l, re.I)]
    if not links:
        raise RuntimeError("release page has no SIBC xlsx link")
    return links[0], url


def validate_sibc(url):
    import openpyxl
    xurl, page = _rbi_release_to_xlsx(url)
    b, e = _get(xurl, timeout=60, binary=True)
    if not b:
        raise RuntimeError(e)
    wb = openpyxl.load_workbook(io.BytesIO(b), data_only=True, read_only=True)
    rows = [r for ws in wb for r in ws.iter_rows(values_only=True)]
    data = parse_sibc_rows(rows)
    if "2.4" not in data or "2.16" not in data:
        raise RuntimeError("SIBC statements not recognised")
    period = data["2.4"]["as_of"]
    return {"rows": data, "xlsx_url": xurl, "release_url": page or xurl}, period


def validate_iip(url):
    b, e = _get(url, timeout=60)
    if not b:
        raise RuntimeError(e)
    s = _text(b.decode("utf-8", "ignore"))
    if "Industrial Production" not in s and "औद्योगिक" not in s:
        raise RuntimeError("not an IIP release")
    data, period = parse_iip_text(s)
    if len(data) < 15 or not period:
        raise RuntimeError(f"NIC 2-digit table not found (got {len(data)} rows)")
    return {"rows": data}, period


def validate_exports(url):
    if not shutil.which("pdftotext"):
        raise RuntimeError("pdftotext missing")
    b, e = _get(url, timeout=60, binary=True)
    if not b or not b.startswith(b"%PDF"):
        raise RuntimeError(e or "not a PDF")
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(b); f.flush()
        t = subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, text=True, timeout=60).stdout
    m = re.search(r"Quick%20Estimates%20(\w+)%20(\d{4})", url) or re.search(r"Quick Estimates (\w+) (\d{4})", url)
    period = month_end(int(m.group(2)), MON3[m.group(1)[:3].lower()]).isoformat() if m else None
    data = parse_exports_text(t, period)
    if len(data) < 25:
        raise RuntimeError(f"export table not found ({len(data)} rows)")
    return {"rows": data}, period


def yahoo_yoy(symbol):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{symbol.replace('=', '%3D')}?range=1y&interval=1d"
    b, e = _get(url)
    if not b:
        return {"error": e, "source_url": url}
    try:
        r0 = json.loads(b)["chart"]["result"][0]
        ts, cl = r0["timestamp"], r0["indicators"]["quote"][0]["close"]
        pts = [(t, c) for t, c in zip(ts, cl) if c is not None]
        (t0, c0), (t1, c1) = pts[0], pts[-1]
        return {"value": round(c1, 3), "year_ago": round(c0, 3), "yoy_pct": round((c1 / c0 - 1) * 100, 1),
                "as_of": datetime.fromtimestamp(t1, IST).date().isoformat(), "source_url": url}
    except Exception as ex:  # noqa: BLE001
        return {"error": f"parse: {ex}", "source_url": url}
