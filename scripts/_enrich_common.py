"""Shared helpers for enrichment entry point scripts."""
from __future__ import annotations

import logging
import sys
from typing import Any

import httpx

import structlog
from supabase import create_client

sys.path.insert(0, "src")

from hak_talent_mapping.config import Settings
from hak_talent_mapping.db.audit_repository import AuditRepository
from hak_talent_mapping.db.detail_repository import DetailRepository
from hak_talent_mapping.db.local_repository import LocalAuditRepository, LocalDetailRepository
from hak_talent_mapping.services.enrichment.scoring.config_loader import (
    get_sector_metadata_schema,
    load_sector_config,
)


def configure_logging() -> None:
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
    logging.getLogger("asyncio").setLevel(logging.ERROR)


def load_settings() -> Settings:
    log = structlog.get_logger()
    try:
        return Settings()  # type: ignore[call-arg]
    except Exception as exc:
        log.error("config_error", error=str(exc))
        log.error("hint", message="Copy .env.example to .env and fill in your credentials")
        sys.exit(1)


def load_sector_config_or_exit(
    sector: str,
    settings: Settings,
) -> tuple[Any, list[str] | None, str | None]:
    """Return (metadata_schema, query_templates, llm_guidance) or exit on error."""
    log = structlog.get_logger()
    try:
        sector_config = load_sector_config(sector, settings.scoring_config_dir)
        metadata_schema = get_sector_metadata_schema(sector_config)
        query_templates: list[str] | None = sector_config.search_queries or None
        llm_guidance: str | None = sector_config.llm_guidance or None
        log.info("sector_config_loaded", config_id=sector_config.config_id)
        return metadata_schema, query_templates, llm_guidance
    except Exception as exc:
        log.error("sector_config_error", error=str(exc))
        return None, None, None


def setup_repos(
    country: str,
    sector: str,
    settings: Settings,
    test_mode: bool,
    local_db_path: str,
    limit: int | None,
) -> tuple[DetailRepository, DetailRepository | LocalDetailRepository, AuditRepository | LocalAuditRepository]:
    """Create repos for enrichment.

    Returns (list_repo, pipeline_repo, audit_repo):
      - list_repo    — always Supabase; used only to fetch companies to enrich
      - pipeline_repo — Supabase normally; LocalDetailRepository in test mode (writes stay local)
      - audit_repo   — Supabase normally; LocalAuditRepository in test mode
    """
    log = structlog.get_logger()
    supabase_client = create_client(settings.supabase_url, settings.supabase_key)
    supabase_detail_repo = DetailRepository(supabase_client)

    if test_mode:
        log.info("test_mode_active", db=local_db_path)
        return (
            supabase_detail_repo,
            LocalDetailRepository(local_db_path),
            LocalAuditRepository(local_db_path),
        )

    return supabase_detail_repo, supabase_detail_repo, AuditRepository(supabase_client)


def preflight_check(settings: Settings, require_perplexity: bool = False) -> None:
    """Validate external service connectivity before starting enrichment.

    Exits with code 1 on any failure so errors surface immediately
    rather than after hours of processing.
    """
    log = structlog.get_logger()
    log.info("preflight_start")
    errors: list[str] = []

    # Supabase
    try:
        client = create_client(settings.supabase_url, settings.supabase_key)
        resp = client.table("companies").select("company_id").limit(1).execute()
        _ = resp.data  # triggers actual network call
        log.info("preflight_supabase", status="ok")
    except Exception as exc:
        errors.append(f"Supabase unreachable: {exc}")
        log.error("preflight_supabase", status="failed", error=str(exc))

    # Perplexity
    if require_perplexity:
        if not settings.perplexity_api_key:
            errors.append("PERPLEXITY_API_KEY not set")
        else:
            try:
                r = httpx.get(
                    "https://api.perplexity.ai/",
                    headers={"Authorization": f"Bearer {settings.perplexity_api_key}"},
                    timeout=10,
                )
                # 401/403 = key wrong but API is reachable; anything else = network issue
                if r.status_code not in (200, 401, 403, 404, 405):
                    errors.append(f"Perplexity API returned unexpected {r.status_code}")
                log.info("preflight_perplexity", status="ok", http=r.status_code)
            except Exception as exc:
                errors.append(f"Perplexity API unreachable: {exc}")
                log.error("preflight_perplexity", status="failed", error=str(exc))
    else:
        if not settings.serper_api_key:
            errors.append("SERPER_API_KEY not set")
        if not settings.openrouter_api_key:
            errors.append("OPENROUTER_API_KEY not set")
        if settings.serper_api_key:
            try:
                r = httpx.get("https://google.serper.dev/", timeout=10)
                log.info("preflight_serper", status="ok", http=r.status_code)
            except Exception as exc:
                errors.append(f"Serper API unreachable: {exc}")
                log.error("preflight_serper", status="failed", error=str(exc))

    if errors:
        for e in errors:
            log.error("preflight_failed", reason=e)
        log.error("preflight_abort", hint="Fix the above issues before running in production")
        sys.exit(1)

    log.info("preflight_passed")


def reset_re_enrich(sector: str, settings: Settings) -> None:
    log = structlog.get_logger()
    client = create_client(settings.supabase_url, settings.supabase_key)
    client.table("company_details").update(
        {"enrichment_status": "pending", "enrichment_error": None}
    ).eq("sector", sector).eq("enrichment_status", "profile_complete").execute()
    log.info("re_enrich_reset", sector=sector)
