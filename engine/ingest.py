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
from engine.config import YAHOO  # noqa: E402
from engine import search_adapter as sa  # noqa: E402
from engine import dbie  # noqa: E402
from engine import release_calendar as cal  # noqa: E402

IST = timezone(timedelta(hours=5, minutes=30))
MANUAL = Path(__file__).resolve().parent / "manual_inputs.json"


def _store(conn, source, indicator, payload, ok, release_date=None, verified=False):
    return db.q(conn,
        "INSERT INTO raw_ingest (source, indicator, payload, fetched_at, release_date, is_verified, ok) VALUES (?,?,?,?,?,?,?)",
        (source, indicator, db.jdump(payload), datetime.now(timezone.utc).isoformat(),
         release_date, bool(verified), bool(ok)))


def _yahoo(conn, key, sym, log):
    r = rd.yahoo_chart(sym, "1mo")
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
    for key in ("repo_rate", "usdinr_ref"):
        v = parsed.get(key)
        if v is not None:
            _store(conn, "rbi", key, {"value": v, "prior": None, "as_of": today,
                   "source_url": url, "extra": parsed, "note": "RBI homepage rates panel"}, True, today, True)
            log.append((key, "rbi.org.in", True, None))
        elif key == "usdinr_ref":  # secondary: Yahoo INR=X
            ok = _yahoo(conn, key, "INR=X", log)
            if not ok:
                _store(conn, "rbi", key, {"error": err or "not parsed", "source_url": url}, False)
        else:
            _store(conn, "rbi", key, {"error": err or "repo not parsed", "source_url": url}, False)
            log.append((key, "rbi.org.in", False, err or "not parsed"))


def ingest_flows_10y(conn, log):
    fii, dii, w = rd.fetch_fii_dii()
    for key, r in (("fii_net", fii), ("dii_net", dii)):
        ok = r.get("value") is not None
        _store(conn, "nse", key, r, ok, r.get("as_of"), ok)
        log.append((key, r.get("source") or "nse", ok, r.get("error") or "; ".join(w) or None))
    y, w2 = rd.fetch_india10y()
    ok = y.get("value") is not None
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
        if last and db.jload(last["payload"]) == rec:
            continue  # unchanged — no duplicate row
        _store(conn, "manual", key, rec, True, rec.get("as_of"), True)
        log.append((key, "manual", True, None))


def ingest_dbie(conn, log):
    """RBI DBIE public API — primary structured source for CPI/food/IIP history (vintage-lagged)."""
    for key in dbie.SERIES:
        try:
            r = dbie.latest(key)
            ok = r is not None
            _store(conn, "dbie", key, r or {"error": "no rows"}, ok, r and r["as_of"], ok)
            log.append((key, "rbi dbie api", ok, None if ok else "no rows"))
        except Exception as e:  # noqa: BLE001
            _store(conn, "dbie", key, {"error": str(e)}, False)
            log.append((key, "rbi dbie api", False, str(e)))


def ingest_stubs(conn, log):
    # Not wired yet (documented in README). Logged as failures so they show as missing, not zero.
    for key, why in (("breadth_200dma", "NSE bhavcopy breadth not wired in v1"),
                     ("credit_growth", "no current fortnightly credit series wired in v1 (DBIE scrape lags) — paste official % in manual_inputs.json")):
        has_manual = db.q(conn, "SELECT id FROM raw_ingest WHERE indicator=? AND ok LIMIT 1", (key,), one=True)
        if not has_manual:
            _store(conn, "stub", key, {"error": why}, False)
            log.append((key, "stub", False, why))


def ingest_language(conn, log, force=False):
    """DeepSeek search+chat for RBI policy LANGUAGE only. Numbers from LLM are never stored as values."""
    jobs = cal.language_jobs_due(datetime.now(IST).date(), force=force)
    if not jobs:
        return
    if not os.environ.get("DEEPSEEK_API_KEY"):
        for j in jobs:
            log.append((j, "deepseek", False, "DEEPSEEK_API_KEY not set — skipped"))
        return
    for j in jobs:
        try:
            res = sa.policy_language(j)
            _store(conn, "deepseek", j, res, res.get("stance") is not None, None, False)
            log.append((j, "deepseek", res.get("stance") is not None, res.get("error")))
        except Exception as e:  # noqa: BLE001
            _store(conn, "deepseek", j, {"error": str(e)}, False)
            log.append((j, "deepseek", False, str(e)))


def ingest_deepseek_numbers(conn, log):
    """Macro numbers via DeepSeek Search+Fetch when no official manual print. Stored is_verified=False;
    becomes verified only if it equals a manual/structured value. Unverified numbers never feed scoring."""
    if not os.environ.get("DEEPSEEK_API_KEY"):
        log.append(("deepseek_numbers", "deepseek", False, "DEEPSEEK_API_KEY not set — skipped"))
        return
    when = datetime.now(IST).strftime("%B %Y")
    for key in [k for k in sa.NAMES if k not in ("cpi_headline", "cpi_core", "food_inflation")]:  # never CPI via LLM
        try:
            r = sa.get_indicator_via_deepseek(key, when)
        except Exception as e:  # noqa: BLE001
            r = {"value": None, "error": f"deepseek: {e}"}
        man = db.q(conn, "SELECT payload FROM raw_ingest WHERE indicator=? AND source='manual' AND ok ORDER BY id DESC LIMIT 1", (key,), one=True)
        mv = db.jload(man["payload"]).get("value") if man else None
        verified = r.get("value") is not None and mv is not None and abs(float(r["value"]) - float(mv)) < 1e-6
        _store(conn, "deepseek", key, r, r.get("value") is not None, r.get("as_of"), verified)
        log.append((key, "deepseek (unverified)" if not verified else "deepseek=manual", r.get("value") is not None, r.get("error")))


def run(conn, force_language=False) -> list:
    log: list = []
    for key, sym in YAHOO.items():
        _yahoo(conn, key, sym, log)
    ingest_rbi(conn, log)
    ingest_flows_10y(conn, log)
    ingest_dbie(conn, log)
    ingest_manual(conn, log)
    ingest_stubs(conn, log)
    ingest_deepseek_numbers(conn, log)
    ingest_language(conn, log, force_language)
    conn.commit()
    return log
