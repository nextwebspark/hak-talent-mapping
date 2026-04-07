from __future__ import annotations

import pytest

from hak_talent_mapping.core.exceptions import (
    EnrichmentError,
    LLMExtractionError,
    ScoringConfigError,
    SearchAPIError,
    VectorStoreError,
)
from hak_talent_mapping.core.models import (
    CompanyProfile,
    CompanyScoreRecord,
    ConfidenceBand,
    DimensionScore,
    EnrichmentStatus,
    ProfileExtractionResult,
    SectorScoringConfig,
    SignalValue,
)


# ---------------------------------------------------------------------------
# EnrichmentStatus
# ---------------------------------------------------------------------------


def test_enrichment_status_values() -> None:
    assert EnrichmentStatus.PENDING.value == "pending"
    assert EnrichmentStatus.PROFILE_COMPLETE.value == "profile_complete"
    assert EnrichmentStatus.FAILED.value == "failed"


def test_enrichment_status_ordering() -> None:
    statuses = list(EnrichmentStatus)
    assert statuses.index(EnrichmentStatus.PENDING) < statuses.index(
        EnrichmentStatus.PROFILE_COMPLETE
    )


# ---------------------------------------------------------------------------
# ProfileExtractionResult
# ---------------------------------------------------------------------------


def test_profile_extraction_result_defaults() -> None:
    result = ProfileExtractionResult(name="Acme LLC")
    assert result.name == "Acme LLC"
    assert result.domain is None
    assert result.sub_sector_tags == []
    assert result.alumni_signals == []
    assert result.leadership_names == []
    assert result.ownership_type is None
    assert result.relevance_type is None
    assert result.extraction_confidence == 0.0


def test_profile_extraction_result_role_aware_leadership() -> None:
    """leadership_names accepts list[dict] with name/title/function."""
    result = ProfileExtractionResult(
        name="Landmark Group",
        leadership_names=[
            {"name": "Alice Chen", "title": "Chief Executive Officer", "function": "general_management"},
            {"name": "Bob Smith", "title": "Chief Financial Officer", "function": "finance"},
        ],
        ownership_type="family_owned",
        relevance_type="direct",
        extraction_confidence=0.9,
    )
    assert len(result.leadership_names) == 2
    assert result.ownership_type == "family_owned"
    assert result.relevance_type == "direct"


def test_profile_extraction_result_legacy_string_leadership() -> None:
    """leadership_names also accepts list[str] for backwards compatibility."""
    result = ProfileExtractionResult(
        name="Legacy Co",
        leadership_names=["CEO John Smith", "CFO Jane Doe"],
        extraction_confidence=0.5,
    )
    assert len(result.leadership_names) == 2


def test_profile_extraction_result_full() -> None:
    result = ProfileExtractionResult(
        name="Landmark Group",
        domain="landmark.ae",
        description_clean="A leading retail group in the Middle East.",
        city="Dubai",
        region="Dubai",
        sub_sector="Fashion Retail",
        sub_sector_tags=["fashion", "home", "food"],
        funding_stage="private",
        headcount_range="5001+",
        headcount_exact=55000,
        founded_year=1973,
        sector_metadata={"store_count": 200, "ded_license_confirmed": True},
        leadership_names=[
            {"name": "CEO John Smith", "title": "Chief Executive Officer", "function": "general_management"},
            {"name": "CFO Jane Doe", "title": "Chief Financial Officer", "function": "finance"},
        ],
        ownership_type="listed",
        relevance_type="direct",
        extraction_confidence=0.9,
    )
    assert result.domain == "landmark.ae"
    assert result.headcount_exact == 55000
    assert result.sector_metadata["store_count"] == 200
    assert len(result.leadership_names) == 2
    assert result.ownership_type == "listed"


def test_profile_extraction_confidence_bounds() -> None:
    with pytest.raises(Exception):
        ProfileExtractionResult(name="X", extraction_confidence=1.5)
    with pytest.raises(Exception):
        ProfileExtractionResult(name="X", extraction_confidence=-0.1)


# ---------------------------------------------------------------------------
# CompanyProfile
# ---------------------------------------------------------------------------


def test_company_profile_defaults() -> None:
    profile = CompanyProfile(
        company_id="cid123",
        sector="Retailers",
        country_code="AE",
        name="Test Co",
    )
    assert profile.enrichment_status == EnrichmentStatus.PENDING
    assert profile.enrichment_version == 1
    assert profile.sub_sector_tags == []
    assert profile.sector_metadata == {}


def test_company_profile_status_update() -> None:
    profile = CompanyProfile(
        company_id="cid123",
        sector="Retailers",
        country_code="AE",
        name="Test Co",
        enrichment_status=EnrichmentStatus.WEB_SEARCH_DONE,
    )
    assert profile.enrichment_status == EnrichmentStatus.WEB_SEARCH_DONE


# ---------------------------------------------------------------------------
# DimensionScore + ConfidenceBand
# ---------------------------------------------------------------------------


def test_dimension_score_bounds() -> None:
    score = DimensionScore(
        score=8.5,
        confidence_band="tight",
        source_level="primary",
        weight_used=0.35,
        effective_weight=0.35,
    )
    assert score.score == 8.5
    assert score.cold_start_active is False


def test_dimension_score_out_of_bounds() -> None:
    with pytest.raises(Exception):
        DimensionScore(
            score=11.0,
            confidence_band="tight",
            source_level="primary",
            weight_used=0.35,
            effective_weight=0.35,
        )


def test_confidence_band_fields() -> None:
    band = ConfidenceBand(band="medium", tolerance_pct=20.0)
    assert band.tolerance_pct == 20.0


# ---------------------------------------------------------------------------
# CompanyScoreRecord
# ---------------------------------------------------------------------------


def test_company_score_record_base_score_bounds() -> None:
    with pytest.raises(Exception):
        CompanyScoreRecord(
            company_detail_id="uuid",
            base_score=105.0,
        )


def test_company_score_record_minimal() -> None:
    record = CompanyScoreRecord(
        company_detail_id="some-uuid",
        base_score=72.5,
    )
    assert record.base_score == 72.5
    assert record.dimension_scores == {}
    assert record.overall_confidence_band == "wide"
    assert record.brief_adjusted_score is None
    assert record.applied_archetype is None
    assert record.d4_is_enriching is False


def test_company_score_record_with_brief_adjusted() -> None:
    record = CompanyScoreRecord(
        company_detail_id="some-uuid",
        base_score=72.5,
        brief_adjusted_score=78.0,
        applied_archetype="cco",
        d4_is_enriching=True,
    )
    assert record.brief_adjusted_score == 78.0
    assert record.applied_archetype == "cco"
    assert record.d4_is_enriching is True


def test_company_score_record_brief_adjusted_bounds() -> None:
    with pytest.raises(Exception):
        CompanyScoreRecord(
            company_detail_id="uuid",
            base_score=50.0,
            brief_adjusted_score=101.0,
        )


# ---------------------------------------------------------------------------
# SignalValue
# ---------------------------------------------------------------------------


def test_signal_value_stores_any_value() -> None:
    sv = SignalValue(value=42, source="linkedin", source_level="secondary")
    assert sv.value == 42

    sv2 = SignalValue(value=True, source="ded_register", source_level="primary")
    assert sv2.value is True


# ---------------------------------------------------------------------------
# Exception hierarchy
# ---------------------------------------------------------------------------


def test_exception_hierarchy() -> None:
    assert issubclass(SearchAPIError, EnrichmentError)
    assert issubclass(LLMExtractionError, EnrichmentError)

    err = SearchAPIError("API down")
    assert "API down" in str(err)


def test_scoring_config_error() -> None:
    err = ScoringConfigError("No config for sector X")
    assert isinstance(err, Exception)
    assert "No config" in str(err)


def test_vector_store_error() -> None:
    err = VectorStoreError("Pinecone upsert failed")
    assert "Pinecone" in str(err)


# ---------------------------------------------------------------------------
# SectorScoringConfig (basic validation)
# ---------------------------------------------------------------------------


def test_sector_scoring_config_minimal() -> None:
    config = SectorScoringConfig(
        sector="Retailers",
        config_id="retailers_v1",
        version="1.0",
    )
    assert config.dimensions == []
    assert config.sub_sector_gate.enabled is False
    assert config.search_queries == []
