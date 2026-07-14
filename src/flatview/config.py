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
    backup_keep = 7                # daily DB backups to keep (0 disables)
    # healthcheck_url = "https://hc-ping.com/<uuid>"  # pinged after every track run

    [analytics]
    iqr_k = 1.5            # outlier fence multiplier; lower = more sensitive
    cma_area_band = 0.25   # CMA comparables within ±25% of the target area

    [ntfy]
    topic = "flatview-abc123"          # subscribe to this topic in the ntfy app
    # server = "https://ntfy.sh"       # or a self-hosted instance
    # token comes from the FLATVIEW_NTFY_TOKEN env var (or `token = ...` here)
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
class NtfyConfig:
    topic: str
    server: str = "https://ntfy.sh"
    token: str = ""  # access token for protected topics / self-hosted servers


@dataclass
class TrackingConfig:
    delist_after_days: int = 2
    digest_dir: Path | None = None
    email_only_on_events: bool = True
    backup_keep: int = 7  # daily DB backups to keep; 0 disables backups
    healthcheck_url: str = ""  # e.g. healthchecks.io ping URL; "" disables


@dataclass
class AnalyticsConfig:
    iqr_k: float = 1.5  # IQR fence multiplier for two-sided outliers
    cma_area_band: float = 0.25  # comparables within ±band of the CMA target area


@dataclass
class Config:
    smtp: SmtpConfig | None = None
    ntfy: NtfyConfig | None = None
    tracking: TrackingConfig = field(default_factory=TrackingConfig)
    analytics: AnalyticsConfig = field(default_factory=AnalyticsConfig)


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

    ntfy: NtfyConfig | None = None
    if "ntfy" in raw:
        n = raw["ntfy"]
        if "topic" not in n:
            raise ConfigError(f"{cfg_path}: [ntfy] section requires 'topic'")
        ntfy = NtfyConfig(
            topic=n["topic"],
            server=str(n.get("server", "https://ntfy.sh")).rstrip("/"),
            token=n.get("token", ""),
        )
        env_token = os.environ.get("FLATVIEW_NTFY_TOKEN")
        if env_token:
            ntfy.token = env_token

    t = raw.get("tracking", {})
    tracking = TrackingConfig(
        delist_after_days=int(t.get("delist_after_days", 2)),
        digest_dir=Path(t["digest_dir"]).expanduser() if "digest_dir" in t else None,
        email_only_on_events=bool(t.get("email_only_on_events", True)),
        backup_keep=int(t.get("backup_keep", 7)),
        healthcheck_url=str(t.get("healthcheck_url", "")),
    )
    if tracking.backup_keep < 0:
        raise ConfigError(f"{cfg_path}: tracking.backup_keep must be >= 0")

    a = raw.get("analytics", {})
    analytics = AnalyticsConfig(
        iqr_k=float(a.get("iqr_k", 1.5)),
        cma_area_band=float(a.get("cma_area_band", 0.25)),
    )
    if analytics.iqr_k <= 0:
        raise ConfigError(f"{cfg_path}: analytics.iqr_k must be > 0")
    if not 0 < analytics.cma_area_band <= 1:
        raise ConfigError(f"{cfg_path}: analytics.cma_area_band must be in (0, 1]")

    return Config(smtp=smtp, ntfy=ntfy, tracking=tracking, analytics=analytics)
