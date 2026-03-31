from __future__ import annotations

import asyncio
import re
from datetime import UTC, datetime

import structlog
from bs4 import BeautifulSoup
from playwright.async_api import Browser, BrowserContext, async_playwright

from hak_talent_mapping.config import Settings
from hak_talent_mapping.core.exceptions import ScrapingError
from hak_talent_mapping.core.models import CompanyDetail
from hak_talent_mapping.utils.http import random_delay

logger = structlog.get_logger()

# Maps lowercase label text (as it appears on the page) → CompanyDetail field
_LABEL_MAP: dict[str, str] = {
    "country of incorporation": "country_of_incorporation",
    "incorporation date": "incorporation_date",
    "business sector": "sector_detail",
    "company address": "address",
    "number of employees": "employees_count",
    "employees": "employees_count",
    "website": "website",
    "phone": "phone",
    "email": "email",
}

# Labels that signal the start of the business description block
_DESCRIPTION_HEADERS = {"business summary", "about", "company overview", "overview"}


def _extract_detail(inner_text: str, html: str) -> CompanyDetail:
    """
    Extract company detail fields from the page's innerText.

    Zawya renders label/value pairs on consecutive lines, e.g.:
        Business Summary
        Emirates Stallions Group is …
        Country of Incorporation
        United Arab Emirates
        Incorporation Date
        2008-07-22
    """
    detail: CompanyDetail = {}
    lines = [ln.strip() for ln in inner_text.splitlines() if ln.strip()]

    i = 0
    while i < len(lines):
        label_lower = lines[i].lower()

        # Description block — consume all lines until the next known label
        if label_lower in _DESCRIPTION_HEADERS:
            desc_lines: list[str] = []
            j = i + 1
            while j < len(lines):
                next_lower = lines[j].lower()
                if next_lower in _LABEL_MAP or next_lower in _DESCRIPTION_HEADERS:
                    break
                # Stop at boilerplate gates
                if "get access" in next_lower or "sign up" in next_lower:
                    break
                desc_lines.append(lines[j])
                j += 1
            if desc_lines:
                detail["description"] = " ".join(desc_lines)
            i = j
            continue

        # Known label → next line is the value
        if label_lower in _LABEL_MAP and i + 1 < len(lines):
            field = _LABEL_MAP[label_lower]
            value = lines[i + 1]

            if field == "incorporation_date":
                # Store full date; also extract founded_year
                match = re.search(r"\b(19\d{2}|20[0-2]\d)\b", value)
                if match:
                    detail["founded_year"] = int(match.group(0))
            elif field == "address":
                detail["address"] = value
            elif field == "employees_count":
                detail["employees_count"] = value
            elif field == "website":
                detail["website"] = value
            elif field == "phone":
                detail["phone"] = value
            elif field == "email":
                detail["email"] = value
            # country_of_incorporation and sector_detail are informational only;
            # they're already captured from the listing page.
            i += 2
            continue

        i += 1

    # --- Fallback: phone/email from HTML links (more reliable than text) ---
    soup = BeautifulSoup(html, "lxml")

    if "phone" not in detail:
        tel_links = soup.select("a[href^='tel:']")
        if tel_links:
            detail["phone"] = tel_links[0]["href"].replace("tel:", "").strip()

    if "email" not in detail:
        mailto_links = soup.select("a[href^='mailto:']")
        if mailto_links:
            raw = mailto_links[0]["href"].replace("mailto:", "").strip()
            # Ignore generic editorial emails
            if "zawya" not in raw and "lseg" not in raw:
                detail["email"] = raw

    if "website" not in detail:
        for a in soup.find_all("a", href=True):
            href: str = a["href"]
            if href.startswith("http") and "zawya.com" not in href and "lseg.com" not in href:
                link_text = a.get_text(strip=True).lower()
                if any(w in link_text for w in ("website", "www.", "visit site")):
                    detail["website"] = href
                    break

    detail["detail_scraped_at"] = datetime.now(UTC).isoformat()
    return detail


async def _scrape_one(
    context: BrowserContext,
    company_id: str,
    profile_url: str,
) -> CompanyDetail:
    """Open a new tab, load the company page, extract detail data."""
    log = logger.bind(company_id=company_id)
    page = await context.new_page()
    try:
        await page.goto(profile_url, wait_until="networkidle", timeout=45_000)
        html = await page.content()
        inner_text: str = await page.evaluate("() => document.body.innerText")
        detail = _extract_detail(inner_text, html)
        log.info("detail_scraped", fields=list(detail.keys()))
        return detail
    except Exception as exc:
        log.error("detail_scrape_failed", error=str(exc))
        raise ScrapingError(
            f"Detail scrape failed for {company_id}: {exc}"
        ) from exc
    finally:
        await page.close()


async def scrape_all_details(
    pending: list[tuple[str, str]],
    settings: Settings,
    on_result: object,  # Callable[[str, CompanyDetail], Awaitable[None]]
) -> tuple[int, int]:
    """
    Scrape detail pages for all pending companies.

    Args:
        pending:   List of (company_id, profile_url) pairs.
        settings:  Application settings.
        on_result: Async callback called with (company_id, detail) on success.

    Returns:
        Tuple of (success_count, failure_count).
    """
    from collections.abc import Awaitable, Callable

    # Runtime type is validated here to satisfy mypy strict
    callback: Callable[[str, CompanyDetail], Awaitable[None]] = on_result  # type: ignore[assignment]

    semaphore = asyncio.Semaphore(settings.detail_concurrency)
    success_count = 0
    failure_count = 0
    lock = asyncio.Lock()

    logger.info(
        "detail_scrape_started",
        total=len(pending),
        concurrency=settings.detail_concurrency,
    )

    async with async_playwright() as pw:
        browser: Browser = await pw.chromium.launch(headless=True)
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 800},
        )

        async def process_one(company_id: str, url: str) -> None:
            nonlocal success_count, failure_count
            async with semaphore:
                try:
                    detail = await _scrape_one(context, company_id, url)
                    await callback(company_id, detail)
                    async with lock:
                        success_count += 1
                except (ScrapingError, Exception):
                    async with lock:
                        failure_count += 1
                finally:
                    await random_delay(
                        settings.request_delay_min, settings.request_delay_max
                    )

        await asyncio.gather(*[process_one(cid, url) for cid, url in pending])
        await context.close()
        await browser.close()

    logger.info(
        "detail_scrape_complete",
        success=success_count,
        failed=failure_count,
    )
    return success_count, failure_count
