from __future__ import annotations

import structlog
from openai import AsyncOpenAI

from hak_talent_mapping.core.exceptions import VectorStoreError

logger = structlog.get_logger()

_DEFAULT_MODEL = "openai/text-embedding-3-small"
_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_EMBED_DIMENSIONS = 1536


def build_embed_text(profile_row: dict, score_row: dict | None = None) -> str:
    """Build the text string that gets embedded for a company.

    Combines identity, profile, and score signals into a single rich
    text representation for semantic search.
    """
    parts: list[str] = []

    name = profile_row.get("name", "")
    sector = profile_row.get("sector", "")
    description = profile_row.get("description_clean", "") or ""
    sub_sector = profile_row.get("sub_sector", "") or ""
    city = profile_row.get("city", "") or ""
    region = profile_row.get("region", "") or ""
    headcount_range = profile_row.get("headcount_range", "") or ""
    founded_year = profile_row.get("founded_year")

    if name:
        parts.append(name)
    if sector:
        parts.append(f"Sector: {sector}")
    if sub_sector:
        parts.append(f"Sub-sector: {sub_sector}")
    if city or region:
        loc = ", ".join(filter(None, [city, region]))
        parts.append(f"Location: {loc}")
    if description:
        parts.append(description)
    if headcount_range:
        parts.append(f"Team size: {headcount_range}")
    if founded_year:
        parts.append(f"Founded: {founded_year}")

    # Sector metadata signals
    sector_meta = profile_row.get("sector_metadata") or {}
    store_count = sector_meta.get("store_count")
    brands = sector_meta.get("brands_owned") or []
    if store_count:
        parts.append(f"Locations: {store_count} stores")
    if brands:
        parts.append(f"Brands: {', '.join(str(b) for b in brands[:5])}")

    # Score context
    if score_row:
        base_score = score_row.get("base_score")
        if base_score is not None:
            parts.append(f"HAK score: {base_score:.1f}/100")

    return " | ".join(filter(None, parts))


def build_pinecone_metadata(
    profile_row: dict, score_row: dict | None = None
) -> dict:
    """Build flat Pinecone metadata dict for filtering.

    All dimension scores are flattened to top-level keys so Pinecone's
    $gte/$lte filters work on them.
    """
    meta: dict = {
        "company_id": profile_row.get("company_id", ""),
        "name": profile_row.get("name", ""),
        "domain": profile_row.get("domain") or "",
        "sector": profile_row.get("sector", ""),
        "sub_sector": profile_row.get("sub_sector") or "",
        "country_code": profile_row.get("country_code", ""),
        "city": profile_row.get("city") or "",
        "region": profile_row.get("region") or "",
        "headcount_range": profile_row.get("headcount_range") or "",
        "founded_year": profile_row.get("founded_year") or 0,
        "data_quality_score": profile_row.get("data_quality_score") or 0.0,
        "enrichment_version": profile_row.get("enrichment_version", 1),
    }

    if score_row:
        meta["base_score"] = score_row.get("base_score", 0.0)
        meta["overall_confidence_band"] = score_row.get("overall_confidence_band", "wide")
        meta["overall_tolerance_pct"] = score_row.get("overall_tolerance_pct", 35.0)

        # Flatten dimension scores
        dim_scores: dict = score_row.get("dimension_scores") or {}
        for dim_key, dim_data in dim_scores.items():
            if isinstance(dim_data, dict):
                meta[f"{dim_key}_score"] = dim_data.get("score", 0.0)
                meta[f"{dim_key}_band"] = dim_data.get("confidence_band", "wide")

    return meta


class OpenAIEmbeddingProvider:
    """Generates embeddings via OpenRouter (OpenAI-compatible embeddings endpoint).

    Uses the OpenAI SDK pointed at OpenRouter's base URL so the same
    OPENROUTER_API_KEY covers both LLM calls and embeddings.
    """

    def __init__(
        self,
        api_key: str,
        model: str = _DEFAULT_MODEL,
        base_url: str = _OPENROUTER_BASE_URL,
    ) -> None:
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch of texts and return a list of vectors."""
        if not texts:
            return []
        try:
            response = await self._client.embeddings.create(
                model=self._model,
                input=texts,
            )
            return [item.embedding for item in response.data]
        except Exception as exc:
            raise VectorStoreError(
                f"OpenAI embedding call failed: {exc}"
            ) from exc

    async def embed_one(self, text: str) -> list[float]:
        """Embed a single text."""
        vectors = await self.embed_texts([text])
        return vectors[0]
