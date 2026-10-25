# India Market Regime Engine

**Live site:** [https://cakashoza-cmyk.github.io/india-regime-engine/](https://cakashoza-cmyk.github.io/india-regime-engine/)

Self-contained SPA for Akash Oza: scores **Growth / Inflation / Liquidity**, places India on the growth×inflation map, and outputs a **sleeve call** (Risk-On, Cyclicals-Reflation, Staples-Defensives, Risk-Off, or Unclear).

This automates scoring and consistency. It does **not** replace judgment when dials conflict — the honest output then is **Unclear / wait**.

## Open locally

```bash
cd india-regime-engine
python3 -m http.server 8765
```

Then open `http://127.0.0.1:8765/` in a browser.

Or open `index.html` directly (file://). The page embeds a fallback copy of the last `data/snapshot.json`; a local server is still best for live fetch.

## Refresh market data

```bash
python3 refresh_data.py
```

Writes `data/snapshot.json` from free Yahoo Finance chart endpoints (Nifty, INR=X, Brent, WTI, US10Y, DXY). India CPI / IIP / GDP / repo / FII are **not** invented — leave Unknown or enter on the **Manual Inputs** tab (saved in `localStorage`).

Optional: on Manual Inputs, use **Apply Oct-2026 press reference** only after you verify figures on MOSPI / RBI.

## GitHub Pages

Hosted from the `main` branch root of this repo:

https://cakashoza-cmyk.github.io/india-regime-engine/

`data/snapshot.json` is also public at: https://cakashoza-cmyk.github.io/india-regime-engine/data/snapshot.json

## Tabs

1. **Today's Call** — regime, sleeve, confidence, OW/UW  
2. **Dials** — indicator tables with fact / manual / inference / unknown tags  
3. **Map** — 2×2 quadrant + liquidity badge  
4. **Drivers** — transmission notes (inference)  
5. **Magnitude & Scenarios** — bull/base/bear monitoring triggers (no fake prices)  
6. **Method** — scoring rules to study and distrust  
7. **Manual Inputs** — macros & flows  

## Times

Refresh timestamps are shown in **Asia/Calcutta**.
