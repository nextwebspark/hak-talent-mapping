from __future__ import annotations

from typing import Any

import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from hak_talent_mapping.core.exceptions import SearchAPIError
from hak_talent_mapping.utils.http import build_async_client, random_delay

logger = structlog.get_logger()

_SERPER_URL = "https://google.serper.dev/search"

# Fallback query templates used when no sector config is provided.
# When a sector config is loaded, its search_queries field is used instead.
_DEFAULT_QUERY_TEMPLATES: list[str] = [
    "{name} company overview {sector}",
    "{name} company employees headcount size",
    "{name} CEO leadership management team",
    "{name} annual revenue funding investment",
    "{name} press news 2024 2025",
    "{name} {sector} company profile",
    "{name} founded history {country}",
    "{name} offices locations branches",
    "{name} executives directors board",
    "{name} alumni careers LinkedIn",
]


class SerperSearchService:
    """Searches Google via serper.dev and returns structured snippets.

    Query templates are resolved in priority order:
    1. ``query_templates`` passed at construction time (from sector YAML ``search_queries``)
    2. ``_DEFAULT_QUERY_TEMPLATES`` (built-in fallback)
    """

    def __init__(
        self,
        api_key: str,
        queries_per_company: int = 10,
        query_templates: list[str] | None = None,
    ) -> None:
        self._api_key = api_key
        templates = query_templates if query_templates else _DEFAULT_QUERY_TEMPLATES
        self._query_templates = templates
        self._queries_per_company = min(queries_per_company, len(templates))

    async def search_company(
        self,
        name: str,
        sector: str,
        country: str = "",
    ) -> list[dict[str, Any]]:
        """Run query templates for a company and return aggregated results.

        Returns a list of result objects, one per query, each containing
        the query string and a list of organic result snippets.
        """
        templates = self._query_templates[: self._queries_per_company]
        all_results: list[dict[str, Any]] = []

        async with build_async_client(timeout=20.0) as client:
            for template in templates:
                query = template.format(name=name, sector=sector, country=country)
                try:
                    results = await self._run_query(client, query)
                    all_results.append({"query": query, "results": results})
                    logger.debug(
                        "search_query_done",
                        query=query,
                        result_count=len(results),
                    )
                except SearchAPIError as exc:
                    logger.warning(
                        "search_query_failed",
                        query=query,
                        error=str(exc),
                    )
                    all_results.append({"query": query, "results": [], "error": str(exc)})
                await random_delay(0.5, 1.5)

        return all_results

    @retry(
        retry=retry_if_exception_type(SearchAPIError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=15),
        reraise=True,
    )
    async def _run_query(
        self,
        client: Any,
        query: str,
    ) -> list[dict[str, Any]]:
        """Execute a single Serper search query."""
        try:
            response = await client.post(
                _SERPER_URL,
                headers={
                    "X-API-KEY": self._api_key,
                    "Content-Type": "application/json",
                },
                json={"q": query, "num": 10},
            )
            response.raise_for_status()
            data = response.json()
        except Exception as exc:
            raise SearchAPIError(f"Serper request failed: {exc}") from exc

        organic = data.get("organic", [])
        return [
            {
                "title": r.get("title", ""),
                "link": r.get("link", ""),
                "snippet": r.get("snippet", ""),
                "position": r.get("position", 0),
            }
            for r in organic
        ]
