from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

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
