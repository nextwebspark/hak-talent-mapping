from __future__ import annotations

import asyncio
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


def _parse_listing_page(html: str, base_url: str) -> list[Company]:
    """Parse HTML from a listing page and return Company objects."""
    soup = BeautifulSoup(html, "lxml")
    companies: list[Company] = []

    rows = soup.select("table tbody tr")
    for row in rows:
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

        company_id = parts[1]
        slug = parts[2]

        companies.append(
            Company(
                company_id=company_id,
                name=link.get_text(strip=True),
                slug=slug,
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
    page: int,
) -> list[Company]:
    """Fetch a single listing page and return parsed companies."""
    url = f"{settings.base_url}{_LISTING_PATH}"
    params: dict[str, str | int] = {
        "country": settings.country,
        "sector": settings.sector,
        "page": page,
    }
    log = logger.bind(page=page)

    try:
        response = await client.get(url, params=params)

        if response.status_code == 429:
            log.warning("rate_limited", page=page)
            raise RateLimitError(f"Rate limited on page {page}")

        response.raise_for_status()

        companies = _parse_listing_page(response.text, settings.base_url)
        log.info("page_fetched", company_count=len(companies))
        return companies

    except RateLimitError:
        raise
    except httpx.HTTPStatusError as exc:
        raise ScrapingError(
            f"HTTP {exc.response.status_code} on page {page}"
        ) from exc
    except Exception as exc:
        raise ScrapingError(f"Failed to fetch listing page {page}: {exc}") from exc


async def scrape_all_listings(
    settings: Settings,
    already_scraped: set[str] | None = None,
) -> list[Company]:
    """
    Scrape all listing pages concurrently and return every Company found.

    Pass already_scraped IDs to skip pages whose companies are already stored
    (note: we still fetch the page; filtering happens after parsing).
    """
    semaphore = asyncio.Semaphore(settings.listing_concurrency)
    all_companies: list[Company] = []
    failed_pages: list[int] = []

    async def fetch_with_semaphore(
        client: httpx.AsyncClient, page: int
    ) -> list[Company]:
        async with semaphore:
            result = await _fetch_page(client, settings, page)
            await random_delay(settings.request_delay_min, settings.request_delay_max)
            return result

    logger.info(
        "listing_scrape_started",
        total_pages=settings.total_pages,
        concurrency=settings.listing_concurrency,
    )

    async with build_async_client() as client:
        tasks = [
            fetch_with_semaphore(client, page)
            for page in range(1, settings.total_pages + 1)
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

    for page_num, result in enumerate(results, start=1):
        if isinstance(result, Exception):
            logger.error("page_failed", page=page_num, error=str(result))
            failed_pages.append(page_num)
        else:
            companies = result
            if already_scraped:
                companies = [
                    c for c in companies if c.company_id not in already_scraped
                ]
            all_companies.extend(companies)

    logger.info(
        "listing_scrape_complete",
        total_companies=len(all_companies),
        failed_pages=len(failed_pages),
    )

    if failed_pages:
        logger.warning("some_pages_failed", pages=failed_pages)

    return all_companies
