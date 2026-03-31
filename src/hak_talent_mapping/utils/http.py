from __future__ import annotations

import asyncio
import random

import httpx
import structlog

logger = structlog.get_logger()

# Realistic browser headers to reduce the chance of being blocked
_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;q=0.9,"
        "image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}


def build_async_client(timeout: float = 30.0) -> httpx.AsyncClient:
    """Return a configured async HTTP client."""
    return httpx.AsyncClient(
        headers=_HEADERS,
        timeout=httpx.Timeout(timeout),
        follow_redirects=True,
        http2=True,
    )


async def random_delay(min_seconds: float = 1.0, max_seconds: float = 3.0) -> None:
    """Sleep for a random duration to be polite to the target server."""
    delay = random.uniform(min_seconds, max_seconds)
    await asyncio.sleep(delay)
