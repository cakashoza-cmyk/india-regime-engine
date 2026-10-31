"""Local always-on scheduler (APScheduler). GitHub Actions cron is the free hosted equivalent."""
from apscheduler.schedulers.blocking import BlockingScheduler
from engine import pipeline

s = BlockingScheduler(timezone="Asia/Kolkata")
for hh, mm, days in [(10, 15, "mon-fri"), (12, 45, "mon-fri"), (16, 5, "mon-fri"), (18, 30, "mon-fri")]:
    s.add_job(pipeline.run, "cron", day_of_week=days, hour=hh, minute=mm)
s.add_job(pipeline.run, "cron", day=1, hour=12, minute=0)  # GST day
if __name__ == "__main__":
    s.start()
