"""Custom exception types for flatview."""

from __future__ import annotations


class FlatviewError(Exception):
    """Base class for all flatview errors."""


class ScrapeError(FlatviewError):
    """A portal scrape failed (network, parse, or structure drift)."""


class ConfigError(FlatviewError):
    """The config file is missing required values or malformed."""


class EmailError(FlatviewError):
    """Sending the digest email failed."""
