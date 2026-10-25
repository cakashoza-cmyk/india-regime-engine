#!/usr/bin/env python3
"""
Fetch free public market/macro signals and write data/snapshot.json.
Never invents numbers: failed fetches become null / Unknown.
Run: python3 refresh_data.py
"""
from __future__ import annotations

import json
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta
from pathlib import Path

OUT = Path(__file__).resolve().parent / "data" / "snapshot.json"
IST = timezone(timedelta(hours=5, minutes=30), name="Asia/Calcutta")
UA = "Mozilla/5.0 (compatible; RegimeEngine/1.0; +local)"


def now_ist() -> str:
    return datetime.now(IST).strftime("%Y-%m-%d %H:%M:%S Asia/Calcutta")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def http_get(url: str, timeout: int = 20) -> tuple[bytes | None, str | None]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as resp:
            return resp.read(), None
    except Exception as e:  # noqa: BLE001
        return None, f"{type(e).__name__}: {e}"


def yahoo_chart(symbol: str) -> dict:
    """Return last close, prior close, as-of, direction from Yahoo chart API."""
    enc = urllib.parse.quote(symbol, safe="")
    url = (
        f"https://query1.finance.yahoo.com/v8/finance/chart/{enc}"
        f"?range=5d&interval=1d"
    )
    raw, err = http_get(url)
    out = {
        "symbol": symbol,
        "value": None,
        "prior": None,
        "as_of": None,
        "direction": "unknown",
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
            # fallback to meta regularMarketPrice
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


def main() -> int:
    symbols = {
        "nifty": "^NSEI",
        "inr_usd": "INR=X",  # INR per USD (higher = weaker INR)
        "brent": "BZ=F",
        "wti": "CL=F",
        "us10y": "^TNX",
        "dxy": "DX-Y.NYB",
    }
    market = {}
    for key, sym in symbols.items():
        print(f"Fetching {key} ({sym})...", flush=True)
        market[key] = yahoo_chart(sym)

    # India 10Y G-Sec via Yahoo if available
    print("Fetching india10y (INR=X already done; trying ^NSEI related)...", flush=True)
    # Common Yahoo symbol for India 10Y is sometimes IN10Y.B or similar — try a few
    india10y = yahoo_chart("IN10Y.B")
    if india10y.get("value") is None:
        india10y = yahoo_chart("^IN10Y")
    if india10y.get("value") is None:
        india10y = {
            "symbol": "India 10Y G-Sec",
            "value": None,
            "prior": None,
            "as_of": None,
            "direction": "unknown",
            "source": "Yahoo Finance (symbol not resolved)",
            "source_url": None,
            "error": "no free symbol resolved — enter manually",
            "evidence": "unknown",
        }
    market["india10y"] = india10y

    snapshot = {
        "generated_at_utc": now_iso(),
        "generated_at_ist": now_ist(),
        "disclaimer": (
            "Automated fetch only. Macro fields without a successful free feed "
            "are null/Unknown. Manual overrides in the UI are tagged separately. "
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
            "fii_net": {
                "name": "FII/FPI net (equity, recent session/month)",
                "value": None,
                "unit": "INR crore",
                "as_of": None,
                "direction": "unknown",
                "source": "NSDL / NiftyInvestors — no free unauth feed used",
                "source_url": None,
                "error": "enter manually; persists in browser localStorage",
                "evidence": "unknown",
            },
            "dii_net": {
                "name": "DII net (equity, recent session/month)",
                "value": None,
                "unit": "INR crore",
                "as_of": None,
                "direction": "unknown",
                "source": "NSE / NSDL — enter manually",
                "source_url": None,
                "error": "enter manually",
                "evidence": "unknown",
            },
        },
        "fetch_notes": [],
    }

    ok = sum(1 for v in market.values() if v.get("value") is not None)
    snapshot["fetch_notes"].append(
        f"Market series with values: {ok}/{len(market)}. Macro left Unknown for manual entry."
    )
    for k, v in market.items():
        if v.get("error"):
            snapshot["fetch_notes"].append(f"{k}: {v['error']}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")
    print(f"Wrote {OUT}", flush=True)
    print(f"IST: {snapshot['generated_at_ist']}", flush=True)
    for k, v in market.items():
        print(f"  {k}: value={v.get('value')} dir={v.get('direction')} err={v.get('error')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
