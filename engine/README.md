# Macro Regime Intelligence Engine — v1

Cascade pipeline (each module stateless, talks only through the DB):

`ingest.py → score.py → classify.py → stage_gap.py → decide.py (+ sectors.py) → alert.py → data/regime_latest.json`

Dashboard: `engine.html` on GitHub Pages (reads `data/regime_latest.json` + `data/regime_history.json`).

> **All sizing output is PAPER / FOR REVIEW.** The earlier backtests of these rules (backtest/report_v2.md) showed
> **no confirmed edge**. Each decision is stored with a check-back date (`regime_history.json`, `outcome: null`) so
> an outcome log can build a track record before anything is treated as a live instruction.

## Run it (free)
- **Hosted:** GitHub Actions `.github/workflows/engine.yml` runs the pipeline on cron, commits `engine/regime.db`
  (SQLite) + JSON exports; Pages serves the dashboard. No server, no cost.
- **Local:** `python engine/pipeline.py [--force-language]`; API `pip install fastapi uvicorn && uvicorn engine.api:app`
  (`GET /latest`, `GET /history`, `POST /run`); always-on scheduler `python -m engine.scheduler` (APScheduler).
- **Postgres:** set `DATABASE_URL=postgresql://...` and `pip install "psycopg[binary]"`. `schema.sql` is Postgres-native;
  SQLite gets a translated copy automatically.
- Tests: `python -m pytest -q engine/tests`.

## Schedule (IST; Actions cron is UTC)
| IST | UTC cron | Why |
|---|---|---|
| Mon–Fri 10:15 | `45 4 * * 1-5` | RBI MPC decision (~10:00) / rates panel |
| Mon–Fri 12:45 | `15 7 * * 1-5` | RBI USD/INR reference rate (~12:30) |
| Mon–Fri 16:05 | `35 10 * * 1-5` | CPI + IIP (4:00 PM on the 12th) and market close |
| Mon–Fri 18:30 | `0 13 * * 1-5` | NSE provisional FII/DII (~18:00) |
| 1st of month 12:00 | `30 6 1 * *` | GST collections |
GitHub cron can run 5–20 min late; that is fine for these release times. MPC dates live in `release_calendar.py` (verify each FY).

## Sources — live vs stubbed (two sources + `raw_ingest` audit trail)
| Indicator | Primary | Secondary | Status |
|---|---|---|---|
| Repo rate (+SDF/MSF/CRR) | rbi.org.in rates panel | manual_inputs / DeepSeek stance language | **live** |
| USD/INR | RBI reference rate (rbi.org.in) | Yahoo `INR=X` | **live** |
| India 10Y | CCIL (403 from runners) | Investing.com | **live via fallback** |
| FII / DII cash | Moneycontrol (403) | NSE cash CM API | **live via fallback** |
| Nifty, Bank, Auto, Metal, VIX, Brent, US10Y, DXY | Yahoo chart API | — (yfinance same backend) | **live** |
| CPI headline, food (CFPI), IIP | `manual_inputs.json` (official MOSPI print) | **RBI DBIE public API** (`data-api.dbie.rbihub.in`) | DBIE live but **vintage-lagged** (CPI to Dec-2025, IIP to Mar-2026) → flagged STALE, shown, does not vote |
| Core CPI, GDP, GST, credit growth, OBICUS | `manual_inputs.json` | DeepSeek search+fetch (unverified; never scored) — CPI excluded | **manual** |
| Breadth % > 200DMA | NSE bhavcopy | — | **stub (v2)** |
| OIS | — | — | not wired (no free source) |
| RBI stance / minutes tone | DeepSeek Search+Fetch + deepseek-flash (language only) | — | needs `DEEPSEEK_API_KEY` secret |

nsepython/jugaad-data were not added: NSE blocks most datacenter IPs; the existing NSE fallback already works from runners.

### Rules
- Failed pull → `raw_ingest.ok=false` with the error; last good value carried forward with `is_stale/stale_since`. Never invented, never null-overwritten.
- Values older than their cadence (daily 7d, monthly 75d, quarterly 140d) are **STALE**: shown, but excluded from dial votes, flips and invalidations.
- **DeepSeek numbers** (`get_indicator_via_deepseek`) are stored `is_verified=false` and never feed scoring until they equal an official/structured value. CPI is never taken from the LLM.
- Default output is **"no change"**; alerts fire only on regime change, triggered invalidation, or source failure. Labels are never forced — insufficient data → `Unclear` → STOP.

### DeepSeek Search + Fetch
`POST https://api.deepseek.com/v1/tools/search` (`query` ≤128 chars, `count` 1–50 — the spec's `max_results` is ignored by the API, we send `count=5`)
and `POST /v1/tools/fetch` (`url`) are real, documented endpoints (api-docs.deepseek.com/guides/search.md). Both are **billed per DeepSeek's pricing** in addition to chat tokens.
On 4xx/5xx/timeout, fetch falls back to plain HTTP (`search_adapter.plain_fetch`) and the run logs the failure (alerted).

## Logic (ported from AUDIT_LOGIC.md so wizard and engine agree)
- **Scoring** (+1 favourable): rate & inflation +1 if falling (spec); growth/vote/credit +1 if rising; fragility (VIX, US10Y, DXY, USDINR) −1 if rising; FII net ±500 cr thresholds; DII display only. *(rate/inflation from spec; the rest are assumptions — spec was truncated.)*
- Dial labels: majority ≥60%; Transitory inflation rule; liquidity hard-stress (`con≥4 or n≥3 & con/n≥0.75`); 2-evaluation confirmation. Extra safeguard: inflation needs ≥2 live series.
- Regime: Goldilocks / Reflation / Slowdown / Stagflation / **Tightening** (hard liquidity contraction overrides non-stagflation quadrant — assumption) / Unclear.
- **Stage 0–6** gates: rate peak → credit stabilises → rate-sensitives (Nifty Bank) bottom → cyclicals (Nifty Auto) → commodities (Metal + Brent) → next tightening. Unknown data stops the climb.
- **Gap**: macro regime vs market vote dial → underpriced / overpriced / none / unknown.
- **Module 6 sectors** (`sector_matrix.json`, only the 6 spec'd sectors): impact = driver change × transmission; marginal driver = max |impact|; top-two within 20% with opposite signs → **TOO CLOSE TO CALL** (Gate 5). Driver derivation: currency=USDINR dir, rates=funding_cost=avg(repo,10Y dir), credit_growth=credit dir, liquidity=liquidity dial, commodities=Brent dir, inflation=−inflation dial, risk_off=−fragility dial, growth=growth dial, asset_quality=null. Null → 0 and logged.
  Note: REAL_ESTATE `liquidity −0.7` is implemented exactly as given (it makes expanding liquidity negative for real estate — looks like a sign slip worth checking).
- **Module 7** `size_position(stage, gap_conviction, fragility)`: stage<2 or gap none/unknown → wait 0; base 0.10, ×1.5 if conviction>0.7, ×0.5 if fragility>0.7. gap_conviction = Strong 1.0 / Mixed 0.6 / Unclear 0; fragility = max(0, −fragility dial). Any triggered invalidation forces wait.
- **Invalidations**: capacity utilisation >75%, CPI >6.0, US10Y >5.5, USDINR >98 → triggered / not triggered / unknown.

## Secrets (repo → Settings → Secrets → Actions)
`DEEPSEEK_API_KEY` (language jobs + unverified number search), optional `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, `SMTP_HOST`, `SMTP_USER`, `SMTP_PASS`, `ALERT_EMAIL_TO`. All skip cleanly when absent.

## Feeding official prints
Edit `engine/manual_inputs.json` (value, prior, as_of = reference period, source_url) after each MOSPI/RBI/PIB release and commit; the next run uses it over the older DBIE vintage.

## Backtest (lower priority, shipped after MVP)
`python backtest/run_2018_2024.py` replays 2018–2024 month-ends through `engine/logic.py` using only sourced history
(DBIE CPI/food/IIP, FRED GDP/call-money/India 10Y, Yahoo markets) → `backtest/report_2018_2024.md`.
Gaps not invented: core CPI, GST, credit growth, FII, breadth, OBICUS, RBI stance; repo history uses call-money as proxy.
Because credit growth has no sourced history, the stage climb can't pass gate 2 in replay (max stage 1).

## Sources & validation (v1.1, Nov 2026 audit)
| Indicator | Primary | Cross-check |
|---|---|---|
| Nifty, Bank, Auto, Metal, India VIX | NSE `ind_close_all_DDMMYYYY.csv` (official) | Yahoo |
| US 10Y | US Treasury par yield CSV | Yahoo ^TNX |
| Brent | ICE active contract (`BZ<mon><yy>.NYM`, rolls on expiry day; value+prior same contract) | Yahoo BZ=F |
| Repo / USDINR | RBI homepage (ref rate dated to its FBIL publication day) + MPC press release in manual_inputs | Yahoo INR=X |
| Credit growth | RBI Scheduled Banks' Statement of Position (auto, YoY computed) | — |
| Breadth | % of Nifty 50 above 200-DMA (NSE list + Yahoo prices) — unverified | — |
| CPI, food, IIP, GDP, GST | `manual_inputs.json` official MOSPI/PIB/GSTN prints with URLs | — |
| India 10Y | Investing (unverified; CCIL page is JS-only) | — |

DBIE CPI is the discontinued base-2012 series: stored as history only, never scored.
`engine/validate.py` assigns each value `verified | unverified | stale | failed` (sanity ranges + same-date
two-source tolerance). `failed` values are forced to score 0. Dashboard shows a badge per value and a
"Missing" table with the reason for every null.

## Developer Change Specification (Nov 2026)
**Data layer (Module 1).** Each `raw_ingest` row has a `source_tier`: official_primary, official_secondary, market_data or news_llm (`config.tier_for`, `PREFERRED_SOURCES`). Each indicator is exported with `source_tier`, `data_period` (`survey_quarter` for OBICUS), `is_stale` and `diagnostics`. Only verified, fresh data is scored. Anything else gets score `null` with `excluded: unverified` or `excluded: stale` (`score.gate_score`). Tier-1 signals (RBI stance, OIS, 10Y, curve, core CPI, Brent) are scored only from official_primary or market_data. news_llm data is never verified.
- **CPI:** pulled at 16:00 IST on the 12th. If the 12th falls on a weekend or an NSE holiday (NSE holiday-master API), the pull rolls to the next business day (`release_calendar.should_pull`). Source order is MoSPI API + PDF. PIB was tried, but its listing shows only today's releases, so it can't be used as a fallback.
- **Capacity utilisation:** scraped from the RBI OBICUS publication page (PublicationsView, probing forward from the last id found). The `survey_quarter` is checked against the quarter expected to be out (quarter end + ~100 days). When the reading is stale, the >75% invalidation shows `stale` and does not fire. Trading Economics was dropped as a source: it labelled RBI's Q4FY26 77.4% as the latest quarter, when RBI's Q1FY27 reading is 74.6%.
- **FII/DII:** primary source is the NSE `api/fiidiiTradeReact` endpoint after a cookie warm-up. The older fetch is kept as a fallback.
- **10Y:** FIMMDA-PDAI was tried. fimmda.org returns a JS shell with no data, so CCIL (headless) is primary. TE and Investing are cross-checks only.
- **OIS 1Y:** no fetchable official source was found (CCIL curve page, FBIL, NSE and FIMMDA all tried). The manual ET value is tagged news_llm. It is display only and excluded from Tier 1.

**Calibration (Module 3).** The CPI flip is now 6.0 (was 4.0) and the US10Y flip is 5.5 (was 4.5). Each level carries `last_calibrated` and `calibration_note`, also written to the `flip_levels` table. A level older than 180 days triggers `FLIP_LEVEL_STALE`, logged at startup and shown on the dashboard. The spec mentions a core_cpi <4 Tier-1 flip, but there is none in FLIP_LEVELS. core CPI stays null because MoSPI publishes no division weights, so no such flip was added.

**DeepSeek (Module 4).** Numeric indicators never go through DeepSeek (`get_indicator_via_deepseek` is disabled). All prompts use the mandatory extraction-only system prompt. The RBI stance is returned as `{stance, keywords[]}`, and every keyword must appear verbatim in the source. It is stored as `llm_rbi_stance`, used only as a cross-check against the rule-based MPC parse, and never scored. Numbers the LLM extracts from official domains are tagged official_secondary and unverified. Consensus needs at least 2 independent domains that agree. Capex and earnings commentary is tagged news_llm and shown for display only. Each qualitative check runs at most once a week, with at most 2 retries.
