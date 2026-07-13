from __future__ import annotations

import logging
import time

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class BazosClient:
    """HTTP client with rate limiting and retry/backoff, shared by all portals."""

    def __init__(self, *, timeout: float = 15.0, delay: float = 1.0, retries: int = 3) -> None:
        self._timeout = timeout
        self._delay = delay
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
        retry = Retry(
            total=retries,
            backoff_factor=1.5,
            status_forcelist=(429, 500, 502, 503, 504),
            allowed_methods=frozenset({"GET"}),
        )
        adapter = HTTPAdapter(max_retries=retry)
        self._session.mount("https://", adapter)
        self._session.mount("http://", adapter)
        self._last_request: float = 0

    def get(self, url: str) -> str:
        """Fetch a page and return decoded HTML text."""
        elapsed = time.monotonic() - self._last_request
        if elapsed < self._delay and self._last_request > 0:
            time.sleep(self._delay - elapsed)

        logger.debug("GET %s", url)
        resp = self._session.get(url, timeout=self._timeout)
        self._last_request = time.monotonic()
        resp.raise_for_status()

        resp.encoding = "utf-8"
        return resp.text
