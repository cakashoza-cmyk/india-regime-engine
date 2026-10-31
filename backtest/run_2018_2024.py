"""Replay 2018-01..2024-12 month-ends through the ENGINE's scoring/classify/stage (engine/logic.py).

Only genuinely sourced history is used (cached under backtest/cache):
  CPI headline + food (CFPI) YoY  -> RBI DBIE public API (cpi_ruc_rn, base 2012), +1 month release lag
  IIP general YoY                 -> RBI DBIE public API (inx_inds_prod_rn),      +2 month release lag
  GDP                             -> FRED NGDPRNSAXDCINQ (real, NSA; YoY),       +2 month lag after quarter
  Policy-rate direction           -> FRED IRSTCI01INM156N (call money) as PROXY (DBIE repo-history table scrape is empty)
  India 10Y                       -> FRED INDIRLTLT01STM (OECD monthly)
  Nifty, Bank, Auto, Metal, Brent, US10Y, DXY, USDINR, India VIX -> Yahoo (yfinance) monthly closes
Gaps (NOT invented; series treated as unknown -> do not vote): core CPI, GST, bank credit growth,
FII net flows, breadth, OBICUS, RBI stance language. Credit unknown => Stage gate 2 can never pass,
so stage is capped at 1 in replay — reported as a finding, not patched.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent)); sys.path.insert(0, str(HERE))
from backtest_v2 import fred_csv, yahoo_monthly, CACHE  # noqa: E402
from engine import logic, dbie  # noqa: E402

GAPS = ["cpi_core", "gst_yoy", "credit_growth", "fii_net", "breadth_200dma", "capacity_util", "rbi_stance"]


def dbie_series(key):
    p = CACHE / f"dbie_{key}.json"
    if not p.exists():
        p.write_text(json.dumps(dbie.series(key, frm="2014-01-01")))
    s = pd.Series({pd.Timestamp(d): v for d, v in json.loads(p.read_text())})
    return s.resample("ME").last()


def lagged(s, months):
    s = s.copy(); s.index = s.index + pd.offsets.MonthEnd(months); return s


def panel():
    idx = pd.date_range("2017-01-31", "2025-06-30", freq="ME")
    cols = {
        "cpi_headline": lagged(dbie_series("cpi_headline"), 1),
        "food_inflation": lagged(dbie_series("food_inflation"), 1),
        "iip_yoy": lagged(dbie_series("iip_yoy"), 2),
    }
    g = fred_csv("NGDPRNSAXDCINQ"); g = (g / g.shift(4) - 1) * 100
    g.index = g.index + pd.offsets.QuarterEnd(0) + pd.offsets.MonthEnd(2)
    cols["gdp_yoy"] = g.resample("ME").last()
    r = fred_csv("IRSTCI01INM156N"); r.index = r.index + pd.offsets.MonthEnd(0); cols["repo_rate"] = r
    y = fred_csv("INDIRLTLT01STM"); y.index = y.index + pd.offsets.MonthEnd(0); cols["india10y"] = y
    for k, sym in {"nifty": "^NSEI", "nifty_bank": "^NSEBANK", "nifty_auto": "^CNXAUTO", "nifty_metal": "^CNXMETAL",
                   "brent": "BZ=F", "us10y": "^TNX", "dxy": "DX-Y.NYB", "usdinr_ref": "INR=X", "india_vix": "^INDIAVIX"}.items():
        cols[k] = yahoo_monthly(sym)
    return pd.DataFrame(cols).reindex(idx).ffill(limit=3)


def direction(cur, prev, key):
    if pd.isna(cur) or pd.isna(prev):
        return None
    if key in ("cpi_headline", "food_inflation", "iip_yoy", "gdp_yoy", "repo_rate", "india10y"):
        d = cur - prev; th = 0.1 if key != "repo_rate" else 0.1
        return 1 if d > th else (-1 if d < -th else 0)
    ch = cur / prev - 1
    return 1 if ch > 0.0015 else (-1 if ch < -0.0015 else 0)


def run():
    df = panel()
    rows = []
    for t in pd.date_range("2018-01-31", "2024-12-31", freq="ME"):
        i0 = df.index.get_loc(t)
        cur, prev3, prev1 = df.iloc[i0], df.iloc[i0 - 3], df.iloc[i0 - 1]
        ind = {}
        for k in df.columns:
            ref = prev3 if k in ("repo_rate", "india10y", "nifty", "nifty_bank", "nifty_auto", "nifty_metal", "brent") else prev1
            d = direction(cur[k], ref[k], k)
            if d is not None:
                ind[k] = {"value": float(cur[k]), "direction": d, "is_stale": False}
        g = logic.score_growth(ind); i = logic.score_inflation(ind); l, hard = logic.score_liquidity(ind)
        quad = logic.quadrant(g, i); st, _ = logic.stage(ind)
        fwd = {}
        for k in ("nifty", "nifty_bank", "nifty_auto", "nifty_metal"):
            j = min(i0 + 6, len(df) - 1)
            fwd[k + "_fwd6m"] = round((df.iloc[j][k] / cur[k] - 1) * 100, 2) if not pd.isna(cur[k]) else None
        rows.append({"month": t.strftime("%Y-%m"), "growth": g, "inflation": i, "liquidity": l, "hard": hard,
                     "regime": logic.regime_label(quad, l, hard), "stage": st, **fwd})
    out = pd.DataFrame(rows)
    out["stage_change"] = out["stage"].diff().fillna(0) != 0
    out["regime_change"] = out["regime"] != out["regime"].shift()
    out.to_csv(HERE / "results_2018_2024.csv", index=False)
    by_regime = out.groupby("regime")[["nifty_fwd6m", "nifty_bank_fwd6m", "nifty_auto_fwd6m", "nifty_metal_fwd6m"]].agg(["mean", "count"]).round(2)
    by_stage = out.groupby("stage")[["nifty_fwd6m", "nifty_bank_fwd6m", "nifty_auto_fwd6m", "nifty_metal_fwd6m"]].agg(["mean", "count"]).round(2)
    trans = out[out["regime_change"] | out["stage_change"]][["month", "regime", "stage", "nifty_fwd6m", "nifty_bank_fwd6m", "nifty_auto_fwd6m", "nifty_metal_fwd6m"]]
    md = ["# Engine replay 2018-2024 (paper research, not a performance claim)", "",
          "Sources and lags: see module docstring. **Gaps (not invented, treated unknown):** " + ", ".join(GAPS) + ".",
          "Policy rate uses call-money (FRED IRSTCI01INM156N) as a proxy because DBIE's repo-history scrape is empty.", "",
          f"Months: {len(out)}. Unclear regime months: {(out.regime=='Unclear').sum()}. Max stage reached: {out.stage.max()} "
          "(gate 2 'credit stabilises' has no sourced history, so the climb cannot pass it).", "",
          "## Forward 6m returns (%) by regime", by_regime.to_markdown(), "", "## By stage", by_stage.to_markdown(), "",
          "## Regime/stage transitions", trans.to_markdown(index=False)]
    (HERE / "report_2018_2024.md").write_text("\n".join(md))
    print("\n".join(md[:12])); print(by_regime)


if __name__ == "__main__":
    run()
