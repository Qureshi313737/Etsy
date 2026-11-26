"""Daily summary delivery: Telegram bot (free) and/or email via SMTP (e.g. Gmail app password)."""
from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from .config import Config
from .http import ApiError, HttpClient

log = logging.getLogger(__name__)


def send_telegram(cfg: Config, text: str) -> bool:
    if not (cfg.get("notify.telegram") and cfg.has("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")):
        return False
    http = HttpClient(qps=1.0)
    url = f"https://api.telegram.org/bot{cfg.secret('TELEGRAM_BOT_TOKEN')}/sendMessage"
    chunks = [text[i:i + 3900] for i in range(0, len(text), 3900)] or [""]
    try:
        for chunk in chunks:
            http.request("POST", url, json={"chat_id": cfg.secret("TELEGRAM_CHAT_ID"), "text": chunk,
                                            "disable_web_page_preview": True})
        return True
    except ApiError as exc:
        log.warning("Telegram send failed: %s", exc)
        return False


def send_email(cfg: Config, subject: str, text: str, html: str | None = None) -> bool:
    if not (cfg.get("notify.email") and cfg.has("SMTP_HOST", "SMTP_USER", "SMTP_PASSWORD", "REPORT_EMAIL_TO")):
        return False
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = cfg.secret("SMTP_USER")
    msg["To"] = cfg.secret("REPORT_EMAIL_TO")
    msg.set_content(text)
    if html:
        msg.add_alternative(html, subtype="html")
    try:
        with smtplib.SMTP(cfg.secret("SMTP_HOST"), int(cfg.secret("SMTP_PORT") or 587), timeout=30) as s:
            s.starttls()
            s.login(cfg.secret("SMTP_USER"), cfg.secret("SMTP_PASSWORD"))
            s.send_message(msg)
        return True
    except (smtplib.SMTPException, OSError) as exc:
        log.warning("Email send failed: %s", exc)
        return False
