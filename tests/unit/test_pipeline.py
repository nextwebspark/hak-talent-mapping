from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hak_talent_mapping.core.models import (
    CompanyProfile,
    EnrichmentStatus,
    ProfileExtractionResult,
)
from hak_talent_mapping.services.enrichment.pipeline import (
    EnrichmentPipeline,
    EnrichmentRunner,
    _compute_content_hash,
    _compute_quality_score,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

VALID_EXTRACTION = ProfileExtractionResult(
    name="Landmark Group",
    domain="landmark.ae",
    description_clean="A leading retail group in the Middle East.",
    city="Dubai",
    region="Dubai",
    sub_sector="Fashion Retail",
    sub_sector_tags=["fashion", "home"],
    headcount_range="5001+",
    headcount_exact=55000,
    founded_year=1973,
    sector_metadata={"store_count": 200, "ded_license_confirmed": True},
    leadership_names=["CEO", "CFO"],
    extraction_confidence=0.9,
)

SAMPLE_COMPANY: dict[str, Any] = {
    "company_id": "cid-001",
    "name": "Landmark Group",
    "sector": "Retailers",
    "country": "United Arab Emirates",
    "country_code": "AE",
    "website": "https://landmark.ae",
    "slug": "landmark-group",
}


def _make_settings() -> MagicMock:
    settings = MagicMock()
    settings.enrichment_concurrency = 2
    return settings


def _make_detail_repo(existing_row: dict | None = None) -> MagicMock:
    repo = MagicMock()
    repo.get_by_company_sector = MagicMock(return_value=existing_row)
    repo.create_async = AsyncMock(
        return_value=CompanyProfile(
            id="detail-uuid-001",
            company_id="cid-001",
            sector="Retailers",
            country_code="AE",
            name="Landmark Group",
        )
    )
    repo.upsert_raw_search_async = AsyncMock()
    repo.upsert_raw_website_async = AsyncMock()
    repo.upsert_profile_async = AsyncMock()
    repo.mark_profile_complete_async = AsyncMock()
    repo.update_status_async = AsyncMock()
    return repo


def _make_search_service() -> MagicMock:
    svc = MagicMock()
    svc.search_company = AsyncMock(
        return_value=[{"query": "Landmark overview", "results": []}]
    )
    return svc


def _make_scraper(pages: dict[str, str] | None = None) -> MagicMock:
    scraper = MagicMock()
    result = MagicMock()
    result.combined_text.return_value = "About page text"
    result.to_dict.return_value = {"pages": pages or {"/about": "About page text"}}
    result.pages = pages or {"/about": "About page text"}
    scraper.scrape = AsyncMock(return_value=result)
    return scraper


def _make_llm(extraction: ProfileExtractionResult = VALID_EXTRACTION) -> MagicMock:
    provider = MagicMock()
    provider.extract_profile = AsyncMock(return_value=extraction)
    return provider


def _make_pipeline(
    existing_row: dict | None = None,
    extraction: ProfileExtractionResult = VALID_EXTRACTION,
) -> tuple[EnrichmentPipeline, MagicMock]:
    detail_repo = _make_detail_repo(existing_row)
    pipeline = EnrichmentPipeline(
        settings=_make_settings(),
        detail_repo=detail_repo,
        search_service=_make_search_service(),
        website_scraper=_make_scraper(),
        llm_provider=_make_llm(extraction),
    )
    return pipeline, detail_repo


# ---------------------------------------------------------------------------
# Stage 1 — Init
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_creates_new_detail_row() -> None:
    pipeline, repo = _make_pipeline(existing_row=None)
    result = await pipeline.run_company(SAMPLE_COMPANY)
    assert result == "detail-uuid-001"
    repo.create_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_pipeline_skips_already_complete() -> None:
    existing = {
        "id": "existing-uuid",
        "enrichment_status": EnrichmentStatus.PROFILE_COMPLETE.value,
    }
    pipeline, repo = _make_pipeline(existing_row=existing)
    result = await pipeline.run_company(SAMPLE_COMPANY)
    assert result == "existing-uuid"
    # No new row created, no stages run
    repo.create_async.assert_not_awaited()
    repo.upsert_raw_search_async.assert_not_awaited()


@pytest.mark.asyncio
async def test_pipeline_resumes_from_web_search_done() -> None:
    """If status is web_search_done, skip Stage 2 and resume from Stage 3."""
    existing = {
        "id": "existing-uuid",
        "enrichment_status": EnrichmentStatus.WEB_SEARCH_DONE.value,
        "raw_search_results": [{"query": "cached", "results": []}],
        "raw_website_data": None,
    }
    pipeline, repo = _make_pipeline(existing_row=existing)
    result = await pipeline.run_company(SAMPLE_COMPANY)
    assert result is not None
    # Stage 2 should NOT have run (already done)
    repo.upsert_raw_search_async.assert_not_awaited()
    # Stage 3 should have run
    repo.upsert_raw_website_async.assert_awaited_once()


# ---------------------------------------------------------------------------
# Stage 2 — Web Search
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_calls_search_service() -> None:
    pipeline, repo = _make_pipeline()
    await pipeline.run_company(SAMPLE_COMPANY)
    pipeline._search.search_company.assert_awaited_once()


@pytest.mark.asyncio
async def test_pipeline_stores_search_results_in_db() -> None:
    pipeline, repo = _make_pipeline()
    await pipeline.run_company(SAMPLE_COMPANY)
    repo.upsert_raw_search_async.assert_awaited_once()


@pytest.mark.asyncio
async def test_pipeline_marks_failed_on_search_error() -> None:
    pipeline, repo = _make_pipeline()
    pipeline._search.search_company = AsyncMock(side_effect=Exception("API error"))
    result = await pipeline.run_company(SAMPLE_COMPANY)
    assert result is None
    repo.update_status_async.assert_awaited()
    call_args = repo.update_status_async.await_args
    assert call_args.args[1] == EnrichmentStatus.FAILED


# ---------------------------------------------------------------------------
# Stage 3 — Website Scrape
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_calls_website_scraper() -> None:
    pipeline, repo = _make_pipeline()
    await pipeline.run_company(SAMPLE_COMPANY)
    pipeline._scraper.scrape.assert_awaited_once_with("https://landmark.ae")


@pytest.mark.asyncio
async def test_pipeline_continues_if_scrape_fails() -> None:
    """Stage 3 failure is non-fatal — pipeline should still reach profile_complete."""
    pipeline, repo = _make_pipeline()
    pipeline._scraper.scrape = AsyncMock(side_effect=Exception("playwright crash"))
    result = await pipeline.run_company(SAMPLE_COMPANY)
    # Should continue and eventually succeed (scrape error is a warning, not fatal)
    assert result is not None
    repo.mark_profile_complete_async.assert_awaited_once()


# ---------------------------------------------------------------------------
# Stage 4 — LLM Extraction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_calls_llm_provider() -> None:
    pipeline, repo = _make_pipeline()
    await pipeline.run_company(SAMPLE_COMPANY)
    pipeline._llm.extract_profile.assert_awaited_once()


@pytest.mark.asyncio
async def test_pipeline_stores_extracted_profile() -> None:
    pipeline, repo = _make_pipeline()
    await pipeline.run_company(SAMPLE_COMPANY)
    repo.upsert_profile_async.assert_awaited_once()
    profile_arg: CompanyProfile = repo.upsert_profile_async.await_args.args[0]
    assert profile_arg.name == "Landmark Group"
    assert profile_arg.domain == "landmark.ae"
    assert profile_arg.city == "Dubai"


@pytest.mark.asyncio
async def test_pipeline_marks_failed_on_llm_error() -> None:
    pipeline, repo = _make_pipeline()
    pipeline._llm.extract_profile = AsyncMock(side_effect=Exception("LLM timeout"))
    result = await pipeline.run_company(SAMPLE_COMPANY)
    assert result is None
    call_args = repo.update_status_async.await_args
    assert call_args.args[1] == EnrichmentStatus.FAILED


# ---------------------------------------------------------------------------
# Stage 5 — Profile Complete
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_marks_profile_complete() -> None:
    pipeline, repo = _make_pipeline()
    result = await pipeline.run_company(SAMPLE_COMPANY)
    assert result is not None
    repo.mark_profile_complete_async.assert_awaited_once()
    detail_id, quality_score, content_hash = repo.mark_profile_complete_async.await_args.args
    assert 0.0 <= quality_score <= 1.0
    assert len(content_hash) == 16  # first 16 chars of sha256 hex


# ---------------------------------------------------------------------------
# Quality score + content hash (pure helpers)
# ---------------------------------------------------------------------------


def test_compute_quality_score_all_populated() -> None:
    score = _compute_quality_score(VALID_EXTRACTION, {})
    assert score == 1.0  # all 6 key fields are populated


def test_compute_quality_score_partial() -> None:
    partial = ProfileExtractionResult(
        name="X",
        description_clean="Some description",
        # city, headcount_range, founded_year, domain, sub_sector all None
    )
    score = _compute_quality_score(partial, {})
    assert 0.0 < score < 1.0


def test_compute_quality_score_none_extraction() -> None:
    assert _compute_quality_score(None, {}) == 0.0


def test_compute_content_hash_is_deterministic() -> None:
    h1 = _compute_content_hash(VALID_EXTRACTION, {})
    h2 = _compute_content_hash(VALID_EXTRACTION, {})
    assert h1 == h2
    assert len(h1) == 16


def test_compute_content_hash_changes_on_different_input() -> None:
    other = ProfileExtractionResult(name="Other Company")
    h1 = _compute_content_hash(VALID_EXTRACTION, {})
    h2 = _compute_content_hash(other, {})
    assert h1 != h2


def test_compute_content_hash_none() -> None:
    assert _compute_content_hash(None, {}) == ""


# ---------------------------------------------------------------------------
# EnrichmentRunner — concurrency
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_runner_processes_all_companies() -> None:
    companies = [
        {**SAMPLE_COMPANY, "company_id": f"cid-{i}", "name": f"Company {i}"}
        for i in range(5)
    ]

    pipeline = MagicMock()
    pipeline.run_company = AsyncMock(return_value="some-id")

    runner = EnrichmentRunner(pipeline, concurrency=3)
    summary = await runner.run_batch(companies)

    assert summary["total"] == 5
    assert summary["succeeded"] == 5
    assert summary["failed"] == 0
    assert pipeline.run_company.await_count == 5


@pytest.mark.asyncio
async def test_runner_counts_failures() -> None:
    companies = [
        {**SAMPLE_COMPANY, "company_id": f"cid-{i}"} for i in range(4)
    ]

    async def mixed_result(company: dict, sector_metadata_schema: object = None) -> str | None:
        return None if company["company_id"] in ("cid-1", "cid-3") else "ok"

    pipeline = MagicMock()
    pipeline.run_company = AsyncMock(side_effect=mixed_result)

    runner = EnrichmentRunner(pipeline, concurrency=2)
    summary = await runner.run_batch(companies)

    assert summary["succeeded"] == 2
    assert summary["failed"] == 2
