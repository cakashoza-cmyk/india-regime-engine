"""Module 2 — freshness gate. A point is fresh only if it is for the latest period whose scheduled
release time has passed (NOT previous_month(today))."""
from __future__ import annotations
from datetime import date, datetime, timedelta
from engine import release_calendar as cal
from engine.official import expected_obicus_quarter

MONTHLY = {"cpi_headline": (1, "cpi_headline"), "food_inflation": (1, "cpi_headline"), "cpi_core": (1, "cpi_headline"),
           "iip_yoy": (1, "iip_yoy")}  # (lag in months between period and release month, calendar key)
DAILY = {"ois_1y", "india10y", "fii_net", "dii_net"}
GRACE_BUSINESS_DAYS = 2  # retry/alert window after a scheduled release (pull keeps retrying; INGEST_FAILED after it)


def _month_end(y, m):
    return (date(y + (m == 12), m % 12 + 1, 1) - timedelta(days=1))


def expected_period(key: str, now) -> str:
    """Month-end ISO date of the latest period whose release (16:00 IST, rolled over) has passed."""
    lag, ck = MONTHLY[key]
    now = cal._ist(now)
    y, m = now.year, now.month
    if not cal.should_pull(ck, now):  # this month's release not out yet -> latest is the one released last month
        y, m = (y - 1, 12) if m == 1 else (y, m - 1)
    m -= lag
    if m <= 0:
        y, m = y - 1, m + 12
    return _month_end(y, m).isoformat()


def last_trading_day(today: date) -> date:
    d = today - timedelta(days=1)
    while d.weekday() >= 5 or d.isoformat() in cal.HOLIDAYS:
        d -= timedelta(days=1)
    return d


def in_grace(key: str, now) -> bool:
    lag, ck = MONTHLY[key]
    now = cal._ist(now)
    rd = cal.release_date(ck, now.year, now.month)
    d, n = rd, 0
    while n < GRACE_BUSINESS_DAYS:
        d += timedelta(days=1)
        if d.weekday() < 5 and d.isoformat() not in cal.HOLIDAYS:
            n += 1
    return cal.should_pull(ck, now) and now.date() <= d


def compute_is_stale(key: str, payload: dict, now=None):
    """-> (is_stale, stale_reason or None, expected or None)."""
    now = cal._ist(now or datetime.now(cal.IST))
    period = payload.get("as_of")
    if key in MONTHLY:
        exp = expected_period(key, now)
        if not period or str(period)[:7] < exp[:7]:
            extra = " (release passed; within grace, retrying)" if in_grace(key, now) else ""
            return True, f"excluded: stale (period={str(period)[:7]}, expected={exp[:7]}){extra}", exp[:7]
        return False, None, exp[:7]
    if key == "capacity_util":
        q, exp = payload.get("survey_quarter"), expected_obicus_quarter(now.date())
        return (q != exp, f"excluded: stale (period={q}, expected={exp})" if q != exp else None, exp)
    if key in DAILY:
        exp = last_trading_day(now.date() + timedelta(days=1) if now.hour >= 19 else now.date()).isoformat()
        rel = payload.get("release_date") or period
        stale = not rel or str(rel)[:10] < exp
        return stale, f"excluded: stale (period={rel}, expected={exp})" if stale else None, exp
    return None, None, None  # not covered: caller keeps cadence-age rule
