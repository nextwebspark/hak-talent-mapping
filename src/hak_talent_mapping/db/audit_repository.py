from __future__ import annotations

import asyncio
from typing import Any

import structlog
from supabase import Client

from hak_talent_mapping.core.exceptions import DatabaseError

logger = structlog.get_logger()

_TABLE = "enrichment_audit"


class AuditRepository:
    """Writes enrichment audit events to the enrichment_audit table."""

    def __init__(self, client: Client) -> None:
        self._client = client

    def log_event(
        self,
        company_detail_id: str,
        stage: str,
        event_type: str,
        request_data: dict[str, Any],
        response_data: dict[str, Any],
    ) -> None:
        try:
            self._client.table(_TABLE).insert(
                {
                    "company_detail_id": company_detail_id,
                    "stage": stage,
                    "event_type": event_type,
                    "request_data": request_data,
                    "response_data": response_data,
                }
            ).execute()
        except Exception as exc:
            # Audit failures must never abort the pipeline
            logger.warning(
                "audit_log_failed",
                stage=stage,
                event_type=event_type,
                error=str(exc),
            )

    async def log_event_async(
        self,
        company_detail_id: str,
        stage: str,
        event_type: str,
        request_data: dict[str, Any],
        response_data: dict[str, Any],
    ) -> None:
        await asyncio.to_thread(
            self.log_event,
            company_detail_id,
            stage,
            event_type,
            request_data,
            response_data,
        )
