from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any

from hak_talent_mapping.core.exceptions import LLMExtractionError
from hak_talent_mapping.core.models import ProfileExtractionResult


class LLMProvider(ABC):
    """Abstract base for LLM providers used in the enrichment pipeline."""

    @abstractmethod
    async def extract_profile(
        self,
        company_name: str,
        sector: str,
        search_results: list[dict[str, Any]],
        website_text: str,
        sector_metadata_schema: dict[str, Any] | None = None,
        llm_guidance: str | None = None,
    ) -> ProfileExtractionResult:
        """Extract a structured company profile from raw search + website data.

        Args:
            company_name: The company's display name.
            sector: The Zawya sector string (e.g. "Retailers").
            search_results: List of search result objects from the search service.
            website_text: Combined innerText from the website scraper.
            sector_metadata_schema: Optional JSON schema describing expected
                sector_metadata fields (from the sector YAML config).
            llm_guidance: Optional sector-specific reasoning instructions injected
                into the system prompt (from the sector YAML config).

        Returns:
            A ProfileExtractionResult with all extractable fields populated.
        """


def parse_llm_json(raw_text: str, company_name: str) -> ProfileExtractionResult:
    """Strip markdown fences, parse JSON, validate into ProfileExtractionResult."""
    text = raw_text
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.rsplit("```", 1)[0].strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMExtractionError(
            f"LLM returned invalid JSON for {company_name}: {exc}\nRaw: {raw_text[:200]}"
        ) from exc

    try:
        return ProfileExtractionResult.model_validate(data)
    except Exception as exc:
        raise LLMExtractionError(
            f"ProfileExtractionResult validation failed for {company_name}: {exc}"
        ) from exc
