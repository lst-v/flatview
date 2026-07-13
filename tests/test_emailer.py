from __future__ import annotations

import smtplib

import pytest

from flatview.config import SmtpConfig
from flatview.emailer import send_html_email
from flatview.errors import EmailError


class FakeSMTP:
    instances: list[FakeSMTP] = []

    def __init__(self, host, port, timeout=None):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.calls: list[str] = []
        self.login_args = None
        self.message = None
        FakeSMTP.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def starttls(self):
        self.calls.append("starttls")

    def login(self, user, password):
        self.calls.append("login")
        self.login_args = (user, password)

    def send_message(self, msg):
        self.calls.append("send_message")
        self.message = msg


@pytest.fixture(autouse=True)
def fake_smtp(monkeypatch):
    FakeSMTP.instances = []
    monkeypatch.setattr("flatview.emailer.smtplib.SMTP", FakeSMTP)
    return FakeSMTP


SMTP_CFG = SmtpConfig(
    host="smtp.example.com",
    port=587,
    username="me@example.com",
    password="secret",
    from_addr="flatview@example.com",
    to_addrs=["you@example.com"],
)


def test_sends_multipart_email():
    send_html_email(smtp=SMTP_CFG, subject="test", html="<p>hi</p>", text_fallback="hi")

    (server,) = FakeSMTP.instances
    assert server.host == "smtp.example.com"
    assert server.calls == ["starttls", "login", "send_message"]
    assert server.login_args == ("me@example.com", "secret")
    assert server.message["Subject"] == "test"
    assert server.message["From"] == "flatview@example.com"
    assert server.message["To"] == "you@example.com"
    assert server.message.get_content_type() == "multipart/alternative"


def test_no_starttls_when_disabled():
    cfg = SmtpConfig(host="h", to_addrs=["a@b.c"], starttls=False)
    send_html_email(smtp=cfg, subject="s", html="<p>x</p>")
    (server,) = FakeSMTP.instances
    assert "starttls" not in server.calls
    assert "login" not in server.calls  # no username configured


def test_no_recipients_raises():
    cfg = SmtpConfig(host="h", to_addrs=[])
    with pytest.raises(EmailError, match="no recipients"):
        send_html_email(smtp=cfg, subject="s", html="x")
    assert FakeSMTP.instances == []


def test_smtp_failure_raises_email_error(monkeypatch):
    def boom(*a, **kw):
        raise smtplib.SMTPConnectError(421, "unavailable")

    monkeypatch.setattr("flatview.emailer.smtplib.SMTP", boom)
    with pytest.raises(EmailError, match="sending email failed"):
        send_html_email(smtp=SMTP_CFG, subject="s", html="x")
