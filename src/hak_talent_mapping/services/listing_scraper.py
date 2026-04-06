from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from urllib.parse import urljoin

import httpx
import structlog
from bs4 import BeautifulSoup
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from hak_talent_mapping.config import Settings
from hak_talent_mapping.core.exceptions import RateLimitError, ScrapingError
from hak_talent_mapping.core.models import Company
from hak_talent_mapping.utils.http import build_async_client, random_delay

logger = structlog.get_logger()

_LISTING_PATH = "/en/companies/find-companies"

# Callback type: receives a page's worth of new companies for immediate persistence.
OnPageCallback = Callable[[list[Company]], Awaitable[None]]


def _parse_listing_page(html: str, base_url: str) -> list[Company]:
    """Parse a listing page HTML and return Company objects."""
    soup = BeautifulSoup(html, "lxml")
    companies: list[Company] = []

    for row in soup.select("table tbody tr"):
        cells = row.find_all("td")
        if len(cells) < 4:
            continue

        link = cells[0].find("a")
        if not link:
            continue

        href: str = link.get("href", "")
        # URL format: /company/{company_id}/{slug}
        parts = href.strip("/").split("/")
        if len(parts) < 3:
            continue

        companies.append(
            Company(
                company_id=parts[1],
                name=link.get_text(strip=True),
                slug=parts[2],
                sector=cells[1].get_text(strip=True),
                country=cells[2].get_text(strip=True),
                company_type=cells[3].get_text(strip=True),
                profile_url=urljoin(base_url, href),
                listing_scraped_at=datetime.now(UTC),
            )
        )

    return companies


@retry(
    retry=retry_if_exception_type(ScrapingError),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=15),
    reraise=True,
)
async def _fetch_page(
    client: httpx.AsyncClient,
    settings: Settings,
    country_code: str,
    sector: str,
    page: int,
) -> list[Company]:
    """Fetch one listing page and return parsed companies."""
    url = f"{settings.base_url}{_LISTING_PATH}"
    params: dict[str, str | int] = {
        "country": country_code,
        "sector": sector,
        "page": page,
        "pageSize": settings.results_per_page,
    }
    log = logger.bind(country=country_code, sector=sector, page=page)

    try:
        response = await client.get(url, params=params)

        if response.status_code == 429:
            log.warning("rate_limited")
            raise RateLimitError(f"Rate limited on {country_code}/{sector} page {page}")

        if response.status_code == 500:
            # Zawya intermittently 500s mid-pagination — raise ScrapingError so tenacity retries.
            # If all retries fail, the caller treats it as end-of-results.
            log.warning("server_error_retrying", page=page)
            raise ScrapingError(f"HTTP 500 on {country_code}/{sector} page {page}")

        response.raise_for_status()

        companies = _parse_listing_page(response.text, settings.base_url)
        log.info("page_fetched", company_count=len(companies))
        return companies

    except (RateLimitError, ScrapingError):
        raise
    except httpx.HTTPStatusError as exc:
        raise ScrapingError(
            f"HTTP {exc.response.status_code} on {country_code}/{sector} page {page}"
        ) from exc
    except Exception as exc:
        raise ScrapingError(
            f"Failed to fetch {country_code}/{sector} page {page}: {exc}"
        ) from exc


async def _fetch_all_pages(
    client: httpx.AsyncClient,
    country: str,
    sector: str,
    settings: Settings,
) -> list[Company]:
    """
    Paginate through all listing pages for a (country, sector) and return every company found.

    Fetches pages in concurrent batches. Stops when a full batch returns no results.
    Failed pages are skipped with a warning.
    """
    log = logger.bind(country=country, sector=sector)
    all_companies: list[Company] = []
    page = 1

    async def fetch_one(p: int) -> list[Company]:
        companies = await _fetch_page(client, settings, country, sector, p)
        await random_delay(settings.request_delay_min, settings.request_delay_max)
        return companies

    while True:
        batch = list(range(page, page + settings.listing_concurrency))
        results = await asyncio.gather(*[fetch_one(p) for p in batch], return_exceptions=True)

        batch_had_results = False
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                log.warning("page_failed_skipping", page=batch[i], error=str(result))
                continue
            if result:
                batch_had_results = True
                all_companies.extend(result)

        if not batch_had_results:
            break
        page += settings.listing_concurrency

    return all_companies


async def scrape_listings(
    country: str,
    sector: str,
    settings: Settings,
    already_scraped: set[tuple[str, str]] | None = None,
    on_page: OnPageCallback | None = None,
) -> int:
    """
    Scrape all listing pages for a (country, sector) pair. Returns count of new companies.

    Deduplicates against already_scraped and calls on_page with each batch of new companies
    so they can be persisted immediately.
    """
    log = logger.bind(country=country, sector=sector)
    scraped_ids: set[tuple[str, str]] = already_scraped or set()
    log.info("listing_scrape_started")

    async with build_async_client() as client:
        companies = await _fetch_all_pages(client, country, sector, settings)

    new_companies = [c for c in companies if (c.company_id, c.sector) not in scraped_ids]

    if on_page and new_companies:
        scraped_ids.update((c.company_id, c.sector) for c in new_companies)
        await on_page(new_companies)

    log.info("listing_scrape_complete", total=len(new_companies))
    return len(new_companies)
