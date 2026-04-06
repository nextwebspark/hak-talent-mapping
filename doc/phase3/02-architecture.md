# Phase 3: System Architecture

---

## High-Level Data Flow

```
┌────────────────────────────────────────────────────────────────────────────────────┐
│                           HAK ENRICHMENT PIPELINE                                   │
│                                                                                     │
│  ┌─────────────┐    ┌───────────────────────────────────────────────────────────┐  │
│  │  Supabase    │    │          Per-Company Pipeline (7 stages)                  │  │
│  │  companies   │───▶│                                                           │  │
│  │  (Phase 1+2) │    │  ┌────────┐  ┌─────────┐  ┌──────────┐  ┌───────────┐  │  │
│  └─────────────┘    │  │  Web   │  │ Website │  │  LLM     │  │ PROFILE   │  │  │
│                      │  │ Search │─▶│ Scrape  │─▶│ Profile  │─▶│ COMPLETE  │  │  │
│                      │  └────────┘  └─────────┘  │ Extract  │  └─────┬─────┘  │  │
│                      │                            └──────────┘        │         │  │
│                      └───────────────────────────────────────────────┘         │  │
│                                                                        │         │  │
│  ┌─────────────────────────────────────────────────────────────────┐  │         │  │
│  │                    STORAGE LAYER                                  │  │         │  │
│  │                                                                   │  │         │  │
│  │  ┌──────────────────┐  ┌──────────────┐  ┌──────────────────┐  │  │         │  │
│  │  │   Supabase        │  │   Supabase    │  │     Pinecone      │  │  │         │  │
│  │  │  company_details  │  │ company_scores│  │  hak-company-     │  │  │         │  │
│  │  │                   │  │               │  │  profiles          │  │  │         │  │
│  │  │ • rich profile    │  │ • 5 dimension │  │                    │  │  │         │  │
│  │  │ • sector_metadata │  │   scores JSONB│  │ • 1536-dim vectors │  │  │         │  │
│  │  │ • audit trail     │  │ • base_score  │  │ • metadata filters │  │  │         │  │
│  │  │ • pipeline state  │  │ • conf bands  │  │ • cosine similarity│  │  │         │  │
│  │  └──────────────────┘  └──────────────┘  └──────────────────┘  │  │         │  │
│  └─────────────────────────────────────────────────────────────────┘  │         │  │
│                                                                        │         │  │
│  ┌─────────────────────────────────────────────────────────────────┐  │         │  │
│  │                   EXTERNAL SERVICES                               │  │         │  │
│  │  ┌────────────────┐  ┌──────────────┐  ┌──────────────────┐    │  │         │  │
│  │  │ Google/Bing    │  │  Claude /     │  │  OpenAI          │    │  │         │  │
│  │  │ Search API     │  │  OpenAI LLM   │  │  Embeddings      │    │  │         │  │
│  │  │ (12-14 queries │  │  (1-2 calls   │  │  (text-embedding │    │  │         │  │
│  │  │  per company)  │  │   per company) │  │   -3-small)      │    │  │         │  │
│  │  └────────────────┘  └──────────────┘  └──────────────────┘    │  │         │  │
│  └─────────────────────────────────────────────────────────────────┘  │         │  │
└────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 7-Stage Enrichment Pipeline

The key change: **Stages 1-5 produce a rich company profile. Stage 6 computes scores from that profile. Stage 7 embeds both.**

This means:
- You can build profiles across all 30 sectors even before any scoring config exists
- You can re-score with updated weights without touching the profile
- Stage 7 re-runs whenever either the profile or scores change

### Stage Flow

```
Stage 1          Stage 2          Stage 3          Stage 4          Stage 5
┌──────────┐    ┌──────────┐    ┌──────────┐    ┌──────────────┐  ┌───────────┐
│  INIT    │───▶│   WEB    │───▶│ WEBSITE  │───▶│ LLM PROFILE  │─▶│ PROFILE   │
│          │    │  SEARCH  │    │  SCRAPE  │    │ EXTRACTION   │  │ COMPLETE  │
│ Create   │    │          │    │          │    │              │  │           │
│ detail   │    │ 12-14    │    │ About,   │    │ 1 LLM call   │  │ Validate  │
│ row      │    │ queries  │    │ Team,    │    │ → structured │  │ quality   │
│          │    │ (from    │    │ Contact  │    │   profile    │  │ score     │
│ Status:  │    │  config, │    │          │    │              │  │           │
│ pending  │    │  {country│    │ Status:  │    │ Status:      │  │ Status:   │
│          │    │  } param)│    │ website_ │    │ llm_         │  │ profile_  │
│          │    │ Status:  │    │ scraped  │    │ extracted    │  │ complete  │
│          │    │ web_done │    │          │    │              │  │           │
└──────────┘    └──────────┘    └──────────┘    └──────────────┘  └─────┬─────┘
                                                                        │
                                    ┌───────────────────────────────────┘
                                    ▼
                  Stage 6                                  Stage 7
                  ┌──────────────────────────────┐        ┌──────────────┐
                  │           SCORING             │───────▶│  VECTORIZE   │
                  │                               │        │              │
                  │ 6a. Load sector config YAML   │        │ Build embed  │
                  │     + resolve country sources │        │ text from    │
                  │                               │        │ profile +    │
                  │ 6b. Sub-sector gate           │        │ scores       │
                  │     (if config.enabled)       │        │              │
                  │     → classify sub-sector     │        │ Upsert to    │
                  │     → check user intent       │        │ Pinecone     │
                  │                               │        │              │
                  │ 6c. Compute 5 dimensions      │        │ Set:         │
                  │     with country-specific     │        │ pinecone_    │
                  │     source selection          │        │ synced_at    │
                  │                               │        └──────────────┘
                  │ 6d. Apply confidence bands    │
                  │     per dimension (source     │
                  │     level → tight/medium/wide)│
                  │                               │
                  │ 6e. Compute base score        │
                  │     (weighted sum, applying   │
                  │     cold-start adjustments    │
                  │     for Talent Export History)│
                  │                               │
                  │ → company_scores table        │
                  │   dimension_scores JSONB      │
                  └──────────────────────────────┘
```

### Stage Details

| Stage | Input | External Calls | Output | DB Table | Status |
|-------|-------|----------------|--------|----------|--------|
| 1. Init | Company row from `companies` | None | New `company_details` row | company_details | `pending` |
| 2. Web Search | Company name, sector, `country_code` | Google/Bing API (12-14 queries) | `raw_search_results` JSONB | company_details | `web_search_done` |
| 3. Website Scrape | `company.website` URL | Playwright (2-5 pages) | `raw_website_data` JSONB | company_details | `website_scraped` |
| 4. LLM Profile | Search results + website data | LLM API (1-2 calls) | Structured profile fields | company_details | `llm_extracted` |
| 5. Profile Complete | Extracted fields | None (validation) | quality score, content hash | company_details | `profile_complete` |
| 6. Scoring | Profile fields + sector YAML config | None (local computation) | `dimension_scores` JSONB + `base_score` + confidence bands | company_scores | (separate table) |
| 7. Vectorize | Profile + scores | OpenAI Embeddings + Pinecone | Vector in Pinecone | company_details | `pinecone_synced_at` set |

---

## LLM Approach: 1 Call, Not 4

The old plan made 4 parallel LLM calls (one per dimension). The new plan uses **1-2 calls**:

1. **Profile extraction** (Stage 4): Single call receives all raw data → produces the full structured profile (description_clean, city, sub_sector, headcount, sector_metadata, alumni_signals, etc.)
2. **Scoring evidence** (Stage 6, optional): Only if scoring engine can't compute from profile fields alone

Benefits: lower cost, more coherent profiles, fewer API calls to manage.

---

## Country Source Resolution

At Stage 6, the scoring engine resolves data sources for each signal dynamically based on the company's `country_code`:

```
Company country_code: "SA"
        │
        ▼
For each dimension → for each signal:
  signal.source_config["SA"] → found → use SA sources
  signal.source_config["SA"] → not found → use signal.source_config["_default"]
        │
        ▼
Source level used determines confidence band:
  "primary"   → tight band  (±10%)
  "secondary" → medium band (±20%)
  "fallback"  → wide band   (±35%, flagged in UI)
```

This means:
- A UAE company uses DED trade license data for Dimension 1 (tight band)
- A Kuwait company uses the MOCI register (tight band if available, medium if falling through to LinkedIn)
- Any unlisted country falls to `_default` (LinkedIn/website/press — medium or wide band)
- No UAE-specific logic in the scoring engine itself — all sources come from YAML config

---

## Sub-Sector Gating Flow

An optional pre-scoring step that applies when `sub_sector_gate.enabled: true` in the sector config. Currently required for Academic & Educational Services; not needed for Retailers.

```
Profile: sub_sector_tags, description_clean
        │
        ▼
Does sector config have sub_sector_gate.enabled: true?
        │
   ┌────┴────┐
  YES        NO
   │          │
   ▼          └──▶ Proceed to scoring (all 5 dimensions)
Classify company into sub-sector
using classification_signals from config
        │
        ▼
Does company sub-sector match user's target sub-sector?
        │
   ┌────┴────┐
  YES        NO
   │          │
   ▼          ▼
Proceed     sub_sector_gate_result = "excluded"
to scoring  Company excluded from ranked list
            (still scored, but hidden unless user toggles)
```

Cross-sub-sector ranking is permitted with explicit user opt-in — results are grouped by sub-sector before being ranked within each group.

---

## Concurrency Model

```
Semaphore (max=3 concurrent companies for enrichment)
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  ┌──────────────────┐  ┌──────────────────┐                    │
│  │ Company Worker 1 │  │ Company Worker 2 │  ...               │
│  │ Stages 1-5:      │  │ Stages 1-5:      │                    │
│  │  sequential per   │  │  sequential per   │                    │
│  │  company          │  │  company          │                    │
│  └──────────────────┘  └──────────────────┘                    │
└─────────────────────────────────────────────────────────────────┘

Scoring (Stage 6) runs as a separate batch pass:
  - Load all 'profile_complete' rows
  - Score in parallel (no external API calls, pure computation)
  - Sub-sector gate runs per company before scoring

Vectorize (Stage 7) also runs as a separate batch pass:
  - Embed in batches (OpenAI supports batch embedding)
  - Upsert to Pinecone in batches
  - Flatten dimension_scores JSONB to top-level metadata keys for $gte filter support
```

Within each enrichment worker:
- Web search queries: sequential (rate limit)
- Website pages: sequential (same domain)
- LLM extraction: 1 call (profile extraction)
- Profile validation: local, instant

---

## Error Handling & Resumability

### State Machine

```
        ┌───────────────────────────────────────────────────────┐
        │                                                       │
        ▼                                                       │
┌──────────────┐     ┌─────────────────┐     ┌────────────────┐ │
│   pending    │───▶ │ web_search_done │───▶ │website_scraped │ │
└──────────────┘     └─────────────────┘     └───────┬────────┘ │
                                                     │           │
                                                     ▼           │
                                              ┌──────────────┐  │
                                              │llm_extracted │  │
                                              └──────┬───────┘  │
                                                     │           │
                                                     ▼           │
                                              ┌──────────────┐  │
                                              │profile_      │  │
                                              │complete      │  │
                                              └──────────────┘  │
                                                                 │
        ┌──────────────────────────────────────────────────────┐ │
        │                       failed                         │─┘
        │  (enrichment_error = "error message")                │
        │  (retry with --re-enrich or next run)                │
        └──────────────────────────────────────────────────────┘
```

On resume: pipeline checks current status, skips to next incomplete stage.
On `--re-enrich`: resets status to `pending`, bumps `enrichment_version`.

### Retry Strategy

```python
@retry(
    retry=retry_if_exception_type((SearchAPIError, LLMError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    reraise=True,
)
```

---

## Component Interaction

```
                       ┌──────────────────┐
                       │   CLI Entry Point │
                       │ run_scraper.py    │
                       │ enrich/score/vec  │
                       └────────┬─────────┘
                                │
                ┌───────────────┼───────────────────────┐
                ▼               ▼                       ▼
    ┌───────────────┐  ┌──────────────┐       ┌──────────────┐
    │ Enrichment    │  │  Scoring     │       │  Vectorizer  │
    │ Pipeline      │  │  Engine      │       │              │
    │ (Stages 1-5)  │  │  (Stage 6)  │       │  (Stage 7)   │
    └───┬───┬───┬───┘  └──────┬──────┘       └──────┬───────┘
        │   │   │              │                     │
        ▼   ▼   ▼              ▼                     ▼
  ┌─────────────────────────────────────────────────────────────┐
  │ Services: WebSearch, WebsiteScraper, LLMProvider            │
  │ Repos:    DetailRepository, ScoreRepository                 │
  │ Configs:  ScoringConfigRegistry (YAML)                      │
  │           CountrySourceResolver (reads source_config blocks)│
  │           SubSectorGate (optional, per sector config)       │
  │           ConfidenceBandCalculator                          │
  │ Vector:   EmbeddingProvider, PineconeStore                  │
  └─────────────────────────────────────────────────────────────┘
```
