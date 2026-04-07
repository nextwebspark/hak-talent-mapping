from __future__ import annotations

import asyncio
from typing import Any

import structlog
from supabase import Client

from hak_talent_mapping.core.exceptions import DatabaseError
from hak_talent_mapping.core.models import CompanyScoreRecord

logger = structlog.get_logger()

_TABLE = "company_scores"


class ScoreRepository:
    """Handles all Supabase persistence for company_scores rows."""

    def __init__(self, client: Client) -> None:
        self._client = client

    # ------------------------------------------------------------------ #
    # Write operations                                                     #
    # ------------------------------------------------------------------ #

    def upsert_scores(self, record: CompanyScoreRecord) -> CompanyScoreRecord:
        """Insert or update a score record, keyed on (company_detail_id, scoring_config_id)."""
        data: dict[str, Any] = {
            "company_detail_id": record.company_detail_id,
            "base_score": record.base_score,
            "dimension_scores": {
                k: v.model_dump() for k, v in record.dimension_scores.items()
            },
            "confidence_bands": {
                k: v.model_dump() for k, v in record.confidence_bands.items()
            },
            "overall_confidence_band": record.overall_confidence_band,
            "overall_tolerance_pct": record.overall_tolerance_pct,
            "sub_sector_gate_result": record.sub_sector_gate_result,
            "sub_sector_classified": record.sub_sector_classified,
            "brief_adjusted_score": record.brief_adjusted_score,
            "applied_archetype": record.applied_archetype,
            "d4_is_enriching": record.d4_is_enriching,
            "scoring_config_id": record.scoring_config_id,
            "config_hash": record.config_hash,
        }
        try:
            response = (
                self._client.table(_TABLE)
                .upsert(
                    data,
                    on_conflict="company_detail_id,scoring_config_id",
                )
                .execute()
            )
            row = response.data[0]
            return record.model_copy(update={"id": row["id"]})
        except Exception as exc:
            raise DatabaseError(
                f"Failed to upsert scores for detail {record.company_detail_id}"
            ) from exc

    # ------------------------------------------------------------------ #
    # Read operations                                                      #
    # ------------------------------------------------------------------ #

    def get_by_detail_id(
        self, company_detail_id: str
    ) -> list[dict[str, Any]]:
        """Return all score records for a company_detail."""
        try:
            response = (
                self._client.table(_TABLE)
                .select("*")
                .eq("company_detail_id", company_detail_id)
                .execute()
            )
            return response.data or []
        except Exception as exc:
            raise DatabaseError(
                f"Failed to fetch scores for detail {company_detail_id}"
            ) from exc

    def get_unvectorized(
        self,
        scoring_config_id: str,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Return score records whose parent detail has not been synced to Pinecone."""
        try:
            response = (
                self._client.table(_TABLE)
                .select("*, company_details!inner(id,pinecone_synced_at,sector,country_code)")
                .eq("scoring_config_id", scoring_config_id)
                .is_("company_details.pinecone_synced_at", "null")
                .limit(limit)
                .execute()
            )
            return response.data or []
        except Exception as exc:
            raise DatabaseError(
                "Failed to fetch unvectorized score records"
            ) from exc

    # ------------------------------------------------------------------ #
    # Async wrappers                                                       #
    # ------------------------------------------------------------------ #

    async def upsert_scores_async(
        self, record: CompanyScoreRecord
    ) -> CompanyScoreRecord:
        return await asyncio.to_thread(self.upsert_scores, record)

    async def get_by_detail_id_async(
        self, company_detail_id: str
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(self.get_by_detail_id, company_detail_id)
