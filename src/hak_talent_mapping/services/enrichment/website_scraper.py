from __future__ import annotations

import re
from typing import Any
from urllib.parse import urljoin, urlparse

import structlog
from playwright.async_api import Browser, async_playwright

from hak_talent_mapping.core.exceptions import EnrichmentError
from hak_talent_mapping.utils.http import random_delay

logger = structlog.get_logger()

# Pages to attempt scraping (in order of priority)
_TARGET_PATHS: list[str] = [
    "",           # homepage
    "/about",
    "/about-us",
    "/team",
    "/leadership",
    "/management",
    "/contact",
    "/contact-us",
]

_MIN_TEXT_LENGTH = 100  # ignore pages with very little text


class WebsiteScrapeResult:
    """Holds text content scraped from a company website."""

    __slots__ = ("pages",)

    def __init__(self) -> None:
        self.pages: dict[str, str] = {}

    def to_dict(self) -> dict[str, Any]:
        return {"pages": self.pages}

    def combined_text(self, max_chars: int = 8000) -> str:
        """Concatenate page texts, trimmed to max_chars total."""
        combined = "\n\n---\n\n".join(
            f"[{path}]\n{text}" for path, text in self.pages.items()
        )
        return combined[:max_chars]


class WebsiteScraper:
    """Scrapes About/Team/Contact pages from a company website using Playwright."""

    def __init__(self, timeout: int = 30) -> None:
        self._timeout = timeout * 1000  # Playwright uses milliseconds

    async def scrape(self, website_url: str) -> WebsiteScrapeResult:
        """Scrape key pages from website_url.

        Returns a WebsiteScrapeResult with page texts. If the site is
        unreachable, returns an empty result (does not raise).
        """
        result = WebsiteScrapeResult()
        if not website_url:
            return result

        base_url = _normalize_base_url(website_url)

        async with async_playwright() as pw:
            browser: Browser = await pw.chromium.launch(headless=True)
            try:
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/124.0.0.0 Safari/537.36"
                    ),
                    viewport={"width": 1280, "height": 800},
                )
                for path in _TARGET_PATHS:
                    url = urljoin(base_url, path) if path else base_url
                    text = await self._fetch_page(context, url)
                    if text and len(text) >= _MIN_TEXT_LENGTH:
                        label = path or "/"
                        result.pages[label] = text
                        logger.debug(
                            "page_scraped",
                            url=url,
                            text_length=len(text),
                        )
                    await random_delay(0.5, 1.5)
            except Exception as exc:
                logger.warning("website_scrape_error", url=base_url, error=str(exc))
            finally:
                await browser.close()

        return result

    async def _fetch_page(self, context: Any, url: str) -> str:
        """Fetch a single page and return its cleaned innerText."""
        try:
            page = await context.new_page()
            try:
                await page.goto(url, timeout=self._timeout, wait_until="domcontentloaded")
                text: str = await page.evaluate("() => document.body.innerText")
                return _clean_text(text)
            finally:
                await page.close()
        except Exception as exc:
            logger.debug("page_fetch_failed", url=url, error=str(exc))
            return ""


def _normalize_base_url(url: str) -> str:
    """Ensure URL has a scheme."""
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _clean_text(text: str) -> str:
    """Collapse excessive whitespace from innerText."""
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()
