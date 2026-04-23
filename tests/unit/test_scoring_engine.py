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
                key="sector_fit_confidence",
                label="Sector Fit Confidence",
                default_weight=0.30,
            ),
            DimensionConfig(
                key="brand_market_prominence",
                label="Brand & Market Prominence",
                default_weight=0.35,
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
    press_mentions_count: int | None = None,
    award_mentions_count: int | None = None,
    sector_concentration: str | None = None,
) -> dict:
    sector_meta: dict = {}
    if store_count is not None:
        sector_meta["store_count"] = store_count
    if ded_confirmed is not None:
        sector_meta["ded_license_confirmed"] = ded_confirmed
    if leadership_names is not None:
        sector_meta["leadership_names"] = leadership_names
    if press_mentions_count is not None:
        sector_meta["press_mentions_count"] = press_mentions_count
    if award_mentions_count is not None:
        sector_meta["award_mentions_count"] = award_mentions_count
    if sector_concentration is not None:
        sector_meta["sector_concentration"] = sector_concentration
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
# Brand & Market Prominence (D4)
# ---------------------------------------------------------------------------


def test_brand_prominence_zero_signals(engine: ScoringEngine) -> None:
    profile = _profile()
    record = engine.score(profile)
    d4 = record.dimension_scores["brand_market_prominence"]
    assert d4.score == 0.0
    assert d4.source_level == "none"
    assert d4.confidence_band == "wide"


def test_brand_prominence_leadership_only(engine: ScoringEngine) -> None:
    """Named executives alone give a non-zero score with secondary confidence."""
    profile = _profile(leadership_names=["CEO", "CFO", "COO", "CMO", "CHRO"])
    record = engine.score(profile)
    d4 = record.dimension_scores["brand_market_prominence"]
    # 5 executives → leadership_score=7.0; D4 = 7.0 * 0.20 = 1.4
    assert d4.score == pytest.approx(1.4)
    assert d4.source_level == "secondary"
    assert d4.confidence_band == "medium"
    assert "named_executives" in d4.evidence


def test_brand_prominence_press_and_leadership(engine: ScoringEngine) -> None:
    """Press coverage + leadership should combine correctly."""
    profile = _profile(press_mentions_count=6, leadership_names=["CEO", "CFO", "COO"])
    record = engine.score(profile)
    d4 = record.dimension_scores["brand_market_prominence"]
    # press=7.5*0.55=4.125, leadership(3 names)=5.0*0.20=1.0 → 5.125
    assert d4.score == pytest.approx(5.12, abs=0.05)
    assert d4.source_level == "fallback"


def test_brand_prominence_all_signals(engine: ScoringEngine) -> None:
    """All three signals present: press + awards + leadership."""
    profile = _profile(
        press_mentions_count=3,
        award_mentions_count=1,
        leadership_names=["CEO", "CFO", "COO", "CMO", "CHRO"],
    )
    record = engine.score(profile)
    d4 = record.dimension_scores["brand_market_prominence"]
    # press=5.5*0.55=3.025, awards=4.0*0.25=1.0, leadership(5)=7.0*0.20=1.4 → 5.425
    assert d4.score == pytest.approx(5.43, abs=0.05)
    assert d4.score > 0
    assert "press_mentions_count" in d4.evidence
    assert "award_mentions_count" in d4.evidence
    assert "named_executives" in d4.evidence


def test_brand_prominence_large_company_no_leadership(engine: ScoringEngine) -> None:
    """A large private company with press but 0 named executives still scores > 0."""
    profile = _profile(press_mentions_count=15)
    record = engine.score(profile)
    d4 = record.dimension_scores["brand_market_prominence"]
    # press=9.0*0.55=4.95, no leadership → 4.95
    assert d4.score == pytest.approx(4.95)


# ---------------------------------------------------------------------------
# Sector Fit Confidence
# ---------------------------------------------------------------------------


def test_fit_primary_concentration(engine: ScoringEngine) -> None:
    profile = _profile(sector_concentration="primary")
    fit = engine.score(profile).dimension_scores["sector_fit_confidence"]
    assert fit.score == pytest.approx(10.0)
    assert fit.source_level == "secondary"
    assert fit.confidence_band == "medium"


def test_fit_secondary_concentration(engine: ScoringEngine) -> None:
    profile = _profile(sector_concentration="secondary")
    fit = engine.score(profile).dimension_scores["sector_fit_confidence"]
    assert fit.score == pytest.approx(6.0)
    assert fit.confidence_band == "wide"


def test_fit_diversified_not_penalised(engine: ScoringEngine) -> None:
    """Diversified conglomerates score same as secondary — scale is measured by D1."""
    profile = _profile(sector_concentration="diversified")
    fit = engine.score(profile).dimension_scores["sector_fit_confidence"]
    assert fit.score == pytest.approx(6.0)
    assert fit.confidence_band == "wide"


def test_fit_null_concentration(engine: ScoringEngine) -> None:
    """When LLM can't confirm retail presence, apply 3.0 uncertainty penalty."""
    profile = _profile()
    fit = engine.score(profile).dimension_scores["sector_fit_confidence"]
    assert fit.score == pytest.approx(3.0)
    assert fit.confidence_band == "wide"


# ---------------------------------------------------------------------------
# Base score + confidence bands
# ---------------------------------------------------------------------------


def test_base_score_in_range(engine: ScoringEngine) -> None:
    profile = _profile(
        headcount_exact=5000,
        leadership_names=["CEO", "CFO", "COO"],
        press_mentions_count=8,
        award_mentions_count=2,
    )
    record = engine.score(profile, country_code="AE")
    assert 0.0 <= record.base_score <= 100.0
    assert "brand_market_prominence" in record.dimension_scores


def test_base_score_null_sector_only_when_no_signals(engine: ScoringEngine) -> None:
    """With no org/brand signals, only the null sector-fit penalty contributes."""
    # D1=0, D3 null=3.0×0.30=0.9, D4=0 → base = 0.9/1.0 × 10 = 9.0
    profile = _profile()
    record = engine.score(profile)
    assert record.base_score == pytest.approx(9.0)


def test_overall_band_is_worst_dimension(engine: ScoringEngine) -> None:
    # DED confirmed (tight) but no headcount (wide) → overall should be wide
    profile = _profile(ded_confirmed=True)
    record = engine.score(profile, country_code="AE")
    assert record.overall_confidence_band == "wide"


def test_overall_band_tight_when_all_primary(engine: ScoringEngine) -> None:
    # Only sector fit with DED (tight) — other dims are wide → overall wide
    # To get all-tight, all dims would need primary sources
    profile = _profile(
        ded_confirmed=True,
        headcount_exact=10000,
        leadership_names=["CEO", "CFO"],
        press_mentions_count=5,
    )
    record = engine.score(profile, country_code="AE")
    # headcount and press/awards use "secondary"/"fallback" → overall is at best medium
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
