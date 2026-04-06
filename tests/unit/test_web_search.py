from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hak_talent_mapping.core.exceptions import SearchAPIError
from hak_talent_mapping.services.enrichment.web_search import SerperSearchService


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _serper_response(organic: list[dict]) -> MagicMock:
    """Build a mock httpx response for a Serper API call."""
    mock_resp = MagicMock()
    mock_resp.raise_for_status = MagicMock()
    mock_resp.json.return_value = {"organic": organic}
    return mock_resp


SAMPLE_ORGANIC = [
    {
        "title": "Landmark Group Overview",
        "link": "https://landmark.ae",
        "snippet": "Landmark Group is a leading retail conglomerate in the Middle East.",
        "position": 1,
    },
    {
        "title": "Landmark Careers",
        "link": "https://landmark.ae/careers",
        "snippet": "Join our team of 50,000+ employees.",
        "position": 2,
    },
]


# ---------------------------------------------------------------------------
# Unit tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_search_company_returns_results() -> None:
    mock_response = _serper_response(SAMPLE_ORGANIC)

    with patch(
        "hak_talent_mapping.services.enrichment.web_search.build_async_client"
    ) as mock_build:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(return_value=mock_response)
        mock_build.return_value = mock_client

        with patch("hak_talent_mapping.services.enrichment.web_search.random_delay", new_callable=AsyncMock):
            service = SerperSearchService(api_key="test-key", queries_per_company=2)
            results = await service.search_company(
                name="Landmark Group",
                sector="Retailers",
                country="United Arab Emirates",
            )

    assert len(results) == 2  # 2 queries
    first = results[0]
    assert "query" in first
    assert "results" in first
    assert first["results"][0]["title"] == "Landmark Group Overview"


@pytest.mark.asyncio
async def test_search_company_interpolates_name_in_query() -> None:
    mock_response = _serper_response([])
    captured_bodies: list[dict] = []

    async def capture_post(url: str, **kwargs: object) -> MagicMock:
        captured_bodies.append(kwargs.get("json", {}))  # type: ignore[arg-type]
        return mock_response

    with patch(
        "hak_talent_mapping.services.enrichment.web_search.build_async_client"
    ) as mock_build:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=capture_post)
        mock_build.return_value = mock_client

        with patch("hak_talent_mapping.services.enrichment.web_search.random_delay", new_callable=AsyncMock):
            service = SerperSearchService(api_key="test-key", queries_per_company=1)
            await service.search_company(name="Acme Corp", sector="Retailers")

    assert len(captured_bodies) == 1
    assert "Acme Corp" in captured_bodies[0]["q"]


@pytest.mark.asyncio
async def test_search_company_handles_api_failure_gracefully() -> None:
    """A failed query is recorded with an error key but doesn't abort the batch."""
    with patch(
        "hak_talent_mapping.services.enrichment.web_search.build_async_client"
    ) as mock_build:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        # First call raises, subsequent calls succeed (retry exhausted → stored as error)
        mock_client.post = AsyncMock(side_effect=Exception("connection refused"))
        mock_build.return_value = mock_client

        with patch("hak_talent_mapping.services.enrichment.web_search.random_delay", new_callable=AsyncMock):
            service = SerperSearchService(api_key="test-key", queries_per_company=2)
            results = await service.search_company(name="Broken Co", sector="Retailers")

    # Results should still be returned (with error entries) not an exception
    assert isinstance(results, list)
    for r in results:
        assert "error" in r or "results" in r


@pytest.mark.asyncio
async def test_run_query_raises_search_api_error_on_failure() -> None:
    """_run_query raises SearchAPIError when the HTTP request fails."""
    with patch(
        "hak_talent_mapping.services.enrichment.web_search.build_async_client"
    ) as mock_build:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=Exception("timeout"))
        mock_build.return_value = mock_client

        service = SerperSearchService(api_key="test-key")

        async with mock_client:
            with pytest.raises(SearchAPIError):
                await service._run_query(mock_client, "test query")


@pytest.mark.asyncio
async def test_search_company_respects_queries_per_company_limit() -> None:
    mock_response = _serper_response([])

    call_count = 0

    async def count_calls(url: str, **kwargs: object) -> MagicMock:
        nonlocal call_count
        call_count += 1
        return mock_response

    with patch(
        "hak_talent_mapping.services.enrichment.web_search.build_async_client"
    ) as mock_build:
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=count_calls)
        mock_build.return_value = mock_client

        with patch("hak_talent_mapping.services.enrichment.web_search.random_delay", new_callable=AsyncMock):
            service = SerperSearchService(api_key="test-key", queries_per_company=3)
            await service.search_company(name="Test", sector="Retailers")

    assert call_count == 3


def test_service_caps_queries_at_template_count() -> None:
    """queries_per_company is capped at the number of available templates."""
    service = SerperSearchService(api_key="key", queries_per_company=999)
    from hak_talent_mapping.services.enrichment.web_search import _QUERY_TEMPLATES

    assert service._queries_per_company == len(_QUERY_TEMPLATES)
