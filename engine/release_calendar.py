"""Release calendar (IST). Drives language jobs + 'missed print' alerts. MPC dates: edit each FY."""
from datetime import date

# RBI MPC decision days FY2026-27 (verify against RBI's published schedule; edit when announced)
# Verified vs RBI press release 23 Mar 2026 (prid=62422) and rbi.org.in fs_overview fn=2752 (decision = last meeting day)
MPC_DATES = ["2026-04-08", "2026-06-05", "2026-08-05", "2026-10-07", "2026-12-04", "2027-02-05"]

SCHEDULE_IST = [
    # (job, cadence, IST time)
    ("rbi_policy", "MPC decision day", "10:15"),
    ("gst", "1st of month", "12:00"),
    ("usdinr_ref", "daily", "12:45"),
    ("cpi_iip", "12th of month", "16:05"),
    ("market_close", "daily", "16:00"),
    ("credit_growth", "fortnightly Friday", "18:00"),
    ("fii_dii", "daily", "18:30"),
    ("gdp", "quarterly (MOSPI calendar)", "weekly poll Mon 16:05"),
]


def language_jobs_due(d: date, force: bool = False) -> list[str]:
    jobs = []
    iso = d.isoformat()
    after_mpc = any(0 <= (d - date.fromisoformat(m)).days <= 2 for m in MPC_DATES)
    if force or after_mpc or d.weekday() == 0:  # MPC window, or weekly refresh Monday
        jobs.append("rbi_stance")
    minutes = any(13 <= (d - date.fromisoformat(m)).days <= 16 for m in MPC_DATES)
    if force or minutes:
        jobs.append("rbi_minutes_tone")
    return jobs


def cpi_release_passed(d: date) -> bool:
    return d.day >= 12


# ---- Spec 1.2: CPI/IIP release time 16:00 IST; weekend/holiday rollover to next business day.
from datetime import datetime, time, timedelta, timezone  # noqa: E402
IST = timezone(timedelta(hours=5, minutes=30))
RELEASE_DAY = {"cpi_headline": 12, "food_inflation": 12, "cpi_core": 12, "iip_yoy": 28}
RELEASE_TIME = time(16, 0)
HOLIDAYS: set[str] = set()  # filled from NSE holiday-master at runtime (official.nse_holidays); weekend rollover always applies


def release_date(key: str, year: int, month: int, holidays: set[str] | None = None) -> date:
    hol = HOLIDAYS if holidays is None else holidays
    d = date(year, month, RELEASE_DAY[key])
    while d.weekday() >= 5 or d.isoformat() in hol:
        d += timedelta(days=1)
    return d


def _ist(now):
    if isinstance(now, str):
        now = datetime.fromisoformat(now)
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    return now.astimezone(IST)


RELEASE_CALENDAR = {
    "cpi": {"day": 12, "time_ist": "16:00", "rollover": "next business day (weekend / NSE holiday)", "source": "MoSPI"},
    "iip": {"day": 28, "time_ist": "16:00", "rollover": "next business day", "source": "MoSPI"},
    "rbi_mpc": {"dates": MPC_DATES, "time_ist": "10:00", "source": "rbi.org.in fs_overview fn=2752 (scraped, verified)"},
    "obicus": {"poll": "weekly", "ingest": "only when a new publication appears", "source": "rbi.org.in PublicationsView"},
}


def scrape_mpc_dates():
    """Scrape RBI's MPC schedule; returns decision dates (last day of each meeting). Falls back to MPC_DATES."""
    import re, urllib.request
    try:
        t = urllib.request.urlopen(urllib.request.Request("https://www.rbi.org.in/scripts/fs_overview.aspx?fn=2752",
                                   headers={"User-Agent": "Mozilla/5.0"}), timeout=30).read().decode("utf-8", "ignore")
        i = t.find("Meeting Schedule of the Monetary Policy Committee")
        t = t[i:i + 3000] if i >= 0 else ""
        out = []
        for mon, days, yr in re.findall(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+([\d,\sand]+?),?\s+(20\d\d)", t):
            last = int(re.findall(r"\d+", days)[-1])
            out.append(datetime.strptime(f"{last} {mon} {yr}", "%d %B %Y").date().isoformat())
        return sorted(set(out)) or MPC_DATES
    except Exception:  # noqa: BLE001
        return MPC_DATES


def is_release_day(today) -> list[str]:
    """Daily 16:05 IST cron: the code decides what is due today."""
    due = []
    if today == release_date("cpi_headline", today.year, today.month):
        due.append("cpi")
    if today == release_date("iip_yoy", today.year, today.month):
        due.append("iip")
    if today.isoformat() in MPC_DATES:
        due.append("rbi_mpc")
    if today.weekday() == 0:
        due.append("obicus_weekly_poll")
    return due


def should_pull(key: str, now, holidays: set[str] | None = None) -> bool:
    """True once this month's official release (16:00 IST, rolled over) has happened."""
    if isinstance(now, str):
        now = datetime.fromisoformat(now)
    if now.tzinfo is None:
        now = now.replace(tzinfo=IST)
    now = now.astimezone(IST)
    rd = release_date(key, now.year, now.month, holidays)
    return now >= datetime.combine(rd, RELEASE_TIME, tzinfo=IST)
