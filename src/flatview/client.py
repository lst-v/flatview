from __future__ import annotations

import time

import requests


class BazosClient:
    """HTTP client for fetching bazos pages."""

    DELAY = 1.0  # seconds between requests

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "sk,cs;q=0.9,en;q=0.8",
            }
        )
        self._last_request: float = 0

    def get(self, url: str) -> str:
        """Fetch a page and return decoded HTML text."""
        elapsed = time.monotonic() - self._last_request
        if elapsed < self.DELAY and self._last_request > 0:
            time.sleep(self.DELAY - elapsed)

        resp = self._session.get(url, timeout=15)
        self._last_request = time.monotonic()
        resp.raise_for_status()

        resp.encoding = "utf-8"
        return resp.text
