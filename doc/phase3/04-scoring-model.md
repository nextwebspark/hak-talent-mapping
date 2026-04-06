# Phase 3: Scoring Model & Sector Configs

---

## 5 Scoring Dimensions — Universal Framework

The scoring framework has **5 fixed dimensions**. Their names and semantic meaning are universal across all sectors. What varies per sector is defined entirely in the sector's YAML config: which signals to collect, which data sources to use per country, how to weight the signals, and how to interpret the thresholds.

```
┌──────────────────────────────────────────────────────────────────────────┐
│                        COMPANY SCORE CARD                                │
│                                                                          │
│  ┌────────────────────────────────────────────────────────────────────┐  │
│  │  Landmark Group — Retail Division                                  │  │
│  │  Base Score: 84/100  │  Brief-Adjusted (CCO): 89/100  │ ±8%       │  │
│  └────────────────────────────────────────────────────────────────────┘  │
│                                                                          │
│  ┌─────────────────────┐  ┌─────────────────────┐                       │
│  │ Organisational Scale│  │ Brand & Market       │                       │
│  │ Weight: 25%         │  │ Prominence           │                       │
│  │ Score: 8.5/10       │  │ Weight: 20%          │                       │
│  │ Band: tight (±10%)  │  │ Score: 8.8/10        │                       │
│  │                     │  │ Band: tight (±10%)   │                       │
│  │ ~50,000 UAE staff   │  │ 14 tier-1 press mnts │                       │
│  │ 200+ locations      │  │ Retailer of Year ME  │                       │
│  └─────────────────────┘  └─────────────────────┘                       │
│                                                                          │
│  ┌─────────────────────┐  ┌─────────────────────┐                       │
│  │ Leadership Depth    │  │ Talent Export        │                       │
│  │ Weight: 25%         │  │ History [Enriching]  │                       │
│  │ Score: 8.2/10       │  │ Weight: 8% (cold)    │                       │
│  │ Band: tight (±10%)  │  │ Score: 7.5/10        │                       │
│  │                     │  │ Band: medium (±20%)  │                       │
│  │ CEO, CFO, CCO, COO, │  │ 8 alumni in VP+      │                       │
│  │ CMO confirmed       │  │ roles elsewhere      │                       │
│  └─────────────────────┘  └─────────────────────┘                       │
│                                                                          │
│  ┌─────────────────────────────────────────────┐                        │
│  │ Sector Fit Confidence                        │                        │
│  │ Weight: 15%  │  Score: 10.0/10              │                        │
│  │ Band: tight (±10%)                          │                        │
│  │ DED trade license → retail confirmed        │                        │
│  │ Direct — multi-format retail                │                        │
│  └─────────────────────────────────────────────┘                        │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Universal Dimension Definitions

Each dimension has a **fixed semantic meaning** that holds across all sectors. The signals, proxies, thresholds, and sources are sector-variable and defined in YAML.

### Dimension 1: Organisational Scale

**What it always measures:** Operational complexity and executive leadership capacity. Larger organisations tend to have deeper leadership structures — more functions, more levels, more mappable talent.

**Sector-variable elements:**

| | Retail | Academic |
|---|---|---|
| Primary proxy | Employee headcount | Student enrolment |
| Secondary proxy | Store / location count | Campus count |
| Thresholds | < 100 staff → 1–2 | < 1,000 students → 1–2 |
| Bonus | +1.5 pts for store count | +1.0 pts for multi-campus |
| Scale note | Headcount 50% weight; locations 30%; revenue 20% | Enrolment 60%; campus 30%; staff 10% |

Formula (logarithmic — prevents mega-companies dominating by raw size alone):
```
primary_score = min(10, threshold_bracket_lookup(primary_signal))
secondary_score = min(10, 2.0 × log₁₀(secondary_signal + 1))
scale_score = primary_weight × primary_score + secondary_weight × secondary_score + bonus
```

### Dimension 2: Brand & Market Prominence

**What it always measures:** Competitive relevance and talent gravity. Companies that attract executive-calibre people are either well-known or well-regarded in their sector.

**Sector-variable elements:**

| | Retail | Academic |
|---|---|---|
| Primary signal | Tier-1 press mentions (last 12 months) | Regulatory inspection rating (KHDA/ADEK Outstanding) |
| Secondary signal | Trade press, category leadership | International accreditation (IB, AACSB, QS Top 500) |
| Tertiary signal | Industry awards | Education sector press |
| Score cap if unverifiable | 4/10 | 3/10 |
| Recency decay | Yes — 0.5× per 12 months | No — regulatory ratings are stable |

For Academic, regulatory ratings are the *primary* signal, not media — a KHDA "Outstanding" is objective, structured, and publicly verifiable. Media prominence is supporting only.

### Dimension 3: Leadership Depth

**What it always measures:** Mappable senior leadership. A company scores here based on whether it employs identifiable executives — not just whether it is large or prominent.

**Sector-variable elements:**

| | Retail | Academic (K-12 Group) |
|---|---|---|
| C-suite equivalent | CEO / MD | CEO / Superintendent / Director General |
| N-1 equivalent | CCO, COO, CFO, CMO | Regional Director, Director of Education |
| N-2 equivalent | Director / Head of function | Head of Curriculum, Head of Operations |
| Breadth functions | Commercial, Ops, Finance, Marketing, Tech, HR | Academic, Ops, Commercial, Finance, HR, Curriculum |
| Sector flag | None | Expat leadership flag (−0.5 stability discount for GCC K-12) |

Scoring logic:
```
named_ceo_confirmed:                         +2.0 points
each additional C-suite named (max 3):       +1.0 each
director / head level confirmed (max 4):     +0.5 each
functional breadth bonus (3+ functions):     +1.0
tenure stability (avg 3+ years visible):     +1.0
expat leadership flag (if applicable):       −0.5
total capped at 10
```

**LinkedIn penetration adjustments** (per country, per sector config):

| Market | Penetration | Confidence Adjustment |
|--------|-------------|----------------------|
| UAE | High | No adjustment |
| Saudi Arabia | Good | −5% confidence |
| Qatar / Bahrain | Moderate | −10% confidence |
| Kuwait / Jordan | Moderate | −10% confidence |
| Egypt (mid-market) | Lower | −20% confidence |

### Dimension 4: Talent Export History

**What it always measures:** A quality multiplier. Organisations that have historically produced leaders now working at other major companies in the sector are proven talent pools — regardless of current size.

**Sector-variable elements:**

| | Retail | Academic |
|---|---|---|
| Alumni source | LinkedIn alumni search | LinkedIn alumni search |
| Named clusters tracked | None at launch | GEMS alumni, Taaleem alumni, AUS alumni (first-class signals) |
| Sector note | Alumni tracked in VP+ retail roles | Education talent moves within recognisable clusters; pattern recognition > anonymous counts |
| Cold-start weight | 8% (→ 15% post-launch) | 8% (→ 15% post-launch) |

Scoring logic:
```
1–2 tracked alumni in VP+ roles elsewhere:     3–4 points
3–5 tracked alumni in VP+ roles elsewhere:     5–7 points
6–10 tracked alumni in VP+ roles elsewhere:    8–9 points
10+ tracked alumni in VP+ roles elsewhere:     10 points
press-confirmed export (no LinkedIn):          up to 5 points
named network cluster identified:              +1.0 bonus (Academic only, via sector_extensions config)
no signal available:                           0 points, flagged
```

### Dimension 5: Sector Fit Confidence

**What it always measures:** A gate and a score simultaneously. Confirms this is a genuine operator in the target sector and country before ranking it. Mismatch here pollutes the entire result list.

**Sector-variable elements:**

| | Retail | Academic |
|---|---|---|
| Gate: primary confirmation | DED trade license activity code (AE) | KHDA/ADEK licensed school register (AE) |
| Sub-sector gate | Not needed | Required: K-12 / HE / Vocational / EdTech must not be ranked together |
| Sub-sector tags: direct | Fashion retail, Grocery, Electronics, Luxury, F&B, Multi-format, E-commerce | K-12 Schools, Universities, Vocational Institutes, Professional Dev, EdTech |
| Sub-sector tags: adjacent | Wholesale, Franchise operator, Retail real estate | Education Management, Assessment Bodies, Educational Publishing |
| Sub-sector tags: inferred | Holding company with retail subsidiary | Holding company with education subsidiary |

Fallback hierarchy (universal logic — sources vary by sector and country YAML):
```
1. Regulatory activity code confirms sector as primary activity → 9–10
2. Stock exchange classification confirms sector              → 7–8
3. Company website clearly describes sector as primary       → 6–7
4. Press consistently describes company as in-sector         → 5–6
5. Sector inferred from holding group structure              → 3–4
6. Sector inferred from product/brand description only       → 1–2
```

---

## Cold-Start Handling for Talent Export History

Talent Export History is the hardest dimension to populate at launch because it requires accumulated platform data. Two-phase approach:

```
Phase 1 — Launch
  effective_weight = 0.08  (reduced from 0.15)
  redistribution:
    organisational_scale += 0.04   (25% → 29%)
    leadership_depth     += 0.03   (25% → 28%)
  ui_flag = "Enriching"
  cold_start_active = true in dimension_scores JSONB

Phase 2 — Post-launch (when platform accumulates sufficient alumni data)
  cold_start_weight set to null in YAML config
  effective_weight = 0.15  (full weight restored)
  cold_start_active = false
  Named alumni clusters tracked per company over time
```

This is a **config-driven runtime check** — no code change needed to exit cold-start. Set `cold_start_weight: null` in the sector YAML and re-score.

---

## Country-Portable Source Resolution

Every signal in every dimension has a `source_config` block with per-country entries and a `_default` fallback. At scoring time:

```
company.country_code = "SA"
        │
        ▼
signal.source_config["SA"] found → use SA primary/secondary/fallback
signal.source_config["SA"] not found → use signal.source_config["_default"]
        │
        ▼
Record source_level used: "primary" / "secondary" / "fallback"
→ determines confidence band for this signal
```

Example for Dimension 1 (Organisational Scale) across countries:

| Country | Primary Source | Secondary Source | Fallback |
|---------|---------------|-----------------|---------|
| UAE | DED trade license database, DIFC/ADGM registers | LinkedIn headcount, mall tenant lists | Job posting volume, press |
| Saudi Arabia | MISA commercial register, CR | Tadawul filings, LinkedIn | Press, brand website |
| Qatar | Ministry of Commerce registration | Qatar Stock Exchange filings | LinkedIn, press |
| Kuwait | Ministry of Commerce & Industry | Kuwait Stock Exchange | LinkedIn, brand website |
| Egypt | GAFI commercial register | EGX filings | Press, LinkedIn |
| Bahrain | MOIC Sijilat register | Bahrain Bourse | LinkedIn, press |
| Jordan | Companies Control Department | ASE filings | LinkedIn, press |
| `_default` | LinkedIn company page headcount | Brand website, store locator | Press mentions of scale |

---

## Confidence Band System

Three structured bands — not a continuous numeric score. Tied directly to the source quality level used per dimension.

| Band | Source Level | Tolerance | Trigger |
|------|-------------|-----------|---------|
| tight | primary confirmed | ±10% | Normal — no UI flag |
| medium | secondary source only | ±20% | Normal — no UI flag |
| wide | fallback only | ±35% | Flagged in UI — "data thin" warning |

**Per-dimension band** = worst band among signals used for that dimension.
**Overall band** = weighted combination across all 5 dimensions.

LinkedIn confidence adjustments (from Dimension 3) are applied on top of the base band, not as a separate band — they reduce the confidence numeric value within the band.

---

## Sub-Sector Gating

An optional pre-scoring gate, activated by `sub_sector_gate.enabled: true` in the sector config. Currently required for Academic; not used for Retail.

**When used (Academic example):**
- Before any scoring runs, each institution is classified into one of: K-12 / Higher Education / Vocational / EdTech
- A search for "top academic institutions in Saudi Arabia" with a Head of School brief only scores K-12 institutions
- HE, Vocational, EdTech are excluded from the ranked list unless the user explicitly toggles them in
- Cross-sub-sector searches are permitted but flagged — results are grouped by sub-sector

**Result stored in `company_scores`:**
- `sub_sector_gate_result`: `"passed"` / `"excluded"` / `null` (no gate for this sector)
- `sub_sector_classified`: `"k12"` / `"higher_education"` / etc.

---

## Sector Config YAML Schema

All sector scoring logic lives in `src/hak_talent_mapping/scoring_configs/`. One file per sector. The schema below is the universal template.

```yaml
# scoring_configs/retailers_v2.yaml
config_id: retailers_v2
sector_match: "Retailers"          # must match companies.sector value exactly
version: 2

# ─── SUB-SECTOR GATE (optional) ────────────────────────────────────
sub_sector_gate:
  enabled: false                   # true for Academic, Healthcare, etc.

# ─── DIMENSIONS ─────────────────────────────────────────────────────
dimensions:

  organisational_scale:
    weight: 0.25
    cold_start_weight: null        # only set for talent_export_history
    label: "Organisational Scale"
    sector_label: null             # override display name (e.g. null = use default)

    signals:
      - name: estimated_headcount
        type: integer
        primary_proxy: true
        scoring_thresholds:
          - {max: 100,   score_range: [1, 2]}
          - {max: 500,   score_range: [3, 4]}
          - {max: 2000,  score_range: [5, 6]}
          - {max: 10000, score_range: [7, 8]}
          - {min: 10001, score_range: [9, 10]}
        source_config:
          AE:
            primary: "DED trade license database, DIFC/ADGM registers"
            secondary: "LinkedIn headcount, mall operator tenant lists"
            fallback: "Job posting volume, press mentions of store count"
          SA:
            primary: "MISA commercial register, CR (Commercial Registration)"
            secondary: "Tadawul filings (listed companies), LinkedIn"
            fallback: "Press mentions, brand website store locator"
          QA:
            primary: "Ministry of Commerce registration"
            secondary: "Qatar Stock Exchange filings"
            fallback: "LinkedIn, press"
          KW:
            primary: "Ministry of Commerce & Industry register"
            secondary: "Kuwait Stock Exchange"
            fallback: "LinkedIn, brand website"
          EG:
            primary: "GAFI commercial register"
            secondary: "EGX filings (listed companies)"
            fallback: "Press, LinkedIn, store locator"
          BH:
            primary: "MOIC Sijilat register"
            secondary: "Bahrain Bourse filings"
            fallback: "LinkedIn, press"
          JO:
            primary: "Companies Control Department"
            secondary: "ASE filings"
            fallback: "LinkedIn, press"
          _default:
            primary: "LinkedIn company page headcount"
            secondary: "Brand website, store locator"
            fallback: "Press mentions of scale"
        search_queries:
          - '"{company_name}" {country} employees headcount'
          - '"{company_name}" number of staff team size'

      - name: location_count
        type: integer
        scoring_bonus: {max_bonus: 1.5, description: "Physical footprint confirms scale independently"}
        source_config:
          _default:
            primary: "Brand website store locator, Google Maps"
            secondary: "Mall operator tenant lists"
            fallback: "Press mentions of store openings"
        search_queries:
          - '"{company_name}" number of stores locations {country}'

      - name: revenue_proxy
        type: string
        source_config:
          _default:
            primary: "Annual reports, stock exchange filings"
            secondary: "Press releases, Zawya financials"
            fallback: "Press mentions of revenue range"
        search_queries:
          - '"{company_name}" revenue annual report'

  brand_prominence:
    weight: 0.20
    cold_start_weight: null
    label: "Brand & Market Prominence"
    sector_label: null

    signals:
      - name: media_mentions
        type: integer
        recency_decay:
          tiers:
            - {age_months_max: 3,  weight: 1.5, max_points: 3.0}
            - {age_months_max: 12, weight: 1.0, max_points: 2.0}
        source_config:
          AE:
            primary: "Gulf News, The National, Arabian Business, Khaleej Times"
            secondary: "Retail ME, RetailGulf, MEED"
            fallback: "Google News: '[company] retail [country]'"
          SA:
            primary: "Arab News, Saudi Gazette, Argaam, Aleqtisadiah"
            secondary: "Saudi Retail Forum, MEED"
            fallback: "Google News query"
          _default:
            primary: "Google News: '[company] [sector] [country]'"
            secondary: "LinkedIn company updates"
            fallback: "Any award mention confirmed via web search"
        search_queries:
          - '"{company_name}" {country} {sector} news {year}'

      - name: awards
        type: string_list
        scoring_points: {per_award: 1.0, max: 2.0}
        source_config:
          AE:
            primary: "Dubai Lynx retail awards, Retailer of the Year ME"
          SA:
            primary: "Saudi Excellence Award, GRSA recognitions"
          _default:
            primary: "Any recognised retail industry award"
        search_queries:
          - '"{company_name}" award OR recognition retail {country}'

      - name: category_leadership
        type: boolean
        scoring_points: {value: 1.5}
        search_queries:
          - '"{company_name}" "leading" OR "largest" OR "first in" {sector} {country}'

    fallback_hierarchy:
      - {level: 1, description: "Named in tier-1 business press (last 12 months)"}
      - {level: 2, description: "Regional trade press mention (Retail ME, MEED)"}
      - {level: 3, description: "Award or accreditation mention"}
      - {level: 4, description: "Active web presence with press page"}
      - {level: 5, description: "Existence confirmed, prominence unverifiable", score_cap: 4}

  leadership_depth:
    weight: 0.25
    cold_start_weight: null
    label: "Leadership Depth"

    signals:
      - name: named_executives
        type: integer
        scoring_logic:
          ceo_confirmed_points: 2.0
          additional_csuite: {per: 1.0, max_count: 3}
          director_level: {per: 0.5, max_count: 4}
          breadth_bonus: 1.0           # awarded if 3+ functions covered
          tenure_stability_bonus: 1.0  # awarded if avg tenure 3+ years visible
        source_config:
          AE:
            primary: "LinkedIn (high penetration)"
            secondary: "Company website leadership page"
            fallback: "Press — 'appointed' announcements"
          SA:
            primary: "LinkedIn (good penetration, improving)"
            secondary: "Company website, Tadawul board disclosures"
            fallback: "Press appointments, Argaam executive profiles"
          QA:
            primary: "LinkedIn (moderate penetration)"
            secondary: "Company website"
            fallback: "Press, QSE disclosures"
          EG:
            primary: "LinkedIn (lower penetration for mid-market)"
            secondary: "Company website"
            fallback: "Press, EGX disclosures"
          _default:
            primary: "LinkedIn company page"
            secondary: "Company website leadership page"
            fallback: "Web search: '[company] leadership team [sector] [country]'"
        search_queries:
          - '"{company_name}" CEO OR CFO OR COO OR "managing director" OR CCO'
          - '"{company_name}" executive team leadership'
          - '"{company_name}" appointed VP director {country}'

    linkedin_confidence_adjustments:
      AE: 0.0
      SA: -0.05
      QA: -0.10
      BH: -0.10
      KW: -0.10
      JO: -0.10
      EG: -0.20

    sector_flags: []   # e.g. ['expat_leadership'] for Academic K-12

  talent_export_history:
    weight: 0.15
    cold_start_weight: 0.08          # reduced at launch; set to null when data accumulates
    cold_start_redistribution:
      organisational_scale: 0.04
      leadership_depth: 0.03
    cold_start_ui_flag: "enriching"
    label: "Talent Export History"

    signals:
      - name: alumni_in_senior_roles
        type: integer
        scoring_thresholds:
          - {max: 2,  score_range: [3, 4]}
          - {max: 5,  score_range: [5, 7]}
          - {max: 10, score_range: [8, 9]}
          - {min: 11, score_range: [10, 10]}
        source_config:
          AE:
            primary: "LinkedIn alumni search (past company filter)"
            secondary: "Press: 'former [company] executive appointed'"
            fallback: "Platform's accumulated candidate database"
          _default:
            primary: "LinkedIn alumni search"
            secondary: "Press appointments"
            fallback: "Platform candidate database"
        search_queries:
          - '"{company_name}" "former" OR "previously" OR "ex-" executive appointed {sector}'
          - '"{company_name}" alumni senior roles'

      - name: press_confirmed_export
        type: integer
        scoring_points: {max: 5}

    sector_extensions: {}  # e.g. named_network_clusters for Academic

  sector_fit_confidence:
    weight: 0.15
    cold_start_weight: null
    label: "Sector Fit Confidence"
    gate: true

    signals:
      - name: primary_activity_confirmed
        type: boolean
        source_config:
          AE:
            primary: "DED trade license activity code"
            secondary: "DIFC/ADGM sector classification"
            fallback: "Company website primary description"
          SA:
            primary: "CR (Commercial Registration) activity code"
            secondary: "MISA sector classification"
            fallback: "Company website, press"
          QA:
            primary: "Ministry of Commerce activity classification"
            secondary: "QFC sector"
            fallback: "Company website"
          KW:
            primary: "MOCI activity code"
            secondary: "KSE sector classification"
            fallback: "Company website"
          EG:
            primary: "GAFI activity registration"
            secondary: "EGX sector"
            fallback: "Company website"
          BH:
            primary: "MOIC Sijilat activity"
            secondary: "BHB sector"
            fallback: "Company website"
          JO:
            primary: "CCD activity classification"
            secondary: "ASE sector"
            fallback: "Company website"
          _default:
            primary: "Company website primary description"
            secondary: "Press description of business activity"
            fallback: "LinkedIn company description"
        search_queries:
          - '"{company_name}" {sector} operations {country}'
          - '"{company_name}" company profile industry'

    sub_sector_tags:
      direct:
        - "Fashion retail"
        - "Grocery & FMCG retail"
        - "Electronics retail"
        - "Luxury retail"
        - "F&B retail"
        - "Multi-format retail"
        - "E-commerce retail"
      adjacent:
        - "Wholesale & distribution"
        - "Franchise operator"
        - "Retail real estate"
      inferred:
        - "Holding company with retail subsidiary"
        - "Hospitality with retail arm"

    fallback_hierarchy:
      - {level: 1, description: "Regulatory activity code confirms retail as primary", score_range: [9, 10]}
      - {level: 2, description: "Stock exchange sector classification confirms retail", score_range: [7, 8]}
      - {level: 3, description: "Company website clearly describes retail as primary", score_range: [6, 7]}
      - {level: 4, description: "Press consistently describes as retailer", score_range: [5, 6]}
      - {level: 5, description: "Retail inferred from holding group structure", score_range: [3, 4]}
      - {level: 6, description: "Retail inferred from brand/product description only", score_range: [1, 2]}

# ─── CONFIDENCE BANDS ──────────────────────────────────────────────
confidence_bands:
  primary:   {tolerance_pct: 10, label: "tight"}
  secondary: {tolerance_pct: 20, label: "medium"}
  fallback:  {tolerance_pct: 35, label: "wide", ui_flag: true}

# ─── SECTOR METADATA SCHEMA ────────────────────────────────────────
sector_metadata_schema:
  - {name: store_count,     type: integer}
  - {name: brand_tier,      type: string, enum: [luxury, premium, mid_range, value, discount]}
  - {name: online_presence, type: string, enum: [ecommerce_primary, omnichannel, physical_only]}
  - {name: loyalty_program, type: boolean}
  - {name: franchise_model, type: boolean}
  - {name: product_categories, type: list}
  - {name: mall_presence,   type: boolean}

# ─── BRIEF-ADJUSTED REWEIGHTING ────────────────────────────────────
brief_reweighting:
  role_archetypes:
    - id: cco
      label: "Chief Commercial Officer"
      weights:
        organisational_scale:    0.20
        brand_prominence:        0.30
        leadership_depth:        0.25
        talent_export_history:   0.10
        sector_fit_confidence:   0.15
      rationale: "Commercial leaders come from visible, well-positioned brands — up-weight prominence"

    - id: coo
      label: "Chief Operating Officer"
      weights:
        organisational_scale:    0.30
        brand_prominence:        0.10
        leadership_depth:        0.25
        talent_export_history:   0.20
        sector_fit_confidence:   0.15
      rationale: "Operational complexity scales with company size — up-weight scale"

    - id: cfo
      label: "CFO / Finance"
      weights:
        organisational_scale:    0.25
        brand_prominence:        0.10
        leadership_depth:        0.25
        talent_export_history:   0.25
        sector_fit_confidence:   0.15
      rationale: "Finance talent moves across sectors — export history matters more than brand"

    - id: md_ceo
      label: "MD / CEO (Group)"
      weights:
        organisational_scale:    0.30
        brand_prominence:        0.20
        leadership_depth:        0.25
        talent_export_history:   0.15
        sector_fit_confidence:   0.10

    - id: buying_merch
      label: "Buying & Merchandising Director"
      weights:
        organisational_scale:    0.15
        brand_prominence:        0.25
        leadership_depth:        0.25
        talent_export_history:   0.20
        sector_fit_confidence:   0.15
      rationale: "Product and buying talent clusters in category-leading brands — up-weight brand"

    - id: supply_chain
      label: "Supply Chain Director"
      weights:
        organisational_scale:    0.30
        brand_prominence:        0.05
        leadership_depth:        0.25
        talent_export_history:   0.25
        sector_fit_confidence:   0.15
      rationale: "Operational complexity is the primary qualification — up-weight scale"
```

---

## Academic Sector — Key Config Differences

The `academic_educational_v1.yaml` config uses the same 5-dimension schema but with sector-specific overrides. Key differences from Retail:

```yaml
config_id: academic_educational_v1
sector_match: "Academic & Educational Services"

sub_sector_gate:
  enabled: true
  sub_sectors:
    - {id: k12,              label: "K-12 Schools & School Groups",              classification_signals: [school, curriculum, primary, secondary, grade]}
    - {id: higher_education, label: "Higher Education Institutions",              classification_signals: [university, college, faculty, degree, provost]}
    - {id: vocational,       label: "Vocational, Professional & Corporate Training", classification_signals: [training, certification, vocational, professional development]}
    - {id: edtech,           label: "EdTech & Digital Learning Platforms",       classification_signals: [edtech, online learning, digital, lms, platform]}
  cross_sub_sector_allowed: true
  cross_sub_sector_warning: "Results span multiple talent pools — grouped by sub-sector"

dimensions:

  organisational_scale:
    weight: 0.20        # lower than Retail — scale is weaker proxy in education
    signals:
      - name: student_enrollment   # different primary proxy to Retail's headcount
        scoring_thresholds:
          # K-12 sub-sector thresholds:
          - {max: 1000,  score_range: [1, 2]}
          - {max: 5000,  score_range: [3, 4]}
          - {max: 15000, score_range: [5, 6]}
          - {max: 40000, score_range: [7, 8]}
          - {min: 40001, score_range: [9, 10]}
        source_config:
          AE_DUBAI:
            primary: "KHDA annual school census data (khda.ae)"
            secondary: "LinkedIn headcount, school website"
            fallback: "Press mentions of enrolment milestones"
          AE_ABUDHABI:
            primary: "ADEK licensed school register"
            secondary: "LinkedIn, institution website"
            fallback: "Press"
          SA:
            primary: "Ministry of Education school census"
            secondary: "ETEC data"
            fallback: "LinkedIn, institution website, press"
          _default:
            primary: "Institution website (about/facts page)"
            secondary: "LinkedIn company page"
            fallback: "Press mentions of scale"

  brand_prominence:
    weight: 0.25        # higher than Retail — reputation is the dominant signal
    sector_label: "Brand & Institutional Reputation"   # overrides display name
    signals:
      - name: regulatory_rating   # replaces media_mentions as primary signal
        type: string
        scoring_map:
          outstanding: 4.0
          good:        2.5
          acceptable:  1.0
        source_config:
          AE_DUBAI:    {primary: "KHDA inspection ratings (khda.ae)", secondary: null, fallback: "Press"}
          AE_ABUDHABI: {primary: "ADEK inspection ratings (adek.gov.ae)", secondary: null, fallback: "Press"}
          SA:          {primary: "ETEC / Ministry of Education ratings", secondary: null, fallback: "Press"}
          BH:          {primary: "BQA inspection rating (bqa.edu.bh)", secondary: null, fallback: "Press"}
          _default:    {primary: "Any national inspection body rating", secondary: null, fallback: "Web presence quality"}

      - name: international_accreditation
        type: string_list
        scoring_points: {per_accreditation: 1.5, max_count: 2}
        accreditation_signal_strength:
          IB:     strong
          CAIE:   strong
          NEASC:  strong
          AACSB:  very_strong
          EQUIS:  strong
          ABET:   strong
          QS_top_500: strong
          THE_top_500: strong

      - name: university_ranking
        type: string
        scoring_map:
          top_200:  3.0
          top_500:  2.0
          top_1000: 1.0

    fallback_hierarchy:
      - {level: 1, description: "Official regulatory inspection rating (Outstanding/Good)", score_range: [8, 10]}
      - {level: 2, description: "International accreditation confirmed", score_range: [7, 9]}
      - {level: 3, description: "National accreditation body approval", score_range: [5, 7]}
      - {level: 4, description: "Positive regional education press", score_range: [4, 6]}
      - {level: 5, description: "Active web presence with academic programming", score_range: [3, 4]}
      - {level: 6, description: "Licensed operator only, no quality signal", score_cap: 3}

  leadership_depth:
    weight: 0.25
    sector_flags: [expat_leadership]   # applies −0.5 stability discount in GCC K-12
    # Title mapping is sub-sector-aware (handled in scoring engine)

  talent_export_history:
    weight: 0.15
    cold_start_weight: 0.08
    sector_extensions:
      named_network_clusters:    # first-class signals, not anonymous counts
        enabled: true
        known_clusters:
          - {name: "GEMS Alumni — GCC K-12",    bonus_points: 1.0}
          - {name: "Taaleem Alumni — UAE K-12",  bonus_points: 1.0}
          - {name: "Nord Anglia Alumni",          bonus_points: 1.0}
          - {name: "AUS Alumni — GCC HE",         bonus_points: 1.0}

  sector_fit_confidence:
    weight: 0.15
    sub_sector_tags:
      direct:
        - "K-12 Schools & School Groups"
        - "Universities & Higher Education"
        - "Vocational & Technical Training"
        - "Professional Development & Certification"
        - "EdTech & Digital Learning"
      adjacent:
        - "Education Management & Consulting"
        - "Assessment & Examination Bodies"
        - "Educational Publishing & Content"
      inferred:
        - "Holding company with education subsidiary"
        - "Corporate with internal training academy"

brief_reweighting:
  role_archetypes:
    - id: head_of_school
      label: "Head of School / Principal"
      weights:
        organisational_scale:    0.15
        brand_prominence:        0.35   # Outstanding-rated schools are the target
        leadership_depth:        0.25
        talent_export_history:   0.10
        sector_fit_confidence:   0.15

    - id: group_ceo
      label: "Group CEO / Superintendent"
      weights:
        organisational_scale:    0.30   # multi-site operational complexity
        brand_prominence:        0.20
        leadership_depth:        0.25
        talent_export_history:   0.15
        sector_fit_confidence:   0.10

    - id: vp_academic
      label: "VP Academic / Provost"
      weights:
        organisational_scale:    0.10
        brand_prominence:        0.35   # academic leadership clusters in prestige institutions
        leadership_depth:        0.25
        talent_export_history:   0.20
        sector_fit_confidence:   0.10

    - id: coo_operations
      label: "COO / Operations Director"
      weights:
        organisational_scale:    0.30
        brand_prominence:        0.10
        leadership_depth:        0.25
        talent_export_history:   0.20
        sector_fit_confidence:   0.15

    - id: head_curriculum
      label: "Head of Curriculum"
      weights:
        organisational_scale:    0.10
        brand_prominence:        0.35
        leadership_depth:        0.25
        talent_export_history:   0.20
        sector_fit_confidence:   0.10

    - id: cfo
      label: "CFO / Finance Director"
      weights:
        organisational_scale:    0.20
        brand_prominence:        0.10
        leadership_depth:        0.25
        talent_export_history:   0.30   # finance talent moves across sectors
        sector_fit_confidence:   0.15
```

---

## Base Score Computation

```
# Normal operation
base_score = (
    dim_scores["organisational_scale"]    × weights["organisational_scale"]  +
    dim_scores["brand_prominence"]        × weights["brand_prominence"]       +
    dim_scores["leadership_depth"]        × weights["leadership_depth"]       +
    dim_scores["talent_export_history"]   × weights["talent_export_history"]  +
    dim_scores["sector_fit_confidence"]   × weights["sector_fit_confidence"]
) × 10

# Cold-start operation (talent_export_history.cold_start_weight is set)
effective_weights = dict(config.weights)
effective_weights["talent_export_history"]  = config.cold_start_weight   # 0.08
effective_weights["organisational_scale"]  += cold_start_redistribution["organisational_scale"]  # +0.04
effective_weights["leadership_depth"]      += cold_start_redistribution["leadership_depth"]       # +0.03

base_score = Σ(dim_score × effective_weight) × 10

Range: 0–100
```

---

## `sector_metadata` JSONB — Per-Sector Examples

Validated in Python via per-sector Pydantic models. Governed by `sector_metadata_schema` in the YAML config.

### Retailers

```json
{
    "store_count": 45,
    "brand_tier": "premium",
    "online_presence": "omnichannel",
    "loyalty_program": true,
    "franchise_model": true,
    "product_categories": ["grocery", "fashion", "electronics"],
    "mall_presence": true
}
```

### Academic & Educational Services

```json
{
    "student_enrollment": 125000,
    "campus_count": 47,
    "curriculum_type": ["IB", "CAIE", "American"],
    "regulatory_rating": "Outstanding",
    "accreditations": ["IB", "CAIE", "NEASC"],
    "sub_sector": "k12",
    "expat_leadership_flag": true
}
```

### Software & IT Services

```json
{
    "tech_stack": ["python", "react", "aws", "kubernetes"],
    "product_type": "saas",
    "deployment_model": "cloud",
    "active_role_types": ["engineering", "product", "data_science"],
    "hiring_velocity": "aggressive",
    "ml_hiring": true,
    "key_clients_public": ["ADNOC", "Emirates NBD"]
}
```

### Healthcare Services & Equipment

```json
{
    "facility_count": 12,
    "specialties": ["cardiology", "oncology", "orthopedics"],
    "accreditations": ["JCI", "DHA"],
    "facility_type": "hospital",
    "bed_count": 350,
    "telemedicine": true
}
```

### Banking & Investment Services

```json
{
    "license_type": "full_bank",
    "assets_under_mgmt": "AED 280B",
    "digital_banking": true,
    "branch_count": 65,
    "regulatory_authority": "CBUAE",
    "islamic_finance": true,
    "wealth_management": true
}
```

---

## Brief-Adjusted Reweighting (Query Time — Phase 4+)

> Stored per-dimension scores enable reweighting at query time without re-embedding or re-scoring.

Role archetype tables are defined **per sector** in the YAML config, not hardcoded globally. The reweighting loop iterates over the config's dimension list dynamically:

```python
brief_adjusted_score = sum(
    dim_scores[dim_id] * archetype_weights[dim_id]
    for dim_id in sector_config.dimensions
) * 10
```

Uses stored `dimension_scores` from Pinecone metadata — no re-embedding or re-enrichment needed.

### User Override

After brief-adjusted ranking renders, user can manually adjust weight sliders:
- "They only want candidates from large, well-known brands" → up-weight prominence
- "Exploring adjacent sectors" → down-weight sector fit
- Slider adjustments are ephemeral — not persisted to `company_scores`
