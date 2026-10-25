#!/usr/bin/env python3
"""
Fetch free public market/macro signals and write data/snapshot.json.
Never invents numbers: failed fetches become null / Unknown + warning string.
Run: python3 refresh_data.py
"""
from __future__ import annotations

import json
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from http.cookiejar import CookieJar
from pathlib import Path

OUT = Path(__file__).resolve().parent / "data" / "snapshot.json"
IST = timezone(timedelta(hours=5, minutes=30), name="Asia/Calcutta")
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def now_ist() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S Asia/Calcutta")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def http_get(
    url: str,
    timeout: int = 25,
    headers: dict | None = None,
    opener: urllib.request.OpenerDirector | None = None,
) -> tuple[bytes | None, str | None, str | None]:
    """Return (body, error, final_url)."""
    h = {
        "User-Agent": UA,
        "Accept": "application/json,text/html,application/xhtml+xml,*/*;q=0.8",
        "Accept-Language": "en-IN,en;q=0.9",
    }
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, headers=h)
    ctx = ssl.create_default_context()
    try:
        if opener is not None:
            with opener.open(req, timeout=timeout) as resp:
                return resp.read(), None, resp.geturl()
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return resp.read(), None, resp.geturl()
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}", None


def yahoo_chart(symbol: str, range_: str = "5d") -> dict:
    """Return last close, prior close, as-of, direction from Yahoo chart API."""
    enc = urllib.parse.quote(symbol, safe="")
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{enc}"
        f"?range={range_}&interval=1d"
    )
    raw, err, _ = http_get(url)
    out = {
        "symbol": symbol,
        "value": None,
        "prior": None,
        "as_of": None,
        "direction": "unknown",
        "change_1m_pct": None,
        "source": "Yahoo Finance chart API",
        "source_url": url,
        "error": err,
        "evidence": "fact",
    }
    if not raw:
        return out
    try:
        data = json.loads(raw.decode("utf-8", errors="replace"))
        result = (data.get("chart") or {}).get("result") or []
        if not result:
            out["error"] = "empty chart result"
            return out
        r0 = result[0]
        meta = r0.get("meta") or {}
        ts = r0.get("timestamp") or []
        quote = ((r0.get("indicators") or {}).get("quote") or [{}])[0]
        closes = [c for c in (quote.get("close") or []) if c is not None]
        if not closes:
            price = meta.get("regularMarketPrice")
            if price is None:
                out["error"] = "no closes"
                return out
            out["value"] = float(price)
            out["as_of"] = datetime.fromtimestamp(
                meta.get("regularMarketTime") or 0, tz=IST
            ).strftime("%Y-%m-%d")
            out["direction"] = "unknown"
            out["error"] = None
            return out
        out["value"] = float(closes[-1])
        out["prior"] = float(closes[-2]) if len(closes) >= 2 else None
        if ts:
            out["as_of"] = datetime.fromtimestamp(ts[-1], tz=IST).strftime("%Y-%m-%d")
        if out["prior"] is not None and out["prior"] != 0:
            chg = (out["value"] - out["prior"]) / abs(out["prior"])
            if chg > 0.0015:
                out["direction"] = "rising"
            elif chg < -0.0015:
                out["direction"] = "falling"
            else:
                out["direction"] = "flat"
        # 1m change when range covers ~20 sessions
        if len(closes) >= 2 and closes[0] != 0:
            out["change_1m_pct"] = round(
                (closes[-1] - closes[0]) / abs(closes[0]) * 100.0, 4
            )
        out["error"] = None
    except Exception as e:  # noqa: BLE001
        out["error"] = f"parse: {e}"
    return out


def empty_macro(name: str, note: str) -> dict:
    return {
        "name": name,
        "value": None,
        "unit": "%",
        "as_of": None,
        "direction": "unknown",
        "prior": None,
        "source": note,
        "source_url": None,
        "error": "not fetched automatically — enter manually in UI",
        "evidence": "unknown",
    }


def _parse_nse_date(s: str) -> str | None:
    """23-Oct-2026 → 2026-10-23"""
    try:
        return datetime.strptime(s.strip(), "%d-%b-%Y").strftime("%Y-%m-%d")
    except Exception:  # noqa: BLE001
        return None


def fetch_fii_dii() -> tuple[dict, dict, list[str]]:
    """
    Equity cash CM FII/DII net INR crore.
    Prefer Moneycontrol page; fall back to NSE provisional cash API.
    NEVER use NSDL grand total (equity+debt).
    """
    warnings: list[str] = []
    blank = {
        "name": "",
        "value": None,
        "unit": "INR crore",
        "as_of": None,
        "direction": "unknown",
        "source": None,
        "source_url": None,
        "error": None,
        "evidence": "unknown",
        "scope": "equity_cash_CM",
    }
    fii = dict(blank)
    fii["name"] = "FII/FPI net (equity cash CM)"
    dii = dict(blank)
    dii["name"] = "DII net (equity cash CM)"

    # --- try Moneycontrol HTML ---
    mc_url = "https://www.moneycontrol.com/markets/fii-dii-data/"
    raw, err, _ = http_get(mc_url)
    if raw and not err:
        text = raw.decode("utf-8", errors="replace")
        # Heuristic: look for FII/DII cash tables with net figures
        # Moneycontrol often embeds JSON; keep conservative parse
        parsed = _parse_moneycontrol_fii_dii(text, mc_url)
        if parsed:
            return parsed[0], parsed[1], warnings
        warnings.append(
            "Moneycontrol FII/DII page fetched but cash CM numbers not parsed; trying NSE."
        )
    else:
        warnings.append(f"Moneycontrol FII/DII scrape failed ({err}); trying NSE cash CM API.")

    # --- NSE provisional cash CM (equity only — not NSDL grand total) ---
    nse_api = "https://www.nseindia.com/api/fiidiiTradeReact"
    nse_home = "https://www.nseindia.com/reports/fii-dii"
    jar = CookieJar()
    ctx = ssl.create_default_context()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(jar),
        urllib.request.HTTPSHandler(context=ctx),
    )
    # Warm cookies
    http_get(nse_home, opener=opener, headers={"Referer": "https://www.nseindia.com/"})
    raw2, err2, _ = http_get(
        nse_api,
        opener=opener,
        headers={
            "Referer": nse_home,
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json",
        },
    )
    if not raw2 or err2:
        msg = f"NSE FII/DII API failed ({err2}). FII/DII left null — do not invent."
        warnings.append(msg)
        fii["error"] = msg
        dii["error"] = msg
        return fii, dii, warnings

    try:
        rows = json.loads(raw2.decode("utf-8", errors="replace"))
        if not isinstance(rows, list):
            raise ValueError("unexpected NSE payload type")
        by_cat = {}
        as_of = None
        for row in rows:
            cat = str(row.get("category") or "").upper()
            net = float(str(row.get("netValue")).replace(",", ""))
            as_of = _parse_nse_date(str(row.get("date") or "")) or as_of
            by_cat[cat] = net
        # Categories: FII/FPI and DII — equity cash CM provisional
        fii_val = None
        dii_val = None
        for k, v in by_cat.items():
            if "FII" in k or "FPI" in k:
                fii_val = v
            if k == "DII" or k.startswith("DII"):
                dii_val = v
        src = "NSE provisional cash CM (fiidiiTradeReact) — equity only, not NSDL grand total"
        if fii_val is not None:
            fii.update(
                {
                    "value": round(fii_val, 2),
                    "as_of": as_of,
                    "direction": _flow_dir(fii_val),
                    "source": src,
                    "source_url": nse_home,
                    "error": None,
                    "evidence": "fact",
                }
            )
        else:
            fii["error"] = "NSE payload missing FII/FPI row"
            warnings.append(fii["error"])
        if dii_val is not None:
            dii.update(
                {
                    "value": round(dii_val, 2),
                    "as_of": as_of,
                    "direction": _flow_dir(dii_val),
                    "source": src,
                    "source_url": nse_home,
                    "error": None,
                    "evidence": "fact",
                }
            )
        else:
            dii["error"] = "NSE payload missing DII row"
            warnings.append(dii["error"])
    except Exception as e:  # noqa: BLE001
        msg = f"NSE FII/DII parse failed: {e}. Left null."
        warnings.append(msg)
        fii["error"] = msg
        dii["error"] = msg
    return fii, dii, warnings


def _flow_dir(net: float) -> str:
    if net > 500:
        return "rising"  # expanding liquidity contribution
    if net < -500:
        return "falling"
    return "flat"


def _parse_moneycontrol_fii_dii(text: str, url: str) -> tuple[dict, dict] | None:
    """Best-effort Moneycontrol cash table parse. Return None if unsure."""
    # Look for patterns like FII ... net ... number in proximity — only if clear
    # Many MC layouts are JS-rendered; if we cannot find both, return None.
    # Example historical HTML sometimes has data attributes; keep strict.
    fii_m = re.search(
        r"FII/?FPI[^%]{0,200}?([+-]?\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(?:Cr|crore)?",
        text,
        re.I | re.S,
    )
    dii_m = re.search(
        r"\bDII\b[^%]{0,200}?([+-]?\d{1,3}(?:,\d{3})*(?:\.\d+)?)\s*(?:Cr|crore)?",
        text,
        re.I | re.S,
    )
    # Too ambiguous on JS shells — refuse unless both match and look like daily nets
    if not fii_m or not dii_m:
        return None
    # Refuse if page is mostly a shell (tiny meaningful content)
    if "fii" not in text.lower() or len(text) < 2000:
        return None
    # For safety: Moneycontrol often blocked; this path rarely succeeds.
    # Require explicit cash/provisional marker nearby.
    window = text[max(0, (fii_m.start() - 400)) : fii_m.end() + 400].lower()
    if "cash" not in window and "provisional" not in window:
        return None
    try:
        fii_v = float(fii_m.group(1).replace(",", ""))
        dii_v = float(dii_m.group(1).replace(",", ""))
    except ValueError:
        return None
    src = "Moneycontrol FII/DII (equity cash CM)"
    fii = {
        "name": "FII/FPI net (equity cash CM)",
        "value": round(fii_v, 2),
        "unit": "INR crore",
        "as_of": None,
        "direction": _flow_dir(fii_v),
        "source": src,
        "source_url": url,
        "error": None,
        "evidence": "fact",
        "scope": "equity_cash_CM",
    }
    dii = {
        "name": "DII net (equity cash CM)",
        "value": round(dii_v, 2),
        "unit": "INR crore",
        "as_of": None,
        "direction": _flow_dir(dii_v),
        "source": src,
        "source_url": url,
        "error": None,
        "evidence": "fact",
        "scope": "equity_cash_CM",
    }
    return fii, dii


def fetch_india10y() -> tuple[dict, list[str]]:
    """India 10Y G-Sec yield %. Prefer CCIL tenorwise; fall back to Investing.com."""
    warnings: list[str] = []
    out = {
        "symbol": "India 10Y G-Sec",
        "value": None,
        "prior": None,
        "as_of": None,
        "direction": "unknown",
        "change": None,
        "change_pct": None,
        "source": None,
        "source_url": None,
        "error": None,
        "evidence": "unknown",
        "tenor_note": "target 9Y-10Y / GS ~2035-36 tenorwise when CCIL available",
    }

    # CCIL often 403 from datacenter — try once
    for ccil_url in (
        "https://www.ccilindia.com/web_content/Gsec_tenorwise.aspx",
        "https://www.ccilindia.com/content/gsec_tenorwise.aspx",
    ):
        raw, err, _ = http_get(ccil_url)
        if raw and not err:
            parsed = _parse_ccil_tenorwise(raw.decode("utf-8", errors="replace"), ccil_url)
            if parsed:
                return parsed, warnings
            warnings.append(f"CCIL page fetched but 9Y-10Y yield not parsed ({ccil_url}).")
        else:
            warnings.append(f"CCIL tenorwise failed ({err}).")

    # Investing.com India 10Y
    inv_url = "https://www.investing.com/rates-bonds/india-10-year-bond-yield"
    raw, err, _ = http_get(inv_url)
    if not raw or err:
        msg = f"Investing.com India 10Y failed ({err}). india10y left null — do not invent."
        warnings.append(msg)
        out["error"] = msg
        return out, warnings
    text = raw.decode("utf-8", errors="replace")
    m = re.search(
        r'data-test="instrument-price-last"[^>]*>\s*([0-9]+(?:\.[0-9]+)?)',
        text,
    )
    if not m:
        msg = "Investing.com India 10Y page had no instrument-price-last. Left null."
        warnings.append(msg)
        out["error"] = msg
        return out, warnings
    try:
        val = float(m.group(1))
    except ValueError:
        msg = "Investing.com India 10Y price parse failed. Left null."
        warnings.append(msg)
        out["error"] = msg
        return out, warnings

    chg_m = re.search(
        r'data-test="instrument-price-change"[^>]*>\s*([+-]?[0-9]+(?:\.[0-9]+)?)',
        text,
    )
    chg_pct_m = re.search(
        r'data-test="instrument-price-change-percent"[^>]*>\s*\(?([+-]?[0-9]+(?:\.[0-9]+)?)%?\)?',
        text,
    )
    change = float(chg_m.group(1)) if chg_m else None
    change_pct = float(chg_pct_m.group(1)) if chg_pct_m else None
    direction = "unknown"
    if change is not None:
        if change > 0.005:
            direction = "rising"
        elif change < -0.005:
            direction = "falling"
        else:
            direction = "flat"
    out.update(
        {
            "value": val,
            "prior": round(val - change, 4) if change is not None else None,
            "as_of": datetime.now(IST).strftime("%Y-%m-%d"),  # last print day; weekend = last session page
            "direction": direction,
            "change": change,
            "change_pct": change_pct,
            "source": "Investing.com India 10-Year Bond Yield",
            "source_url": inv_url,
            "error": None,
            "evidence": "fact",
        }
    )
    return out, warnings


def _parse_ccil_tenorwise(text: str, url: str) -> dict | None:
    """Extract ~9Y-10Y / GS 2035-36 style yield if present."""
    # Look for 9-10 year bucket or GS 2036
    patterns = [
        r"(?:9\s*[-–]\s*10\s*Y(?:ear)?s?|9Y\s*[-–]\s*10Y)[^0-9%]{0,40}([0-9]\.[0-9]{2,4})\s*%?",
        r"GS\s*203[56][^0-9%]{0,40}([0-9]\.[0-9]{2,4})\s*%?",
        r"10\s*Year[^0-9%]{0,40}([0-9]\.[0-9]{2,4})\s*%?",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            try:
                val = float(m.group(1))
            except ValueError:
                continue
            if not (5.0 <= val <= 12.0):
                continue
            return {
                "symbol": "India 10Y G-Sec",
                "value": val,
                "prior": None,
                "as_of": datetime.now(IST).strftime("%Y-%m-%d"),
                "direction": "unknown",
                "change": None,
                "change_pct": None,
                "source": "CCIL G-Sec tenorwise",
                "source_url": url,
                "error": None,
                "evidence": "fact",
                "tenor_note": m.group(0)[:80],
            }
    return None


def main() -> int:
    warnings: list[str] = []
    symbols = {
        "nifty": ("^NSEI", "5d"),
        "inr_usd": ("INR=X", "1mo"),  # 1mo for soft-proxy 1m change
        "brent": ("BZ=F", "5d"),
        "wti": ("CL=F", "5d"),
        "us10y": ("^TNX", "5d"),
        "dxy": ("DX-Y.NYB", "5d"),
        "india_vix": ("^INDIAVIX", "1mo"),
    }
    market: dict = {}
    for key, (sym, rng) in symbols.items():
        print(f"Fetching {key} ({sym}, {rng})...", flush=True)
        market[key] = yahoo_chart(sym, rng)

    print("Fetching FII/DII (Moneycontrol → NSE cash CM)...", flush=True)
    fii, dii, w1 = fetch_fii_dii()
    warnings.extend(w1)
    print(f"  FII={fii.get('value')} as_of={fii.get('as_of')} src={fii.get('source')}", flush=True)
    print(f"  DII={dii.get('value')} as_of={dii.get('as_of')} src={dii.get('source')}", flush=True)

    print("Fetching India 10Y (CCIL → Investing.com)...", flush=True)
    india10y, w2 = fetch_india10y()
    warnings.extend(w2)
    market["india10y"] = india10y
    print(
        f"  india10y={india10y.get('value')} dir={india10y.get('direction')} src={india10y.get('source')}",
        flush=True,
    )

    # Soft-proxy inputs (populated for UI optional use; default OFF in wizard)
    soft_proxy = {
        "enabled_default": False,
        "note": (
            "Optional Gate-2 soft proxy ONLY when FII is null AND user enables in UI. "
            "Uses USDINR 1m change + India VIX. Clearly labeled proxy, lower weight. Default OFF."
        ),
        "inr_usd_1m_pct": market.get("inr_usd", {}).get("change_1m_pct"),
        "india_vix": {
            "value": market.get("india_vix", {}).get("value"),
            "direction": market.get("india_vix", {}).get("direction"),
            "as_of": market.get("india_vix", {}).get("as_of"),
            "source_url": market.get("india_vix", {}).get("source_url"),
        },
    }

    snapshot = {
        "generated_at_utc": now_iso(),
        "generated_at_ist": now_ist(),
        "disclaimer": (
            "Automated fetch only. Failed scrapes are null with warnings — never invented. "
            "FII/DII are equity cash CM (NSE provisional / Moneycontrol), NOT NSDL equity+debt grand total. "
            "Manual overrides in the UI are tagged separately. "
            "This tool scores dials; it does not replace judgment when dials conflict."
        ),
        "market": market,
        "macro": {
            "gdp_yoy": empty_macro(
                "Real GDP growth (YoY)",
                "NSO / RBI — not auto-fetched; paste from MOSPI or RBI press release",
            ),
            "iip_yoy": empty_macro(
                "IIP growth (YoY)",
                "MOSPI — not auto-fetched; paste from official release",
            ),
            "cpi_headline": empty_macro(
                "CPI headline (YoY)",
                "MOSPI — not auto-fetched; paste from official release",
            ),
            "cpi_core": empty_macro(
                "CPI core ex food & fuel (YoY)",
                "RBI / MOSPI derived — not auto-fetched",
            ),
            "food_inflation": empty_macro(
                "Food inflation (YoY)",
                "MOSPI — not auto-fetched",
            ),
            "wpi_yoy": empty_macro(
                "WPI (YoY)",
                "DPIIT / OEA — not auto-fetched",
            ),
            "repo_rate": {
                "name": "RBI repo rate",
                "value": None,
                "unit": "%",
                "as_of": None,
                "direction": "unknown",
                "stance": None,
                "prior": None,
                "source": "RBI MPC resolution — enter manually after each meeting",
                "source_url": "https://www.rbi.org.in/",
                "error": "not auto-fetched",
                "evidence": "unknown",
            },
        },
        "flows": {
            "fii_net": fii,
            "dii_net": dii,
        },
        "soft_proxy": soft_proxy,
        "warnings": warnings,
        "fetch_notes": [],
    }

    ok = sum(1 for v in market.values() if v.get("value") is not None)
    snapshot["fetch_notes"].append(
        f"Market series with values: {ok}/{len(market)}."
    )
    snapshot["fetch_notes"].append(
        f"FII={fii.get('value')} DII={dii.get('value')} india10y={india10y.get('value')} "
        f"(null means scrape failed — do not invent)."
    )
    for k, v in market.items():
        if v.get("error"):
            snapshot["fetch_notes"].append(f"{k}: {v['error']}")
    for w in warnings:
        snapshot["fetch_notes"].append("WARN: " + w)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    print(f"Wrote {OUT}", flush=True)
    print(f"IST: {snapshot['generated_at_ist']}", flush=True)
    if warnings:
        print("Warnings:", flush=True)
        for w in warnings:
            print("  -", w, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
