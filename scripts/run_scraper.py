#!/usr/bin/env python
"""
Zawya company scraper — entry point.

Usage:
    # Phase 1: scrape all listing pages (fast, ~681 pages via httpx)
    python scripts/run_scraper.py listings

    # Phase 2: scrape company detail pages (slow, uses Playwright)
    python scripts/run_scraper.py details

    # Test Phase 2 with just 5 records
    python scripts/run_scraper.py details --limit 5

    # Run both phases end-to-end
    python scripts/run_scraper.py all
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
from hak_talent_mapping.core.models import CompanyDetail
from hak_talent_mapping.db.repository import CompanyRepository
from hak_talent_mapping.services.detail_scraper import scrape_all_details
from hak_talent_mapping.services.listing_scraper import scrape_all_listings


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


async def run_listings(settings: Settings, repo: CompanyRepository) -> None:
    """Phase 1 — scrape all listing pages and upsert into Supabase."""
    log = structlog.get_logger()

    log.info("phase1_start", total_pages=settings.total_pages)

    # Resume: skip companies already in DB
    already_scraped = await repo.get_scraped_listing_ids_async()
    log.info("resume_info", already_scraped=len(already_scraped))

    companies = await scrape_all_listings(settings, already_scraped=already_scraped)

    if not companies:
        log.info("no_new_companies_found")
        return

    # Upsert in batches of 200 to avoid hitting Supabase payload limits
    batch_size = 200
    for i in range(0, len(companies), batch_size):
        batch = companies[i : i + batch_size]
        await repo.upsert_many_async(batch)

    log.info("phase1_complete", total_upserted=len(companies))


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
    settings: Settings, repo: CompanyRepository, limit: int | None = None
) -> None:
    await run_listings(settings, repo)
    if settings.scrape_details:
        await run_details(settings, repo, limit=limit)


def main() -> None:
    _configure_logging()
    log = structlog.get_logger()

    parser = argparse.ArgumentParser(
        description="Scrape Zawya company listings into Supabase"
    )
    parser.add_argument(
        "phase",
        choices=["listings", "details", "all"],
        help=(
            "listings: scrape company list pages only  |  "
            "details: scrape company detail pages only  |  "
            "all: run both phases"
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        metavar="N",
        help="Only scrape the first N companies (useful for testing details)",
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

    log.info("scraper_starting", phase=args.phase, limit=args.limit)

    try:
        if args.phase == "listings":
            asyncio.run(run_listings(settings, repo))
        elif args.phase == "details":
            asyncio.run(run_details(settings, repo, limit=args.limit))
        else:
            asyncio.run(run_all(settings, repo, limit=args.limit))
    except KeyboardInterrupt:
        log.info("interrupted_by_user")
    except Exception as exc:
        log.error("fatal_error", error=str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
