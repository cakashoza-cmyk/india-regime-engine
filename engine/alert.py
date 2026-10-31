"""Module 5 — Alerting. Telegram + email; skips cleanly if secrets absent. Alerts only on change/failure."""
from __future__ import annotations
import json, os, smtplib, urllib.parse, urllib.request
from email.message import EmailMessage


def compose(snap: dict, failures: list) -> str | None:
    d = snap["detail"]
    lines = []
    if d.get("change") != "no change":
        lines.append(f"Regime change: {d.get('change')} (stage {snap['stage']})")
    trig = [x["rule"] for x in snap.get("invalidation_conditions") or [] if x["status"] == "triggered"]
    if trig:
        lines.append("Invalidation triggered: " + ", ".join(trig))
    if failures:
        lines.append("Source failures (stale carried): " + ", ".join(failures))
    if not lines:
        return None  # default output is 'no change' -> no alert
    lines.append(snap.get("sizing_recommendation") or "")
    return "Macro Regime Engine\n" + "\n".join(lines)


def send(text: str) -> list[str]:
    sent = []
    tok, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if tok and chat:
        data = urllib.parse.urlencode({"chat_id": chat, "text": text[:4000]}).encode()
        urllib.request.urlopen(f"https://api.telegram.org/bot{tok}/sendMessage", data=data, timeout=30)
        sent.append("telegram")
    host, to = os.environ.get("SMTP_HOST"), os.environ.get("ALERT_EMAIL_TO")
    if host and to:
        m = EmailMessage(); m["Subject"] = "Macro Regime Engine alert"; m["To"] = to
        m["From"] = os.environ.get("SMTP_USER", to); m.set_content(text)
        with smtplib.SMTP(host, int(os.environ.get("SMTP_PORT", "587")), timeout=30) as s:
            s.starttls()
            if os.environ.get("SMTP_USER"):
                s.login(os.environ["SMTP_USER"], os.environ.get("SMTP_PASS", ""))
            s.send_message(m)
        sent.append("email")
    return sent


def run(snap, failures):
    text = compose(snap, failures)
    if not text:
        return {"sent": [], "text": None, "note": "no change — nothing sent"}
    try:
        return {"sent": send(text), "text": text, "note": "skipped: no TELEGRAM_*/SMTP_* secrets" if not (os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("SMTP_HOST")) else None}
    except Exception as e:  # noqa: BLE001
        return {"sent": [], "text": text, "note": f"alert send failed: {e}"}
