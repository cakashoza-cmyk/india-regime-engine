# India Market Regime Engine

**Live site:** [https://cakashoza-cmyk.github.io/india-regime-engine/](https://cakashoza-cmyk.github.io/india-regime-engine/)

Self-contained SPA for Akash Oza: scores **Growth / Inflation / Liquidity**, places India on the growth×inflation map, and outputs a **sleeve call** (Risk-On, Cyclicals-Reflation, Staples-Defensives, Risk-Off, or Unclear).

This automates scoring and consistency. It does **not** replace human judgment when dials conflict — the honest output then is **Unclear / wait**.

AI macro fill uses **DeepSeek only** and is **best-effort**. Models can hallucinate or return stale figures. AI-filled fields are tagged `ai` — always verify against MOSPI / RBI / NSDL before acting.

## Open locally

```bash
cd india-regime-engine
python3 -m http.server 8765
```

Then open `http://127.0.0.1:8765/` in a browser.

Or open `index.html` directly (file://). The page embeds a fallback copy of the last `data/snapshot.json`; a local server is still best for live fetch. Browser calls to DeepSeek need network access.

## Fill macros via AI (DeepSeek)

On **Manual Inputs** (and a shortcut on **Today's Call**):

1. Provider is fixed to **DeepSeek**.
2. Choose model: `deepseek-chat` (default) or `deepseek-reasoner`.
3. Paste your DeepSeek API key — stored only in browser `localStorage` (`regimeEngineAiKey_v1`). **Never committed to git.**
4. Click **Fill macros via AI**.

### Get a DeepSeek API key

1. Sign in at [platform.deepseek.com](https://platform.deepseek.com/).
2. Create an API key under the API keys section.
3. Paste it into the password field on Manual Inputs (or Today's Call uses the same saved key).

Calls go to `https://api.deepseek.com/v1/chat/completions` with `Authorization: Bearer <key>`.

### Evidence tags

| Tag | Meaning |
|-----|---------|
| `fact` | Yahoo / snapshot market series |
| `manual` | You typed or used the press-seed button |
| `ai` | Filled by DeepSeek — verify |
| `inference` | Dial/sleeve rule output |
| `unknown` | Missing |

## Refresh market data

```bash
python3 refresh_data.py
```

Writes `data/snapshot.json` from free Yahoo Finance chart endpoints (Nifty, INR=X, Brent, WTI, US10Y, DXY). India CPI / IIP / GDP / repo / FII are **not** invented by the refresh script — leave Unknown, enter manually, or use AI fill.

Optional: on Manual Inputs, use **Apply Oct-2026 press reference** only after you verify figures on MOSPI / RBI (tagged `manual`).

## GitHub Pages

Hosted from the `main` branch root of this repo:

https://cakashoza-cmyk.github.io/india-regime-engine/

`data/snapshot.json` is also public at: https://cakashoza-cmyk.github.io/india-regime-engine/data/snapshot.json

## Tabs

1. **Today's Call** — regime, sleeve, confidence, OW/UW + AI fill shortcut  
2. **Dials** — indicator tables with evidence tags  
3. **Map** — 2×2 quadrant + liquidity badge  
4. **Drivers** — transmission notes (inference)  
5. **Magnitude & Scenarios** — bull/base/bear monitoring triggers (no fake prices)  
6. **Method** — scoring rules to study and distrust  
7. **Manual Inputs** — macros, flows, DeepSeek key/model  

## Times

Refresh timestamps are shown in **Asia/Calcutta**.
