from __future__ import annotations

import asyncio

import structlog
from supabase import Client

from hak_talent_mapping.core.exceptions import DatabaseError
from hak_talent_mapping.core.models import Company, CompanyDetail

logger = structlog.get_logger()

_TABLE = "companies"


class CompanyRepository:
    """Handles all Supabase persistence for Company records."""

    def __init__(self, client: Client) -> None:
        self._client = client

    # ------------------------------------------------------------------ #
    # Write operations                                                     #
    # ------------------------------------------------------------------ #

    def upsert_many(self, companies: list[Company]) -> None:
        """Insert or update a batch of companies (keyed on company_id)."""
        if not companies:
            return
        try:
            data = [c.model_dump(mode="json") for c in companies]
            self._client.table(_TABLE).upsert(
                data, on_conflict="company_id"
            ).execute()
            logger.info("upserted_batch", count=len(companies))
        except Exception as exc:
            raise DatabaseError(
                f"Failed to upsert batch of {len(companies)} companies"
            ) from exc

    def update_detail(self, company_id: str, detail: CompanyDetail) -> None:
        """Patch a company row with detail-page data."""
        try:
            self._client.table(_TABLE).update(
                dict(detail)  # type: ignore[arg-type]  # TypedDict is a plain dict at runtime
            ).eq("company_id", company_id).execute()
        except Exception as exc:
            raise DatabaseError(
                f"Failed to update detail for company {company_id}"
            ) from exc

    # ------------------------------------------------------------------ #
    # Read operations                                                      #
    # ------------------------------------------------------------------ #

    def get_scraped_listing_ids(self) -> set[str]:
        """Return IDs of companies whose listing data has been saved."""
        response = (
            self._client.table(_TABLE)
            .select("company_id")
            .not_.is_("listing_scraped_at", "null")
            .execute()
        )
        return {row["company_id"] for row in response.data}

    def get_pending_detail_companies(self) -> list[tuple[str, str]]:
        """Return (company_id, profile_url) for companies still needing detail scrape."""
        response = (
            self._client.table(_TABLE)
            .select("company_id,profile_url")
            .is_("detail_scraped_at", "null")
            .execute()
        )
        return [(row["company_id"], row["profile_url"]) for row in response.data]

    # ------------------------------------------------------------------ #
    # Async wrappers (run sync Supabase client in a thread)               #
    # ------------------------------------------------------------------ #

    async def upsert_many_async(self, companies: list[Company]) -> None:
        await asyncio.to_thread(self.upsert_many, companies)

    async def update_detail_async(
        self, company_id: str, detail: CompanyDetail
    ) -> None:
        await asyncio.to_thread(self.update_detail, company_id, detail)

    async def get_scraped_listing_ids_async(self) -> set[str]:
        return await asyncio.to_thread(self.get_scraped_listing_ids)

    async def get_pending_detail_companies_async(self) -> list[tuple[str, str]]:
        return await asyncio.to_thread(self.get_pending_detail_companies)
