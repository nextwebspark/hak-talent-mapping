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
        elif key == "leadership_depth":
            return self._score_leadership_depth(dim_config, profile, country_code)
        elif key == "sector_fit_confidence":
            return self._score_sector_fit(dim_config, profile, country_code)
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

        # Weighted combination
        score = headcount_score * 0.60 + location_score * 0.40
        score = min(10.0, round(score, 2))

        return DimensionScore(
            score=score,
            confidence_band=_SOURCE_LEVEL_BAND.get(source_level, "wide"),
            source_level=source_level,
            weight_used=dim_config.default_weight,
            effective_weight=dim_config.default_weight,
            evidence=evidence,
            rationale=_scale_rationale(score, headcount_exact or headcount_range, store_count),
        )

    def _score_leadership_depth(
        self,
        dim_config: Any,
        profile: dict[str, Any],
        country_code: str,
    ) -> DimensionScore:
        """Score based on named executives in leadership_names."""
        # leadership_names is stored in raw_llm_extraction since we serialize
        # ProfileExtractionResult.sector_metadata there — but we also need
        # the alumni_signals/leadership_names. For MVP, derive from sector_metadata.
        sector_meta: dict[str, Any] = profile.get("sector_metadata") or {}
        leadership_raw: list[Any] = sector_meta.get("leadership_names", [])

        # Also check if raw_llm_extraction has it
        raw_llm: dict[str, Any] = profile.get("raw_llm_extraction") or {}
        if not leadership_raw and isinstance(raw_llm, dict):
            leadership_raw = raw_llm.get("leadership_names", [])

        # Support both legacy list[str] and new list[dict] formats
        n = len(leadership_raw)
        evidence: dict[str, SignalValue] = {}
        source_level = "none"

        # Scoring: 0 names → 0, 1 → 2, 2 → 4, 3 → 5, 5+ → 7, 8+ → 9
        if n == 0:
            score = 0.0
        elif n == 1:
            score = 2.0
        elif n <= 2:
            score = 4.0
        elif n <= 3:
            score = 5.0
        elif n <= 5:
            score = 7.0
        elif n <= 8:
            score = 8.5
        else:
            score = min(10.0, 8.5 + (n - 8) * 0.2)

        if n > 0:
            source_level = "secondary"
            evidence["named_executives"] = SignalValue(
                value=n,
                source="linkedin_or_website",
                source_level="secondary",
            )

        return DimensionScore(
            score=round(score, 2),
            confidence_band=_SOURCE_LEVEL_BAND.get(source_level, "wide"),
            source_level=source_level,
            weight_used=dim_config.default_weight,
            effective_weight=dim_config.default_weight,
            evidence=evidence,
            rationale=f"{n} named executive(s) found",
        )

    def _score_sector_fit(
        self,
        dim_config: Any,
        profile: dict[str, Any],
        country_code: str,
    ) -> DimensionScore:
        """Score sector fit based on regulatory confirmation and description."""
        sector_meta: dict[str, Any] = profile.get("sector_metadata") or {}
        ded_confirmed: bool | None = sector_meta.get("ded_license_confirmed")
        description: str = profile.get("description_clean") or ""

        evidence: dict[str, SignalValue] = {}
        source_level = "none"
        score = 0.0

        if ded_confirmed is True:
            score = 9.5
            source_level = "primary"
            evidence["ded_license"] = SignalValue(
                value=True,
                source="ded_register",
                source_level="primary",
            )
        elif description:
            # Heuristic: if description mentions the sector keyword, score modestly
            sector_keywords = ["retail", "store", "shop", "brand", "supermarket", "fashion"]
            desc_lower = description.lower()
            matches = sum(1 for kw in sector_keywords if kw in desc_lower)
            if matches >= 2:
                score = 6.5
                source_level = "secondary"
            elif matches == 1:
                score = 5.0
                source_level = "fallback"
            else:
                score = 3.0
                source_level = "fallback"
            evidence["description_match"] = SignalValue(
                value=matches,
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
            rationale=_fit_rationale(score, ded_confirmed),
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
) -> str:
    parts = []
    if headcount:
        parts.append(f"headcount: {headcount}")
    if store_count:
        parts.append(f"{store_count} locations")
    return ", ".join(parts) if parts else "No size signals found"


def _fit_rationale(score: float, ded_confirmed: bool | None) -> str:
    if ded_confirmed is True:
        return "DED trade license confirmed"
    if score >= 6:
        return "Sector keywords present in description"
    if score >= 4:
        return "Weak sector match from description"
    return "Sector fit unclear from available data"
