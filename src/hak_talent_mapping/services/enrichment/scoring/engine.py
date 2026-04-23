from __future__ import annotations

import math
from typing import Any

import structlog

from hak_talent_mapping.core.models import (
    CompanyScoreRecord,
    ConfidenceBand,
    DimensionScore,
    SectorScoringConfig,
    SignalValue,
)
from hak_talent_mapping.services.enrichment.scoring.config_loader import (
    compute_config_hash,
)

logger = structlog.get_logger()

# Confidence band thresholds mapped to tolerance percentages
_BAND_TOLERANCE: dict[str, float] = {
    "tight": 10.0,
    "medium": 20.0,
    "wide": 35.0,
}

# Source level → confidence band
_SOURCE_LEVEL_BAND: dict[str, str] = {
    "primary": "tight",
    "secondary": "medium",
    "fallback": "wide",
    "none": "wide",
}

# Headcount range → approximate midpoint for scoring
_HEADCOUNT_SCORE: dict[str, float] = {
    "1-10": 1.0,
    "11-50": 2.5,
    "51-200": 4.5,
    "201-500": 6.0,
    "501-1000": 7.5,
    "1001-5000": 8.5,
    "5001+": 10.0,
}


class ScoringEngine:
    """Computes dimension scores from a company profile row using sector YAML config."""

    def __init__(self, config: SectorScoringConfig) -> None:
        self._config = config
        self._config_hash = compute_config_hash(config)

    def score(
        self,
        profile_row: dict[str, Any],
        country_code: str = "",
    ) -> CompanyScoreRecord:
        """Compute scores for all active dimensions and return a CompanyScoreRecord.

        Args:
            profile_row: A company_details row dict from Supabase.
            country_code: ISO-2 country code for source resolution.
        """
        detail_id: str = profile_row["id"]
        dimension_scores: dict[str, DimensionScore] = {}
        confidence_bands: dict[str, ConfidenceBand] = {}

        active_dims = [d for d in self._config.dimensions if d.default_weight > 0]

        for dim_config in active_dims:
            score = self._score_dimension(dim_config, profile_row, country_code)
            dimension_scores[dim_config.key] = score
            band = ConfidenceBand(
                band=score.confidence_band,
                tolerance_pct=_BAND_TOLERANCE.get(score.confidence_band, 35.0),
            )
            confidence_bands[dim_config.key] = band

        base_score = self._compute_base_score(dimension_scores, active_dims)
        overall_band = self._compute_overall_band(confidence_bands)

        return CompanyScoreRecord(
            company_detail_id=detail_id,
            base_score=base_score,
            dimension_scores=dimension_scores,
            confidence_bands=confidence_bands,
            overall_confidence_band=overall_band,
            overall_tolerance_pct=_BAND_TOLERANCE.get(overall_band, 35.0),
            scoring_config_id=self._config.config_id,
            config_hash=self._config_hash,
        )

    def _score_dimension(
        self,
        dim_config: Any,
        profile: dict[str, Any],
        country_code: str,
    ) -> DimensionScore:
        key = dim_config.key

        if key == "organisational_scale":
            return self._score_organisational_scale(dim_config, profile, country_code)
        elif key == "sector_fit_confidence":
            return self._score_sector_fit(dim_config, profile, country_code)
        elif key == "brand_market_prominence":
            return self._score_brand_prominence(dim_config, profile, country_code)
        else:
            # Placeholder for future dimensions
            return DimensionScore(
                score=0.0,
                confidence_band="wide",
                source_level="none",
                weight_used=dim_config.default_weight,
                effective_weight=dim_config.default_weight,
                rationale="Dimension not yet active",
            )

    def _score_organisational_scale(
        self,
        dim_config: Any,
        profile: dict[str, Any],
        country_code: str,
    ) -> DimensionScore:
        """Score based on headcount and location count."""
        headcount_range: str | None = profile.get("headcount_range")
        headcount_exact: int | None = profile.get("headcount_exact")
        sector_meta: dict[str, Any] = profile.get("sector_metadata") or {}
        store_count: int | None = sector_meta.get("store_count")
        annual_revenue_usd: int | None = sector_meta.get("annual_revenue_usd")

        evidence: dict[str, SignalValue] = {}
        source_level = "none"

        # Headcount score (logarithmic)
        headcount_score = 0.0
        if headcount_exact and headcount_exact > 0:
            # log10 scale: 10→1, 100→2, 1000→3, 10000→4, 50000→4.7
            headcount_score = min(10.0, math.log10(headcount_exact) * 2.5)
            source_level = "secondary"
            evidence["headcount"] = SignalValue(
                value=headcount_exact,
                source="linkedin_or_website",
                source_level="secondary",
            )
        elif headcount_range and headcount_range in _HEADCOUNT_SCORE:
            headcount_score = _HEADCOUNT_SCORE[headcount_range]
            source_level = "secondary"
            evidence["headcount_range"] = SignalValue(
                value=headcount_range,
                source="linkedin_or_website",
                source_level="secondary",
            )

        # Location count bonus
        location_score = 0.0
        if store_count:
            # 1 store → 1, 10 stores → 3, 100 stores → 5, 500+ → 7
            location_score = min(7.0, math.log10(store_count + 1) * 3.5)
            evidence["store_count"] = SignalValue(
                value=store_count,
                source="website_or_press",
                source_level="fallback",
            )
            if source_level == "none":
                source_level = "fallback"

        # Revenue score (log10 scale: $1M→3.75, $100M→5, $1B→5.6, $10B→10)
        revenue_score = 0.0
        if annual_revenue_usd and annual_revenue_usd > 0:
            revenue_score = min(10.0, math.log10(annual_revenue_usd) * 0.625)
            evidence["annual_revenue_usd"] = SignalValue(
                value=annual_revenue_usd,
                source="press_or_annual_report",
                source_level="fallback",
            )
            if source_level == "none":
                source_level = "fallback"

        # Weighted combination
        score = headcount_score * 0.50 + location_score * 0.30 + revenue_score * 0.20
        score = min(10.0, round(score, 2))

        return DimensionScore(
            score=score,
            confidence_band=_SOURCE_LEVEL_BAND.get(source_level, "wide"),
            source_level=source_level,
            weight_used=dim_config.default_weight,
            effective_weight=dim_config.default_weight,
            evidence=evidence,
            rationale=_scale_rationale(
                score, headcount_exact or headcount_range, store_count, annual_revenue_usd
            ),
        )

    def _score_sector_fit(
        self,
        dim_config: Any,
        profile: dict[str, Any],
        country_code: str,
    ) -> DimensionScore:
        """Score sector fit as a relevance gate — confirms retail presence."""
        sector_meta: dict[str, Any] = profile.get("sector_metadata") or {}
        concentration: str | None = sector_meta.get("sector_concentration")
        other_sectors: list[str] = sector_meta.get("other_sectors") or []

        _CONCENTRATION_SCORE: dict[str, tuple[float, str]] = {
            "primary": (10.0, "secondary"),
            "secondary": (6.0, "fallback"),
            "diversified": (6.0, "fallback"),
        }

        if concentration and concentration in _CONCENTRATION_SCORE:
            score, source_level = _CONCENTRATION_SCORE[concentration]
        else:
            # LLM couldn't confirm retail presence — uncertainty penalty
            score, source_level = 3.0, "fallback"

        evidence: dict[str, SignalValue] = {
            "sector_concentration": SignalValue(
                value=concentration or "unknown",
                source="website_description",
                source_level=source_level,
            ),
        }
        if other_sectors:
            evidence["other_sectors"] = SignalValue(
                value=other_sectors,
                source="website_description",
                source_level=source_level,
            )

        return DimensionScore(
            score=round(score, 2),
            confidence_band=_SOURCE_LEVEL_BAND.get(source_level, "wide"),
            source_level=source_level,
            weight_used=dim_config.default_weight,
            effective_weight=dim_config.default_weight,
            evidence=evidence,
            rationale=_dominance_rationale(concentration, other_sectors),
        )

    def _score_brand_prominence(
        self,
        dim_config: Any,
        profile: dict[str, Any],
        country_code: str,
    ) -> DimensionScore:
        """Score brand visibility from press coverage, awards, and named leadership."""
        sector_meta: dict[str, Any] = profile.get("sector_metadata") or {}
        press_count: int | None = sector_meta.get("press_mentions_count")
        award_count: int | None = sector_meta.get("award_mentions_count")

        # Leadership names: check sector_metadata first, fall back to raw_llm_extraction
        leadership_raw: list[Any] = sector_meta.get("leadership_names", [])
        if not leadership_raw:
            raw_llm: dict[str, Any] = profile.get("raw_llm_extraction") or {}
            if isinstance(raw_llm, dict):
                leadership_raw = raw_llm.get("leadership_names", [])
        n = len(leadership_raw)

        evidence: dict[str, SignalValue] = {}
        source_level = "none"

        # Press coverage score (0-10, step function)
        press_score = 0.0
        if press_count:
            if press_count >= 21:
                press_score = 10.0
            elif press_count >= 11:
                press_score = 9.0
            elif press_count >= 6:
                press_score = 7.5
            elif press_count >= 3:
                press_score = 5.5
            else:  # 1-2
                press_score = 3.0
            source_level = "fallback"
            evidence["press_mentions_count"] = SignalValue(
                value=press_count,
                source="web_search",
                source_level="fallback",
            )

        # Awards score (0-10, step function)
        awards_score = 0.0
        if award_count:
            if award_count >= 4:
                awards_score = 9.0
            elif award_count >= 2:
                awards_score = 6.5
            else:  # 1
                awards_score = 4.0
            if source_level == "none":
                source_level = "fallback"
            evidence["award_mentions_count"] = SignalValue(
                value=award_count,
                source="web_search",
                source_level="fallback",
            )

        # Named leadership score (0-10, step function) — corroborating signal
        if n == 0:
            leadership_score = 0.0
        elif n == 1:
            leadership_score = 2.0
        elif n <= 2:
            leadership_score = 4.0
        elif n <= 3:
            leadership_score = 5.0
        elif n <= 5:
            leadership_score = 7.0
        elif n <= 8:
            leadership_score = 8.5
        else:
            leadership_score = min(10.0, 8.5 + (n - 8) * 0.2)

        if n > 0:
            # LinkedIn/website source: upgrade to secondary only if no press/awards yet
            if source_level == "none":
                source_level = "secondary"
            evidence["named_executives"] = SignalValue(
                value=n,
                source="linkedin_or_website",
                source_level="secondary",
            )

        score = press_score * 0.55 + awards_score * 0.25 + leadership_score * 0.20
        score = min(10.0, round(score, 2))

        return DimensionScore(
            score=score,
            confidence_band=_SOURCE_LEVEL_BAND.get(source_level, "wide"),
            source_level=source_level,
            weight_used=dim_config.default_weight,
            effective_weight=dim_config.default_weight,
            evidence=evidence,
            rationale=_prominence_rationale(press_count, award_count, n),
        )

    def _compute_base_score(
        self,
        dimension_scores: dict[str, DimensionScore],
        active_dims: list[Any],
    ) -> float:
        """Weighted sum of dimension scores, scaled to 0–100."""
        total_weight = sum(d.default_weight for d in active_dims)
        if total_weight == 0:
            return 0.0
        weighted_sum = sum(
            dimension_scores[d.key].score * d.default_weight
            for d in active_dims
            if d.key in dimension_scores
        )
        # Normalize to 0-100
        base = (weighted_sum / total_weight) * 10
        return round(min(100.0, base), 1)

    def _compute_overall_band(
        self, confidence_bands: dict[str, ConfidenceBand]
    ) -> str:
        """Overall band = worst (widest) band across all dimensions."""
        band_order = {"tight": 0, "medium": 1, "wide": 2}
        worst = "tight"
        for band in confidence_bands.values():
            if band_order.get(band.band, 2) > band_order.get(worst, 0):
                worst = band.band
        return worst


# ---- Private helpers ----

def _scale_rationale(
    score: float,
    headcount: Any,
    store_count: int | None,
    annual_revenue_usd: int | None = None,
) -> str:
    parts = []
    if headcount:
        parts.append(f"headcount: {headcount}")
    if store_count:
        parts.append(f"{store_count} locations")
    if annual_revenue_usd:
        parts.append(f"revenue: ${annual_revenue_usd:,}")
    return ", ".join(parts) if parts else "No size signals found"


def _prominence_rationale(
    press_count: int | None,
    award_count: int | None,
    leadership_count: int = 0,
) -> str:
    parts = []
    if press_count:
        parts.append(f"{press_count} press mention(s)")
    if award_count:
        parts.append(f"{award_count} award(s)")
    if leadership_count:
        parts.append(f"{leadership_count} named executive(s)")
    return ", ".join(parts) if parts else "No brand prominence signals found"


def _dominance_rationale(concentration: str | None, other_sectors: list[str]) -> str:
    if concentration == "primary":
        return "Retail is the primary business"
    elif concentration == "secondary":
        others = ", ".join(other_sectors[:2]) if other_sectors else "other sectors"
        return f"Retail is secondary to {others}"
    elif concentration == "diversified":
        others = ", ".join(other_sectors[:3]) if other_sectors else "multiple sectors"
        return f"Diversified conglomerate — also operates in {others}"
    return "Sector concentration could not be determined"
