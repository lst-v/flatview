from __future__ import annotations

import pytest

from flatview.config import default_config_path, load_config
from flatview.errors import ConfigError

FULL_TOML = """
[smtp]
host = "smtp.example.com"
port = 465
username = "me@example.com"
password = "file-secret"
from = "flatview@example.com"
to = ["me@example.com", "agent@example.com"]
starttls = false

[tracking]
delist_after_days = 5
digest_dir = "~/digests"
email_only_on_events = false

[ntfy]
topic = "flatview-test"
"""


def test_missing_file_returns_defaults(tmp_path):
    cfg = load_config(tmp_path / "nope.toml")
    assert cfg.smtp is None
    assert cfg.tracking.delist_after_days == 2
    assert cfg.tracking.digest_dir is None
    assert cfg.tracking.email_only_on_events is True


def test_full_config_parsed(tmp_path, monkeypatch):
    monkeypatch.delenv("FLATVIEW_SMTP_PASSWORD", raising=False)
    path = tmp_path / "config.toml"
    path.write_text(FULL_TOML)

    cfg = load_config(path)
    assert cfg.smtp is not None
    assert cfg.smtp.host == "smtp.example.com"
    assert cfg.smtp.port == 465
    assert cfg.smtp.password == "file-secret"
    assert cfg.smtp.from_addr == "flatview@example.com"
    assert cfg.smtp.to_addrs == ["me@example.com", "agent@example.com"]
    assert cfg.smtp.starttls is False
    assert cfg.tracking.delist_after_days == 5
    assert cfg.tracking.digest_dir is not None
    assert cfg.tracking.digest_dir.name == "digests"
    assert cfg.tracking.email_only_on_events is False


def test_ntfy_defaults_and_full(tmp_path, monkeypatch):
    monkeypatch.delenv("FLATVIEW_NTFY_TOKEN", raising=False)
    path = tmp_path / "config.toml"
    path.write_text(FULL_TOML)
    cfg = load_config(path)
    assert cfg.ntfy is not None
    assert cfg.ntfy.topic == "flatview-test"
    assert cfg.ntfy.server == "https://ntfy.sh"
    assert cfg.ntfy.token == ""

    path.write_text(
        '[ntfy]\ntopic = "t"\nserver = "https://ntfy.example.com/"\ntoken = "tk_file"\n'
    )
    cfg = load_config(path)
    assert cfg.ntfy is not None
    assert cfg.ntfy.server == "https://ntfy.example.com"  # trailing slash stripped
    assert cfg.ntfy.token == "tk_file"


def test_ntfy_missing_topic_raises(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[ntfy]\nserver = "https://ntfy.sh"\n')
    with pytest.raises(ConfigError, match="topic"):
        load_config(path)


def test_ntfy_token_env_override(tmp_path, monkeypatch):
    monkeypatch.setenv("FLATVIEW_NTFY_TOKEN", "tk_env")
    path = tmp_path / "config.toml"
    path.write_text('[ntfy]\ntopic = "t"\ntoken = "tk_file"\n')
    cfg = load_config(path)
    assert cfg.ntfy is not None
    assert cfg.ntfy.token == "tk_env"


def test_no_ntfy_section(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[smtp]\nhost = "h"\n')
    assert load_config(path).ntfy is None


def test_env_var_overrides_password(tmp_path, monkeypatch):
    monkeypatch.setenv("FLATVIEW_SMTP_PASSWORD", "env-secret")
    path = tmp_path / "config.toml"
    path.write_text(FULL_TOML)

    cfg = load_config(path)
    assert cfg.smtp is not None
    assert cfg.smtp.password == "env-secret"


def test_to_as_single_string(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[smtp]\nhost = "h"\nto = "one@example.com"\n')
    cfg = load_config(path)
    assert cfg.smtp is not None
    assert cfg.smtp.to_addrs == ["one@example.com"]


def test_malformed_toml_raises(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text("[smtp\nhost =")
    with pytest.raises(ConfigError):
        load_config(path)


def test_smtp_without_host_raises(tmp_path):
    path = tmp_path / "config.toml"
    path.write_text('[smtp]\nusername = "x"\n')
    with pytest.raises(ConfigError, match="host"):
        load_config(path)


def test_default_config_path_respects_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert default_config_path() == tmp_path / "flatview" / "config.toml"
