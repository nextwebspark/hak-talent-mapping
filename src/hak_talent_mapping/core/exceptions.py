from __future__ import annotations


class HakTalentError(Exception):
    """Base exception for hak-talent-mapping."""


class ScrapingError(HakTalentError):
    """Raised when a scraping operation fails."""


class RateLimitError(ScrapingError):
    """Raised when the target site rate-limits the scraper."""


class ParseError(ScrapingError):
    """Raised when HTML parsing produces unexpected results."""


class DatabaseError(HakTalentError):
    """Raised when a Supabase database operation fails."""


class EnrichmentError(HakTalentError):
    """Raised when an enrichment pipeline stage fails."""


class SearchAPIError(EnrichmentError):
    """Raised when a web search API call fails."""


class LLMExtractionError(EnrichmentError):
    """Raised when the LLM profile extraction call fails."""


class VectorStoreError(HakTalentError):
    """Raised when a Pinecone operation fails."""


class ScoringConfigError(HakTalentError):
    """Raised when a sector scoring config is invalid or missing."""
