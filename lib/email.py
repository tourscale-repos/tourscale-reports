"""SMTP email sender — uses Gmail-style SMTP via env vars."""
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart


def send(
    *,
    subject: str,
    html: str,
    to: list[str],
    cc: list[str] | None = None,
    from_addr: str | None = None,
    smtp_host: str | None = None,
    smtp_port: int | None = None,
    smtp_user: str | None = None,
    smtp_pass: str | None = None,
):
    """Send an HTML email via SMTP. Reads from env if args omitted.

    Env vars: REPORTS_SMTP_HOST, REPORTS_SMTP_PORT, REPORTS_SMTP_USER,
    REPORTS_SMTP_PASS, REPORTS_FROM_EMAIL.
    """
    smtp_host = smtp_host or os.environ.get("REPORTS_SMTP_HOST", "smtp.gmail.com")
    smtp_port = smtp_port or int(os.environ.get("REPORTS_SMTP_PORT", "587"))
    smtp_user = smtp_user or os.environ["REPORTS_SMTP_USER"]
    smtp_pass = smtp_pass or os.environ["REPORTS_SMTP_PASS"]
    from_addr = from_addr or os.environ.get("REPORTS_FROM_EMAIL", smtp_user)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)

    msg.attach(MIMEText(html, "html"))

    rcpts = list(to) + list(cc or [])
    with smtplib.SMTP(smtp_host, smtp_port) as s:
        s.starttls()
        s.login(smtp_user, smtp_pass)
        s.sendmail(from_addr, rcpts, msg.as_string())
