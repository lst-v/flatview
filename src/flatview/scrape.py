"""Portal scraping decoupled from the CLI.

`SearchParams` captures everything a scrape needs so both `flatview search`
and the tracking pipeline can invoke portals without going through argparse.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

import requests
from requests import HTTPError

from flatview.client import BazosClient
from flatview.models import Listing, SearchResult
from flatview.nehnutelnosti_parser import (
    parse_nehnutelnosti_listings,
    parse_nehnutelnosti_total_count,
)
from flatview.nehnutelnosti_urls import build_nehnutelnosti_url
from flatview.parser import parse_detail, parse_listings, parse_total_count
from flatview.topreality_parser import (
    parse_topreality_listings,
    parse_topreality_total_count,
)
from flatview.topreality_urls import build_topreality_url, resolve_location
from flatview.urls import build_search_url

logger = logging.getLogger(__name__)

SOURCES = ("bazos", "nehnutelnosti", "topreality")


@dataclass(frozen=True)
class SearchParams:
    """Plain-data search parameters, mirroring the `search` CLI flags 1:1."""

    query: str = ""
    source: str = "bazos"  # bazos | nehnutelnosti | topreality | all
    site: str = "bazos.sk"
    category: str = "reality"
    subcategory: str = ""
    location: str = ""
    radius: int = 25
    strict_location: bool = False
    zip_code: str = ""
    price_from: int | None = None
    price_to: int | None = None
    title_filter: str = ""
    pages: int | None = None  # None → all pages if no query, else 1


def resolve_max_pages(params: SearchParams) -> int:
    """0 means all pages. Default: all pages for browse (no query), 1 with a query."""
    if params.pages is not None:
        return params.pages
    return 0 if not params.query else 1


def scrape(params: SearchParams, client: BazosClient | None = None) -> list[SearchResult]:
    """Scrape the portal(s) selected by params.source and return one result per portal."""
    client = client or BazosClient()
    results: list[SearchResult] = []
    if params.source in ("bazos", "all"):
        results.append(scrape_bazos(params, client))
    if params.source in ("nehnutelnosti", "all"):
        results.append(scrape_nehnutelnosti(params, client))
    if params.source in ("topreality", "all"):
        results.append(scrape_topreality(params, client))
    return results


def _filter_regex(params: SearchParams) -> re.Pattern | None:
    return re.compile(params.title_filter, re.IGNORECASE) if params.title_filter else None


def _apply_filters(
    listings: list[Listing],
    params: SearchParams,
    filter_re: re.Pattern | None,
    *,
    strict_location: bool = True,
    zip_filter: bool = True,
) -> list[Listing]:
    """Apply post-parse filters. Portals without postcode data disable zip_filter."""
    if strict_location and params.strict_location and params.location:
        loc = params.location.lower()
        listings = [l for l in listings if l.city.lower() == loc]
    if zip_filter and params.zip_code:
        zip_norm = params.zip_code.replace(" ", "")
        listings = [l for l in listings if l.postcode.replace(" ", "") == zip_norm]
    if filter_re:
        listings = [l for l in listings if filter_re.search(l.title)]
    return listings


def _warn_if_drift(source: str, n_parsed: int, total_count: int | None) -> None:
    """Heuristic: HTTP 200 but nothing parsed usually means the HTML changed."""
    if n_parsed == 0 and (total_count is None or total_count > 0):
        logger.warning(
            "%s: HTTP 200 but 0 listings parsed (total_count=%s) — page structure may have changed",
            source,
            total_count,
        )


def scrape_bazos(params: SearchParams, client: BazosClient) -> SearchResult:
    max_pages = resolve_max_pages(params)
    filter_re = _filter_regex(params)
    result = SearchResult(
        query=params.query,
        category=params.category,
        location=params.location,
        site=params.site,
    )

    page = 0
    while max_pages == 0 or page < max_pages:
        url = build_search_url(
            category=params.category,
            site=params.site,
            subcategory=params.subcategory,
            query=params.query,
            location=params.location,
            radius=params.radius,
            price_from=params.price_from,
            price_to=params.price_to,
            page=page,
        )

        logger.info("bazos: fetching page %d… %s", page + 1, url)

        try:
            html = client.get(url)
        except HTTPError as e:
            if e.response is not None and e.response.status_code == 404:
                break
            logger.error("bazos: error fetching page %d: %s", page + 1, e)
            break
        except requests.RequestException as e:
            logger.error("bazos: error fetching page %d: %s", page + 1, e)
            break

        if page == 0:
            result.total_count = parse_total_count(html)

        listings = parse_listings(html, site=params.site)
        if not listings:
            if page == 0:
                _warn_if_drift("bazos", 0, result.total_count)
            break

        listings = _apply_filters(listings, params, filter_re)
        result.listings.extend(listings)
        page += 1

    # Fetch detail pages for m² data
    total = len(result.listings)
    if total:
        logger.info("bazos: fetching detail pages for m² data (%d listings)…", total)
    for i, listing in enumerate(result.listings, 1):
        if not listing.url:
            continue
        # Fix subdomain: detail URLs default to www.bazos.xx but need category subdomain
        listing.url = listing.url.replace(
            f"://www.{params.site}", f"://{params.category}.{params.site}"
        )
        detail_url = listing.url
        logger.debug("bazos: detail %d/%d… %s", i, total, detail_url)
        try:
            detail_html = client.get(detail_url)
        except requests.RequestException as e:
            logger.warning("bazos: detail fetch failed for %s: %s", detail_url, e)
            continue
        area, description = parse_detail(detail_html)
        if area:
            listing.area = area
        if description:
            listing.description = description

    return result


def scrape_nehnutelnosti(params: SearchParams, client: BazosClient) -> SearchResult:
    max_pages = resolve_max_pages(params)
    filter_re = _filter_regex(params)

    if params.category != "reality":
        logger.warning(
            "nehnutelnosti.sk only covers real estate; --category '%s' ignored.",
            params.category,
        )
    if params.zip_code:
        logger.warning("--zip filter not supported for nehnutelnosti.sk (no postcode data).")

    result = SearchResult(
        query=params.query,
        category="reality",
        location=params.location,
        site="nehnutelnosti.sk",
    )

    page = 1
    pages_fetched = 0
    while max_pages == 0 or pages_fetched < max_pages:
        url = build_nehnutelnosti_url(
            query=params.query,
            subcategory=params.subcategory,
            location=params.location,
            price_from=params.price_from,
            price_to=params.price_to,
            page=page,
        )

        logger.info("nehnutelnosti: fetching page %d… %s", page, url)

        try:
            html = client.get(url)
        except requests.RequestException as e:
            logger.error("nehnutelnosti: error fetching page %d: %s", page, e)
            break

        if pages_fetched == 0:
            result.total_count = parse_nehnutelnosti_total_count(html)

        listings = parse_nehnutelnosti_listings(html)
        if not listings:
            if pages_fetched == 0:
                _warn_if_drift("nehnutelnosti", 0, result.total_count)
            break

        if params.location:
            for listing in listings:
                if not listing.city:
                    listing.city = params.location

        listings = _apply_filters(
            listings, params, filter_re, strict_location=False, zip_filter=False
        )
        result.listings.extend(listings)
        pages_fetched += 1
        page += 1

    return result


def scrape_topreality(params: SearchParams, client: BazosClient) -> SearchResult:
    max_pages = resolve_max_pages(params)
    filter_re = _filter_regex(params)

    if params.category != "reality":
        logger.warning(
            "topreality.sk only covers real estate; --category '%s' ignored.",
            params.category,
        )
    if params.zip_code:
        logger.warning("--zip filter not supported for topreality.sk (no postcode data).")

    result = SearchResult(
        query=params.query,
        category="reality",
        location=params.location,
        site="topreality.sk",
    )

    # Resolve location name to topreality district ID
    location_id = ""
    if params.location:
        logger.info("topreality: resolving location for '%s'…", params.location)
        location_id = resolve_location(params.location)
        if location_id:
            logger.debug("topreality: resolved to %s", location_id)
        else:
            logger.warning("topreality: could not resolve location '%s'", params.location)

    page = 1
    pages_fetched = 0
    while max_pages == 0 or pages_fetched < max_pages:
        url = build_topreality_url(
            query=params.query,
            subcategory=params.subcategory,
            location_id=location_id,
            price_from=params.price_from,
            price_to=params.price_to,
            page=page,
        )

        logger.info("topreality: fetching page %d… %s", page, url)

        try:
            html = client.get(url)
        except requests.RequestException as e:
            logger.error("topreality: error fetching page %d: %s", page, e)
            break

        if pages_fetched == 0:
            result.total_count = parse_topreality_total_count(html)

        listings = parse_topreality_listings(html)
        if not listings:
            if pages_fetched == 0:
                _warn_if_drift("topreality", 0, result.total_count)
            break

        if params.location:
            for listing in listings:
                if not listing.city:
                    listing.city = params.location

        listings = _apply_filters(listings, params, filter_re, zip_filter=False)
        result.listings.extend(listings)
        pages_fetched += 1
        page += 1

    return result
