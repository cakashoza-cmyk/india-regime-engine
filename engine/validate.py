"""Validation: sanity ranges, two-source cross-check with tolerance, per-value status badge.

status:  verified   - official/exchange source, or two independent sources agree within tolerance
         unverified - single non-official source (or flagged verified:false) — shown, scored only if not LLM
         stale      - last good value older than its cadence allows (does not vote)
         failed     - outside sanity range or sources disagree beyond tolerance (score forced to 0)
"""
from __future__ import annotations
from engine import db

SANITY = {
    "gdp_yoy": (-25, 30), "iip_yoy": (-40, 60), "gst_yoy": (-40, 80), "cpi_headline": (-5, 20),
    "cpi_core": (-3, 15), "food_inflation": (-20, 35), "brent": (20, 250), "repo_rate": (2, 12),
    "india10y": (4, 12), "fii_net": (-60000, 60000), "dii_net": (-60000, 60000), "credit_growth": (-10, 40),
    "usdinr_ref": (60, 140), "us10y": (0, 10), "dxy": (70, 130), "nifty": (5000, 80000),
    "nifty_bank": (10000, 200000), "breadth_200dma": (0, 100), "india_vix": (5, 90),
    "nifty_auto": (3000, 100000), "nifty_metal": (1000, 50000), "capacity_util": (50, 100), "ois_1y": (2, 12),
}
# tolerance: ("rel", fraction) or ("abs", units)
TOL = {"nifty": ("rel", .005), "nifty_bank": ("rel", .005), "nifty_auto": ("rel", .005), "nifty_metal": ("rel", .005),
       "india_vix": ("rel", .02), "us10y": ("abs", .06), "brent": ("rel", .02), "usdinr_ref": ("rel", .01),
       "india10y": ("abs", .05), "repo_rate": ("abs", 1e-6)}
OFFICIAL_SOURCES = {"rbi", "nse_archive", "treasury", "rbi_press", "nse"}
OFFICIAL_DOMAINS = ("mospi.gov.in", "pib.gov.in", "rbi.org.in", "gst.gov.in", "nseindia.com", "treasury.gov")


def _within(a, b, tol):
    kind, t = tol
    return abs(a - b) <= (t * abs(b) if kind == "rel" else t)


def check(conn, rec) -> dict:
    key, v = rec["indicator"], rec["value"]
    notes = []
    lo, hi = SANITY.get(key, (None, None))
    if v is None:
        return {"status": "failed", "checks": ["no value"]}
    if lo is not None and not (lo <= float(v) <= hi):
        return {"status": "failed", "checks": [f"sanity: {v} outside [{lo}, {hi}]"]}
    # second source: any other ok row, different source, same reference date
    others = db.q(conn, "SELECT source, payload FROM raw_ingest WHERE indicator=? AND ok AND id<>? ORDER BY id DESC LIMIT 40",
                  (key, rec["source_raw_id"]))
    agree = None
    for o in others:
        p = db.jload(o["payload"])
        if o["source"] == rec["source"] or p.get("role") == "history" or p.get("value") is None:
            continue
        if str(p.get("as_of"))[:10] != str(rec["as_of"])[:10]:
            continue
        tol = TOL.get(key, ("abs", .05))
        if _within(float(p["value"]), float(v), tol):
            agree = True; notes.append(f"cross-check {o['source']}={round(float(p['value']), 4)} within " + (f"{tol[1]*100:g}%" if tol[0] == "rel" else f"{tol[1]:g}"))
        else:
            agree = False; notes.append(f"MISMATCH {o['source']}={round(float(p['value']), 4)} vs {v} (tol {tol})")
        break
    url = rec.get("source_url") or ""
    official = rec["source"] in OFFICIAL_SOURCES or (rec["source"] == "manual" and any(d in url for d in OFFICIAL_DOMAINS))
    if agree is False:
        return {"status": "failed", "checks": notes}
    if rec.get("is_stale"):
        return {"status": "stale", "checks": notes + [f"stale since {rec.get('stale_since')}"]}
    if rec.get("unverified"):
        return {"status": "unverified", "checks": notes + ["flagged verified:false (secondary source)"]}
    if official or agree:
        return {"status": "verified", "checks": notes + (["official source"] if official else [])}
    return {"status": "unverified", "checks": notes + ["single non-official source"]}
