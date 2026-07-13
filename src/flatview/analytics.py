"""Statistics, outlier detection, and segment classification for Listings."""

from __future__ import annotations

import re
from collections.abc import Iterable

from flatview.models import Listing, Segment

_NEW_BUILD_PATTERNS = [
    re.compile(r"novostavb\w*", re.IGNORECASE),
    re.compile(r"nov[ýy]\s+projekt", re.IGNORECASE),
    re.compile(r"\bdeveloper\w*", re.IGNORECASE),
    re.compile(r"kolaud[áa]ci\w*\s+20(2[3-9]|3\d)", re.IGNORECASE),
    re.compile(r"\bnew\s+building\b", re.IGNORECASE),
]

_RESALE_PATTERNS = [
    re.compile(r"rekonštru\w*", re.IGNORECASE),
    re.compile(r"po\s+rekonštrukcii", re.IGNORECASE),
    re.compile(r"pôvodný\s+stav", re.IGNORECASE),
    re.compile(r"\bpanel\w*", re.IGNORECASE),
    re.compile(r"zachovalý", re.IGNORECASE),
]

_RESALE_OVERRIDE = re.compile(r"po\s+rekonštrukcii", re.IGNORECASE)


# Sellers use token prices ("1 €") as reservation/negotiation placeholders;
# treating them as real prices poisons stats and bargain detection.
PLACEHOLDER_PRICE_MAX = 1.0


def has_real_price(listing: Listing) -> bool:
    return listing.price is not None and listing.price > PLACEHOLDER_PRICE_MAX


def price_per_m2(listing: Listing) -> float | None:
    if (
        listing.price is not None
        and listing.price > PLACEHOLDER_PRICE_MAX
        and listing.area
        and listing.area > 0
    ):
        return listing.price / listing.area
    return None


def cheapest_by_pm2(listings: list[Listing], n: int = 5) -> list[Listing]:
    """The n listings with the lowest valid €/m², ascending."""
    priced = [(pm2, l) for l in listings if (pm2 := price_per_m2(l)) is not None]
    priced.sort(key=lambda pair: pair[0])
    return [l for _, l in priced[:n]]


def compute_percentiles(
    values: list[float], pcts: Iterable[int] = (10, 25, 50, 75, 90)
) -> dict[int, float]:
    if not values:
        return {}
    s = sorted(values)
    n = len(s)
    result: dict[int, float] = {}
    for p in pcts:
        if n == 1:
            result[p] = s[0]
            continue
        # Linear interpolation, NumPy-style "linear" method.
        rank = (p / 100) * (n - 1)
        lo = int(rank)
        hi = min(lo + 1, n - 1)
        frac = rank - lo
        result[p] = s[lo] + (s[hi] - s[lo]) * frac
    return result


def _basic_stats(values: list[float]) -> dict:
    if not values:
        return {"n": 0}
    pcts = compute_percentiles(values)
    return {
        "n": len(values),
        "avg": sum(values) / len(values),
        "min": min(values),
        "max": max(values),
        "p10": pcts[10],
        "p25": pcts[25],
        "p50": pcts[50],
        "p75": pcts[75],
        "p90": pcts[90],
    }


def compute_stats(listings: list[Listing], *, exclude_outliers: bool = False) -> dict:
    """Return overall stats for price and €/m²."""
    pool = [l for l in listings if not (exclude_outliers and l.is_outlier)]
    prices = [l.price for l in pool if l.price is not None and l.price > PLACEHOLDER_PRICE_MAX]
    pm2s = [v for v in (price_per_m2(l) for l in pool) if v is not None]
    currency = next((l.currency for l in pool if has_real_price(l)), "EUR")
    return {
        "currency": currency,
        "n_total": len(pool),
        "price": _basic_stats(prices),
        "pm2": _basic_stats(pm2s),
    }


def flag_outliers_iqr(listings: list[Listing], k: float = 1.5) -> tuple[int, int]:
    """Mark listings as outliers based on €/m² IQR fence.

    Sets `outlier_side` to "bargain" (below the low fence) or "overpriced"
    (above the high fence). Returns (n_flagged, n_considered). Skips when
    fewer than 4 listings have both price and area.
    """
    for l in listings:
        l.is_outlier = False
        l.outlier_side = None

    pm2_pairs = [(l, v) for l in listings if (v := price_per_m2(l)) is not None]
    n = len(pm2_pairs)
    if n < 4:
        return 0, n

    values = sorted(v for _, v in pm2_pairs)
    pcts = compute_percentiles(values, (25, 75))
    q1, q3 = pcts[25], pcts[75]
    iqr = q3 - q1
    low, high = q1 - k * iqr, q3 + k * iqr

    flagged = 0
    for l, v in pm2_pairs:
        if v < low:
            l.is_outlier = True
            l.outlier_side = "bargain"
            flagged += 1
        elif v > high:
            l.is_outlier = True
            l.outlier_side = "overpriced"
            flagged += 1
    return flagged, n


def iqr_fence(listings: list[Listing], k: float = 1.5) -> tuple[float, float] | None:
    """Return the (low, high) €/m² fence used by flag_outliers_iqr, if computable."""
    vals = sorted(v for v in (price_per_m2(l) for l in listings) if v is not None)
    if len(vals) < 4:
        return None
    pcts = compute_percentiles(vals, (25, 75))
    q1, q3 = pcts[25], pcts[75]
    iqr = q3 - q1
    return q1 - k * iqr, q3 + k * iqr


def classify_segment(listing: Listing) -> Segment:
    haystack = " ".join(filter(None, [listing.title, listing.description or ""]))
    if not haystack.strip():
        return "unknown"

    is_resale = any(p.search(haystack) for p in _RESALE_PATTERNS)
    is_new = any(p.search(haystack) for p in _NEW_BUILD_PATTERNS)

    # Explicit "po rekonštrukcii" wins even if other new-build markers are present.
    if _RESALE_OVERRIDE.search(haystack):
        return "resale"
    if is_new:
        return "new"
    if is_resale:
        return "resale"
    return "unknown"


def annotate_segments(listings: list[Listing]) -> None:
    for l in listings:
        l.segment = classify_segment(l)


def stats_by_segment(
    listings: list[Listing], *, exclude_outliers: bool = False, min_n: int = 3
) -> dict[str, dict]:
    """Return per-segment stats, only including segments with at least min_n listings."""
    by_seg: dict[str, list[Listing]] = {}
    for l in listings:
        by_seg.setdefault(l.segment, []).append(l)
    out: dict[str, dict] = {}
    for seg, group in by_seg.items():
        if len(group) < min_n:
            continue
        out[seg] = compute_stats(group, exclude_outliers=exclude_outliers)
    return out
