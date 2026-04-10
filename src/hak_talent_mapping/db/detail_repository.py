from __future__ import annotations

import asyncio
from typing import Any

import structlog
from supabase import Client

from hak_talent_mapping.core.exceptions import DatabaseError
from hak_talent_mapping.core.models import CompanyProfile, EnrichmentStatus

logger = structlog.get_logger()

_TABLE = "company_details"
_COMPANIES_TABLE = "companies"
_PAGE_SIZE = 1000

# Mapping from ISO country code to the full country name stored in the companies table.
_COUNTRY_CODE_TO_NAME: dict[str, str] = {
    "AE": "United Arab Emirates",
    "SA": "Saudi Arabia",
    "KW": "Kuwait",
    "QA": "Qatar",
    "BH": "Bahrain",
    "OM": "Oman",
    "EG": "Egypt",
    "JO": "Jordan",
    "LB": "Lebanon",
}


class DetailRepository:
    """Handles all Supabase persistence for company_details rows."""

    def __init__(self, client: Client) -> None:
        self._client = client

    # ------------------------------------------------------------------ #
    # Write operations                                                     #
    # ------------------------------------------------------------------ #

    def create(self, profile: CompanyProfile) -> CompanyProfile:
        """Insert a new company_details row and return it with its DB id."""
        data: dict[str, Any] = {
            "company_id": profile.company_id,
            "sector": profile.sector,
            "country_code": profile.country_code,
            "name": profile.name,
            "enrichment_status": EnrichmentStatus.PENDING.value,
            "enrichment_version": profile.enrichment_version,
        }
        if profile.companies_id is not None:
            data["companies_id"] = profile.companies_id
        try:
            response = (
                self._client.table(_TABLE)
                .upsert(data, on_conflict="company_id,sector")
                .execute()
            )
            row = response.data[0]
            return profile.model_copy(update={"id": row["id"]})
        except Exception as exc:
            raise DatabaseError(
                f"Failed to create detail row for {profile.company_id}"
            ) from exc

    def update_status(
        self,
        detail_id: str,
        status: EnrichmentStatus,
        error: str | None = None,
    ) -> None:
        """Update the enrichment_status (and optionally enrichment_error) for a row."""
        patch: dict[str, Any] = {"enrichment_status": status.value}
        if error is not None:
            patch["enrichment_error"] = error
        elif status != EnrichmentStatus.FAILED:
            patch["enrichment_error"] = None
        try:
            self._client.table(_TABLE).update(patch).eq("id", detail_id).execute()
        except Exception as exc:
            raise DatabaseError(
                f"Failed to update status for detail {detail_id}"
            ) from exc

    def upsert_raw_search(self, detail_id: str, results: list[dict[str, Any]]) -> None:
        """Store raw search results JSONB and advance status."""
        try:
            self._client.table(_TABLE).update(
                {
                    "raw_search_results": results,
                    "enrichment_status": EnrichmentStatus.WEB_SEARCH_DONE.value,
                }
            ).eq("id", detail_id).execute()
        except Exception as exc:
            raise DatabaseError(
                f"Failed to store search results for detail {detail_id}"
            ) from exc

    def upsert_raw_website(self, detail_id: str, data: dict[str, Any]) -> None:
        """Store raw website data JSONB and advance status."""
        try:
            self._client.table(_TABLE).update(
                {
                    "raw_website_data": data,
                    "enrichment_status": EnrichmentStatus.WEBSITE_SCRAPED.value,
                }
            ).eq("id", detail_id).execute()
        except Exception as exc:
            raise DatabaseError(
                f"Failed to store website data for detail {detail_id}"
            ) from exc

    def upsert_profile(self, profile: CompanyProfile) -> None:
        """Persist all extracted profile fields and advance to llm_extracted."""
        patch: dict[str, Any] = {
            "name": profile.name,
            "domain": profile.domain,
            "description_clean": profile.description_clean,
            "country_code": profile.country_code,
            "country": profile.country,
            "city": profile.city,
            "region": profile.region,
            "sub_sector": profile.sub_sector,
            "sub_sector_tags": profile.sub_sector_tags,
            "funding_stage": profile.funding_stage,
            "funding_total_usd": profile.funding_total_usd,
            "headcount_range": profile.headcount_range,
            "headcount_exact": profile.headcount_exact,
            "founded_year": profile.founded_year,
            "sector_metadata": profile.sector_metadata,
            "raw_llm_extraction": profile.sector_metadata,
            "enrichment_status": EnrichmentStatus.LLM_EXTRACTED.value,
        }
        try:
            self._client.table(_TABLE).update(patch).eq("id", profile.id).execute()
        except Exception as exc:
            raise DatabaseError(
                f"Failed to upsert profile for detail {profile.id}"
            ) from exc

    def mark_profile_complete(
        self,
        detail_id: str,
        quality_score: float,
        content_hash: str,
    ) -> None:
        """Finalize profile with quality score + hash, set status=profile_complete."""
        try:
            self._client.table(_TABLE).update(
                {
                    "data_quality_score": quality_score,
                    "content_hash": content_hash,
                    "enrichment_status": EnrichmentStatus.PROFILE_COMPLETE.value,
                }
            ).eq("id", detail_id).execute()
        except Exception as exc:
            raise DatabaseError(
                f"Failed to mark profile complete for {detail_id}"
            ) from exc

    def mark_pinecone_synced(
        self,
        detail_id: str,
        embedding_model: str,
        synced_at: str,
    ) -> None:
        """Record that the vector was upserted to Pinecone."""
        try:
            self._client.table(_TABLE).update(
                {
                    "pinecone_synced_at": synced_at,
                    "embedding_model": embedding_model,
                }
            ).eq("id", detail_id).execute()
        except Exception as exc:
            raise DatabaseError(
                f"Failed to mark pinecone synced for {detail_id}"
            ) from exc

    # ------------------------------------------------------------------ #
    # Read operations                                                      #
    # ------------------------------------------------------------------ #

    def get_companies_to_enrich(
        self,
        sector: str,
        country_code: str,
        top_only: bool = True,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return companies from the companies table that still need enriching.

        Excludes companies that already have a profile_complete detail row.
        Respects top_only flag to filter by top_company=true.
        """
        try:
            # IDs already enriched (profile_complete) for this sector/country
            done_resp = (
                self._client.table(_TABLE)
                .select("company_id")
                .eq("sector", sector)
                .eq("enrichment_status", EnrichmentStatus.PROFILE_COMPLETE.value)
                .execute()
            )
            done_ids = {row["company_id"] for row in (done_resp.data or [])}

            results: list[dict[str, Any]] = []
            offset = 0
            while True:
                query = (
                    self._client.table(_COMPANIES_TABLE)
                    .select("id,company_id,name,sector,country,website,slug")
                    .eq("sector", sector)
                )
                if country_code:
                    country_name = _COUNTRY_CODE_TO_NAME.get(country_code, country_code)
                    query = query.eq("country", country_name)
                if top_only:
                    query = query.eq("top_company", True)
                response = query.range(offset, offset + _PAGE_SIZE - 1).execute()
                if not response.data:
                    break
                for row in response.data:
                    if row["company_id"] not in done_ids:
                        results.append(row)
                if len(response.data) < _PAGE_SIZE:
                    break
                offset += _PAGE_SIZE

            if limit is not None:
                return results[:limit]
            return results
        except Exception as exc:
            raise DatabaseError(
                f"Failed to fetch companies to enrich for {sector}/{country_code}"
            ) from exc

    def get_by_id(self, detail_id: str) -> dict[str, Any] | None:
        """Fetch a single company_details row by id."""
        try:
            response = (
                self._client.table(_TABLE).select("*").eq("id", detail_id).execute()
            )
            return response.data[0] if response.data else None
        except Exception as exc:
            raise DatabaseError(
                f"Failed to fetch detail row {detail_id}"
            ) from exc

    def get_by_company_sector(
        self, company_id: str, sector: str
    ) -> dict[str, Any] | None:
        """Fetch a company_details row by (company_id, sector)."""
        try:
            response = (
                self._client.table(_TABLE)
                .select("*")
                .eq("company_id", company_id)
                .eq("sector", sector)
                .execute()
            )
            return response.data[0] if response.data else None
        except Exception as exc:
            raise DatabaseError(
                f"Failed to fetch detail for {company_id}/{sector}"
            ) from exc

    def get_profile_complete(
        self,
        sector: str,
        country_code: str,
        unsynced_only: bool = False,
    ) -> list[dict[str, Any]]:
        """Return all profile_complete rows for scoring / vectorization."""
        try:
            results: list[dict[str, Any]] = []
            offset = 0
            while True:
                query = (
                    self._client.table(_TABLE)
                    .select("*")
                    .eq("sector", sector)
                    .eq("country_code", country_code)
                    .eq("enrichment_status", EnrichmentStatus.PROFILE_COMPLETE.value)
                )
                if unsynced_only:
                    query = query.is_("pinecone_synced_at", "null")
                response = query.range(offset, offset + _PAGE_SIZE - 1).execute()
                if not response.data:
                    break
                results.extend(response.data)
                if len(response.data) < _PAGE_SIZE:
                    break
                offset += _PAGE_SIZE
            return results
        except Exception as exc:
            raise DatabaseError(
                f"Failed to fetch profile_complete rows for {sector}/{country_code}"
            ) from exc

    # ------------------------------------------------------------------ #
    # Async wrappers                                                       #
    # ------------------------------------------------------------------ #

    async def create_async(self, profile: CompanyProfile) -> CompanyProfile:
        return await asyncio.to_thread(self.create, profile)

    async def update_status_async(
        self,
        detail_id: str,
        status: EnrichmentStatus,
        error: str | None = None,
    ) -> None:
        await asyncio.to_thread(self.update_status, detail_id, status, error)

    async def upsert_raw_search_async(
        self, detail_id: str, results: list[dict[str, Any]]
    ) -> None:
        await asyncio.to_thread(self.upsert_raw_search, detail_id, results)

    async def upsert_raw_website_async(
        self, detail_id: str, data: dict[str, Any]
    ) -> None:
        await asyncio.to_thread(self.upsert_raw_website, detail_id, data)

    async def upsert_profile_async(self, profile: CompanyProfile) -> None:
        await asyncio.to_thread(self.upsert_profile, profile)

    async def mark_profile_complete_async(
        self,
        detail_id: str,
        quality_score: float,
        content_hash: str,
    ) -> None:
        await asyncio.to_thread(
            self.mark_profile_complete, detail_id, quality_score, content_hash
        )

    async def mark_pinecone_synced_async(
        self,
        detail_id: str,
        embedding_model: str,
        synced_at: str,
    ) -> None:
        await asyncio.to_thread(
            self.mark_pinecone_synced, detail_id, embedding_model, synced_at
        )

    async def get_companies_to_enrich_async(
        self,
        sector: str,
        country_code: str,
        top_only: bool = True,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self.get_companies_to_enrich, sector, country_code, top_only, limit
        )

    async def get_profile_complete_async(
        self,
        sector: str,
        country_code: str,
        unsynced_only: bool = False,
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self.get_profile_complete, sector, country_code, unsynced_only
        )
