# Current Implementation: Retailers Enrichment & Scoring

*This document describes what the system does today — business logic, data collection, scoring formulas, and output. It is a snapshot of the current state, not the target design.*

---

## What This System Does

For every retail company scraped from Zawya, the enrichment pipeline:
1. Searches the web for information about the company
2. Scrapes their website
3. Uses an LLM (Claude Haiku) to extract a structured company profile
4. Scores the company across three active dimensions to produce a 0–100 base score

The score reflects how large, sector-focused, and publicly visible the company is — making it useful for prioritising which companies to map talent from.

---

## Stage 1 — Web Search

Nine search queries are run against Google (via Serper API) for each company:

| Query | Purpose |
|---|---|
| `{name} retail company overview {country}` | General company profile |
| `{name} number of employees headcount` | Staff size |
| `{name} CEO managing director leadership team` | Who leads the company |
| `{name} stores locations world wise` | Physical footprint |
| `{name} press news retail 2024 2025 2026` | Recent news and press mentions |
| `{name} founded history brand` | Origin and history |
| `{name} annual revenue turnover financial results` | Financial scale (annual report → website → aggregators → web) |
| `{name} executives directors board` | Board and senior team |
| `{name} business divisions subsidiaries sectors` | Multi-sector classification |

`{name}` and `{country}` are substituted at runtime per company. `{country}` resolves to the full country name (e.g. "United Arab Emirates").

Each query returns up to 10 results (title, link, snippet). All results are stored raw for audit purposes.

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

Claude receives the search result snippets and website text via a structured prompt and extracts a profile. The system prompt is assembled dynamically — a universal base schema plus sector-specific field definitions and reasoning guidance injected as XML sections (`<sector-metadata-schema>`, `<extraction-guidance>`).

### Universal Fields

| Field | What It Is |
|---|---|
| **name** | Canonical company name |
| **domain** | Primary website (no https://) |
| **description_clean** | 2–4 sentence factual description |
| **city** | Primary city of operations |
| **region** | Emirate or state (e.g. Dubai, Abu Dhabi) |
| **sub_sector** | Specific category within Retail (e.g. fashion, grocery, electronics) |
| **sub_sector_tags** | List of applicable sub-sector labels |
| **funding_stage** | One of: bootstrapped, seed, series_a, ipo, private |
| **headcount_range** | Employee bucket: 1-10 / 11-50 / 51-200 / 201-500 / 501-1000 / 1001-5000 / 5001+ |
| **headcount_exact** | Exact employee count if stated |
| **founded_year** | Year the company was established |
| **leadership_names** | List of `{name, title}` objects for current executives |
| **alumni_signals** | Named people who used to work here and moved elsewhere |
| **extraction_confidence** | LLM self-reported confidence (0.0–1.0) |

### Retail-Specific Fields (`sector_metadata`)

| Field | What It Is |
|---|---|
| **store_count** | Number of retail locations; LLM uses best estimate if source gives approximate figure (e.g. "over 300" → 300) |
| **store_formats** | Types of stores (e.g. hypermarket, specialty, mall-based) |
| **brands_owned** | Brand names the company operates |
| **mall_presence** | Names of malls where the company has stores |
| **annual_revenue_usd** | Most recent annual revenue in USD; LLM converts from local currency if needed |
| **ded_license_confirmed** | Whether a UAE DED trade license was found |
| **sector_concentration** | `primary` / `secondary` / `diversified` — how central is retail to this company's business |
| **other_sectors** | Other major sectors the company significantly operates in |
| **press_mentions_count** | Count of distinct third-party press/news articles found in search results (capped at 30; excludes the company's own press releases) |
| **award_mentions_count** | Count of industry awards, rankings, or formal recognitions (each distinct award counts once) |

### LLM Guidance Injected per Sector

The system prompt includes explicit reasoning rules for judgment-call fields:

- **sector_concentration**: classify as `primary` only if the majority of revenue/brand recognition is retail-focused; `secondary` if retail exists but another sector dominates; `diversified` if 3+ unrelated sectors with no dominant one
- **store_count**: use best estimate from approximate figures — do not leave null just because the number is not exact
- **press_mentions_count**: count third-party articles only, cap at 30
- **award_mentions_count**: count each distinct award once regardless of how many articles mention it
- **annual_revenue_usd**: source hierarchy — annual report → company website → financial aggregators/press (Bloomberg, Reuters, Forbes) → any web mention. Always convert to USD using approximate exchange rates; do not leave null because the figure is in a local currency. Round to nearest $1M. A stale figure from a prior year is better than null.

---

## Stage 4 — Data Quality Score

After extraction, the system checks how complete the profile is across 6 key fields:

- `description_clean`, `city`, `headcount_range`, `founded_year`, `domain`, `sub_sector`

**Quality score = populated fields ÷ 6** (e.g. 5/6 = 0.83)

This is a completeness measure, not a quality judgement.

---

## Scoring — How Companies Are Ranked

Companies are scored across **three active dimensions**. Each scores 0–10. The final base score is the weighted average of all active dimensions, normalized by total weight, then multiplied by 10 to give a **0–100 score**.

### Current Weights

| Dimension | Declared Weight | Effective Weight |
|---|---|---|
| Organisational Scale | 0.35 | 35.0% |
| Sector Fit Confidence | 0.30 | 30.0% |
| Brand & Market Prominence | 0.35 | 35.0% |
| **Total** | **1.00** | **100%** |

One additional dimension — **Talent Export History** — is defined but not yet active (weight 0.0).

> **Note on Leadership Depth (removed as standalone dimension):** Named leadership was previously a standalone D2 dimension (weight 0.35). It has been absorbed into Brand & Market Prominence as a lightweight corroborating signal (20% of D4). This prevents large private companies that don't publicise their senior team from being unfairly penalised. Press coverage, awards, and named leadership are all expressions of external visibility — consolidating them into one dimension avoids double-counting the concept.

---

### Dimension 1: Organisational Scale

*How big is this company operationally?*

Three signals, weighted internally:

**Signal A — Headcount (50%)**

If exact count is known:
```
score = log₁₀(headcount) × 2.5   (capped at 10.0)
```

| Employees | Score |
|---|---|
| 10 | 2.5 |
| 100 | 5.0 |
| 1,000 | 7.5 |
| 10,000+ | 10.0 (capped) |

If only a range is known:

| Range | Score |
|---|---|
| 1–10 | 1.0 |
| 11–50 | 2.5 |
| 51–200 | 4.5 |
| 201–500 | 6.0 |
| 501–1,000 | 7.5 |
| 1,001–5,000 | 8.5 |
| 5,001+ | 10.0 |

**Signal B — Store Count (30%)**

```
score = log₁₀(store_count + 1) × 3.5   (capped at 7.0)
```

| Stores | Score |
|---|---|
| 1 | 1.0 |
| 10 | 3.7 |
| 50 | 5.9 |
| 100+ | 7.0 (capped) |

Capped at 7.0 because physical presence is a weaker proxy for scale than headcount.

**Signal C — Annual Revenue (20%)**

```
score = log₁₀(annual_revenue_usd) × 0.625   (capped at 10.0)
```

| Revenue | Score |
|---|---|
| $1M | 3.75 |
| $100M | 5.0 |
| $1B | 5.6 |
| $16B+ | 10.0 (capped) |

**Final dimension score:**
```
scale_score = (headcount_score × 0.50) + (location_score × 0.30) + (revenue_score × 0.20)
```

---

### Dimension 2: Sector Fit Confidence

*Does this company have meaningful retail operations? (relevance gate, not a purity score)*

A single signal — `sector_concentration` — classified by the LLM. This dimension answers one question: is retail a meaningful part of this business? It does **not** penalise companies for being diversified — the scale of a company's retail arm is measured by D1, not D3.

| Classification | Score | Meaning |
|---|---|---|
| `primary` | 10.0 | Retail is the dominant business — fully in scope |
| `secondary` | 6.0 | Retail exists meaningfully — in scope |
| `diversified` | 6.0 | Large retail arm — in scope, size judged by D1 |
| `null` | 3.0 | LLM could not confirm retail presence — uncertainty penalty |

`secondary` and `diversified` score the same (6.0) because both confirm retail relevance. A diversified conglomerate with a major retail arm (e.g. Al-Futtaim, Majid Al Futtaim) is as relevant a talent mapping target as a pure-play retailer — their scale is correctly captured by D1.

---

### Dimension 3: Brand & Market Prominence

*How publicly visible and recognised is this company?*

Three signals measuring external presence. Named leadership is a corroborating signal — not a standalone measure — so large private companies that don't publicise their team are not penalised on this dimension alone.

**Signal A — Press Coverage (55%)**

Counts distinct third-party news/media articles found in search results:

| Press Mentions | Score |
|---|---|
| 0 | 0.0 |
| 1–2 | 3.0 |
| 3–5 | 5.5 |
| 6–10 | 7.5 |
| 11–20 | 9.0 |
| 21+ | 10.0 |

**Signal B — Awards & Recognition (25%)**

Counts distinct industry awards, rankings, or formal recognitions:

| Awards | Score |
|---|---|
| 0 | 0.0 |
| 1 | 4.0 |
| 2–3 | 6.5 |
| 4+ | 9.0 |

**Signal C — Named Leadership (20%)**

Counts named executives extracted by the LLM (`leadership_names`). Weighted lightly as a corroborating signal:

| Named Executives | Score |
|---|---|
| 0 | 0.0 |
| 1 | 2.0 |
| 2 | 4.0 |
| 3 | 5.0 |
| 4–5 | 7.0 |
| 6–8 | 8.5 |
| 9+ | 8.5 + (count − 8) × 0.2, capped at 10.0 |

Source level: fallback (web search) for press/awards, secondary (LinkedIn/website) for leadership. When only leadership data is present, the dimension carries medium confidence.

**Final dimension score:**
```
prominence_score = (press_score × 0.55) + (awards_score × 0.25) + (leadership_score × 0.20)
```

---

## Confidence Bands

Every score carries a confidence band based on the quality of underlying data:

| Source Quality | Band | Tolerance |
|---|---|---|
| LinkedIn / company website | Medium | ±20% |
| Web search / press / self-reported | Wide | ±35% |
| No data found | Wide | ±35% |

**Overall confidence** = the worst (widest) band across all active dimensions.

---

## Final Score Calculation

The engine normalizes by total declared weight:

```
base_score = (weighted_sum / total_weight) × 10
```

Where `total_weight = 0.35 + 0.30 + 0.35 = 1.00`

**Example — Rivoli Group LLC:**

| Dimension | Score | Weight | Contribution |
|---|---|---|---|
| Organisational Scale | 7.14 | 0.35 | 2.499 |
| Sector Fit Confidence | 10.0 | 0.30 | 3.000 |
| Brand & Market Prominence | 5.53 | 0.35 | 1.936 |
| **Weighted sum** | | | **7.435** |

D3 breakdown: press=6 mentions→7.5×0.55=4.125, awards=0→0, leadership=4 execs→7.0×0.20=1.40; total=5.525 → 5.53

```
base_score = (7.435 / 1.00) × 10 = 74.4
```

---

## Example Score Card

```
Rivoli Group LLC
Country: UAE  |  Sub-sector: Luxury watches, accessories, eyewear

Base Score:                    74.4 / 100
Overall Confidence:            Wide  (±35%)

Organisational Scale:          7.14 / 10   [medium confidence]
  → headcount_exact: 1,600 → score 7.5
  → store_count: 100 → score 7.0 (capped)
  → annual_revenue_usd: $190.6M → score 5.1
  → final: (7.5 × 0.50) + (7.0 × 0.30) + (5.1 × 0.20) = 7.14

Sector Fit Confidence:         10.0 / 10   [medium confidence]
  → sector_concentration: "primary"
  → score: 10.0

Brand & Market Prominence:     5.53 / 10   [wide confidence]
  → press_mentions_count: 6 → score 7.5
  → award_mentions_count: 0 → score 0.0
  → named_executives: 4 → score 7.0
  → final: (7.5 × 0.55) + (0 × 0.25) + (7.0 × 0.20) = 4.125 + 0 + 1.4 = 5.53
```
