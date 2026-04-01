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

# All countries available on Zawya's find-companies filter dropdown.
ZAWYA_COUNTRIES: list[tuple[str, str]] = [
    ("AE", "United Arab Emirates"),
    ("SA", "Saudi Arabia"),
    ("IN", "India"),
    ("DZ", "Algeria"),
    ("AO", "Angola"),
    ("BH", "Bahrain"),
    ("CY", "Cyprus"),
    ("EG", "Egypt"),
    ("ET", "Ethiopia"),
    ("IQ", "Iraq"),
    ("IL", "Israel"),
    ("JO", "Jordan"),
    ("KE", "Kenya"),
    ("KW", "Kuwait"),
    ("LB", "Lebanon"),
    ("MU", "Mauritius"),
    ("MA", "Morocco"),
    ("MZ", "Mozambique"),
    ("NG", "Nigeria"),
    ("OM", "Oman"),
    ("PK", "Pakistan"),
    ("QA", "Qatar"),
    ("SC", "Seychelles"),
    ("ZA", "South Africa"),
    ("TZ", "Tanzania"),
    ("TN", "Tunisia"),
    ("TR", "Turkey"),
    ("UG", "Uganda"),
]

# All sectors available on Zawya's find-companies filter dropdown.
# Values are the option `value` attributes from the <select name="sector"> dropdown.
ZAWYA_SECTORS: list[str] = [
    "Academic & Educational Services",
    "Applied Resources",
    "Automobiles & Auto Parts",
    "Banking & Investment Services",
    "Chemicals",
    "Collective Investments",
    "Energy - Fossil Fuels",
    "Financial Technology (Fintech) & Infrastructure",
    "Food & Beverages",
    "Food & Drug Retailing",
    "Government Activity",
    "Healthcare Services & Equipment",
    "Cyclical Consumer Services",      # displayed as "Hotels & Entertainment"
    "Industrial & Commercial Services",
    "Industrial Goods",
    "Institutions, Associations & Organizations",
    "Insurance",
    "Investment Holding Companies",
    "Mineral Resources",
    "Personal & Household Products & Services",
    "Pharmaceuticals & Medical Research",
    "Real Estate",
    "Renewable Energy",
    "Retailers",
    "Software & IT Services",
    "Technology Equipment",
    "Telecommunications Services",
    "Cyclical Consumer Products",      # displayed as "Textiles"
    "Transportation",
    "Utilities",
]

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


async def _scrape_pair(
    client: httpx.AsyncClient,
    settings: Settings,
    country_code: str,
    sector: str,
    already_scraped: set[tuple[str, str]],
    on_page: OnPageCallback,
) -> int:
    """
    Scrape all pages for one (country, sector) pair.

    Fetches pages in concurrent batches of `listing_concurrency`. After each batch,
    calls on_page with the new companies so they can be persisted immediately.
    Stops when a full batch returns no results (empty pages or all failures).

    Returns the total number of new companies found.
    """
    log = logger.bind(country=country_code, sector=sector)
    total = 0
    page = 1
    failed_pages: list[int] = []

    async def fetch_one(p: int) -> list[Company]:
        result = await _fetch_page(client, settings, country_code, sector, p)
        await random_delay(settings.request_delay_min, settings.request_delay_max)
        return result

    while True:
        batch = list(range(page, page + settings.listing_concurrency))
        results = await asyncio.gather(*[fetch_one(p) for p in batch], return_exceptions=True)

        batch_had_results = False
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                log.warning("page_failed_skipping", page=batch[i], error=str(result))
                failed_pages.append(batch[i])
                continue

            companies: list[Company] = result
            if not companies:
                continue

            batch_had_results = True
            new = [c for c in companies if (c.company_id, c.sector) not in already_scraped]
            if new:
                already_scraped.update((c.company_id, c.sector) for c in new)
                await on_page(new)
                total += len(new)

        if not batch_had_results:
            break
        page += settings.listing_concurrency

    if failed_pages:
        log.warning(
            "pair_complete_with_failures",
            total=total,
            failed_page_count=len(failed_pages),
            failed_pages=sorted(failed_pages),
        )
    else:
        log.info("pair_complete", total=total)
    return total


async def scrape_all_listings(
    settings: Settings,
    already_scraped: set[tuple[str, str]] | None = None,
    on_page: OnPageCallback | None = None,
) -> int:
    """
    Scrape all (country, sector) pairs and return total new companies found.

    Calls on_page after every page batch so results are persisted continuously
    rather than buffered until the end.

    Filters:
    - settings.country: scrape only that country (default: all 28)
    - settings.sector:  scrape only that sector  (default: all 21)
    """
    scraped_ids: set[tuple[str, str]] = already_scraped or set()

    if settings.country:
        name = next(
            (n for code, n in ZAWYA_COUNTRIES if code == settings.country),
            settings.country,
        )
        countries: list[tuple[str, str]] = [(settings.country, name)]
    else:
        countries = ZAWYA_COUNTRIES

    sectors = [settings.sector] if settings.sector else ZAWYA_SECTORS

    async def noop(companies: list[Company]) -> None:  # noqa: ARG001
        pass

    callback: OnPageCallback = on_page or noop

    logger.info(
        "listing_scrape_started",
        countries=len(countries),
        sectors=len(sectors),
        pairs=len(countries) * len(sectors),
        country=settings.country or "all",
        sector=settings.sector or "all",
    )

    total = 0
    async with build_async_client() as client:
        for country_code, country_name in countries:
            for sector in sectors:
                logger.info("pair_start", country=country_code, name=country_name, sector=sector)
                total += await _scrape_pair(
                    client, settings, country_code, sector, scraped_ids, callback
                )

    logger.info("listing_scrape_complete", total_companies=total)
    return total
