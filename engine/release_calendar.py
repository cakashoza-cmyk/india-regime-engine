"""Release calendar (IST). Drives language jobs + 'missed print' alerts. MPC dates: edit each FY."""
from datetime import date

# RBI MPC decision days FY2026-27 (verify against RBI's published schedule; edit when announced)
MPC_DATES = ["2026-04-08", "2026-06-05", "2026-08-07", "2026-10-07", "2026-12-04", "2027-02-05"]

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
