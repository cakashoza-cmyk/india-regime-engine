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
                    cands.append(step["url"].format(rel_yyyy_mm=f"{ry}-{rm:02d}", month_name=MONTHS[m - 1], year=y,
                                                    mon3_lower=MONTHS[m - 1][:3].lower()))
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
    sheets = [list(ws.iter_rows(values_only=True)) for ws in wb]
    data = parse_sibc_rows([r for sh in sheets[1:] for r in sh]) if len(sheets) > 1 else {}
    s1 = parse_sibc_rows(sheets[0]) if sheets else {}
    for k, v in s1.items():  # Statement 1 (incl. MSME split) re-uses codes -> keep under "S1:" prefix
        data["S1:" + k] = v
        data.setdefault(k, v)
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


# ------------------------------------------------------------------ state-level datasets
def norm_state(n):
    n = html.unescape(str(n or "")).lower().replace("&", " and ")
    n = re.sub(r"\(.*?\)|\bthe\b|\but of\b|\bislands?\b|\bterritory\b|\bstate\b|[^a-z ]", " ", n)
    return re.sub(r"\s+", " ", n).strip()


def _num(x):
    return float(x.replace(",", "")) if isinstance(x, str) else float(x)


GST_CODES = {1: "Jammu and Kashmir", 2: "Himachal Pradesh", 3: "Punjab", 4: "Chandigarh", 5: "Uttarakhand", 6: "Haryana", 7: "Delhi",
             8: "Rajasthan", 9: "Uttar Pradesh", 10: "Bihar", 11: "Sikkim", 12: "Arunachal Pradesh", 13: "Nagaland", 14: "Manipur",
             15: "Mizoram", 16: "Tripura", 17: "Meghalaya", 18: "Assam", 19: "West Bengal", 20: "Jharkhand", 21: "Odisha",
             22: "Chhattisgarh", 23: "Madhya Pradesh", 24: "Gujarat", 26: "Dadra and Nagar Haveli and Daman & Diu", 27: "Maharashtra",
             29: "Karnataka", 30: "Goa", 31: "Lakshadweep", 32: "Kerala", 33: "Tamil Nadu", 34: "Puducherry",
             35: "Andaman and Nicobar Islands", 36: "Telangana", 37: "Andhra Pradesh", 38: "Ladakh"}  # official GST state codes


def parse_gst_text(t):
    """GSTN monthly revenue report: Table 3 (state month YoY) + Table 4 (state Apr-to-date total, growth)."""
    m = re.search(r"Table\s*3\s*:\s*State-wise growth of GST Revenues during\s+(\w+),?\s*(\d{4})", t)
    if not m:
        raise ValueError("GST Table 3 not found")
    mon = MONTHS.index(m.group(1).capitalize()) + 1
    period = month_end(int(m.group(2)), mon).isoformat()
    t3 = t[m.end(): t.find("Table 4", m.end())]
    out = {}
    for name, a, b, g in re.findall(r"^\s*([A-Za-z][A-Za-z &.\-]+?)\s{2,}([\d,]+)\s+([\d,]+)\s+(-?\d+)%\s*$", t3, re.M):
        a, b, g = _num(a), _num(b), int(g)
        calc = (b / a - 1) * 100 if a else None
        out[name.strip()] = {"month_prev_cr": a, "month_cr": b, "month_yoy_pct": round(calc, 1) if calc is not None else None,
                             "check_ok": calc is not None and abs(calc - g) <= 1.0}
    t2 = t[t.find("Table-2"): t.find("Table 3")] if "Table-2" in t else ""
    sgst_ytd = {norm_state(n): _num(b) for n, a, b in re.findall(r"^\s*([A-Za-z][A-Za-z &.\-]+?)\s{2,}([\d,]+)\s+([\d,]+)\s+-?\d+%", t2, re.M)}
    t4 = t[t.find("Table 4"):]
    for line in t4.splitlines():
        mm = re.match(r"^\s*(\d{1,2})?\s*([A-Za-z][A-Za-z &.\-]+?)\s{2,}([\d,\s]+?)\s+(-?[\d.]+)%\s+(-?[\d.]+)%\s+(-?[\d.]+)%\s*$", line)
        if not mm:
            continue
        nums = re.findall(r"[\d,]+", mm.group(3))
        if len(nums) < 9:
            continue
        nm = GST_CODES.get(int(mm.group(1)), mm.group(2).strip()) if mm.group(1) else mm.group(2).strip()
        cur, prev = _num(nums[-1]), _num(nums[(len(nums) - 1) // 2])  # Apr-to-date total this year vs last year block
        g = float(mm.group(6))
        key = next((k for k in out if norm_state(k) == norm_state(nm)), nm)
        rec = out.setdefault(key, {"check_ok": True})
        sg = sgst_ytd.get(norm_state(nm))  # cross-check: Table 4 SGST Apr-to-date must equal Table 2 pre-settlement SGST
        rec.update({"fytd_cr": cur, "fytd_pct": g, "fytd_check_ok": sg is not None and abs(_num(nums[-3]) - sg) <= 1})
    if len(out) < 25:
        raise ValueError(f"GST state table too small ({len(out)})")
    if "Grand Total" in out:
        out["India"] = out.pop("Grand Total")
    if "India" in out and "fytd_cr" not in out["India"]:
        tot = re.search(r"^\s*(?:Grand Total|Total)\s+([\d,\s]+?)\s+(-?[\d.]+)%\s+(-?[\d.]+)%\s+(-?[\d.]+)%\s*$", t4, re.M)
        if tot:
            n = re.findall(r"[\d,]+", tot.group(1))
            out["India"].update({"fytd_cr": _num(n[-1]), "fytd_pct": float(tot.group(4)), "fytd_check_ok": True})
    return out, period


def validate_gst(url):
    b, e = _get(url, timeout=60, binary=True)
    if not b or not b.startswith(b"%PDF"):
        raise RuntimeError(e or "not a PDF")
    rows, period = parse_gst_text(_pdftext(b))
    return {"rows": rows, "release_url": url}, period


def _pdftext(b):
    with tempfile.NamedTemporaryFile(suffix=".pdf") as f:
        f.write(b); f.flush()
        return subprocess.run(["pdftotext", "-layout", f.name, "-"], capture_output=True, text=True, timeout=120).stdout


CEA_SKIP = ("region", "all india", "dvc", "others", "lakshadweep", "andaman")


def parse_cea_text(t):
    """CEA Power Supply Position (Energy): per state, month and Apr-to-date energy requirement (MU)."""
    m = re.search(r"/\s*(\w+),\s*(\d{4})\s+\S*\s*[^/\n]*?/\s*April,\s*(\d{4})\s+to\s+(\w+),\s*(\d{4})", t)
    if not m:
        raise ValueError("CEA header not found")
    mon = MONTHS.index(m.group(1).capitalize()) + 1
    period = month_end(int(m.group(2)), mon).isoformat()
    out, pending = {}, None
    for line in t.splitlines():
        eng = re.findall(r"[A-Za-z][A-Za-z&.\- ]{2,}", line)
        nums = re.findall(r"(?<![\w.])(\d[\d,]*\.?\d*)(?![\w])", line)
        name = None
        if eng:
            cand = max(eng, key=len).strip(" -/")
            if len(cand) >= 3 and not re.search(r"MU|Energy|Requirement|Supplied|Figures|Report|Region\s*$", cand):
                name = cand
        if name and len(nums) < 8:
            pending = name
            continue
        if len(nums) >= 8:
            nm = name or pending
            pending = None
            if not nm or any(k in nm.lower() for k in CEA_SKIP):
                continue
            v = [_num(x) for x in nums[-8:]]
            out[nm] = {"req_mu": v[0], "sup_mu": v[1], "fytd_req_mu": v[4], "fytd_sup_mu": v[5],
                       "check_ok": abs(v[0] - v[1] - v[2]) <= 2 and v[4] >= v[0]}
    if len(out) < 25:
        raise ValueError(f"CEA state table too small ({len(out)})")
    return out, period


def validate_power(url):
    """url = CEA 'Power Supply Position - Energy' dashboard; picks latest month and the same month a year earlier."""
    b, e = _get(url)
    if not b:
        raise RuntimeError(e)
    h = b.decode("utf-8", "ignore")
    rows = re.findall(r"(20\d\d-\d\d)(?:(?!20\d\d-\d\d).){0,1500}?download-pdf/en/([0-9a-f-]{36})", h, re.S)
    if not rows:
        raise RuntimeError("no monthly report rows on CEA dashboard")
    ym = {r[0]: r[1] for r in rows}
    latest = max(ym)
    y, mo = map(int, latest.split("-"))
    prev = f"{y-1}-{mo:02d}"
    if prev not in ym:
        raise RuntimeError(f"year-ago report {prev} not listed")
    base = "https://cea.nic.in/api/dashboardReports/download-pdf/en/"
    parsed = []
    for k in (latest, prev):
        pb, pe = _get(base + ym[k], timeout=60, binary=True)
        if not pb or not pb.startswith(b"%PDF"):
            raise RuntimeError(pe or "CEA report not a PDF")
        parsed.append(parse_cea_text(_pdftext(pb)))
    (cur, period), (old, _) = parsed
    oldn = {norm_state(k): v for k, v in old.items()}
    out = {}
    for k, v in cur.items():
        o = oldn.get(norm_state(k))
        if not o:
            continue
        out[k] = {"req_mu": v["req_mu"], "month_yoy_pct": round((v["req_mu"] / o["req_mu"] - 1) * 100, 1) if o["req_mu"] else None,
                  "fytd_req_mu": v["fytd_req_mu"], "fytd_pct": round((v["fytd_req_mu"] / o["fytd_req_mu"] - 1) * 100, 1) if o["fytd_req_mu"] else None,
                  "check_ok": v["check_ok"] and o["check_ok"]}
    tot_c, tot_o = sum(v["fytd_req_mu"] for v in cur.values()), sum(oldn[norm_state(k)]["fytd_req_mu"] for k in out)
    out["India"] = {"fytd_req_mu": tot_c, "fytd_pct": round((sum(cur[k]["fytd_req_mu"] for k in out if k in cur) / tot_o - 1) * 100, 1) if tot_o else None,
                    "check_ok": True, "note": "sum of states parsed"}
    return {"rows": out, "release_url": url, "report_url": base + ym[latest], "year_ago_url": base + ym[prev]}, period


def parse_hsis_sheet(rows):
    """RBI Handbook of Statistics on Indian States table: Region/State x end-March years (may be split in blocks/sheets)."""
    hdr, ser, title = None, {}, ""
    for r in rows:
        r = list(r)
        while r and r[0] is None:
            r.pop(0)
        if not r:
            continue
        if isinstance(r[0], str) and r[0].upper().startswith("TABLE"):
            title = title or r[0]
        if isinstance(r[0], str) and "State" in r[0] and sum(isinstance(x, (int, float)) and 1990 < x < 2100 for x in r[1:]) >= 2:
            hdr = r
            continue
        if hdr and isinstance(r[0], str):
            for y, v in zip(hdr[1:], r[1:]):
                if isinstance(y, (int, float)) and isinstance(v, (int, float)):
                    ser.setdefault(r[0].strip(), {})[int(y)] = float(v)
    out = {}
    for k, d in ser.items():
        ys = sorted(d)
        if len(ys) >= 2:
            out[k] = {"year": ys[-1], "value": d[ys[-1]], "prev": d[ys[-2]]}
    return out, title


def validate_rbi_state(url):
    import openpyxl
    b, e = _get(url)
    if not b:
        raise RuntimeError(e)
    h = b.decode("utf-8", "ignore")
    res = {}
    for tid, key in (("153T", "cd_ratio"), ("156T", "credit"), ("158T", "industry_credit")):
        m = re.search(r"id='ADOC_" + tid + r"[^']*'[^>]*href='([^']+)'", h)
        if not m:
            raise RuntimeError(f"Handbook table {tid} link not found")
        xb, xe = _get(m.group(1), timeout=60, binary=True)
        if not xb:
            raise RuntimeError(xe)
        wb = openpyxl.load_workbook(io.BytesIO(xb), data_only=True, read_only=True)
        rows, title = parse_hsis_sheet([r for ws in wb.worksheets for r in ws.iter_rows(values_only=True)])
        res[key] = {"rows": rows, "title": title, "xlsx_url": m.group(1)}
    cr = res["credit"]["rows"]
    year = max(v["year"] for v in cr.values())
    states = {}
    for nm, v in cr.items():
        if "REGION" in nm.upper():
            continue
        rec = {"credit_cr": v["value"], "credit_yoy_pct": round((v["value"] / v["prev"] - 1) * 100, 1) if v["prev"] else None}
        cd = res["cd_ratio"]["rows"].get(nm)
        ind = res["industry_credit"]["rows"].get(nm)
        if cd: rec["cd_ratio_pct"] = cd["value"]
        if ind and ind["prev"]: rec.update(industry_credit_cr=ind["value"], industry_credit_yoy_pct=round((ind["value"] / ind["prev"] - 1) * 100, 1))
        states[nm] = rec
    tot = next((v for k, v in cr.items() if k.upper().startswith("ALL INDIA")), None)
    ssum = sum(v["credit_cr"] for v in states.values() if not v.get("_x"))
    states.pop(next((k for k in states if k.upper().startswith("ALL INDIA")), "__"), None)
    ssum = sum(v["credit_cr"] for v in states.values())
    ok = bool(tot) and abs(ssum / tot["value"] - 1) < 0.02
    for v in states.values():
        v["check_ok"] = ok
    return {"rows": states, "release_url": url, "xlsx_urls": {k: v["xlsx_url"] for k, v in res.items()}}, f"{year}-03-31"


# ---------------- RBI FSR: GNPA ratios of industrial sub-sectors (chart data labels) ----------------
FSR_LABELS = [("mining", "Mining"), ("food", "Food"), ("textiles", "Textiles"), ("paper", "Paper"),
              ("refining", "Petroleum"), ("chemicals", "Chemicals"), ("rubber_plastics", "Rubber"),
              ("cement", "Cement"), ("basic_metals", "Basic"), ("engineering", "Engineering"),
              ("vehicles", "Vehicles"), ("gems_jewellery", "Gems"), ("construction", "Construction"),
              ("infrastructure", "Infrastructure")]


def _fsr_key(name):
    n = name.lower()
    for kw, key in [("mining", "mining"), ("food", "food"), ("textile", "textiles"), ("paper", "paper"),
                    ("petroleum", "refining"), ("chemical", "chemicals"), ("rubber", "rubber_plastics"),
                    ("cement", "cement"), ("basic", "basic_metals"), ("vehicle", "vehicles"),
                    ("gems", "gems_jewellery"), ("construction", "construction"), ("engineering", "engineering"),
                    ("excluding", "infra_ex_power"),
                    ("electricity", "power"), ("power", "power"), ("telecom", "telecom"), ("road", "roads"), ("infrastructure", "infrastructure")]:
        if kw in n:
            return key
    return None


def parse_fsr_subsector_bbox(bbox_html):
    """FSR chart 'GNPA Ratios of Industrial Sub-sectors': rotated category labels with one data label
    (latest bar) each. Pair every data label with the nearest label column on its left (pdftotext -bbox)."""
    import re as _re
    for page in bbox_html.split("<page ")[1:]:
        if "Sub-sectors" not in page or "GNPA" not in page or "Textiles" not in page:
            continue
        W = [(float(a), float(b), t) for a, b, t in
             _re.findall(r'xMin="([\d.]+)" yMin="([\d.]+)" xMax="[\d.]+" yMax="[\d.]+">([^<]*)<', page)]
        title = [w for w in W if w[2] == "Sub-sectors"]
        if not title:
            continue
        tx, ty = title[0][0], title[0][1]
        region = [w for w in W if ty < w[1] < ty + 175 and tx - 270 < w[0] < tx + 230]
        legend = [w for w in region if _re.fullmatch(r"(Mar|Sep)-\d\d", w[2])]
        vals = sorted([w for w in region if _re.fullmatch(r"\d{1,2}\.\d", w[2])], key=lambda w: w[0])
        if not legend or not vals:
            continue
        ytop = max(v[1] for v in vals) + 8
        ybot = min(l[1] for l in legend) - 2
        words = sorted([w for w in region if ytop < w[1] < ybot and not _re.fullmatch(r"[\d.]+", w[2])], key=lambda w: w[0])
        cols = []
        for w in words:
            if cols and w[0] - cols[-1][-1][0] < 12:
                cols[-1].append(w)
            else:
                cols.append([w])
        # a rotated label can span 2 sub-columns (wrapped); merge columns closer than the bar pitch/2
        names = [(min(c, key=lambda w: w[0])[0], " ".join(w[2] for w in sorted(c, key=lambda w: (round(w[0] / 5), -w[1])))) for c in cols]
        if len(names) != len(vals):
            continue
        out, ok = {}, True
        for (lx, nm), v in zip(names, vals):
            k = _fsr_key(nm)
            if not (0 < v[0] - lx < 25) or not k or k in out:
                ok = False; break
            out[k] = float(v[2])
        if not ok or len(out) < 10:
            continue
        def _d(s):
            m, y = s.split("-"); return (2000 + int(y), 3 if m == "Mar" else 9)
        return {"period": max((l[2] for l in legend), key=_d), "gnpa": out}
    return None


def validate_fsr_gnpa(pdf_url):
    b, err = _get(pdf_url, binary=True, timeout=240, tries=2)
    if not b:
        return None, err or "fetch failed"
    import subprocess, tempfile, os
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "f.pdf"); open(p, "wb").write(b)
        subprocess.run(["pdftotext", "-bbox", p, p + ".html"], capture_output=True, timeout=180)
        html = open(p + ".html", encoding="utf8", errors="ignore").read() if os.path.exists(p + ".html") else ""
    r = parse_fsr_subsector_bbox(html)
    return (r, None) if r else (None, "sub-sector GNPA chart not found / labels misaligned")
