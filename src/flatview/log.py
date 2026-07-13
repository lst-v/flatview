"""Logging setup: rich console output plus a rotating file log.

Modules obtain loggers via ``logging.getLogger(__name__)``; the CLI calls
``setup_logging()`` once at startup.
"""

from __future__ import annotations

import logging
import os
from logging.handlers import RotatingFileHandler
from pathlib import Path

from rich.logging import RichHandler


def default_log_path() -> Path:
    """Return the default log path under XDG state home."""
    base = os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")
    return Path(base) / "flatview" / "flatview.log"


def setup_logging(*, verbose: bool = False, log_file: Path | None = None) -> None:
    """Configure root logging: rich console (INFO, DEBUG with verbose) + file (DEBUG).

    Idempotent — repeated calls do not add duplicate handlers.
    """
    root = logging.getLogger()
    if any(isinstance(h, RichHandler) for h in root.handlers):
        return

    root.setLevel(logging.DEBUG)

    console = RichHandler(show_path=False, log_time_format="[%X]")
    console.setLevel(logging.DEBUG if verbose else logging.INFO)
    console.setFormatter(logging.Formatter("%(message)s"))
    root.addHandler(console)

    path = log_file or default_log_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root.addHandler(file_handler)

    # urllib3 DEBUG is too chatty for the file log; retries still surface as WARNING.
    logging.getLogger("urllib3").setLevel(logging.INFO)
