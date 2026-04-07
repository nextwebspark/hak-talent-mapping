#!/usr/bin/env python
"""
Zawya company scraper — entry point.

Usage:
    # Phase 1: scrape all countries, all sectors (httpx, stop-on-empty per country)
    python scripts/run_scraper.py listings

    # Phase 1: single country, all sectors
    python scripts/run_scraper.py listings --country AE

    # Phase 1: single country + single sector
    python scripts/run_scraper.py listings --country AE --sector Retailers

    # Phase 2: scrape company detail pages (slow, uses Playwright)
    python scripts/run_scraper.py details

    # Test Phase 2 with just 5 records
    python scripts/run_scraper.py details --limit 5

    # Run both phases end-to-end
    python scripts/run_scraper.py all

    # Phase 3: enrich top_company=true companies (stages 1-5)
    python scripts/run_scraper.py enrich --country AE --sector Retailers
    python scripts/run_scraper.py enrich --country AE --sector Retailers --limit 5
    python scripts/run_scraper.py enrich --country AE --sector Retailers --re-enrich

    # Phase 3: score profile_complete companies (stage 6)
    python scripts/run_scraper.py score --country AE --sector Retailers

    # Phase 3: vectorize scored companies into Pinecone (stage 7)
    python scripts/run_scraper.py vectorize --country AE --sector Retailers
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import sys

import structlog
from supabase import create_client

# Ensure src/ is on the path when running the script directly
sys.path.insert(0, "src")

from hak_talent_mapping.config import Settings
from hak_talent_mapping.core.models import Company, CompanyDetail
from hak_talent_mapping.db.audit_repository import AuditRepository
from hak_talent_mapping.db.detail_repository import DetailRepository
from hak_talent_mapping.db.repository import CompanyRepository
from hak_talent_mapping.db.score_repository import ScoreRepository
from hak_talent_mapping.services.detail_scraper import scrape_all_details
from hak_talent_mapping.services.enrichment.pipeline import (
    EnrichmentPipeline,
    EnrichmentRunner,
)
from hak_talent_mapping.services.enrichment.scoring.config_loader import (
    get_sector_metadata_schema,
    load_sector_config,
)
from hak_talent_mapping.services.enrichment.scoring.engine import ScoringEngine
from hak_talent_mapping.services.enrichment.web_search import SerperSearchService
from hak_talent_mapping.services.enrichment.website_scraper import WebsiteScraper
from hak_talent_mapping.services.listing_scraper import scrape_listings
from hak_talent_mapping.services.llm.openrouter_provider import OpenRouterProvider
from hak_talent_mapping.services.vector.embeddings import OpenAIEmbeddingProvider
from hak_talent_mapping.services.vector.pinecone_store import (
    PineconeStore,
    VectorizationRunner,
)


def _configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )
    logging.basicConfig(level=logging.WARNING)
    # Suppress noisy asyncio pipe-closed warnings from Playwright browser shutdown
    logging.getLogger("asyncio").setLevel(logging.ERROR)


async def run_listings(
    country: str, sector: str, settings: Settings, repo: CompanyRepository
) -> None:
    """Phase 1 — scrape listing pages for a given country/sector and upsert into Supabase."""
    log = structlog.get_logger()
    log.info("phase1_start", country=country, sector=sector)

    already_scraped = await repo.get_scraped_listing_ids_async()
    log.info("resume_info", already_scraped=len(already_scraped))

    total_upserted = 0

    async def on_page(companies: list[Company]) -> None:
        nonlocal total_upserted
        await repo.upsert_many_async(companies)
        total_upserted += len(companies)
        log.info("page_upserted", count=len(companies), total_so_far=total_upserted)

    total_found = await scrape_listings(
        country,
        sector,
        settings,
        already_scraped=already_scraped,
        on_page=on_page,
    )

    if total_found == 0:
        log.info("no_new_companies_found")
        return

    log.info("phase1_complete", total_upserted=total_upserted)


async def run_details(
    settings: Settings, repo: CompanyRepository, limit: int | None = None
) -> None:
    """Phase 2 — scrape company detail pages and update Supabase rows."""
    log = structlog.get_logger()

    pending = await repo.get_pending_detail_companies_async()
    if limit:
        pending = pending[:limit]
        log.info("phase2_start", pending_count=len(pending), limit=limit)
    else:
        log.info("phase2_start", pending_count=len(pending))

    if not pending:
        log.info("no_pending_detail_scrapes")
        return

    async def on_result(company_id: str, detail: CompanyDetail) -> None:
        await repo.update_detail_async(company_id, detail)

    success, failed = await scrape_all_details(pending, settings, on_result)
    log.info("phase2_complete", success=success, failed=failed)


async def run_all(
    country: str, sector: str, settings: Settings, repo: CompanyRepository, limit: int | None = None
) -> None:
    await run_listings(country, sector, settings, repo)
    if settings.scrape_details:
        await run_details(settings, repo, limit=limit)


async def run_enrich(
    country: str,
    sector: str,
    settings: Settings,
    limit: int | None = None,
    re_enrich: bool = False,
) -> None:
    """Phase 3 Stage 1-5: enrich top_company=true companies."""
    from supabase import create_client

    log = structlog.get_logger()
    supabase_client = create_client(settings.supabase_url, settings.supabase_key)
    detail_repo = DetailRepository(supabase_client)
    audit_repo = AuditRepository(supabase_client)

    # Validate API keys
    if not settings.serper_api_key:
        log.error("missing_serper_api_key", hint="Set SERPER_API_KEY in .env")
        sys.exit(1)
    if not settings.openrouter_api_key:
        log.error("missing_openrouter_api_key", hint="Set OPENROUTER_API_KEY in .env")
        sys.exit(1)

    # Reset profile_complete rows back to pending so they get re-processed
    if re_enrich:
        supabase_client.table("company_details").update(
            {"enrichment_status": "pending", "enrichment_error": None}
        ).eq("sector", sector).eq("enrichment_status", "profile_complete").execute()
        log.info("re_enrich_reset", sector=sector, country=country)

    # Load sector config
    try:
        sector_config = load_sector_config(sector, settings.scoring_config_dir)
        metadata_schema = get_sector_metadata_schema(sector_config)
        log.info("sector_config_loaded", config_id=sector_config.config_id)
    except Exception as exc:
        log.error("sector_config_error", error=str(exc))
        metadata_schema = None

    # Fetch companies to enrich
    companies = await detail_repo.get_companies_to_enrich_async(
        sector=sector,
        country_code=country,
        top_only=settings.enrich_top_only,
        limit=limit,
    )

    if not companies:
        log.info("no_companies_to_enrich", sector=sector, country=country, top_only=settings.enrich_top_only)
        return

    # Inject country_code (CLI arg) into each company dict — the companies table
    # stores full country names, not codes, so country_code is missing from the query.
    for company in companies:
        company["country_code"] = country

    log.info(
        "enrich_start",
        company_count=len(companies),
        sector=sector,
        country=country,
        top_only=settings.enrich_top_only,
    )

    pipeline = EnrichmentPipeline(
        settings=settings,
        detail_repo=detail_repo,
        audit_repo=audit_repo,
        search_service=SerperSearchService(
            api_key=settings.serper_api_key,
            queries_per_company=settings.search_queries_per_company,
            query_templates=sector_config.search_queries if sector_config.search_queries else None,
        ),
        website_scraper=WebsiteScraper(timeout=settings.website_scrape_timeout),
        llm_provider=OpenRouterProvider(
            api_key=settings.openrouter_api_key,
            model=settings.llm_model,
            base_url=settings.openrouter_base_url,
        ),
    )
    runner = EnrichmentRunner(pipeline, concurrency=settings.enrichment_concurrency)
    summary = await runner.run_batch(companies, sector_metadata_schema=metadata_schema)
    log.info("enrich_complete", **summary)


async def run_score(country: str, sector: str, settings: Settings) -> None:
    """Phase 3 Stage 6: score all profile_complete companies."""
    from supabase import create_client

    log = structlog.get_logger()
    supabase_client = create_client(settings.supabase_url, settings.supabase_key)
    detail_repo = DetailRepository(supabase_client)
    score_repo = ScoreRepository(supabase_client)

    try:
        sector_config = load_sector_config(sector, settings.scoring_config_dir)
    except Exception as exc:
        log.error("sector_config_error", error=str(exc))
        sys.exit(1)

    profiles = await detail_repo.get_profile_complete_async(sector=sector, country_code=country)
    if not profiles:
        log.info("no_profiles_to_score", sector=sector, country=country)
        return

    log.info("score_start", profile_count=len(profiles), sector=sector)
    engine = ScoringEngine(sector_config)
    succeeded = 0
    failed = 0

    for profile_row in profiles:
        try:
            record = engine.score(profile_row, country_code=country)
            await score_repo.upsert_scores_async(record)
            succeeded += 1
        except Exception as exc:
            log.error("score_failed", company_id=profile_row.get("company_id"), error=str(exc))
            failed += 1

    log.info("score_complete", succeeded=succeeded, failed=failed, total=len(profiles))


async def run_vectorize(country: str, sector: str, settings: Settings) -> None:
    """Phase 3 Stage 7: embed and upsert to Pinecone."""
    from supabase import create_client

    log = structlog.get_logger()

    if not settings.pinecone_api_key:
        log.error("missing_pinecone_api_key", hint="Set PINECONE_API_KEY in .env")
        sys.exit(1)
    if not settings.openrouter_api_key:
        log.error("missing_openrouter_api_key", hint="Set OPENROUTER_API_KEY in .env")
        sys.exit(1)

    try:
        sector_config = load_sector_config(sector, settings.scoring_config_dir)
    except Exception as exc:
        log.error("sector_config_error", error=str(exc))
        sys.exit(1)

    supabase_client = create_client(settings.supabase_url, settings.supabase_key)
    detail_repo = DetailRepository(supabase_client)
    score_repo = ScoreRepository(supabase_client)

    runner = VectorizationRunner(
        detail_repo=detail_repo,
        score_repo=score_repo,
        embedding_provider=OpenAIEmbeddingProvider(
            api_key=settings.openrouter_api_key,
            model=settings.pinecone_embedding_model,
            base_url=settings.openrouter_base_url,
        ),
        pinecone_store=PineconeStore(
            api_key=settings.pinecone_api_key,
            index_name=settings.pinecone_index_name,
        ),
        embedding_model=settings.pinecone_embedding_model,
        batch_size=settings.pinecone_upsert_batch_size,
    )

    log.info("vectorize_start", sector=sector, country=country)
    summary = await runner.run(
        sector=sector,
        country_code=country,
        scoring_config_id=sector_config.config_id,
    )
    log.info("vectorize_complete", **summary)


def main() -> None:
    _configure_logging()
    log = structlog.get_logger()

    parser = argparse.ArgumentParser(
        description="Scrape Zawya company listings into Supabase"
    )
    parser.add_argument(
        "phase",
        choices=["listings", "details", "all", "enrich", "score", "vectorize"],
        help=(
            "listings: scrape company list pages only  |  "
            "details: scrape company detail pages only  |  "
            "all: run both phases  |  "
            "enrich: Phase 3 stages 1-5 (search+scrape+LLM)  |  "
            "score: Phase 3 stage 6 (scoring)  |  "
            "vectorize: Phase 3 stage 7 (Pinecone)"
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Only scrape the first N companies (useful for testing details)",
    )
    parser.add_argument(
        "--country",
        type=str,
        required=True,
        metavar="CODE",
        help="Country code to scrape (e.g. AE, SA)",
    )
    parser.add_argument(
        "--sector",
        type=str,
        required=True,
        metavar="SECTOR",
        help="Sector name to scrape (e.g. Retailers)",
    )
    parser.add_argument(
        "--re-enrich",
        action="store_true",
        help="(enrich only) Reset status to pending and re-enrich already-enriched companies",
    )
    args = parser.parse_args()

    try:
        settings = Settings()  # type: ignore[call-arg]
    except Exception as exc:
        log.error("config_error", error=str(exc))
        log.error("hint", message="Copy .env.example to .env and fill in your credentials")
        sys.exit(1)

    supabase_client = create_client(settings.supabase_url, settings.supabase_key)
    repo = CompanyRepository(supabase_client)

    log.info(
        "scraper_starting",
        phase=args.phase,
        limit=args.limit,
        country=args.country,
        sector=args.sector,
    )

    try:
        if args.phase == "listings":
            asyncio.run(run_listings(args.country, args.sector, settings, repo))
        elif args.phase == "details":
            asyncio.run(run_details(settings, repo, limit=args.limit))
        elif args.phase == "all":
            asyncio.run(run_all(args.country, args.sector, settings, repo, limit=args.limit))
        elif args.phase == "enrich":
            asyncio.run(
                run_enrich(
                    country=args.country,
                    sector=args.sector,
                    settings=settings,
                    limit=args.limit,
                    re_enrich=getattr(args, "re_enrich", False),
                )
            )
        elif args.phase == "score":
            asyncio.run(run_score(args.country, args.sector, settings))
        elif args.phase == "vectorize":
            asyncio.run(run_vectorize(args.country, args.sector, settings))
    except KeyboardInterrupt:
        log.info("interrupted_by_user")
    except Exception as exc:
        log.error("fatal_error", error=str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
