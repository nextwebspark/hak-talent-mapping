# Current Implementation: Retailers Enrichment & Scoring

*This document describes what the system does today — business logic, data collection, scoring formulas, and output. It is a snapshot of the current MVP, not the target design.*

---

## What This System Does

For every retail company scraped from Zawya, the enrichment pipeline:
1. Searches the web for information about the company
2. Scrapes their website
3. Uses an LLM (Claude) to extract a structured company profile
4. Scores the company across three dimensions to produce a 0–100 score

The score reflects how large, well-led, and clearly retail-classified the company is — making it useful for prioritising which companies to map talent from.

---

## Stage 1 — Web Search

Ten search queries are run against Google (via Serper API) for each company. Each query is designed to pull a specific type of information:

| Query | Purpose |
|---|---|
| `{name} retail company overview UAE` | General company profile |
| `{name} number of employees headcount` | Staff size |
| `{name} CEO managing director leadership team` | Who leads the company |
| `{name} stores locations UAE` | Physical footprint |
| `{name} press news retail 2024 2025` | Recent news |
| `{name} founded history brand` | Origin and history |
| `{name} DED trade license retail` | Regulatory confirmation |
| `{name} revenue annual report` | Financial scale |
| `{name} executives directors board` | Board and senior team |
| `{name} alumni careers LinkedIn` | Where ex-employees went |

Each query returns up to 10 results from Google (title, link, snippet). All results are stored raw for audit purposes.

---

## Stage 2 — Website Scrape

The company's website is visited (headless browser) and text is extracted from these pages:
- Homepage
- /about and /about-us
- /team and /leadership and /management
- /contact and /contact-us

All text is combined into a single block (capped at 8,000 characters). If the website is unreachable, the pipeline continues without it.

---

## Stage 3 — LLM Extraction

Claude receives the search result snippets and website text and extracts a structured profile. It is instructed to return only the data it can confidently confirm — not to guess.

### What the LLM Extracts

| Field | What It Is |
|---|---|
| **name** | Canonical company name |
| **domain** | Primary website (no https://) |
| **description_clean** | 2–4 sentence factual description of what the company does |
| **city** | Primary city of operations |
| **region** | Emirate or state (e.g. Dubai, Abu Dhabi) |
| **sub_sector** | Specific category within Retail (e.g. fashion, grocery, electronics) |
| **sub_sector_tags** | List of applicable sub-sector labels |
| **funding_stage** | One of: bootstrapped, seed, series_a, ipo, private |
| **headcount_range** | Employee count bucket: 1-10 / 11-50 / 51-200 / 201-500 / 501-1000 / 1001-5000 / 5001+ |
| **headcount_exact** | Exact employee count if stated explicitly |
| **founded_year** | Year the company was established |
| **leadership_names** | List of named current executives/directors |
| **alumni_signals** | List of named people who used to work here and moved elsewhere |
| **extraction_confidence** | LLM's self-reported confidence (0.0–1.0) |

### Retail-Specific Fields (sector_metadata)

In addition to the universal fields above, the LLM extracts these retail-specific fields:

| Field | What It Is |
|---|---|
| **store_count** | Number of retail locations |
| **store_formats** | Types of stores (e.g. hypermarket, supermarket, specialty) |
| **brands_owned** | Brand names the company operates |
| **ded_license_confirmed** | Whether a UAE DED trade license was found and confirmed |
| **mall_presence** | Names of malls where the company operates |

---

## Stage 4 — Data Quality Score

After extraction, the system checks how complete the profile is. It counts how many of these 6 key fields were populated:

- `description_clean`
- `city`
- `headcount_range`
- `founded_year`
- `domain`
- `sub_sector`

**Quality score = populated fields ÷ 6** (e.g. 4 out of 6 = 0.67)

This is a completeness measure, not a quality judgement. A company with a score of 1.0 had all fields found; a score of 0.33 means data was thin.

---

## Scoring — How Companies Are Ranked

Companies are scored on three dimensions. Each dimension scores 0–10, and the weighted average is multiplied by 10 to give a final **0–100 base score**.

### Current Weights

| Dimension | Weight |
|---|---|
| Organisational Scale | 35% |
| Leadership Depth | 35% |
| Sector Fit Confidence | 30% |

Two additional dimensions — Brand & Market Prominence and Talent Export History — are defined in the system but not yet active (weight 0%). They will be enabled in a future update.

---

### Dimension 1: Organisational Scale

*How big is this company operationally?*

A larger company has more leadership roles, more functions, and a deeper talent pool to map. This dimension looks at two signals:

**Signal A — Headcount (60% of this dimension)**

If the exact employee count is known:
```
score = log₁₀(headcount) × 2.5   (capped at 10.0)
```

| Employees | Score |
|---|---|
| 10 | 2.5 |
| 100 | 5.0 |
| 1,000 | 7.5 |
| 10,000 | 10.0 |
| 50,000+ | 10.0 (capped) |

If only a range is known (from the LLM):

| Range | Score |
|---|---|
| 1–10 | 1.0 |
| 11–50 | 2.5 |
| 51–200 | 4.5 |
| 201–500 | 6.0 |
| 501–1,000 | 7.5 |
| 1,001–5,000 | 8.5 |
| 5,001+ | 10.0 |

**Signal B — Store Count (40% of this dimension)**

Physical footprint independently confirms operational scale:
```
score = log₁₀(store_count + 1) × 3.5   (capped at 7.0)
```

| Stores | Score |
|---|---|
| 1 | 1.0 |
| 10 | 3.7 |
| 50 | 5.9 |
| 100+ | 7.0 (capped) |

Note: store count is capped at 7.0 (not 10.0) because physical presence is considered a weaker proxy than headcount.

**Final dimension score:**
```
scale_score = (headcount_score × 0.60) + (store_score × 0.40)
```

---

### Dimension 2: Leadership Depth

*Does this company have a visible, named senior team that can be mapped?*

This is the most talent-sourcing-specific dimension. A company scores high here when named executives can be identified from public sources.

**How it's scored:**

The system counts how many named executives were extracted by the LLM (`leadership_names`):

| Named Executives | Score |
|---|---|
| 0 | 0.0 |
| 1 | 2.0 |
| 2 | 4.0 |
| 3 | 5.0 |
| 4–5 | 7.0 |
| 6–8 | 8.5 |
| 9 | 8.7 |
| 10 | 8.9 |
| 15 | 9.9 |
| 20+ | 10.0 (capped) |

*(For 9+: score = 8.5 + (count − 8) × 0.2)*

**Current limitation:** The system counts names but does not distinguish between a CEO and a Director-level hire. All named executives are treated equally regardless of seniority.

---

### Dimension 3: Sector Fit Confidence

*Is this company definitely a retailer operating in the target country?*

This is both a quality gate and a scored dimension. A holding company that owns a retail subsidiary is not the same as an operating retailer. This dimension tries to confirm the company is genuinely in-scope.

**Signal A — Regulatory Confirmation (checked first)**

If the LLM confirmed a UAE DED (Department of Economic Development) trade license:
- Score: **9.5**
- Confidence: Tight (±10%) — this is a regulatory primary source

**Signal B — Description Keyword Match (fallback)**

If no DED confirmation, the system counts how many retail-sector keywords appear in the company description:

Keywords checked: *retail, store, shop, brand, supermarket, fashion*

| Keyword Matches | Score |
|---|---|
| 2 or more | 6.5 |
| 1 | 5.0 |
| 0 | 3.0 |

Note: A score of 3.0 (zero keyword matches) does not mean the company is excluded — it means sector classification is uncertain. The company still appears in results with a low sector fit score.

**Current limitation:** The DED check only applies to UAE. For companies in other countries, the system falls back to keyword matching regardless of whether a local regulatory source exists.

---

## Confidence Bands

Every score carries a confidence band that tells you how reliable the underlying data is.

| Data Source Quality | Confidence Band | Tolerance |
|---|---|---|
| Regulatory / licence data (DED) | Tight | ±10% |
| LinkedIn / company website | Medium | ±20% |
| Description text matching | Wide | ±35% |
| No data found | Wide | ±35% |

**Overall confidence** = the worst (widest) band across all three dimensions.

Example: if Organisational Scale is "medium" and Sector Fit is "tight" but Leadership Depth has no data ("wide"), the overall confidence is "wide".

---

## Final Score Calculation

```
base_score = (scale_score × 0.35 + leadership_score × 0.35 + sector_fit_score × 0.30) × 10
```

| Dimension | Score | Weight | Contribution |
|---|---|---|---|
| Organisational Scale | 7.5 | 35% | 2.625 |
| Leadership Depth | 5.0 | 35% | 1.750 |
| Sector Fit | 8.0 | 30% | 2.400 |
| **Total** | | | **6.775** |

```
base_score = 6.775 × 10 = 67.75  →  rounded to 67.8
```

---

## Example Score Card

```
Landmark Group — Retail Division
Country: UAE  |  Sub-sector: Multi-format retail

Base Score:              84.2 / 100
Overall Confidence:      Medium  (±20%)

Organisational Scale:    8.5 / 10   [medium confidence]
  → headcount_range: "5001+" → score 10.0 (headcount)
  → store_count: 200 → score 7.0 (capped)
  → final: (10.0 × 0.60) + (7.0 × 0.40) = 8.8

Leadership Depth:        7.0 / 10   [medium confidence]
  → 5 named executives found (LinkedIn + website)
  → score lookup: 4-5 executives → 7.0

Sector Fit Confidence:   9.5 / 10   [tight confidence]
  → DED trade licence confirmed
  → score: 9.5 (primary source)
```

---
