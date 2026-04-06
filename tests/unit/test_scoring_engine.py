from __future__ import annotations

import pytest

from hak_talent_mapping.core.models import (
    DimensionConfig,
    SectorScoringConfig,
    SubSectorGateConfig,
)
from hak_talent_mapping.services.enrichment.scoring.engine import ScoringEngine


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def retailers_config() -> SectorScoringConfig:
    """Minimal 3-dimension retailers config for unit tests."""
    return SectorScoringConfig(
        sector="Retailers",
        config_id="retailers_test_v1",
        version="1.0",
        sub_sector_gate=SubSectorGateConfig(enabled=False),
        dimensions=[
            DimensionConfig(
                key="organisational_scale",
                label="Organisational Scale",
                default_weight=0.35,
            ),
            DimensionConfig(
                key="leadership_depth",
                label="Leadership Depth",
                default_weight=0.35,
            ),
            DimensionConfig(
                key="sector_fit_confidence",
                label="Sector Fit Confidence",
                default_weight=0.30,
            ),
        ],
    )


@pytest.fixture
def engine(retailers_config: SectorScoringConfig) -> ScoringEngine:
    return ScoringEngine(retailers_config)


def _profile(
    headcount_range: str | None = None,
    headcount_exact: int | None = None,
    store_count: int | None = None,
    leadership_names: list[str] | None = None,
    ded_confirmed: bool | None = None,
    description: str = "",
) -> dict:
    sector_meta: dict = {}
    if store_count is not None:
        sector_meta["store_count"] = store_count
    if ded_confirmed is not None:
        sector_meta["ded_license_confirmed"] = ded_confirmed
    if leadership_names is not None:
        sector_meta["leadership_names"] = leadership_names
    return {
        "id": "detail-uuid-123",
        "company_id": "cid-001",
        "sector": "Retailers",
        "name": "Test Retailer",
        "headcount_range": headcount_range,
        "headcount_exact": headcount_exact,
        "description_clean": description,
        "sector_metadata": sector_meta,
        "raw_llm_extraction": {},
    }


# ---------------------------------------------------------------------------
# Organisational Scale
# ---------------------------------------------------------------------------


def test_scale_score_with_headcount_range(engine: ScoringEngine) -> None:
    profile = _profile(headcount_range="5001+")
    record = engine.score(profile, country_code="AE")
    scale = record.dimension_scores["organisational_scale"]
    assert scale.score > 0
    assert scale.source_level in ("secondary", "primary")


def test_scale_score_with_exact_headcount(engine: ScoringEngine) -> None:
    profile = _profile(headcount_exact=50000)
    record = engine.score(profile, country_code="AE")
    scale = record.dimension_scores["organisational_scale"]
    # log10(50000) * 2.5 * 0.60 ≈ 6.0 (headcount-only component)
    assert scale.score > 0
    assert scale.source_level == "secondary"


def test_scale_score_with_store_count(engine: ScoringEngine) -> None:
    profile = _profile(headcount_range="201-500", store_count=100)
    record = engine.score(profile, country_code="AE")
    scale = record.dimension_scores["organisational_scale"]
    assert scale.score > 0
    assert "store_count" in scale.evidence


def test_scale_score_no_signals(engine: ScoringEngine) -> None:
    profile = _profile()
    record = engine.score(profile, country_code="AE")
    scale = record.dimension_scores["organisational_scale"]
    assert scale.score == 0.0
    assert scale.source_level == "none"
    assert scale.confidence_band == "wide"


def test_scale_score_capped_at_ten(engine: ScoringEngine) -> None:
    profile = _profile(headcount_exact=1_000_000)
    record = engine.score(profile, country_code="AE")
    assert record.dimension_scores["organisational_scale"].score <= 10.0


# ---------------------------------------------------------------------------
# Leadership Depth
# ---------------------------------------------------------------------------


def test_leadership_zero_executives(engine: ScoringEngine) -> None:
    profile = _profile(leadership_names=[])
    record = engine.score(profile)
    depth = record.dimension_scores["leadership_depth"]
    assert depth.score == 0.0
    assert depth.source_level == "none"


def test_leadership_one_executive(engine: ScoringEngine) -> None:
    profile = _profile(leadership_names=["CEO Alice"])
    record = engine.score(profile)
    depth = record.dimension_scores["leadership_depth"]
    assert depth.score == 2.0


def test_leadership_five_executives(engine: ScoringEngine) -> None:
    names = ["CEO", "CFO", "COO", "CMO", "CHRO"]
    profile = _profile(leadership_names=names)
    record = engine.score(profile)
    depth = record.dimension_scores["leadership_depth"]
    assert depth.score == 7.0


def test_leadership_many_executives(engine: ScoringEngine) -> None:
    names = [f"Exec {i}" for i in range(15)]
    profile = _profile(leadership_names=names)
    record = engine.score(profile)
    depth = record.dimension_scores["leadership_depth"]
    assert depth.score <= 10.0


# ---------------------------------------------------------------------------
# Sector Fit Confidence
# ---------------------------------------------------------------------------


def test_fit_ded_confirmed(engine: ScoringEngine) -> None:
    profile = _profile(ded_confirmed=True)
    record = engine.score(profile, country_code="AE")
    fit = record.dimension_scores["sector_fit_confidence"]
    assert fit.score >= 9.0
    assert fit.source_level == "primary"
    assert fit.confidence_band == "tight"


def test_fit_description_strong_match(engine: ScoringEngine) -> None:
    profile = _profile(
        description="A leading retail store chain with fashion and home brands."
    )
    record = engine.score(profile)
    fit = record.dimension_scores["sector_fit_confidence"]
    assert fit.score >= 6.0


def test_fit_description_weak_match(engine: ScoringEngine) -> None:
    profile = _profile(description="A technology company providing SaaS solutions.")
    record = engine.score(profile)
    fit = record.dimension_scores["sector_fit_confidence"]
    assert fit.score <= 5.0
    assert fit.confidence_band == "wide"


def test_fit_no_signals(engine: ScoringEngine) -> None:
    profile = _profile()
    record = engine.score(profile)
    fit = record.dimension_scores["sector_fit_confidence"]
    assert fit.score == 0.0


# ---------------------------------------------------------------------------
# Base score + confidence bands
# ---------------------------------------------------------------------------


def test_base_score_in_range(engine: ScoringEngine) -> None:
    profile = _profile(
        headcount_exact=5000,
        leadership_names=["CEO", "CFO", "COO"],
        ded_confirmed=True,
    )
    record = engine.score(profile, country_code="AE")
    assert 0.0 <= record.base_score <= 100.0


def test_base_score_zero_when_no_signals(engine: ScoringEngine) -> None:
    profile = _profile()
    record = engine.score(profile)
    assert record.base_score == 0.0


def test_overall_band_is_worst_dimension(engine: ScoringEngine) -> None:
    # DED confirmed (tight) but no headcount (wide) → overall should be wide
    profile = _profile(ded_confirmed=True)
    record = engine.score(profile, country_code="AE")
    assert record.overall_confidence_band == "wide"


def test_overall_band_tight_when_all_primary(engine: ScoringEngine) -> None:
    # Only sector fit with DED (tight) — other dims are wide → overall wide
    # To get all-tight, all dims would need primary sources
    profile = _profile(ded_confirmed=True, headcount_exact=10000, leadership_names=["CEO", "CFO"])
    record = engine.score(profile, country_code="AE")
    # headcount and leadership use "secondary" → overall is at best medium
    assert record.overall_confidence_band in ("medium", "wide")


def test_config_hash_is_stable(engine: ScoringEngine) -> None:
    profile = _profile(headcount_exact=100)
    r1 = engine.score(profile)
    r2 = engine.score(profile)
    assert r1.config_hash == r2.config_hash


def test_scoring_config_id_written_to_record(engine: ScoringEngine) -> None:
    profile = _profile()
    record = engine.score(profile)
    assert record.scoring_config_id == "retailers_test_v1"


# ---------------------------------------------------------------------------
# Inactive dimensions (weight=0) are excluded
# ---------------------------------------------------------------------------


def test_inactive_dimensions_excluded(retailers_config: SectorScoringConfig) -> None:
    # Add a zero-weight dimension
    retailers_config.dimensions.append(
        DimensionConfig(
            key="brand_prominence",
            label="Brand Prominence",
            default_weight=0.0,
        )
    )
    engine = ScoringEngine(retailers_config)
    profile = _profile()
    record = engine.score(profile)
    assert "brand_prominence" not in record.dimension_scores
