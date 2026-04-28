#!/usr/bin/env python
"""
Perplexity enrichment — Phase 3 Stages 1-5.

Perplexity handles web retrieval + LLM extraction in a single provider.
No Serper or OpenRouter needed.

Usage:
    python scripts/run_enrich_perplexity.py --country AE --sector Retailers
    python scripts/run_enrich_perplexity.py --country AE --sector Retailers --limit 10
    python scripts/run_enrich_perplexity.py --country AE --sector Retailers --re-enrich
    python scripts/run_enrich_perplexity.py --country AE --sector Retailers --test --limit 5
      (--test: reads companies from Supabase, writes enrichment results to local SQLite)
"""
from __future__ import annotations

import argparse
import asyncio
import sys

import structlog

sys.path.insert(0, "src")

from hak_talent_mapping.services.enrichment.pipeline import EnrichmentPipeline, EnrichmentRunner
from hak_talent_mapping.services.enrichment.website_scraper import WebsiteScraper
from hak_talent_mapping.services.llm.perplexity_provider import PerplexityProvider

from _enrich_common import (
    configure_logging,
    load_sector_config_or_exit,
    load_settings,
    preflight_check,
    reset_re_enrich,
    setup_repos,
)


async def main() -> None:
    configure_logging()
    log = structlog.get_logger()

    parser = argparse.ArgumentParser(
        description="Enrich companies via Perplexity grounded search (Phase 3, Stages 1-5)"
    )
    parser.add_argument("--country", required=True, metavar="CODE", help="Country code, e.g. AE")
    parser.add_argument("--sector", required=True, metavar="SECTOR", help="Sector name, e.g. Retailers")
    parser.add_argument("--limit", type=int, default=None, metavar="N", help="Max companies to process")
    parser.add_argument("--re-enrich", action="store_true", help="Reset profile_complete rows back to pending")
    parser.add_argument("--test", action="store_true", help="Read companies from Supabase, write results to local SQLite")
    parser.add_argument("--db", type=str, default="local_test.db", metavar="PATH", help="Local SQLite path (--test only)")
    args = parser.parse_args()

    settings = load_settings()

    if not args.test:
        preflight_check(settings, require_perplexity=True)

    if args.re_enrich and not args.test:
        reset_re_enrich(args.sector, settings)

    list_repo, pipeline_repo, audit_repo = setup_repos(
        country=args.country,
        sector=args.sector,
        settings=settings,
        test_mode=args.test,
        local_db_path=args.db,
        limit=args.limit,
    )

    metadata_schema, query_templates, llm_guidance = load_sector_config_or_exit(args.sector, settings)

    companies = await list_repo.get_companies_to_enrich_async(
        sector=args.sector,
        country_code=args.country,
        top_only=settings.enrich_top_only,
        limit=args.limit,
    )

    if not companies:
        log.info("no_companies_to_enrich", sector=args.sector, country=args.country)
        return

    for company in companies:
        company["country_code"] = args.country

    log.info(
        "enrich_start",
        provider="perplexity",
        model=settings.perplexity_model,
        company_count=len(companies),
        sector=args.sector,
        country=args.country,
    )

    pipeline = EnrichmentPipeline(
        settings=settings,
        detail_repo=pipeline_repo,
        audit_repo=audit_repo,
        search_service=None,
        website_scraper=WebsiteScraper(timeout=settings.website_scrape_timeout),
        llm_provider=PerplexityProvider(
            api_key=settings.perplexity_api_key,
            model=settings.perplexity_model,
            country=args.country,
        ),
    )
    runner = EnrichmentRunner(pipeline, concurrency=settings.enrichment_concurrency)
    summary = await runner.run_batch(
        companies,
        sector_metadata_schema=metadata_schema,
        query_templates=query_templates,
        llm_guidance=llm_guidance,
    )
    log.info("enrich_complete", **summary)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        structlog.get_logger().info("interrupted_by_user")
    except Exception as exc:
        structlog.get_logger().error("fatal_error", error=str(exc))
        sys.exit(1)
