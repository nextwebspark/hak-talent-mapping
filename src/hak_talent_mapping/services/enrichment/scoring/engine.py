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

# Headcount range → approximate score (logarithmic scale)
_HEADCOUNT_SCORE: dict[str, float] = {
    "1-10": 1.0,
    "11-50": 2.5,
    "51-200": 4.5,
    "201-500": 6.0,
    "501-1000": 7.5,
    "1001-5000": 8.5,
    "5001+": 10.0,
}

# C-suite title keywords for role-aware leadership scoring.
# GCC companies often use non-standard titles — "managing partner", "vice chairman",
# "group chief executive", "executive chairman" — that carry CEO-equivalent authority.
_CEO_TITLES = {
    "ceo", "md", "managing director", "chief executive", "president",
    "gm", "general manager", "managing partner", "executive chairman",
    "group chief executive", "executive director",
}
_CSUITE_TITLES = {
    "cfo", "coo", "cco", "cmo", "cto", "chro", "cpo", "cso",
    "chief financial", "chief operating", "chief commercial", "chief marketing",
    "chief technology", "chief human", "chief product",
}
_DIRECTOR_TITLES = {"director", "vp", "vice president", "head of", "svp", "evp"}


class ScoringEngine:
    """Computes dimension scores from a company profile row using sector YAML config.

    All sector-specific configuration (weights, archetype tables, signal definitions)
    comes from the sector YAML. The engine contains only shared scoring math so that
    a new sector is added by creating a YAML file, not by changing this class.
    """

    def __init__(self, config: SectorScoringConfig) -> None:
        self._config = config
        self._config_hash = compute_config_hash(config)

    def score(
        self,
        profile_row: dict[str, Any],
        country_code: str = "",
        archetype: str = "base",
    ) -> CompanyScoreRecord:
        """Compute scores for all active dimensions and return a CompanyScoreRecord.

        Args:
            profile_row: A company_details row dict from Supabase.
            country_code: ISO-2 country code for source resolution.
            archetype: Role archetype for brief-adjusted score (e.g. "cco", "coo").
                       Defaults to "base" (uses default dimension weights).
        """
        detail_id: str = profile_row["id"]
        dimension_scores: dict[str, DimensionScore] = {}
        confidence_bands: dict[str, ConfidenceBand] = {}

        active_dims = [d for d in self._config.dimensions if d.default_weight > 0]

        for dim_config in active_dims:
            dim_score = self._score_dimension(dim_config, profile_row, country_code)
            dimension_scores[dim_config.key] = dim_score
            band = ConfidenceBand(
                band=dim_score.confidence_band,
                tolerance_pct=_BAND_TOLERANCE.get(dim_score.confidence_band, 35.0),
            )
            confidence_bands[dim_config.key] = band

        base_score = self._compute_base_score(dimension_scores, active_dims)
        overall_band = self._compute_overall_band(confidence_bands)
        brief_adjusted = self._compute_brief_adjusted_score(dimension_scores, archetype)
        d4_is_enriching = self._check_d4_enriching()

        return CompanyScoreRecord(
            company_detail_id=detail_id,
            base_score=base_score,
            dimension_scores=dimension_scores,
            confidence_bands=confidence_bands,
            overall_confidence_band=overall_band,
            overall_tolerance_pct=_BAND_TOLERANCE.get(overall_band, 35.0),
            brief_adjusted_score=brief_adjusted,
            applied_archetype=archetype,
            d4_is_enriching=d4_is_enriching,
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
        elif key == "brand_market_prominence":
            return self._score_brand_prominence(dim_config, profile, country_code)
        elif key == "leadership_depth":
            return self._score_leadership_depth(dim_config, profile, country_code)
        elif key == "talent_export_history":
            return self._score_talent_export(dim_config, profile, country_code)
        elif key == "sector_fit_confidence":
            return self._score_sector_fit(dim_config, profile, country_code)
        elif key == "executive_talent_momentum":
            return self._score_talent_momentum(dim_config, profile, country_code)
        else:
            return DimensionScore(
                score=0.0,
                confidence_band="wide",
                source_level="none",
                weight_used=dim_config.default_weight,
                effective_weight=dim_config.default_weight,
                rationale=f"No scorer implemented for dimension '{key}'",
            )

    # ------------------------------------------------------------------
    # D1 — Organisational Scale
    # ------------------------------------------------------------------

    def _score_organisational_scale(
        self,
        dim_config: Any,
        profile: dict[str, Any],
        country_code: str,
    ) -> DimensionScore:
        """Score based on headcount, location count, and annual revenue."""
        headcount_range: str | None = profile.get("headcount_range")
        headcount_exact: int | None = profile.get("headcount_exact")
        sector_meta: dict[str, Any] = profile.get("sector_metadata") or {}
        store_count: int | None = sector_meta.get("store_count")
        revenue: int | None = sector_meta.get("annual_revenue_usd")

        evidence: dict[str, SignalValue] = {}
        source_level = "none"

        # Headcount score (logarithmic: 10→1, 100→2, 1000→3, 10000→4, 50000→4.7)
        headcount_score = 0.0
        if headcount_exact and headcount_exact > 0:
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

        # Location count (1 store→1, 10→3, 100→5, 500+→7)
        location_score = 0.0
        if store_count:
            location_score = min(7.0, math.log10(store_count + 1) * 3.5)
            evidence["store_count"] = SignalValue(
                value=store_count,
                source="website_or_press",
                source_level="fallback",
            )
            if source_level == "none":
                source_level = "fallback"

        # Revenue signal ($1M→1, $10M→2, $100M→3, $1B→4, $10B→5, capped at 10)
        revenue_score = 0.0
        if revenue and revenue > 0:
            revenue_score = min(10.0, math.log10(revenue / 1_000_000 + 1) * 3.0)
            evidence["annual_revenue_usd"] = SignalValue(
                value=revenue,
                source="press_or_annual_report",
                source_level="secondary",
            )
            if source_level == "none":
                source_level = "secondary"

        # Signal weights: headcount 50%, location 30%, revenue 20%
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
                headcount_exact or headcount_range, store_count, revenue
            ),
        )

    # ------------------------------------------------------------------
    # D2 — Brand & Market Prominence
    # ------------------------------------------------------------------

    def _score_brand_prominence(
        self,
        dim_config: Any,
        profile: dict[str, Any],
        country_code: str,
    ) -> DimensionScore:
        """Score based on press coverage, awards, and category leadership signals."""
        sector_meta: dict[str, Any] = profile.get("sector_metadata") or {}
        press_count: int = int(sector_meta.get("press_mentions_count") or 0)
        award_count: int = int(sector_meta.get("award_mentions_count") or 0)
        category_leader: bool = bool(sector_meta.get("category_leader_signal"))

        evidence: dict[str, SignalValue] = {}
        source_level = "none"

        # Press: up to 5 points (each mention ~0.8pt, capped at 5)
        press_score = min(5.0, press_count * 0.8)
        if press_count > 0:
            evidence["press_mentions"] = SignalValue(
                value=press_count,
                source="tier1_press",
                source_level="secondary",
            )
            source_level = "secondary"

        # Awards: each award = 1.0 point, capped at 3
        award_score = min(3.0, award_count * 1.0)
        if award_count > 0:
            evidence["award_mentions"] = SignalValue(
                value=award_count,
                source="industry_awards",
                source_level="secondary",
            )
            if source_level == "none":
                source_level = "secondary"

        # Category leadership: 1.5 points (at most once)
        category_score = 1.5 if category_leader else 0.0
        if category_leader:
            evidence["category_leader"] = SignalValue(
                value=True,
                source="press_or_trade",
                source_level="secondary",
            )
            if source_level == "none":
                source_level = "secondary"

        score = min(10.0, round(press_score + award_score + category_score, 2))

        # Cap at 4 if no direct press evidence (only description available)
        if source_level == "none":
            score = 0.0

        return DimensionScore(
            score=score,
            confidence_band=_SOURCE_LEVEL_BAND.get(source_level, "wide"),
            source_level=source_level,
            weight_used=dim_config.default_weight,
            effective_weight=dim_config.default_weight,
            evidence=evidence,
            rationale=_prominence_rationale(press_count, award_count, category_leader),
        )

    # ------------------------------------------------------------------
    # D3 — Leadership Depth
    # ------------------------------------------------------------------

    def _score_leadership_depth(
        self,
        dim_config: Any,
        profile: dict[str, Any],
        country_code: str,
    ) -> DimensionScore:
        """Role-aware scoring: CEO/MD=2pts, each C-suite=1pt, Director/Head=0.5pt.

        Bonuses (per spec):
          +1.0pt if 3+ distinct functions covered
          +0.5pt if Glassdoor/AmbitionBox senior leadership rating >= 4.0
          +0.5pt if CEO approval >= 70%
        """
        sector_meta: dict[str, Any] = profile.get("sector_metadata") or {}
        raw_names: list[Any] = sector_meta.get("leadership_names", [])

        # Also check raw_llm_extraction as fallback
        if not raw_names:
            raw_llm: dict[str, Any] = profile.get("raw_llm_extraction") or {}
            if isinstance(raw_llm, dict):
                raw_names = raw_llm.get("leadership_names", [])

        evidence: dict[str, SignalValue] = {}
        source_level = "none"

        if not raw_names:
            return DimensionScore(
                score=0.0,
                confidence_band="wide",
                source_level="none",
                weight_used=dim_config.default_weight,
                effective_weight=dim_config.default_weight,
                rationale="No named executives found",
            )

        # Support both list[str] (legacy) and list[dict] (new role-aware format)
        has_ceo = False
        c_suite_count = 0
        director_count = 0
        functions_seen: set[str] = set()

        for entry in raw_names:
            if isinstance(entry, dict):
                title = (entry.get("title") or "").lower()
                function = (entry.get("function") or "").strip()
                if function:
                    functions_seen.add(function)
            else:
                # Legacy string format — do best-effort title parsing
                title = str(entry).lower()
                function = ""

            if any(t in title for t in _CEO_TITLES):
                has_ceo = True
            elif any(t in title for t in _CSUITE_TITLES):
                c_suite_count += 1
            elif any(t in title for t in _DIRECTOR_TITLES):
                director_count += 1

        # Score per canonical spec
        ceo_score = 2.0 if has_ceo else 0.0
        c_suite_score = min(3.0, c_suite_count * 1.0)
        director_score = min(2.0, director_count * 0.5)
        breadth_bonus = 1.0 if len(functions_seen) >= 3 else 0.0

        # Fallback: if we only have strings and couldn't parse titles,
        # fall back to count-based scoring (preserves behaviour for old data)
        total_named = len(raw_names)
        if not has_ceo and c_suite_count == 0 and director_count == 0 and total_named > 0:
            score = _count_based_leadership_score(total_named)
        else:
            score = ceo_score + c_suite_score + director_score + breadth_bonus

        # Glassdoor/AmbitionBox sub-signal bonuses
        glassdoor_rating: float | None = sector_meta.get("glassdoor_senior_leadership_rating")
        ceo_approval: int | None = sector_meta.get("ceo_approval_pct")
        glassdoor_bonus = 0.0
        if glassdoor_rating is not None and glassdoor_rating >= 4.0:
            glassdoor_bonus += 0.5
            evidence["glassdoor_rating"] = SignalValue(
                value=glassdoor_rating,
                source="glassdoor_or_ambitionbox",
                source_level="secondary",
            )
        if ceo_approval is not None and ceo_approval >= 70:
            glassdoor_bonus += 0.5
            evidence["ceo_approval"] = SignalValue(
                value=ceo_approval,
                source="glassdoor_or_ambitionbox",
                source_level="secondary",
            )
        score = min(10.0, score + glassdoor_bonus)

        source_level = "secondary"
        evidence["named_executives"] = SignalValue(
            value=total_named,
            source="linkedin_or_website",
            source_level="secondary",
        )
        if has_ceo:
            evidence["ceo_confirmed"] = SignalValue(
                value=True,
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
            rationale=_leadership_rationale(has_ceo, c_suite_count, director_count, total_named),
        )

    # ------------------------------------------------------------------
    # D4 — Talent Export History
    # ------------------------------------------------------------------

    def _score_talent_export(
        self,
        dim_config: Any,
        profile: dict[str, Any],
        country_code: str,
    ) -> DimensionScore:
        """Score based on alumni in VP+ roles at other recognised companies."""
        sector_meta: dict[str, Any] = profile.get("sector_metadata") or {}
        # alumni_signals is stored in sector_metadata by the pipeline
        alumni: list[str] = sector_meta.get("alumni_signals", [])

        # Also check raw_llm_extraction
        if not alumni:
            raw_llm: dict[str, Any] = profile.get("raw_llm_extraction") or {}
            if isinstance(raw_llm, dict):
                alumni = raw_llm.get("alumni_signals", [])

        n = len(alumni)
        evidence: dict[str, SignalValue] = {}
        source_level = "none"

        # Scoring per canonical spec
        if n == 0:
            score = 0.0
        elif n <= 2:
            score = 3.5  # 1-2 alumni → 3-4 range midpoint
        elif n <= 5:
            score = 6.0  # 3-5 alumni → 5-7 range midpoint
        elif n <= 10:
            score = 8.5  # 6-10 alumni → 8-9 range midpoint
        else:
            score = 10.0  # 10+ alumni

        if n > 0:
            source_level = "fallback"  # alumni data is typically unverified at this stage
            evidence["tracked_alumni"] = SignalValue(
                value=n,
                source="linkedin_alumni_or_press",
                source_level="fallback",
            )

        return DimensionScore(
            score=round(score, 2),
            confidence_band=_SOURCE_LEVEL_BAND.get(source_level, "wide"),
            source_level=source_level,
            weight_used=dim_config.default_weight,
            effective_weight=dim_config.default_weight,
            cold_start_active=self._check_d4_enriching(),
            evidence=evidence,
            rationale=f"{n} tracked alumni in VP+ roles at other companies",
        )

    # ------------------------------------------------------------------
    # D5 — Sector Fit Confidence
    # ------------------------------------------------------------------

    def _score_sector_fit(
        self,
        dim_config: Any,
        profile: dict[str, Any],
        country_code: str,
    ) -> DimensionScore:
        """Score sector fit based on regulatory confirmation and description."""
        sector_meta: dict[str, Any] = profile.get("sector_metadata") or {}
        ded_confirmed: bool | None = sector_meta.get("ded_license_confirmed")
        relevance_type: str | None = sector_meta.get("relevance_type")
        description: str = profile.get("description_clean") or ""

        evidence: dict[str, SignalValue] = {}
        source_level = "none"
        score = 0.0

        if ded_confirmed is True:
            score = 9.5
            source_level = "primary"
            evidence["regulatory_confirmation"] = SignalValue(
                value=True,
                source="ded_register",
                source_level="primary",
            )
        elif description:
            sector_keywords = dim_config.sector_keywords or [
                "retail", "retailer", "store", "shop", "brand",
                "supermarket", "fashion", "luxury", "distribution",
            ]
            desc_lower = description.lower()
            matches = sum(1 for kw in sector_keywords if kw in desc_lower)

            # Adjust score based on relevance_type if available
            if relevance_type == "adjacent":
                score = min(5.0, matches * 1.5)
                source_level = "fallback"
            elif relevance_type == "inferred":
                score = min(3.5, matches * 1.0)
                source_level = "fallback"
            elif relevance_type == "direct":
                # Direct sector match — keyword count just confirms, minimum 6.5
                score = 6.5 if matches >= 1 else 5.0
                source_level = "secondary" if matches >= 1 else "fallback"
            elif matches >= 2:
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
            rationale=_fit_rationale(score, ded_confirmed, relevance_type),
        )

    # ------------------------------------------------------------------
    # D6 — Executive Talent Momentum
    # ------------------------------------------------------------------

    def _score_talent_momentum(
        self,
        dim_config: Any,
        profile: dict[str, Any],
        country_code: str,
    ) -> DimensionScore:
        """Score based on open senior roles, C-suite movement, and M&A signals.

        Additive scoring per spec:
          M&A last 12m → 3.0pts, M&A 12-24m → 1.5pts, older/none → 0pts
          2+ VP open roles → 2.0pts, 1 role → 1.0pt
          3+ C-suite departures (18m) → 3.0pts, 1-2 → 1.5pts
          Cap at 10.
        """
        sector_meta: dict[str, Any] = profile.get("sector_metadata") or {}
        open_roles: int = int(sector_meta.get("open_senior_roles_count") or 0)
        departures: int = int(sector_meta.get("c_suite_departures_18m") or 0)
        ma_signal: bool = bool(sector_meta.get("ma_restructure_signal"))
        ma_recency: str | None = sector_meta.get("ma_restructure_recency")

        evidence: dict[str, SignalValue] = {}
        source_level = "none"

        # Open senior roles: 1 role → 1.0pt, 2+ → 2.0pts (primary — LinkedIn Jobs)
        roles_score = 0.0
        if open_roles >= 2:
            roles_score = 2.0
        elif open_roles == 1:
            roles_score = 1.0
        if open_roles > 0:
            evidence["open_senior_roles"] = SignalValue(
                value=open_roles,
                source="linkedin_jobs_or_careers",
                source_level="secondary",
            )
            source_level = "secondary"

        # C-suite departures last 18m: 1-2 → 1.5pts, 3+ → 3.0pts
        departures_score = 0.0
        if departures >= 3:
            departures_score = 3.0
        elif departures >= 1:
            departures_score = 1.5
        if departures > 0:
            evidence["c_suite_departures"] = SignalValue(
                value=departures,
                source="press_or_linkedin",
                source_level="fallback",
            )
            if source_level == "none":
                source_level = "fallback"

        # M&A / restructure: recency-gated per spec
        ma_score = 0.0
        if ma_signal:
            if ma_recency == "last_12m":
                ma_score = 3.0
            elif ma_recency == "12_24m":
                ma_score = 1.5
            # older than 24m or recency unknown but signal present: 0pts
            evidence["ma_restructure"] = SignalValue(
                value=ma_recency or "signal_present",
                source="press",
                source_level="fallback",
            )
            if source_level == "none":
                source_level = "fallback"

        score = min(10.0, round(roles_score + departures_score + ma_score, 2)) if source_level != "none" else 0.0

        return DimensionScore(
            score=score,
            confidence_band=_SOURCE_LEVEL_BAND.get(source_level, "wide"),
            source_level=source_level,
            weight_used=dim_config.default_weight,
            effective_weight=dim_config.default_weight,
            evidence=evidence,
            rationale=_momentum_rationale(open_roles, departures, ma_signal, ma_recency),
        )

    # ------------------------------------------------------------------
    # Score aggregation helpers
    # ------------------------------------------------------------------

    def _compute_base_score(
        self,
        dimension_scores: dict[str, DimensionScore],
        active_dims: list[Any],
    ) -> float:
        """Weighted sum of dimension scores, scaled to 0–100.

        Uses cold_start_weight for D4 when the platform alumni database is not
        yet populated (cold_start_active=True on the D4 dimension score).
        """
        def _effective_weight(dim: Any) -> float:
            if (
                dim.key == "talent_export_history"
                and dim.cold_start_weight is not None
                and dim.cold_start_weight < dim.default_weight
                and dim.key in dimension_scores
                and dimension_scores[dim.key].cold_start_active
            ):
                return dim.cold_start_weight
            return dim.default_weight

        total_weight = sum(_effective_weight(d) for d in active_dims)
        if total_weight == 0:
            return 0.0
        weighted_sum = sum(
            dimension_scores[d.key].score * _effective_weight(d)
            for d in active_dims
            if d.key in dimension_scores
        )
        return round(min(100.0, (weighted_sum / total_weight) * 10), 1)

    def _compute_brief_adjusted_score(
        self,
        dimension_scores: dict[str, DimensionScore],
        archetype: str,
    ) -> float | None:
        """Compute the brief-adjusted score using archetype weights from sector YAML.

        Returns None if no archetype_weights are defined in the config.
        """
        archetype_weights = self._config.archetype_weights
        if not archetype_weights:
            return None

        weights = archetype_weights.get(archetype) or archetype_weights.get("base")
        if not weights:
            return None

        total_weight = sum(weights.values())
        if total_weight == 0:
            return None

        weighted_sum = sum(
            dimension_scores[key].score * w
            for key, w in weights.items()
            if key in dimension_scores
        )
        return round(min(100.0, (weighted_sum / total_weight) * 10), 1)

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

    def _check_d4_enriching(self) -> bool:
        """Return True if D4 is in cold-start mode (cold_start_weight < default_weight)."""
        for dim in self._config.dimensions:
            if dim.key == "talent_export_history":
                cold = dim.cold_start_weight
                return cold is not None and cold < dim.default_weight
        return False


# ---- Private helpers ----


def _count_based_leadership_score(n: int) -> float:
    """Fallback count-based scoring for legacy list[str] leadership_names."""
    if n == 0:
        return 0.0
    elif n == 1:
        return 2.0
    elif n <= 2:
        return 4.0
    elif n <= 3:
        return 5.0
    elif n <= 5:
        return 7.0
    elif n <= 8:
        return 8.5
    else:
        return min(10.0, 8.5 + (n - 8) * 0.2)


def _scale_rationale(
    headcount: Any,
    store_count: int | None,
    revenue: int | None,
) -> str:
    parts = []
    if headcount:
        parts.append(f"headcount: {headcount}")
    if store_count:
        parts.append(f"{store_count} locations")
    if revenue:
        parts.append(f"revenue: ${revenue:,}")
    return ", ".join(parts) if parts else "No size signals found"


def _prominence_rationale(
    press_count: int,
    award_count: int,
    category_leader: bool,
) -> str:
    parts = []
    if press_count:
        parts.append(f"{press_count} press mention(s)")
    if award_count:
        parts.append(f"{award_count} award(s)")
    if category_leader:
        parts.append("category leader signal")
    return ", ".join(parts) if parts else "No prominence signals found"


def _leadership_rationale(
    has_ceo: bool,
    c_suite_count: int,
    director_count: int,
    total: int,
) -> str:
    parts = []
    if has_ceo:
        parts.append("CEO/MD confirmed")
    if c_suite_count:
        parts.append(f"{c_suite_count} other C-suite")
    if director_count:
        parts.append(f"{director_count} Director/VP level")
    if not parts:
        parts.append(f"{total} named executive(s)")
    return ", ".join(parts)


def _fit_rationale(
    score: float,
    ded_confirmed: bool | None,
    relevance_type: str | None,
) -> str:
    if ded_confirmed is True:
        return "DED trade license confirmed (primary source)"
    if relevance_type == "adjacent":
        return "Adjacent sector — partial retail activity confirmed"
    if relevance_type == "inferred":
        return "Retail inferred from holding structure"
    if score >= 6:
        return "Sector keywords present in description"
    if score >= 4:
        return "Weak sector match from description"
    return "Sector fit unclear from available data"


def _momentum_rationale(
    open_roles: int,
    departures: int,
    ma_signal: bool,
    ma_recency: str | None = None,
) -> str:
    parts = []
    if open_roles:
        parts.append(f"{open_roles} open VP+ role(s)")
    if departures:
        parts.append(f"{departures} C-suite departure(s) last 18m")
    if ma_signal:
        recency_label = {"last_12m": " (last 12m)", "12_24m": " (12-24m)"}.get(ma_recency or "", "")
        parts.append(f"M&A/restructure signal{recency_label}")
    return ", ".join(parts) if parts else "No talent momentum signals found"
