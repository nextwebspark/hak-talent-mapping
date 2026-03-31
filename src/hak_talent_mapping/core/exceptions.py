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
