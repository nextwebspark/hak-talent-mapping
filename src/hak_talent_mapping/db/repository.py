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
        """Insert or update a batch of companies (keyed on company_id + sector)."""
        if not companies:
            return
        try:
            data = [c.model_dump(mode="json") for c in companies]
            self._client.table(_TABLE).upsert(
                data, on_conflict="company_id,sector"
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

    def get_scraped_listing_ids(self, page_size: int = 1000) -> set[tuple[str, str]]:
        """Return (company_id, sector) pairs already saved, to skip re-scraping.

        Paginates through all Supabase rows — works around the default 1000-row cap.
        """
        ids: set[tuple[str, str]] = set()
        offset = 0
        while True:
            response = (
                self._client.table(_TABLE)
                .select("company_id,sector")
                .not_.is_("listing_scraped_at", "null")
                .range(offset, offset + page_size - 1)
                .execute()
            )
            if not response.data:
                break
            ids.update((row["company_id"], row["sector"]) for row in response.data)
            if len(response.data) < page_size:
                break
            offset += page_size
        return ids

    def get_pending_detail_companies(self, page_size: int = 1000) -> list[tuple[str, str]]:
        """Return (company_id, profile_url) for companies still needing detail scrape.

        Paginates through all Supabase rows — works around the default 1000-row cap.
        """
        results: list[tuple[str, str]] = []
        offset = 0
        while True:
            response = (
                self._client.table(_TABLE)
                .select("company_id,profile_url")
                .is_("detail_scraped_at", "null")
                .range(offset, offset + page_size - 1)
                .execute()
            )
            if not response.data:
                break
            results.extend(
                (row["company_id"], row["profile_url"]) for row in response.data
            )
            if len(response.data) < page_size:
                break  # last page
            offset += page_size
        return results

    # ------------------------------------------------------------------ #
    # Async wrappers (run sync Supabase client in a thread)               #
    # ------------------------------------------------------------------ #

    async def upsert_many_async(self, companies: list[Company]) -> None:
        await asyncio.to_thread(self.upsert_many, companies)

    async def update_detail_async(
        self, company_id: str, detail: CompanyDetail
    ) -> None:
        await asyncio.to_thread(self.update_detail, company_id, detail)

    async def get_scraped_listing_ids_async(self) -> set[tuple[str, str]]:
        return await asyncio.to_thread(self.get_scraped_listing_ids)

    async def get_pending_detail_companies_async(self) -> list[tuple[str, str]]:
        return await asyncio.to_thread(self.get_pending_detail_companies)
