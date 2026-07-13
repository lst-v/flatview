"""Send the digest email via SMTP (stdlib smtplib/EmailMessage)."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

from flatview.config import SmtpConfig
from flatview.errors import EmailError

logger = logging.getLogger(__name__)


def send_html_email(
    *,
    smtp: SmtpConfig,
    subject: str,
    html: str,
    text_fallback: str = "",
) -> None:
    """Send a multipart (text + HTML) email; raises EmailError on failure."""
    if not smtp.to_addrs:
        raise EmailError("smtp.to is empty — no recipients configured")

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = smtp.from_addr or smtp.username
    msg["To"] = ", ".join(smtp.to_addrs)
    msg.set_content(text_fallback or "This digest is best viewed as HTML.")
    msg.add_alternative(html, subtype="html")

    try:
        with smtplib.SMTP(smtp.host, smtp.port, timeout=30) as server:
            if smtp.starttls:
                server.starttls()
            if smtp.username:
                server.login(smtp.username, smtp.password)
            server.send_message(msg)
    except (smtplib.SMTPException, OSError) as e:
        raise EmailError(f"sending email failed: {e}") from e

    logger.info("digest email sent to %s", ", ".join(smtp.to_addrs))
