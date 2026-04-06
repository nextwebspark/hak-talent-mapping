from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, TypedDict

from pydantic import BaseModel, Field


class Company(BaseModel):
    """Represents a company scraped from Zawya."""

    company_id: str
    name: str
    slug: str
    sector: str
    country: str
    company_type: str
    profile_url: str

    # Detail fields — populated in Phase 2
    description: str | None = None
    website: str | None = None
    founded_year: int | None = None
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    employees_count: str | None = None
    executives: list[dict[str, str]] | None = None

    listing_scraped_at: datetime | None = None
    detail_scraped_at: datetime | None = None


class CompanyDetail(TypedDict, total=False):
    """Fields extracted from a company detail page (all optional)."""

    description: str
    website: str
    founded_year: int
    address: str
    phone: str
    email: str
    employees_count: str
    executives: list[dict[str, str]]
    detail_scraped_at: str


# ---------------------------------------------------------------------------
# Phase 3 — Enrichment pipeline models
# ---------------------------------------------------------------------------


class EnrichmentStatus(str, Enum):
    """State machine stages for company enrichment."""

    PENDING = "pending"
    WEB_SEARCH_DONE = "web_search_done"
    WEBSITE_SCRAPED = "website_scraped"
    LLM_EXTRACTED = "llm_extracted"
    PROFILE_COMPLETE = "profile_complete"
    FAILED = "failed"


class SignalValue(BaseModel):
    """A single extracted signal value with provenance."""

    value: Any
    source: str
    source_level: str  # "primary" | "secondary" | "fallback" | "none"


class DimensionScore(BaseModel):
    """Score for a single scoring dimension."""

    score: float = Field(ge=0.0, le=10.0)
    confidence_band: str  # "tight" | "medium" | "wide"
    source_level: str  # worst source level used across signals
    weight_used: float
    effective_weight: float
    cold_start_active: bool = False
    evidence: dict[str, SignalValue] = Field(default_factory=dict)
    rationale: str = ""


class ConfidenceBand(BaseModel):
    """Confidence band for a score dimension or overall."""

    band: str  # "tight" | "medium" | "wide"
    tolerance_pct: float  # 10 | 20 | 35


class ProfileExtractionResult(BaseModel):
    """Structured output from the LLM profile extraction call."""

    name: str
    domain: str | None = None
    description_clean: str = ""
    city: str | None = None
    region: str | None = None
    sub_sector: str | None = None
    sub_sector_tags: list[str] = Field(default_factory=list)
    funding_stage: str | None = None
    funding_total_usd: int | None = None
    headcount_range: str | None = None
    headcount_exact: int | None = None
    founded_year: int | None = None
    sector_metadata: dict[str, Any] = Field(default_factory=dict)
    alumni_signals: list[str] = Field(default_factory=list)
    leadership_names: list[str] = Field(default_factory=list)
    extraction_confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class CompanyProfile(BaseModel):
    """Maps to the company_details table in Supabase."""

    id: str | None = None
    companies_id: int | None = None  # FK → companies.id
    company_id: str
    sector: str
    country_code: str

    # Core identity
    name: str
    domain: str | None = None
    description_clean: str | None = None

    # Location
    country: str | None = None
    city: str | None = None
    region: str | None = None

    # Sector classification
    sub_sector: str | None = None
    sub_sector_tags: list[str] = Field(default_factory=list)

    # Firmographics
    funding_stage: str | None = None
    funding_total_usd: int | None = None
    headcount_range: str | None = None
    headcount_exact: int | None = None
    founded_year: int | None = None

    # Sector-specific extracted data
    sector_metadata: dict[str, Any] = Field(default_factory=dict)

    # Enrichment pipeline state
    enrichment_status: EnrichmentStatus = EnrichmentStatus.PENDING
    enrichment_error: str | None = None
    enrichment_version: int = 1
    data_quality_score: float | None = None
    content_hash: str | None = None

    # Vector sync state
    pinecone_synced_at: datetime | None = None
    embedding_model: str | None = None

    created_at: datetime | None = None
    updated_at: datetime | None = None


class CompanyScoreRecord(BaseModel):
    """Maps to the company_scores table in Supabase."""

    id: str | None = None
    company_detail_id: str
    base_score: float = Field(ge=0.0, le=100.0)
    dimension_scores: dict[str, DimensionScore] = Field(default_factory=dict)
    confidence_bands: dict[str, ConfidenceBand] = Field(default_factory=dict)
    overall_confidence_band: str = "wide"
    overall_tolerance_pct: float = 35.0
    sub_sector_gate_result: str | None = None  # "passed" | "excluded"
    sub_sector_classified: str | None = None
    scoring_config_id: str = ""
    config_hash: str = ""
    created_at: datetime | None = None
    updated_at: datetime | None = None


# ---------------------------------------------------------------------------
# Scoring config models (loaded from YAML)
# ---------------------------------------------------------------------------


class SignalDefinition(BaseModel):
    """Definition of a single scoring signal within a dimension."""

    name: str
    weight: float
    source_config: dict[str, list[str]] = Field(default_factory=dict)
    extraction_field: str | None = None


class DimensionConfig(BaseModel):
    """Config for one scoring dimension from the sector YAML."""

    key: str
    label: str
    default_weight: float
    cold_start_weight: float | None = None
    signals: list[SignalDefinition] = Field(default_factory=list)


class SubSectorGateConfig(BaseModel):
    """Optional sub-sector gating config."""

    enabled: bool = False
    sub_sectors: list[str] = Field(default_factory=list)
    classification_signals: list[str] = Field(default_factory=list)


class SectorScoringConfig(BaseModel):
    """Full scoring config for a sector, loaded from YAML."""

    model_config = {"extra": "allow"}

    sector: str
    config_id: str
    version: str
    dimensions: list[DimensionConfig] = Field(default_factory=list)
    sub_sector_gate: SubSectorGateConfig = Field(
        default_factory=SubSectorGateConfig
    )
    search_queries: list[str] = Field(default_factory=list)
