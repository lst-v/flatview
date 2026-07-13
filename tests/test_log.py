from __future__ import annotations

import logging

import pytest

from flatview.log import default_log_path, setup_logging


@pytest.fixture
def clean_root_logger():
    """Snapshot and restore root logger handlers around a test."""
    root = logging.getLogger()
    saved = root.handlers[:]
    saved_level = root.level
    root.handlers = []
    yield root
    for h in root.handlers:
        if h not in saved:
            h.close()
    root.handlers = saved
    root.setLevel(saved_level)


def test_default_log_path_respects_xdg(monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_STATE_HOME", str(tmp_path))
    assert default_log_path() == tmp_path / "flatview" / "flatview.log"


def test_setup_creates_file_handler(clean_root_logger, tmp_path):
    log_file = tmp_path / "logs" / "flatview.log"
    setup_logging(log_file=log_file)

    logging.getLogger("flatview.test").debug("hello file")
    for h in clean_root_logger.handlers:
        h.flush()

    assert log_file.exists()
    assert "hello file" in log_file.read_text()


def test_setup_is_idempotent(clean_root_logger, tmp_path):
    setup_logging(log_file=tmp_path / "a.log")
    n = len(clean_root_logger.handlers)
    setup_logging(log_file=tmp_path / "a.log")
    assert len(clean_root_logger.handlers) == n


def test_verbose_lowers_console_level(clean_root_logger, tmp_path):
    from rich.logging import RichHandler

    setup_logging(verbose=True, log_file=tmp_path / "a.log")
    console = next(h for h in clean_root_logger.handlers if isinstance(h, RichHandler))
    assert console.level == logging.DEBUG
