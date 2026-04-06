from __future__ import annotations

import asyncio
import hashlib
import json
from typing import Any

import structlog

from hak_talent_mapping.config import Settings
from hak_talent_mapping.core.exceptions import EnrichmentError
from hak_talent_mapping.core.models import (
    CompanyProfile,
    EnrichmentStatus,
    ProfileExtractionResult,
)
from hak_talent_mapping.db.audit_repository import AuditRepository
from hak_talent_mapping.db.detail_repository import DetailRepository
from hak_talent_mapping.services.enrichment.web_search import SerperSearchService
from hak_talent_mapping.services.enrichment.website_scraper import WebsiteScraper
from hak_talent_mapping.services.llm.base import LLMProvider
from hak_talent_mapping.services.llm.openrouter_provider import OpenRouterProvider

logger = structlog.get_logger()


class EnrichmentPipeline:
    """Orchestrates Stages 1–5 for a single company.

    Stage 1 — Init: create/resume company_details row
    Stage 2 — Web Search: run Serper queries, store raw_search_results
    Stage 3 — Website Scrape: scrape About/Team/Contact, store raw_website_data
    Stage 4 — LLM Extraction: single Claude call → ProfileExtractionResult
    Stage 5 — Profile Complete: compute quality score + content hash
    """

    def __init__(
        self,
        settings: Settings,
        detail_repo: DetailRepository,
        search_service: SerperSearchService,
        website_scraper: WebsiteScraper,
        llm_provider: LLMProvider,
        audit_repo: AuditRepository | None = None,
    ) -> None:
        self._settings = settings
        self._repo = detail_repo
        self._search = search_service
        self._scraper = website_scraper
        self._llm = llm_provider
        self._audit = audit_repo

    async def run_company(
        self,
        company: dict[str, Any],
        sector_metadata_schema: dict[str, Any] | None = None,
    ) -> str | None:
        """Enrich a single company through all 5 stages.

        Args:
            company: A row dict from the companies table.
            sector_metadata_schema: Optional schema for sector-specific fields.

        Returns:
            The company_detail id on success, None on failure.
        """
        company_id: str = company["company_id"]
        companies_id: int | None = company.get("id")
        name: str = company.get("name", company_id)
        sector: str = company.get("sector", "")
        country: str = company.get("country", "")
        country_code: str = company.get("country_code", "")
        website: str = company.get("website") or ""

        log = logger.bind(company_id=company_id, name=name, sector=sector)

        # --- Stage 1: Init ---
        try:
            existing = await asyncio.to_thread(
                self._repo.get_by_company_sector, company_id, sector
            )
            if existing and existing["enrichment_status"] == EnrichmentStatus.PROFILE_COMPLETE.value:
                log.info("already_complete_skip")
                return existing["id"]

            if existing:
                detail_id = existing["id"]
                current_status = EnrichmentStatus(existing["enrichment_status"])
                log.info("resuming_enrichment", status=current_status.value)
            else:
                profile = CompanyProfile(
                    companies_id=companies_id,
                    company_id=company_id,
                    sector=sector,
                    country_code=country_code,
                    name=name,
                    country=country,
                )
                created = await self._repo.create_async(profile)
                detail_id = created.id
                current_status = EnrichmentStatus.PENDING
                log.info("init_complete", detail_id=detail_id)
        except Exception as exc:
            log.error("stage1_failed", error=str(exc))
            return None

        # --- Stage 2: Web Search ---
        search_results: list[dict[str, Any]] = []
        if current_status == EnrichmentStatus.PENDING:
            try:
                search_results = await self._search.search_company(
                    name=name, sector=sector, country=country
                )
                await self._repo.upsert_raw_search_async(detail_id, search_results)
                current_status = EnrichmentStatus.WEB_SEARCH_DONE
                log.info("web_search_done", query_count=len(search_results))
                if self._audit:
                    for entry in search_results:
                        await self._audit.log_event_async(
                            company_detail_id=detail_id,
                            stage="web_search",
                            event_type="serper_query",
                            request_data={"query": entry.get("query", "")},
                            response_data={"results": entry.get("results", [])},
                        )
            except Exception as exc:
                log.error("stage2_failed", error=str(exc))
                await self._repo.update_status_async(
                    detail_id, EnrichmentStatus.FAILED, str(exc)
                )
                return None
        elif existing:
            search_results = existing.get("raw_search_results") or []

        # --- Stage 3: Website Scrape ---
        website_text = ""
        if current_status == EnrichmentStatus.WEB_SEARCH_DONE:
            try:
                scrape_result = await self._scraper.scrape(website)
                website_text = scrape_result.combined_text()
                await self._repo.upsert_raw_website_async(
                    detail_id, scrape_result.to_dict()
                )
                current_status = EnrichmentStatus.WEBSITE_SCRAPED
                log.info(
                    "website_scraped",
                    pages=list(scrape_result.pages.keys()),
                    text_length=len(website_text),
                )
            except Exception as exc:
                log.warning("stage3_failed_continuing", error=str(exc))
                # Website scrape failure is non-fatal — continue with empty text
                await self._repo.update_status_async(
                    detail_id, EnrichmentStatus.WEBSITE_SCRAPED
                )
                current_status = EnrichmentStatus.WEBSITE_SCRAPED
        elif existing:
            raw_web = existing.get("raw_website_data") or {}
            pages = raw_web.get("pages", {})
            website_text = "\n\n---\n\n".join(
                f"[{p}]\n{t}" for p, t in pages.items()
            )[:8000]

        # --- Stage 4: LLM Extraction ---
        extraction: ProfileExtractionResult | None = None
        if current_status == EnrichmentStatus.WEBSITE_SCRAPED:
            try:
                extraction = await self._llm.extract_profile(
                    company_name=name,
                    sector=sector,
                    search_results=search_results,
                    website_text=website_text,
                    sector_metadata_schema=sector_metadata_schema,
                )
                profile = _build_profile_from_extraction(
                    extraction, company_id, sector, country_code, country, detail_id
                )
                await self._repo.upsert_profile_async(profile)
                current_status = EnrichmentStatus.LLM_EXTRACTED
                log.info(
                    "llm_extracted",
                    confidence=extraction.extraction_confidence,
                )
                if self._audit and isinstance(self._llm, OpenRouterProvider):
                    await self._audit.log_event_async(
                        company_detail_id=detail_id,
                        stage="llm_extraction",
                        event_type="llm_call",
                        request_data={
                            "system_prompt": self._llm.last_system_prompt,
                            "user_prompt": self._llm.last_user_prompt,
                        },
                        response_data={
                            "raw_response": self._llm.last_raw_response,
                            "parsed": extraction.model_dump(),
                        },
                    )
            except Exception as exc:
                log.error("stage4_failed", error=str(exc))
                await self._repo.update_status_async(
                    detail_id, EnrichmentStatus.FAILED, str(exc)
                )
                return None

        # --- Stage 5: Profile Complete ---
        if current_status == EnrichmentStatus.LLM_EXTRACTED:
            try:
                row = existing or {}
                quality_score = _compute_quality_score(extraction, row)
                content_hash = _compute_content_hash(extraction, row)
                await self._repo.mark_profile_complete_async(
                    detail_id, quality_score, content_hash
                )
                log.info(
                    "profile_complete",
                    quality_score=quality_score,
                    content_hash=content_hash[:8],
                )
            except Exception as exc:
                log.error("stage5_failed", error=str(exc))
                await self._repo.update_status_async(
                    detail_id, EnrichmentStatus.FAILED, str(exc)
                )
                return None

        return detail_id


def _build_profile_from_extraction(
    extraction: ProfileExtractionResult,
    company_id: str,
    sector: str,
    country_code: str,
    country: str,
    detail_id: str,
) -> CompanyProfile:
    # Merge leadership_names and alumni_signals into sector_metadata so the
    # scoring engine can find them without a dedicated column.
    sector_metadata = {
        **extraction.sector_metadata,
        "leadership_names": extraction.leadership_names,
        "alumni_signals": extraction.alumni_signals,
    }
    return CompanyProfile(
        id=detail_id,
        company_id=company_id,
        sector=sector,
        country_code=country_code,
        name=extraction.name,
        domain=extraction.domain,
        description_clean=extraction.description_clean,
        country=country,
        city=extraction.city,
        region=extraction.region,
        sub_sector=extraction.sub_sector,
        sub_sector_tags=extraction.sub_sector_tags,
        funding_stage=extraction.funding_stage,
        funding_total_usd=extraction.funding_total_usd,
        headcount_range=extraction.headcount_range,
        headcount_exact=extraction.headcount_exact,
        founded_year=extraction.founded_year,
        sector_metadata=sector_metadata,
        enrichment_status=EnrichmentStatus.LLM_EXTRACTED,
    )


def _compute_quality_score(
    extraction: ProfileExtractionResult | None,
    existing_row: dict[str, Any],
) -> float:
    """Score 0.0–1.0 based on how many key fields are populated."""
    if extraction is None:
        return 0.0
    key_fields = [
        extraction.description_clean,
        extraction.city,
        extraction.headcount_range,
        extraction.founded_year,
        extraction.domain,
        extraction.sub_sector,
    ]
    populated = sum(1 for f in key_fields if f)
    return round(populated / len(key_fields), 2)


def _compute_content_hash(
    extraction: ProfileExtractionResult | None,
    existing_row: dict[str, Any],
) -> str:
    """Short SHA-256 of the extracted profile content for change detection."""
    if extraction is None:
        return ""
    content = json.dumps(extraction.model_dump(), sort_keys=True, default=str)
    return hashlib.sha256(content.encode()).hexdigest()[:16]


class EnrichmentRunner:
    """Runs EnrichmentPipeline concurrently across many companies."""

    def __init__(self, pipeline: EnrichmentPipeline, concurrency: int = 3) -> None:
        self._pipeline = pipeline
        self._concurrency = concurrency

    async def run_batch(
        self,
        companies: list[dict[str, Any]],
        sector_metadata_schema: dict[str, Any] | None = None,
    ) -> dict[str, int]:
        """Enrich a list of companies with bounded concurrency.

        Returns a summary dict with counts of succeeded/failed.
        """
        semaphore = asyncio.Semaphore(self._concurrency)
        succeeded = 0
        failed = 0

        async def _run_one(company: dict[str, Any]) -> None:
            nonlocal succeeded, failed
            async with semaphore:
                result = await self._pipeline.run_company(
                    company, sector_metadata_schema
                )
                if result:
                    succeeded += 1
                else:
                    failed += 1

        await asyncio.gather(*[_run_one(c) for c in companies])
        return {"succeeded": succeeded, "failed": failed, "total": len(companies)}
