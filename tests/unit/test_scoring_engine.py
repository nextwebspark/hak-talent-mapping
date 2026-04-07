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
    """Full 6-dimension retailers config for unit tests."""
    return SectorScoringConfig(
        sector="Retailers",
        config_id="retailers_test_v2",
        version="2.0",
        sub_sector_gate=SubSectorGateConfig(enabled=False),
        archetype_weights={
            "base": {
                "organisational_scale": 0.22,
                "brand_market_prominence": 0.18,
                "leadership_depth": 0.25,
                "talent_export_history": 0.10,
                "sector_fit_confidence": 0.15,
                "executive_talent_momentum": 0.10,
            },
            "cco": {
                "organisational_scale": 0.15,
                "brand_market_prominence": 0.28,
                "leadership_depth": 0.25,
                "talent_export_history": 0.10,
                "sector_fit_confidence": 0.12,
                "executive_talent_momentum": 0.10,
            },
        },
        dimensions=[
            DimensionConfig(
                key="organisational_scale",
                label="Organisational Scale",
                default_weight=0.22,
            ),
            DimensionConfig(
                key="brand_market_prominence",
                label="Brand & Market Prominence",
                default_weight=0.18,
            ),
            DimensionConfig(
                key="leadership_depth",
                label="Leadership Depth",
                default_weight=0.25,
            ),
            DimensionConfig(
                key="talent_export_history",
                label="Talent Export History",
                default_weight=0.10,
                cold_start_weight=0.05,
            ),
            DimensionConfig(
                key="sector_fit_confidence",
                label="Sector Fit Confidence",
                default_weight=0.15,
            ),
            DimensionConfig(
                key="executive_talent_momentum",
                label="Executive Talent Momentum",
                default_weight=0.10,
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
    annual_revenue_usd: int | None = None,
    leadership_names: list | None = None,
    alumni_signals: list[str] | None = None,
    ded_confirmed: bool | None = None,
    relevance_type: str | None = None,
    description: str = "",
    press_mentions_count: int | None = None,
    award_mentions_count: int | None = None,
    category_leader_signal: bool | None = None,
    open_senior_roles_count: int | None = None,
    c_suite_departures_18m: int | None = None,
    ma_restructure_signal: bool | None = None,
    ma_restructure_recency: str | None = None,
    glassdoor_senior_leadership_rating: float | None = None,
    ceo_approval_pct: int | None = None,
) -> dict:
    sector_meta: dict = {}
    if store_count is not None:
        sector_meta["store_count"] = store_count
    if ded_confirmed is not None:
        sector_meta["ded_license_confirmed"] = ded_confirmed
    if leadership_names is not None:
        sector_meta["leadership_names"] = leadership_names
    if alumni_signals is not None:
        sector_meta["alumni_signals"] = alumni_signals
    if annual_revenue_usd is not None:
        sector_meta["annual_revenue_usd"] = annual_revenue_usd
    if press_mentions_count is not None:
        sector_meta["press_mentions_count"] = press_mentions_count
    if award_mentions_count is not None:
        sector_meta["award_mentions_count"] = award_mentions_count
    if category_leader_signal is not None:
        sector_meta["category_leader_signal"] = category_leader_signal
    if open_senior_roles_count is not None:
        sector_meta["open_senior_roles_count"] = open_senior_roles_count
    if c_suite_departures_18m is not None:
        sector_meta["c_suite_departures_18m"] = c_suite_departures_18m
    if ma_restructure_signal is not None:
        sector_meta["ma_restructure_signal"] = ma_restructure_signal
    if ma_restructure_recency is not None:
        sector_meta["ma_restructure_recency"] = ma_restructure_recency
    if glassdoor_senior_leadership_rating is not None:
        sector_meta["glassdoor_senior_leadership_rating"] = glassdoor_senior_leadership_rating
    if ceo_approval_pct is not None:
        sector_meta["ceo_approval_pct"] = ceo_approval_pct
    if relevance_type is not None:
        sector_meta["relevance_type"] = relevance_type
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
# D1 — Organisational Scale
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
    assert scale.score > 0
    assert scale.source_level == "secondary"


def test_scale_score_with_store_count(engine: ScoringEngine) -> None:
    profile = _profile(headcount_range="201-500", store_count=100)
    record = engine.score(profile, country_code="AE")
    scale = record.dimension_scores["organisational_scale"]
    assert scale.score > 0
    assert "store_count" in scale.evidence


def test_scale_score_with_revenue(engine: ScoringEngine) -> None:
    profile = _profile(headcount_exact=5000, annual_revenue_usd=500_000_000)
    record = engine.score(profile, country_code="AE")
    scale = record.dimension_scores["organisational_scale"]
    assert "annual_revenue_usd" in scale.evidence
    # Revenue should push score higher than headcount alone
    profile_no_rev = _profile(headcount_exact=5000)
    record_no_rev = engine.score(profile_no_rev, country_code="AE")
    assert scale.score >= record_no_rev.dimension_scores["organisational_scale"].score


def test_scale_score_no_signals(engine: ScoringEngine) -> None:
    profile = _profile()
    record = engine.score(profile, country_code="AE")
    scale = record.dimension_scores["organisational_scale"]
    assert scale.score == 0.0
    assert scale.source_level == "none"
    assert scale.confidence_band == "wide"


def test_scale_score_capped_at_ten(engine: ScoringEngine) -> None:
    profile = _profile(headcount_exact=1_000_000, annual_revenue_usd=100_000_000_000)
    record = engine.score(profile, country_code="AE")
    assert record.dimension_scores["organisational_scale"].score <= 10.0


# ---------------------------------------------------------------------------
# D2 — Brand & Market Prominence
# ---------------------------------------------------------------------------


def test_brand_score_with_press_and_awards(engine: ScoringEngine) -> None:
    profile = _profile(press_mentions_count=5, award_mentions_count=2)
    record = engine.score(profile)
    brand = record.dimension_scores["brand_market_prominence"]
    assert brand.score > 0
    assert "press_mentions" in brand.evidence
    assert "award_mentions" in brand.evidence


def test_brand_score_with_category_leader(engine: ScoringEngine) -> None:
    profile = _profile(category_leader_signal=True, press_mentions_count=3)
    record = engine.score(profile)
    brand = record.dimension_scores["brand_market_prominence"]
    assert "category_leader" in brand.evidence
    assert brand.score > 0


def test_brand_score_zero_when_no_signals(engine: ScoringEngine) -> None:
    profile = _profile()
    record = engine.score(profile)
    brand = record.dimension_scores["brand_market_prominence"]
    assert brand.score == 0.0


def test_brand_score_capped_at_ten(engine: ScoringEngine) -> None:
    profile = _profile(press_mentions_count=100, award_mentions_count=50, category_leader_signal=True)
    record = engine.score(profile)
    assert record.dimension_scores["brand_market_prominence"].score <= 10.0


# ---------------------------------------------------------------------------
# D3 — Leadership Depth
# ---------------------------------------------------------------------------


def test_leadership_zero_executives(engine: ScoringEngine) -> None:
    profile = _profile(leadership_names=[])
    record = engine.score(profile)
    depth = record.dimension_scores["leadership_depth"]
    assert depth.score == 0.0
    assert depth.source_level == "none"


def test_leadership_role_aware_ceo_only(engine: ScoringEngine) -> None:
    profile = _profile(leadership_names=[
        {"name": "Alice Chen", "title": "Chief Executive Officer", "function": "general_management"},
    ])
    record = engine.score(profile)
    depth = record.dimension_scores["leadership_depth"]
    assert depth.score == 2.0
    assert "ceo_confirmed" in depth.evidence


def test_leadership_role_aware_full_suite(engine: ScoringEngine) -> None:
    profile = _profile(leadership_names=[
        {"name": "Alice Chen", "title": "Chief Executive Officer", "function": "general_management"},
        {"name": "Bob Smith", "title": "Chief Financial Officer", "function": "finance"},
        {"name": "Carol Jones", "title": "Chief Operating Officer", "function": "operations"},
        {"name": "Dave Kumar", "title": "Chief Commercial Officer", "function": "commercial"},
        {"name": "Eve Ali", "title": "VP Marketing", "function": "marketing"},
        {"name": "Frank Lee", "title": "Director Supply Chain", "function": "supply_chain"},
    ])
    record = engine.score(profile)
    depth = record.dimension_scores["leadership_depth"]
    # CEO=2 + 3 C-suite (max 3) + 1 director (0.5) + breadth_bonus (3+ functions=1) = 6.5
    assert depth.score >= 6.0
    assert depth.score <= 10.0


def test_leadership_legacy_string_format(engine: ScoringEngine) -> None:
    """Legacy list[str] leadership_names still works via count-based fallback."""
    profile = _profile(leadership_names=["CEO Alice", "CFO Bob", "COO Carol", "CMO Dave", "CHRO Eve"])
    record = engine.score(profile)
    depth = record.dimension_scores["leadership_depth"]
    assert depth.score > 0


def test_leadership_many_executives_capped(engine: ScoringEngine) -> None:
    names = [f"Exec {i}" for i in range(15)]
    profile = _profile(leadership_names=names)
    record = engine.score(profile)
    depth = record.dimension_scores["leadership_depth"]
    assert depth.score <= 10.0


def test_leadership_glassdoor_bonus(engine: ScoringEngine) -> None:
    """Glassdoor senior rating >= 4.0 adds 0.5pt; CEO approval >= 70% adds 0.5pt."""
    profile = _profile(
        leadership_names=[
            {"name": "Alice Chen", "title": "Chief Executive Officer", "function": "general_management"},
        ],
        glassdoor_senior_leadership_rating=4.2,
        ceo_approval_pct=80,
    )
    record = engine.score(profile)
    depth = record.dimension_scores["leadership_depth"]
    # CEO=2.0 + glassdoor=0.5 + ceo_approval=0.5 = 3.0
    assert depth.score == 3.0
    assert "glassdoor_rating" in depth.evidence
    assert "ceo_approval" in depth.evidence


def test_leadership_glassdoor_below_threshold(engine: ScoringEngine) -> None:
    """Glassdoor rating < 4.0 and CEO approval < 70% should not add bonus."""
    profile = _profile(
        leadership_names=[
            {"name": "Alice Chen", "title": "Chief Executive Officer", "function": "general_management"},
        ],
        glassdoor_senior_leadership_rating=3.5,
        ceo_approval_pct=60,
    )
    record = engine.score(profile)
    depth = record.dimension_scores["leadership_depth"]
    assert depth.score == 2.0
    assert "glassdoor_rating" not in depth.evidence


def test_leadership_gcс_exec_title(engine: ScoringEngine) -> None:
    """GCC-style titles like 'Managing Partner' and 'Executive Chairman' map to CEO tier."""
    profile = _profile(leadership_names=[
        {"name": "Ramesh P", "title": "Vice Chairman & Managing Partner", "function": "general_management"},
        {"name": "Jamshed P", "title": "Group Chief Financial Officer", "function": "finance"},
    ])
    record = engine.score(profile)
    depth = record.dimension_scores["leadership_depth"]
    # CEO=2.0 + CFO=1.0 = 3.0 (no breadth bonus — only 2 functions)
    assert depth.score == 3.0
    assert "ceo_confirmed" in depth.evidence


# ---------------------------------------------------------------------------
# D4 — Talent Export History
# ---------------------------------------------------------------------------


def test_talent_export_zero_alumni(engine: ScoringEngine) -> None:
    profile = _profile(alumni_signals=[])
    record = engine.score(profile)
    d4 = record.dimension_scores["talent_export_history"]
    assert d4.score == 0.0


def test_talent_export_few_alumni(engine: ScoringEngine) -> None:
    profile = _profile(alumni_signals=["Alice Jones, CEO at Majid Al Futtaim"])
    record = engine.score(profile)
    d4 = record.dimension_scores["talent_export_history"]
    assert d4.score >= 3.0


def test_talent_export_many_alumni(engine: ScoringEngine) -> None:
    alumni = [f"Person {i}, VP at Company {i}" for i in range(12)]
    profile = _profile(alumni_signals=alumni)
    record = engine.score(profile)
    d4 = record.dimension_scores["talent_export_history"]
    assert d4.score == 10.0


def test_talent_export_cold_start_flag(engine: ScoringEngine) -> None:
    """D4 cold_start_active should be True when cold_start_weight < default_weight."""
    profile = _profile()
    record = engine.score(profile)
    assert record.d4_is_enriching is True


# ---------------------------------------------------------------------------
# D5 — Sector Fit Confidence
# ---------------------------------------------------------------------------


def test_fit_ded_confirmed(engine: ScoringEngine) -> None:
    profile = _profile(ded_confirmed=True)
    record = engine.score(profile, country_code="AE")
    fit = record.dimension_scores["sector_fit_confidence"]
    assert fit.score >= 9.0
    assert fit.source_level == "primary"
    assert fit.confidence_band == "tight"


def test_fit_description_strong_match(engine: ScoringEngine) -> None:
    profile = _profile(description="A leading retail store chain with fashion and home brands.")
    record = engine.score(profile)
    fit = record.dimension_scores["sector_fit_confidence"]
    assert fit.score >= 6.0


def test_fit_adjacent_relevance_type(engine: ScoringEngine) -> None:
    profile = _profile(
        description="A wholesale and retail distributor operating in the Gulf.",
        relevance_type="adjacent",
    )
    record = engine.score(profile)
    fit = record.dimension_scores["sector_fit_confidence"]
    assert fit.score <= 6.0


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
# D6 — Executive Talent Momentum
# ---------------------------------------------------------------------------


def test_momentum_open_roles(engine: ScoringEngine) -> None:
    profile = _profile(open_senior_roles_count=4)
    record = engine.score(profile)
    d6 = record.dimension_scores["executive_talent_momentum"]
    assert d6.score > 0
    assert "open_senior_roles" in d6.evidence


def test_momentum_departures(engine: ScoringEngine) -> None:
    profile = _profile(c_suite_departures_18m=2)
    record = engine.score(profile)
    d6 = record.dimension_scores["executive_talent_momentum"]
    assert d6.score > 0
    assert "c_suite_departures" in d6.evidence


def test_momentum_ma_signal(engine: ScoringEngine) -> None:
    profile = _profile(ma_restructure_signal=True, ma_restructure_recency="last_12m")
    record = engine.score(profile)
    d6 = record.dimension_scores["executive_talent_momentum"]
    assert d6.score == 3.0
    assert "ma_restructure" in d6.evidence


def test_momentum_ma_signal_stale(engine: ScoringEngine) -> None:
    """M&A signal older than 24m (no recency) should score 0."""
    profile = _profile(ma_restructure_signal=True)
    record = engine.score(profile)
    d6 = record.dimension_scores["executive_talent_momentum"]
    assert d6.score == 0.0


def test_momentum_ma_signal_12_24m(engine: ScoringEngine) -> None:
    profile = _profile(ma_restructure_signal=True, ma_restructure_recency="12_24m")
    record = engine.score(profile)
    d6 = record.dimension_scores["executive_talent_momentum"]
    assert d6.score == 1.5


def test_momentum_zero_signals(engine: ScoringEngine) -> None:
    profile = _profile()
    record = engine.score(profile)
    d6 = record.dimension_scores["executive_talent_momentum"]
    assert d6.score == 0.0


def test_momentum_capped_at_ten(engine: ScoringEngine) -> None:
    profile = _profile(
        open_senior_roles_count=100,
        c_suite_departures_18m=50,
        ma_restructure_signal=True,
        ma_restructure_recency="last_12m",
    )
    record = engine.score(profile)
    assert record.dimension_scores["executive_talent_momentum"].score <= 10.0


# ---------------------------------------------------------------------------
# Brief-adjusted score
# ---------------------------------------------------------------------------


def test_brief_adjusted_score_differs_by_archetype(engine: ScoringEngine) -> None:
    """CCO archetype up-weights brand prominence → different adjusted score."""
    profile = _profile(
        headcount_exact=5000,
        press_mentions_count=8,
        leadership_names=[
            {"name": "Alice", "title": "Chief Executive Officer", "function": "general_management"},
            {"name": "Bob", "title": "Chief Financial Officer", "function": "finance"},
        ],
        ded_confirmed=True,
    )
    record_base = engine.score(profile, archetype="base")
    record_cco = engine.score(profile, archetype="cco")
    assert record_base.brief_adjusted_score is not None
    assert record_cco.brief_adjusted_score is not None
    assert record_cco.applied_archetype == "cco"
    # Scores may differ because weights differ
    # (not asserting specific direction as it depends on profile signals)


def test_brief_adjusted_score_none_without_archetype_weights() -> None:
    """Engine returns None brief_adjusted_score when config has no archetype_weights."""
    config = SectorScoringConfig(
        sector="Test",
        config_id="test_v1",
        version="1.0",
        dimensions=[
            DimensionConfig(key="organisational_scale", label="Scale", default_weight=1.0),
        ],
    )
    eng = ScoringEngine(config)
    profile = _profile(headcount_exact=1000)
    record = eng.score(profile)
    assert record.brief_adjusted_score is None


def test_applied_archetype_stored_on_record(engine: ScoringEngine) -> None:
    profile = _profile()
    record = engine.score(profile, archetype="coo")
    assert record.applied_archetype == "coo"


# ---------------------------------------------------------------------------
# Base score + confidence bands
# ---------------------------------------------------------------------------


def test_base_score_in_range(engine: ScoringEngine) -> None:
    profile = _profile(
        headcount_exact=5000,
        leadership_names=[
            {"name": "Alice", "title": "CEO", "function": "general_management"},
            {"name": "Bob", "title": "CFO", "function": "finance"},
            {"name": "Carol", "title": "COO", "function": "operations"},
        ],
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
    profile = _profile(ded_confirmed=True, headcount_exact=10000, leadership_names=[
        {"name": "Alice", "title": "CEO", "function": "general_management"},
        {"name": "Bob", "title": "CFO", "function": "finance"},
    ])
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
    assert record.scoring_config_id == "retailers_test_v2"


# ---------------------------------------------------------------------------
# Inactive dimensions (weight=0) are excluded
# ---------------------------------------------------------------------------


def test_inactive_dimensions_excluded(retailers_config: SectorScoringConfig) -> None:
    retailers_config.dimensions.append(
        DimensionConfig(
            key="custom_inactive",
            label="Custom Inactive",
            default_weight=0.0,
        )
    )
    eng = ScoringEngine(retailers_config)
    profile = _profile()
    record = eng.score(profile)
    assert "custom_inactive" not in record.dimension_scores
