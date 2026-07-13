"""Config file loading for tracking & notifications.

Read from ~/.config/flatview/config.toml (or $XDG_CONFIG_HOME). Missing file
means defaults; a malformed file raises ConfigError. Example:

    [smtp]
    host = "smtp.gmail.com"
    port = 587
    username = "me@gmail.com"
    from = "me@gmail.com"
    to = ["me@gmail.com"]
    # password comes from the FLATVIEW_SMTP_PASSWORD env var (preferred)

    [tracking]
    delist_after_days = 2
    email_only_on_events = true
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from flatview.errors import ConfigError
from flatview.storage import default_db_path


@dataclass
class SmtpConfig:
    host: str
    port: int = 587
    username: str = ""
    password: str = ""
    from_addr: str = ""
    to_addrs: list[str] = field(default_factory=list)
    starttls: bool = True


@dataclass
class TrackingConfig:
    delist_after_days: int = 2
    digest_dir: Path | None = None
    email_only_on_events: bool = True


@dataclass
class Config:
    smtp: SmtpConfig | None = None
    tracking: TrackingConfig = field(default_factory=TrackingConfig)


def default_config_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return Path(base) / "flatview" / "config.toml"


def default_digest_dir() -> Path:
    return default_db_path().parent / "digests"


def load_config(path: Path | None = None) -> Config:
    cfg_path = path or default_config_path()
    if not cfg_path.exists():
        return Config()

    try:
        with open(cfg_path, "rb") as f:
            raw = tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError) as e:
        raise ConfigError(f"cannot read {cfg_path}: {e}") from e

    smtp: SmtpConfig | None = None
    if "smtp" in raw:
        s = raw["smtp"]
        if "host" not in s:
            raise ConfigError(f"{cfg_path}: [smtp] section requires 'host'")
        to = s.get("to", [])
        if isinstance(to, str):
            to = [to]
        smtp = SmtpConfig(
            host=s["host"],
            port=int(s.get("port", 587)),
            username=s.get("username", ""),
            password=s.get("password", ""),
            from_addr=s.get("from", ""),
            to_addrs=list(to),
            starttls=bool(s.get("starttls", True)),
        )
        env_pw = os.environ.get("FLATVIEW_SMTP_PASSWORD")
        if env_pw:
            smtp.password = env_pw

    t = raw.get("tracking", {})
    tracking = TrackingConfig(
        delist_after_days=int(t.get("delist_after_days", 2)),
        digest_dir=Path(t["digest_dir"]).expanduser() if "digest_dir" in t else None,
        email_only_on_events=bool(t.get("email_only_on_events", True)),
    )
    return Config(smtp=smtp, tracking=tracking)
