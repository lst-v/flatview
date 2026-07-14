"""Cross-source duplicate detection (entity resolution).

The same flat is often posted on several portals, usually by the same agency.
Matching on hard attributes (area, price, city) with a soft title check is
far more reliable than the old title-similarity-only heuristic, and hard
contradictions (clearly different price or area) veto a match even when
titles look alike — agencies reuse title templates across different flats.
"""

from __future__ import annotations

from difflib import SequenceMatcher

from flatview.models import Listing

# Cross-posts are synced by agency software, so prices match exactly across
# portals; 0.5% is headroom for rounding. A looser tolerance merges different
# flats in a homogeneous market (two 52 m² flats at 109,990 vs 111,000).
PRICE_TOLERANCE = 0.005
# Portals round area differently (51.6 vs 51.9 vs 52 m²).
AREA_TOLERANCE = 0.03
# Beyond this, price/area disagreement means different flats no matter the title.
VETO_TOLERANCE = 0.10
# Title-only fallback (only when price/area data is missing on a side) must be
# near-identical and non-generic: agency templates ("SIMI real - …") and short
# generic titles ("2 izbový byt") otherwise chain different flats together.
TITLE_STRONG = 0.8
MIN_FALLBACK_TITLE_LEN = 20
TITLE_WEAK = 0.4  # minimum title similarity when area+price already match

_SOURCE_PRIORITY = {"bazos": 0, "nehnutelnosti": 1, "topreality": 2}


def _title_similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()


def _close(a: float, b: float, tolerance: float) -> bool:
    return abs(a - b) <= max(a, b) * tolerance


def is_duplicate(a: Listing, b: Listing) -> bool:
    """Heuristic: do two listings from different sources describe the same flat?"""
    if a.source == b.source:
        return False
    if a.city and b.city and a.city.lower() != b.city.lower():
        return False

    # Both sides have hard data: decide on attributes alone. Titles are too
    # unreliable here (agency templates), so they only act as a weak guard.
    if a.price and b.price and a.area and b.area:
        return (
            _close(a.price, b.price, PRICE_TOLERANCE)
            and _close(a.area, b.area, AREA_TOLERANCE)
            and _title_similarity(a.title, b.title) >= TITLE_WEAK
        )

    # Data missing on a side: conservative near-identical-title fallback,
    # vetoed by any hard contradiction in what data does exist.
    if a.price and b.price and not _close(a.price, b.price, VETO_TOLERANCE):
        return False
    if a.area and b.area and not _close(a.area, b.area, VETO_TOLERANCE):
        return False
    if min(len(a.title), len(b.title)) < MIN_FALLBACK_TITLE_LEN:
        return False
    return _title_similarity(a.title, b.title) >= TITLE_STRONG


def find_duplicate_groups(listings: list[Listing]) -> list[list[Listing]]:
    """Group listings describing the same flat; groups of one are omitted."""
    n = len(listings)
    parent = list(range(n))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(n):
        for j in range(i + 1, n):
            if is_duplicate(listings[i], listings[j]):
                parent[find(i)] = find(j)

    groups: dict[int, list[Listing]] = {}
    for i, listing in enumerate(listings):
        groups.setdefault(find(i), []).append(listing)
    return [g for g in groups.values() if len(g) > 1]


def _richness(listing: Listing) -> int:
    fields = (
        listing.price,
        listing.area,
        listing.description,
        listing.postcode,
        listing.date,
        listing.views,
    )
    return sum(1 for f in fields if f not in (None, ""))


def select_canonical(group: list[Listing]) -> Listing:
    """Pick the most informative listing of a duplicate group."""
    return max(
        group,
        key=lambda l: (_richness(l), -_SOURCE_PRIORITY.get(l.source, len(_SOURCE_PRIORITY))),
    )


def dedupe(
    listings: list[Listing],
    groups: list[list[Listing]] | None = None,
) -> list[Listing]:
    """One listing per entity: the canonical of each group plus all singletons."""
    if groups is None:
        groups = find_duplicate_groups(listings)
    drop: set[int] = set()
    for group in groups:
        keep = select_canonical(group)
        drop.update(id(l) for l in group if l is not keep)
    return [l for l in listings if id(l) not in drop]
