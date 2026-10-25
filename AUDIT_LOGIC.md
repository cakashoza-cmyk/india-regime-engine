# India Regime Engine — Auditor Logic Specification

| Field | Value |
|-------|-------|
| **Document** | Logic extract for independent review |
| **Source of truth** | `index.html` + `app-gates.js` (Seven Gates wizard); prior SPA at `index.legacy.html`
| **Live app** | https://cakashoza-cmyk.github.io/india-regime-engine/ |
| **Source repo** | https://github.com/cakashoza-cmyk/india-regime-engine |
| **Method tab** | Same live URL → **Method** |
| **As of** | 2026-10-26 Asia/Calcutta |
| **Owner** | Akash Oza |

This document describes **rules as implemented in code**. It does not invent thresholds or sleeves that are not in `index.html`.

---

## 1. Purpose & explicit non-claims

**Purpose:** Score three dials (Growth, Inflation, Liquidity), place India on a growth×inflation quadrant with a liquidity overlay, and emit a sleeve label with optional overweight/underweight guidance.

**Explicit non-claims (UI + code framing):**

- Does **not** replace human judgment when dials conflict; Unclear / wait is a valid output.
- Does **not** invent missing macro prints; Unknown stays Unknown until Manual Inputs or AI fill.
- AI-filled values are tagged **`ai`**, not **`fact`**. They can hallucinate; user must verify MOSPI / RBI / NSDL.
- Yahoo snapshot series are **`fact`** only for market prints successfully fetched into `data/snapshot.json`.
- Dial scores and sleeves are tagged **`inference`** (rule outputs).
- Concrete buy lists appear only when conviction is **Strong** and confirmation status is **confirmed** (`showBuyList = confidence === "Strong" && confirm.status === "confirmed"`).

---

## 2. Data inputs

### 2.1 Evidence tags (`fieldEv` / feed tags)

| Tag | When |
|-----|------|
| `fact` | Yahoo / snapshot market series with a non-null value |
| `manual` | User typed or press-seed; `manual._ev[key]` is not `ai` |
| `ai` | Filled by DeepSeek; `markEv(filled, "ai")` |
| `inference` | Dial / sleeve / driver rule output |
| `unknown` | Missing value / unknown direction |

`fieldEv(key, hasValue)`: if `!hasValue` → `unknown`; else if `manual._ev[key] === "ai"` → `ai`; else → `manual`.

### 2.2 Input table

| Field | Dial | Source | Direction / signal rules |
|-------|------|--------|---------------------------|
| Real GDP YoY | Growth | Manual / AI (`manual.gdp`, `gdp_dir`, `gdp_asof`) | User/AI direction |
| IIP YoY | Growth | Manual / AI | User/AI direction |
| Nifty 50 | Growth (display) | Yahoo `^NSEI` in snapshot | Direction from chart; **never sole Growth voter** |
| CPI headline YoY | Inflation | Manual / AI | User/AI direction |
| CPI core YoY | Inflation | Manual / AI | User/AI direction |
| Food inflation YoY | Inflation | Manual / AI | User/AI direction |
| Brent crude | Inflation | Yahoo `BZ=F` | Snapshot direction |
| INR per USD | Inflation + Liquidity | Yahoo `INR=X` | Rising = weaker INR |
| RBI repo + stance | Liquidity | Manual / AI | `tightening`→liq contracting; `accommodative`→expanding; `neutral`→neutral |
| US 10Y | Liquidity | Yahoo `^TNX` | Rising→contracting; falling→expanding |
| DXY | Liquidity | Yahoo `DX-Y.NYB` | Rising→contracting; falling→expanding |
| FII/FPI net (₹ cr) | Liquidity | Manual / AI | **> +500** → expanding; **< −500** → contracting; else flat/neutral |
| DII net (₹ cr) | Liquidity (display) | Manual / AI | Direction thresholds same ±500 for display; **`liq_signal` always `"unknown"`** (does not vote on Liquidity dial) |
| India 10Y G-Sec | Liquidity | Manual / AI | Rising dir→contracting; falling→expanding |

Snapshot refresh: `refresh_data.py` → `data/snapshot.json`. Macros are not auto-fetched by that script.

---

## 3. `majorityDirection(dirs)`

```
known = dirs where d is truthy AND d ≠ "unknown" AND d ≠ "flat"
if known.length < 1 → Unclear ("insufficient known directions")
if rising/known ≥ 0.6 → Rising
if falling/known ≥ 0.6 → Falling
else → Unclear (mixed)
```

**Flat and unknown are excluded from the vote.**

---

## 4. `scoreGrowth(list)`

1. `macros =` indicators whose name does **not** contain `"Nifty"`.
2. If no macro has `direction` other than `unknown` → **Unclear** (“Nifty is display-only proxy”).
3. Else `majorityDirection(macros.map(direction))` — GDP/IIP only in practice.

---

## 5. `scoreInflation(list)`

Indicators found by name: core (`"core"`), Food, Brent, headline, INR.

**Order of checks (as coded):**

1. **Transitory** if `(crude rising OR food rising)` AND core direction known AND (core `flat` OR `falling`).
2. Else **Rising** if core `rising` (sticky), even if others mixed.
3. Else compute `majorityDirection` on all inflation directions:
   - If majority Rising and core unknown → **Rising** (“core unknown — treat cautiously”).
   - If majority Falling → **Falling**.
   - If core falling AND not food/crude up → **Falling**.
   - Else return majority score (Rising / Falling / Unclear).

---

## 6. `scoreLiquidity(list)`

### 6.1 `liq_signal` mapping

| Indicator | Contracting | Expanding | Neutral / unknown |
|-----------|-------------|-----------|-------------------|
| RBI stance | `tightening` | `accommodative` | `neutral` → neutral; else unknown |
| US 10Y | direction rising | direction falling | else unknown |
| DXY | rising | falling | else unknown |
| INR weakness | INR/USD rising | falling | else unknown |
| FII net | value < −500 | value > +500 | \|value\|≤500 → neutral; null → unknown |
| DII net | — | — | **always `unknown`** |
| India 10Y | `in10_dir` rising | falling | else unknown |

### 6.2 Aggregation

```
signals = liq_signal values excluding unknown and neutral
if none → Unclear, hard=false
con/n ≥ 0.6 → Contracting
exp/n ≥ 0.6 → Expanding
else → Unclear (mixed)
hard = (con ≥ 4) OR (n ≥ 3 AND con/n ≥ 0.75)
```

---

## 7. `quadrant(growth, inflation)`

**Transitory is NOT Rising.**

```
gUp = growth === "Rising"
gDown = growth === "Falling"
iUp = inflation === "Rising"          // Transitory excluded
iDown = inflation === "Falling" OR inflation === "Transitory"

gUp && iDown     → Goldilocks
gUp && iUp       → Reflation
gDown && Falling → Slowdown
gDown && Transitory → Slowdown
gDown && iUp     → Stagflation
else → Unclear
```

---

## 8. `mapSleeve(g, i, l, quad, liqHard)` — priority order

Evaluated **in this order**; first match returns:

1. If `g === Unclear` OR `quad === Unclear` → **Unclear**
2. If `quad === Stagflation` OR (`liqHard && l === Contracting`) → **Risk-Off**
3. If `quad === Reflation` AND `l === Contracting` → **Selective cyclicals / dry powder**
4. If `g === Rising` AND `i === Falling` AND `l === Expanding` → **Risk-On**
5. If `quad === Goldilocks`:
   - `l === Expanding` → **Risk-On**
   - `l === Contracting` → **Staples-Defensives**
   - else (liquidity unclear/mixed) → **Staples-Defensives**
6. If `quad === Reflation` AND `l !== Contracting` → **Cyclicals-Reflation**
7. If `quad === Slowdown` OR `g === Falling` → **Staples-Defensives**
8. If `l === Contracting` AND `quad !== Reflation` → **Staples-Defensives**
9. Else → **Unclear**

`finalCall` sets `liqHard` from `scoreLiquidity(...).hard`, prepends a Transitory note when `i === Transitory`, and sets `signature = g|i|l|sleeve`.

---

## 9. `computeConviction(g, i, l, quad, sleeve)`

```
unclearN = count of {g,i,l} that equal "Unclear"

if unclearN ≥ 2 OR sleeve === Unclear OR quad === Unclear → Unclear
if i === Transitory OR unclearN === 1 → Mixed
if g,i,l all not Unclear AND i not Transitory AND sleeve not Unclear → Strong
else → Mixed
```

---

## 10. `applyConfirmation(call, recordEval)`

Storage key: `localStorage.regimeEngineConfirm_v1`.

**When `recordEval` is false** (boot / ordinary re-render): display only; does not advance streak. Shows pending vs last confirmed.

**When `recordEval` is true** (Save & re-score, or successful AI fill):

1. No prior state → save streak=1, `confirmedSleeve=null` → **pending** (“need 1 more confirm”).
2. Else if `prev.lastSignature === call.signature` OR `prev.lastSleeve === call.sleeve` → streak++, set `confirmedSleeve = call.sleeve` → **confirmed**.
3. Else sleeve/signature changed → streak=1, keep prior `confirmedSleeve`, status **pending**.

**Buy list gate in `renderAll`:**

```
showBuyList = (call.confidence === "Strong") && (confirm.status === "confirmed")
```

- Strong + confirmed → full OW/UW from `SLEEVES[sleeve]`.
- Mixed → guidance-only text (no hard buy list).
- Else → wait / dry powder messaging.

---

## 11. OW / UW lists (`SLEEVES` in `index.html`)

### Risk-On
- **OW:** Broad equities; Midcaps (with liquidity expanding); Discretionary / consumption; IT & growth on dips if liquidity ok  
- **UW:** Excess cash; Deep defensives as core; Gold as primary sleeve  

### Cyclicals-Reflation
- **OW:** Banks / PSU banks (select); Industrials & capital goods; Commodities / metals / energy; Autos (if volume data confirms); NBFCs only if funding stress low  
- **UW:** Long-duration rate-sensitives; High-valuation growth without earnings; Crowded midcap momentum without liquidity  

### Selective cyclicals / dry powder
- **OW:** Selective banks / PSU banks (quality); Select industrials & capital goods; Commodities / energy (size small); Keep dry powder / cash sleeve  
- **UW:** Crowded high-beta midcaps; Full auto + NBFC chase; Blanket cyclical beta; Leverage  

### Staples-Defensives
- **OW:** FMCG / staples; Pharma / healthcare; Quality defensives; Select bonds / rate-sensitives as growth cools  
- **UW:** High-beta midcaps; Highly leveraged cyclicals; Commodity beta if growth falling  

### Risk-Off
- **OW:** Cash / liquid funds; Gold; High-quality defensives only; Avoid leverage  
- **UW:** Cyclicals; High-beta midcaps; NBFCs with ALM risk; Fresh leverage  

### Unclear
- **OW:** Preserve dry powder; Wait for dial consensus (2–3 confirming readings); Size down — no forced buys  
- **UW:** New high-conviction cyclical bets; Leverage; Acting on a single indicator  

---

## 12. DeepSeek AI fill

| Item | Implementation |
|------|----------------|
| Provider | Fixed DeepSeek only |
| Endpoint | `POST https://api.deepseek.com/v1/chat/completions` |
| Auth | `Authorization: Bearer <user key>` |
| Models | `deepseek-chat` (default), `deepseek-reasoner` |
| Key storage | `localStorage.regimeEngineAiKey_v1` (never in git) |
| Body | `temperature: 0.1`, `response_format: { type: "json_object" }`, system+user messages; user content is `AI_PROMPT` requesting **strict JSON** for gdp/iip/cpi/core/food/repo/fii/dii/india10y |
| Apply | `parseAiJson` (strips fences); `applyAiPayload` writes fields; `markEv(..., "ai")`; `renderAll({ recordEval: true })` |
| Failure | UI error string; no silent invent by the scoring engine |

---

## 13. Backtest disclaimer

Offline experiments live under `backtest/`:

- `backtest/report.md` — v1 verdict **`NO_CONFIRMED_EDGE`**
- `backtest/report_v2.md` — v2 (Selective / Transitory / confirm / conviction) also **`NO_CONFIRMED_EDGE`** (more conservative; no confirmed statistical edge vs Nifty buy-and-hold on free data)

Treat the live app as a **checklist / consistency engine**, not an autopilot with proven alpha.

---

## 14. Source code links

- Repository: https://github.com/cakashoza-cmyk/india-regime-engine  
- Blob (main `index.html`): https://github.com/cakashoza-cmyk/india-regime-engine/blob/main/index.html  
- Live Method tab: https://cakashoza-cmyk.github.io/india-regime-engine/  
- This audit file (in-repo when pushed): https://github.com/cakashoza-cmyk/india-regime-engine/blob/main/AUDIT_LOGIC.md  
- Raw: https://raw.githubusercontent.com/cakashoza-cmyk/india-regime-engine/main/AUDIT_LOGIC.md  

---

## Audit checklist (one page)

Independent reviewers should ask:

1. **Source match:** Does each threshold in this doc (§3–§10) still match `index.html` on the audited commit SHA?
2. **Non-claims:** Is the UI still explicit that AI ≠ fact and Unclear/wait is allowed?
3. **Growth purity:** Can Nifty alone ever set Growth ≠ Unclear? (Code: no.)
4. **Transitory:** When food/crude↑ and core flat/falling, is Inflation Transitory and excluded from `iUp`?
5. **DII:** Is `liq_signal` still always `unknown` so DII cannot flip Liquidity?
6. **FII bands:** Are ±500 ₹ cr thresholds unchanged?
7. **Hard stress:** Is `hard = con≥4 OR (n≥3 AND con/n≥0.75)` and does it force Risk-Off ahead of Selective?
8. **mapSleeve order:** Does Risk-Off still precede Selective, and Selective precede full Cyclicals-Reflation?
9. **Risk-On rarity:** Is Risk-On still only Rising+Falling+Expanding (plus Goldilocks+Expanding)?
10. **Confirmation:** Do only Save & AI fill set `recordEval: true`? Does first eval stay pending?
11. **Buy list gate:** Is OW/UW concrete list hidden unless Strong **and** confirmed?
12. **Secrets:** Is any API key absent from the git tree?
13. **Backtest:** Do `report.md` / `report_v2.md` still conclude **NO_CONFIRMED_EDGE**?
14. **Evidence tags:** After AI fill, are filled macros tagged `ai` (not `fact`)?
15. **Selective lists:** Does `SLEEVES["Selective cyclicals / dry powder"]` exist so UI does not silently fall back to Unclear OW/UW?

---

*End of specification. Generated from code extract; re-run extract on each release.*

---

## Operating flowchart

The weekly rejection-machine process (Gates 1–7, practice ramp, sequence stages) lives in **[OPERATING_FLOWCHART.md](./OPERATING_FLOWCHART.md)**.

**Implemented vs Target (2026-10-26):** Gates 1–7 are in the live Operating wizard UI. DeepSeek assists fill/interpret; outputs are **AI-assisted, not authoritative**. Legacy sleeve tab + `index.legacy.html` preserve the prior single-page dial/sleeve view.

---

## Snapshot flows & India 10Y (wired 2026-10-26)

`refresh_data.py` populates:

| Field | Source priority | Notes |
|-------|-----------------|-------|
| `flows.fii_net` / `flows.dii_net` | Moneycontrol cash CM → NSE `fiidiiTradeReact` provisional cash | Equity cash CM only — **not** NSDL equity+debt grand total. Null + warning if scrape fails. |
| `market.india10y` | CCIL tenorwise → Investing.com India 10Y | Null + warning if scrape fails. |
| `soft_proxy` | USDINR 1m % + India VIX from Yahoo | UI opt-in only when FII null; **default OFF**; labeled proxy, lower weight. |

Gate 2 Liquidity dial auto-reads snapshot FII / India 10Y. DeepSeek must use snapshot values when present and must not invent nulls.
