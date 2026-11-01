"""Module 1 — Ingestion. Writes raw_ingest rows only. Never invents a value.

Failure policy (spec: "do not write nulls"): a failed pull is logged as ok=0 with the
error payload; Scoring then carries the last good value forward flagged stale.
"""
from __future__ import annotations
import html, json, os, re, sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
import refresh_data as rd  # noqa: E402  (reuse proven fetchers)
from engine import db  # noqa: E402
from engine.config import YAHOO, tier_for  # noqa: E402
from engine import search_adapter as sa  # noqa: E402
from engine import dbie  # noqa: E402
from engine import release_calendar as cal  # noqa: E402
from engine import official  # noqa: E402
from engine import auto_macro  # noqa: E402
IST = cal.IST

IST = timezone(timedelta(hours=5, minutes=30))
MANUAL = Path(__file__).resolve().parent / "manual_inputs.json"


def _store(conn, source, indicator, payload, ok, release_date=None, verified=False):
    tier = tier_for(source, payload if isinstance(payload, dict) else None)
    if tier == "news_llm":
        verified = False  # spec 1.1: news/LLM is never verified
    if isinstance(payload, dict):
        payload = {**payload, "source_tier": tier, "data_period": payload.get("as_of")}
    return db.q(conn,
        "INSERT INTO raw_ingest (source, indicator, payload, fetched_at, release_date, is_verified, ok, source_tier) VALUES (?,?,?,?,?,?,?,?)",
        (source, indicator, db.jdump(payload), datetime.now(timezone.utc).isoformat(),
         release_date, bool(verified), bool(ok), tier))


# Yahoo is only a cross-check where an official/exchange source exists (see ingest_official).
YAHOO_CHECK_ONLY = {"nifty", "nifty_bank", "nifty_auto", "nifty_metal", "india_vix", "us10y", "brent"}


def _yahoo(conn, key, sym, log, role=None):
    r = rd.yahoo_chart(sym, "1mo")
    r["role"] = role or ("check" if key in YAHOO_CHECK_ONLY else "primary")
    lbd = official.last_business_day(datetime.now(IST).date()).isoformat()
    if r.get("as_of") and str(r["as_of"])[:10] > lbd:  # weekend tick -> last session
        r["as_of"] = lbd
    ok = r.get("value") is not None
    _store(conn, "yahoo", key, r, ok, r.get("as_of"), verified=ok)
    log.append((key, "yahoo", ok, r.get("error")))
    return ok


def parse_rbi_home(text: str) -> dict:
    s = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)))
    out = {}
    m = re.search(r"Policy Repo Rate\s*:\s*([\d.]+)\s*%", s)
    if m: out["repo_rate"] = float(m.group(1))
    m = re.search(r"INR\s*/\s*1 USD\s*:\s*([\d.]+)", s)
    if m: out["usdinr_ref"] = float(m.group(1))
    for k, pat in (("sdf", r"Standing Deposit Facility Rate\s*:\s*([\d.]+)"),
                   ("msf", r"Marginal Standing Facility Rate\s*:\s*([\d.]+)"),
                   ("crr", r"CRR\s*:\s*([\d.]+)")):
        m = re.search(pat, s)
        if m: out[k] = float(m.group(1))
    return out


def ingest_rbi(conn, log):
    url = "https://www.rbi.org.in/"
    raw, err, _ = rd.http_get(url)
    parsed = parse_rbi_home(raw.decode("utf-8", "ignore")) if raw else {}
    today = datetime.now(IST).date().isoformat()
    man = json.loads(MANUAL.read_text()) if MANUAL.exists() else {}
    for key in ("repo_rate", "usdinr_ref"):
        v = parsed.get(key)
        if v is not None:
            prior, as_of, note = None, today, "RBI homepage rates panel"
            if key == "repo_rate":
                m = man.get("repo_rate") or {}
                if m.get("value") is not None and abs(float(m["value"]) - v) < 1e-9:
                    prior, as_of = m.get("prior"), m.get("as_of") or today  # last MPC decision
                    note += f"; prior/as_of from MPC decision {m.get('source_url')}"
            else:
                as_of = official.rbi_ref_rate_date()
                note = "FBIL USD/INR reference rate as shown on RBI homepage (dated to its publication day)"
            _store(conn, "rbi", key, {"value": v, "prior": prior, "as_of": as_of, "role": "primary",
                   "source_url": url, "extra": parsed, "note": note}, True, as_of, True)
            log.append((key, "rbi.org.in", True, None))
        elif key == "usdinr_ref":  # fallback: Yahoo INR=X
            ok = _yahoo(conn, key, "INR=X", log, role="primary")
            if not ok:
                _store(conn, "rbi", key, {"error": err or "not parsed", "source_url": url}, False)
        else:
            _store(conn, "rbi", key, {"error": err or "repo not parsed", "source_url": url}, False)
            log.append((key, "rbi.org.in", False, err or "not parsed"))


def ingest_official(conn, log):
    """Official / exchange-published sources (primary where available)."""
    nse = official.nse_close_all()
    for key in official.NSE_NAMES:
        r = nse.get(key)
        ok = r is not None
        _store(conn, "nse_archive", key, dict(r, role="primary") if ok else {"error": "NSE ind_close_all not available"}, ok, r and r["as_of"], ok)
        log.append((key, "nse ind_close_all", ok, None if ok else "not available"))
    for key, src, fn in (("us10y", "treasury", official.treasury_10y), ("brent", "ice_contract", official.brent_active),
                         ("credit_growth", "rbi_press", official.rbi_credit_growth), ("breadth_200dma", "nse+yahoo", official.breadth_nifty50)):
        try:
            r = fn()
        except Exception as e:  # noqa: BLE001
            r = {"error": str(e)}
        ok = r.get("value") is not None and not r.get("error")
        r["role"] = "primary"
        _store(conn, src, key, r, ok, r.get("as_of"), ok)
        log.append((key, src, ok, r.get("error")))
    # second source for USD/INR
    _yahoo(conn, "usdinr_ref", "INR=X", log, role="check")


AUTO_KEYS = {"cpi_headline", "food_inflation", "iip_yoy", "gdp_yoy", "capacity_util"}  # manual rows become cross-checks
# capacity_util removed from TE: TE labelled RBI's Q4FY26 77.4% as the latest quarter (RBI's latest is Q1FY27 74.6%).
TE_ROLE = {"cpi_headline": "check", "food_inflation": "check", "credit_growth": "check", "india10y": "check",
           "iip_yoy": "primary", "gdp_yoy": "primary"}


def ingest_auto(conn, log):
    """Automatic macro: MOSPI API+PDF (CPI/food), CCIL headless (10Y), RBI MPC stance, Trading Economics."""
    now = datetime.now(IST)
    cal.HOLIDAYS = official.nse_holidays() or cal.HOLIDAYS
    have = db.q(conn, "SELECT id FROM raw_ingest WHERE source='mospi' AND indicator='cpi_headline' AND ok AND fetched_at > ? LIMIT 1",
                ((datetime.now(timezone.utc) - timedelta(days=35)).isoformat(),), one=True)
    if cal.should_pull("cpi_headline", now) or not have:
        try:
            cpi = auto_macro.mospi_cpi()  # MoSPI PDF first; PIB has no machine-readable listing (see README)
        except Exception as e:  # noqa: BLE001
            cpi = {"error": f"mospi: {e}"}
    else:
        cpi = {"skip": f"before this month's CPI release ({cal.release_date('cpi_headline', now.year, now.month)} 16:00 IST); last pull kept"}
    for key in ("cpi_headline", "food_inflation"):
        if "skip" in cpi:
            log.append((key, "mospi api+pdf", True, cpi["skip"])); continue
        r = cpi.get(key) if "error" not in cpi else None
        _store(conn, "mospi", key, dict(r, role="primary") if r else {"error": cpi.get("error")}, bool(r), r and r["as_of"], bool(r))
        log.append((key, "mospi api+pdf", bool(r), None if r else cpi.get("error")))
    for key, role in TE_ROLE.items():
        try:
            r = auto_macro.tradingeconomics(key)
        except Exception as e:  # noqa: BLE001
            r = {"error": f"tradingeconomics: {e}"}
        ok = r.get("value") is not None and not r.get("error")
        r["role"] = role
        _store(conn, "tradingeconomics", key, r, ok, r.get("as_of"), ok)
        log.append((key, f"tradingeconomics ({role})", ok, r.get("error")))
    # OBICUS (RBI publication page), probe forward from the last found publication id
    last = db.q(conn, "SELECT payload FROM raw_ingest WHERE source='rbi_obicus' AND ok ORDER BY id DESC LIMIT 1", one=True)
    sid = (db.jload(last["payload"]).get("publication_id") if last else None) or official.OBICUS_SEED_ID
    recent = last and db.q(conn, "SELECT id FROM raw_ingest WHERE source='rbi_obicus' AND ok AND fetched_at > ? LIMIT 1",
                           ((datetime.now(timezone.utc) - timedelta(hours=20)).isoformat(),), one=True)
    try:
        r = official.rbi_obicus(sid, 1) if recent else official.rbi_obicus(sid, 40)  # full forward probe once a day
    except Exception as e:  # noqa: BLE001
        r = {"error": f"obicus: {e}"}
    ok = r.get("value") is not None and not r.get("error")
    if ok:
        r["expected_quarter"] = official.expected_obicus_quarter(datetime.now(IST).date())
        r["role"] = "primary"
    _store(conn, "rbi_obicus", "capacity_util", r, ok, r.get("as_of"), ok)
    log.append(("capacity_util", "rbi obicus", ok, r.get("error")))
    try:
        r = auto_macro.ccil_10y()
    except Exception as e:  # noqa: BLE001
        r = {"error": f"ccil: {e}"}
    ok = r.get("value") is not None and not r.get("error")
    r["role"] = "primary"
    _store(conn, "ccil", "india10y", r, ok, r.get("as_of"), ok)
    log.append(("india10y", "ccil headless", ok, r.get("error")))
    try:
        st = auto_macro.rbi_stance()
        _store(conn, "rbi_mpc", "rbi_stance", st, True, st.get("as_of"), True)
        _store(conn, "rbi_mpc", "rbi_stance_score", {**st, "role": "primary", "prior": None}, True, st.get("as_of"), True)
        log.append(("rbi_stance", "rbi mpc resolution", True, None))
    except Exception as e:  # noqa: BLE001
        _store(conn, "rbi_mpc", "rbi_stance_score", {"error": str(e)}, False)
        log.append(("rbi_stance", "rbi mpc resolution", False, str(e)))


def ingest_flows_10y(conn, log):
    try:
        api = official.nse_fii_dii()  # primary: NSE fiidiiTradeReact (cookie warm-up)
    except Exception as e:  # noqa: BLE001
        api = {}
        log.append(("fii_net", "nse api", False, f"fiidiiTradeReact: {e}"))
    for key in ("fii_net", "dii_net"):
        if key in api:
            _store(conn, "nse_api", key, {**api[key], "role": "primary"}, True, api[key]["as_of"], True)
            log.append((key, "nse api", True, None))
    fii, dii, w = rd.fetch_fii_dii()  # fallback (kept)
    for key, r in (("fii_net", fii), ("dii_net", dii)):
        ok = r.get("value") is not None
        _store(conn, "nse", key, r, ok, r.get("as_of"), ok)
        log.append((key, r.get("source") or "nse", ok, r.get("error") or "; ".join(w) or None))
    y, w2 = rd.fetch_india10y()
    ok = y.get("value") is not None
    if ok:  # Investing shows the last traded yield; on weekends/holidays date it to the last business day
        lbd = official.last_business_day(datetime.now(IST).date()).isoformat()
        if not y.get("as_of") or str(y["as_of"])[:10] > lbd:
            y["as_of"] = lbd
        y["role"] = "check"  # CCIL (official) is primary
    _store(conn, "investing" if ok else "ccil", "india10y", y, ok, y.get("as_of"), ok)
    log.append(("india10y", y.get("source") or "ccil/investing", ok, y.get("error") or "; ".join(w2) or None))


def ingest_manual(conn, log):
    """Official macro prints pasted by the user (MOSPI/RBI/PIB). Only non-null values are stored."""
    if not MANUAL.exists():
        return
    data = json.loads(MANUAL.read_text())
    for key, rec in data.items():
        if key.startswith("_") or not isinstance(rec, dict):
            continue
        if rec.get("value") is None:
            log.append((key, "manual", False, "no official print entered in engine/manual_inputs.json"))
            continue
        last = db.q(conn, "SELECT payload FROM raw_ingest WHERE indicator=? AND source='manual' AND ok ORDER BY id DESC LIMIT 1", (key,), one=True)
        if last and {k: v for k, v in db.jload(last["payload"]).items() if k != "role"} == rec:
            continue  # unchanged — no duplicate row
        _store(conn, "manual", key, dict(rec, role="check" if key in AUTO_KEYS else "primary"), True, rec.get("as_of"), rec.get("verified", True) is not False)
        log.append((key, "manual", True, None))


def ingest_dbie(conn, log):
    """RBI DBIE public API — primary structured source for CPI/food/IIP history (vintage-lagged)."""
    for key in dbie.SERIES:
        try:
            r = dbie.latest(key)
            ok = r is not None
            # CPI on DBIE is the discontinued base-2012 series (MOSPI switched to base 2024 in 2026):
            # kept for history/backtest only, never verified for current scoring.
            old_base = key in ("cpi_headline", "food_inflation", "cpi_core")
            if r:
                r = dict(r, role="history" if old_base else "primary",
                         note="DBIE base-2012 CPI (discontinued) - history only" if old_base else "DBIE")
            _store(conn, "dbie", key, r or {"error": "no rows"}, ok, r and r["as_of"], ok and not old_base)
            log.append((key, "rbi dbie api", ok, None if ok else "no rows"))
        except Exception as e:  # noqa: BLE001
            _store(conn, "dbie", key, {"error": str(e)}, False)
            log.append((key, "rbi dbie api", False, str(e)))


def ingest_stubs(conn, log):
    """breadth + credit are now real scrapers (engine/official.py)."""
    return


def ingest_language(conn, log, force=False):
    """DeepSeek search+chat for RBI policy LANGUAGE only. Numbers from LLM are never stored as values."""
    jobs = cal.language_jobs_due(datetime.now(IST).date(), force=force)
    if not jobs:
        return
    if not os.environ.get("DEEPSEEK_API_KEY"):
        for j in jobs:
            log.append((j, "deepseek", False, "DEEPSEEK_API_KEY not set — skipped"))
        return
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    for j in jobs:
        if not force and db.q(conn, "SELECT id FROM raw_ingest WHERE source='deepseek' AND indicator=? AND fetched_at > ? LIMIT 1",
                              (f"llm_{j}", week_ago), one=True):
            log.append((j, "deepseek", True, "ran within 7 days - skipped (spec 4.4)"))
            continue
        res, err = None, None
        for _attempt in range(3):  # 1 try + at most 2 retries
            try:
                res = sa.policy_language(j); break
            except Exception as e:  # noqa: BLE001
                err = str(e)
        res = res or {"error": err}
        rule = db.q(conn, "SELECT payload FROM raw_ingest WHERE source='rbi_mpc' AND indicator='rbi_stance' AND ok ORDER BY id DESC LIMIT 1", one=True)
        if rule and res.get("stance"):
            res["agrees_with_rule_based"] = sa.normalise_stance(db.jload(rule["payload"]).get("stance")) == res["stance"]
        # stored under llm_* so it never overrides the rule-based stance (cross-check only, display only)
        _store(conn, "deepseek", f"llm_{j}", res, res.get("stance") is not None, None, False)
        log.append((j, "deepseek (cross-check)", res.get("stance") is not None, res.get("error")))


def ingest_deepseek_numbers(conn, log):
    """Spec 4.4: numeric indicators never go through DeepSeek (structured sources only)."""
    return


def run(conn, force_language=False) -> list:
    log: list = []
    for key, sym in YAHOO.items():
        _yahoo(conn, key, sym, log)
    ingest_official(conn, log)
    ingest_auto(conn, log)
    ingest_rbi(conn, log)
    ingest_flows_10y(conn, log)
    ingest_dbie(conn, log)
    ingest_manual(conn, log)
    ingest_stubs(conn, log)
    ingest_deepseek_numbers(conn, log)
    ingest_language(conn, log, force_language)
    conn.commit()
    return log
