from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from hak_talent_mapping.core.exceptions import VectorStoreError
from hak_talent_mapping.db.detail_repository import DetailRepository
from hak_talent_mapping.db.score_repository import ScoreRepository
from hak_talent_mapping.services.vector.embeddings import (
    OpenAIEmbeddingProvider,
    build_embed_text,
    build_pinecone_metadata,
)

logger = structlog.get_logger()

_DEFAULT_BATCH_SIZE = 100


class PineconeStore:
    """Upserts company vectors into a Pinecone index."""

    def __init__(
        self,
        api_key: str,
        index_name: str,
    ) -> None:
        try:
            from pinecone import Pinecone  # type: ignore[import]
        except ImportError as exc:
            raise VectorStoreError(
                "pinecone-client is not installed. Run: uv add pinecone-client"
            ) from exc

        pc = Pinecone(api_key=api_key)
        self._index = pc.Index(index_name)
        self._index_name = index_name

    def upsert_vectors(self, vectors: list[dict[str, Any]]) -> None:
        """Upsert a list of vector dicts to Pinecone.

        Each dict must have: id (str), values (list[float]), metadata (dict).
        """
        if not vectors:
            return
        try:
            self._index.upsert(vectors=vectors)
            logger.info("pinecone_upsert", count=len(vectors), index=self._index_name)
        except Exception as exc:
            raise VectorStoreError(f"Pinecone upsert failed: {exc}") from exc

    def describe_stats(self) -> dict[str, Any]:
        """Return index stats (useful for verification)."""
        try:
            return dict(self._index.describe_index_stats())
        except Exception as exc:
            raise VectorStoreError(f"Pinecone stats failed: {exc}") from exc


class VectorizationRunner:
    """Orchestrates Stage 7: embed + upsert all profile_complete companies."""

    def __init__(
        self,
        detail_repo: DetailRepository,
        score_repo: ScoreRepository,
        embedding_provider: OpenAIEmbeddingProvider,
        pinecone_store: PineconeStore,
        embedding_model: str,
        batch_size: int = _DEFAULT_BATCH_SIZE,
    ) -> None:
        self._detail_repo = detail_repo
        self._score_repo = score_repo
        self._embeddings = embedding_provider
        self._pinecone = pinecone_store
        self._embedding_model = embedding_model
        self._batch_size = batch_size

    async def run(
        self,
        sector: str,
        country_code: str,
        scoring_config_id: str,
    ) -> dict[str, int]:
        """Embed all unsynced profile_complete rows and upsert to Pinecone.

        Returns summary counts.
        """
        profile_rows = await self._detail_repo.get_profile_complete_async(
            sector=sector,
            country_code=country_code,
            unsynced_only=True,
        )

        if not profile_rows:
            logger.info("vectorize_nothing_to_do", sector=sector)
            return {"processed": 0, "skipped": 0}

        logger.info("vectorize_start", count=len(profile_rows), sector=sector)
        processed = 0
        skipped = 0

        # Process in batches
        for batch_start in range(0, len(profile_rows), self._batch_size):
            batch = profile_rows[batch_start : batch_start + self._batch_size]
            vectors, synced_ids = await self._build_vectors(batch, scoring_config_id)
            if vectors:
                self._pinecone.upsert_vectors(vectors)
                now = datetime.now(timezone.utc).isoformat()
                for detail_id in synced_ids:
                    await self._detail_repo.mark_pinecone_synced_async(
                        detail_id=detail_id,
                        embedding_model=self._embedding_model,
                        synced_at=now,
                    )
                processed += len(vectors)
            skipped += len(batch) - len(vectors)

        logger.info("vectorize_done", processed=processed, skipped=skipped)
        return {"processed": processed, "skipped": skipped}

    async def _build_vectors(
        self,
        profile_rows: list[dict[str, Any]],
        scoring_config_id: str,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Build Pinecone vector dicts for a batch of profiles."""
        texts: list[str] = []
        score_rows: list[dict[str, Any] | None] = []

        for row in profile_rows:
            scores = self._score_repo.get_by_detail_id(row["id"])
            score_row = next(
                (s for s in scores if s["scoring_config_id"] == scoring_config_id),
                scores[0] if scores else None,
            )
            score_rows.append(score_row)
            texts.append(build_embed_text(row, score_row))

        embeddings = await self._embeddings.embed_texts(texts)

        vectors: list[dict[str, Any]] = []
        synced_ids: list[str] = []

        for i, (profile_row, score_row, embedding) in enumerate(
            zip(profile_rows, score_rows, embeddings, strict=True)
        ):
            vector_id = f"{profile_row['company_id']}_{profile_row['sector']}"
            metadata = build_pinecone_metadata(profile_row, score_row)
            vectors.append(
                {
                    "id": vector_id,
                    "values": embedding,
                    "metadata": metadata,
                }
            )
            synced_ids.append(profile_row["id"])

        return vectors, synced_ids
