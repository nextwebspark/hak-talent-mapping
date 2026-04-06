# Phase 3: Database Schema

---

## Entity-Relationship Diagram

```
┌──────────────────┐       ┌──────────────────────────┐       ┌──────────────────────┐
│   companies       │       │    company_details        │       │    company_scores     │
│──────────────────│       │──────────────────────────│       │──────────────────────│
│ company_id (UK*) │◀─1:1─▶│ company_id (FK, UK*)     │◀─1:N─│ company_detail_id FK │
│ sector (UK*)     │       │ sector (FK, UK*)         │       │ company_id (denorm)  │
│ name, slug       │       │                          │       │ sector (denorm)      │
│ profile_url      │       │ name, domain             │       │                      │
│ description      │       │ description_clean        │       │ base_score (0-100)   │
│ (sparse Phase 2) │       │ country_code, city       │       │ dimension_scores     │
│                  │       │ sub_sector, tags[]       │       │   JSONB (5+ dims)    │
│                  │       │ headcount, funding       │       │ confidence_bands     │
│                  │       │ sector_metadata (JSONB)  │       │   JSONB              │
│                  │       │ enrichment_status        │       │ sub_sector_gate      │
│                  │       │ raw_* audit trail        │       │   _result, _classif. │
│                  │       │ pinecone_synced_at       │       │ scoring_config_id    │
└──────────────────┘       └──────────────────────────┘       │ scoring_weights JSONB│
                                     │ synced to               │ scoring_version      │
                                     ▼                         └──────────────────────┘
                           ┌──────────────────────────┐    ┌─────────────────────┐
                           │   Pinecone               │    │  scoring_configs/    │
                           │   hak-company-profiles   │    │  (YAML on disk)     │
                           │  • rich profile text     │    │  retailers_v2.yaml  │
                           │  • metadata (filterable) │    │  academic_ed_v1.yaml│
                           │  • 1536-dim cosine       │    │  default_v1.yaml    │
                           └──────────────────────────┘    └─────────────────────┘
```

**Key design decisions:**
- `company_details` extends `companies` via FK — the original table is **never modified**
- `company_scores` links to `company_details.id` (UUID), not the composite key — cleaner for the 1:N relationship
- Scoring is decoupled: drop and rebuild `company_scores` without touching profiles
- `dimension_scores` is JSONB — adding a 6th/7th dimension in the future requires zero schema migration
- `base_score` is kept as a named column for fast `ORDER BY` ranking queries
- `domain` has a unique partial index for cross-sector dedup (same company in multiple Zawya sectors)

---

## Table 1: `company_details` — Rich Company Profile

**Migration file:** `supabase/migrations/002_add_company_details.sql`

One row per (company_id, sector) pair. This is the primary output of the enrichment pipeline (Stages 1-5).

```sql
create table if not exists public.company_details (
    id                      uuid primary key default gen_random_uuid(),

    -- ═══════════════════════════════════════════════════════════════
    -- FOREIGN KEY — links to existing companies table
    -- ═══════════════════════════════════════════════════════════════
    company_id              text not null,
    sector                  text not null,

    -- ═══════════════════════════════════════════════════════════════
    -- IDENTITY (Tier 1) — always populated after enrichment
    -- ═══════════════════════════════════════════════════════════════
    name                    text not null,
    domain                  text,                   -- canonical website domain (dedup key)
    description             text,                   -- raw description from Zawya/website
    description_clean       text,                   -- LLM-cleaned version for embedding

    -- ═══════════════════════════════════════════════════════════════
    -- LOCATION (Tier 1)
    -- ═══════════════════════════════════════════════════════════════
    country                 text,                   -- 'United Arab Emirates'
    country_code            text,                   -- 'AE'
    city                    text,                   -- 'Dubai'
    region                  text,                   -- 'GCC'

    -- ═══════════════════════════════════════════════════════════════
    -- SECTOR CLASSIFICATION (Tier 1)
    -- ═══════════════════════════════════════════════════════════════
    sub_sector              text,                   -- 'fashion_retail', 'k12', 'digital_health'
    sub_sector_tags         text[],                 -- ['luxury','multi-format','ecommerce']

    -- ═══════════════════════════════════════════════════════════════
    -- SIZE & STAGE (Tier 2)
    -- ═══════════════════════════════════════════════════════════════
    funding_stage           text,                   -- 'seed','series_a','series_b','public'
    funding_total_usd       bigint,
    headcount_range         text,                   -- '51-200'
    headcount_exact         integer,
    founded_year            integer,

    -- ═══════════════════════════════════════════════════════════════
    -- SECTOR-SPECIFIC SIGNALS (JSONB — validated by Python models)
    -- Schema varies by sector. See 04-scoring-model.md for examples.
    -- Examples: store_count (retail), student_enrollment (academic),
    --           facility_count (healthcare), branch_count (banking)
    -- ═══════════════════════════════════════════════════════════════
    sector_metadata         jsonb not null default '{}',

    -- ═══════════════════════════════════════════════════════════════
    -- DISPLAY & LINKS (Tier 3)
    -- ═══════════════════════════════════════════════════════════════
    logo_url                text,
    linkedin_url            text,
    crunchbase_url          text,

    -- ═══════════════════════════════════════════════════════════════
    -- EXTERNAL SOURCE IDs (placeholders for future API integration)
    -- ═══════════════════════════════════════════════════════════════
    crunchbase_uuid         text,
    pdl_id                  text,
    linkedin_company_id     text,

    -- ═══════════════════════════════════════════════════════════════
    -- DATA QUALITY & FRESHNESS
    -- ═══════════════════════════════════════════════════════════════
    data_quality_score      real,                   -- 0.0-1.0, computed from field completeness
    content_hash            text,                   -- SHA256 of profile fields, for change detection
    sources_used            text[],                 -- ['zawya','web_search','website','llm']

    -- ═══════════════════════════════════════════════════════════════
    -- ENRICHMENT PIPELINE STATE (resumable)
    -- ═══════════════════════════════════════════════════════════════
    enrichment_status       text not null default 'pending',
        -- Values: pending → web_search_done → website_scraped
        --       → llm_extracted → profile_complete → failed
    enrichment_error        text,
    enrichment_started_at   timestamptz,
    enrichment_completed_at timestamptz,
    enrichment_version      integer not null default 1,

    -- ═══════════════════════════════════════════════════════════════
    -- VECTOR SYNC STATE
    -- ═══════════════════════════════════════════════════════════════
    pinecone_synced_at      timestamptz,
    embedding_model         text,                   -- 'text-embedding-3-small'

    -- ═══════════════════════════════════════════════════════════════
    -- RAW DATA AUDIT TRAIL (JSONB — full responses for debugging)
    -- ═══════════════════════════════════════════════════════════════
    raw_search_results      jsonb not null default '[]',
    raw_website_data        jsonb not null default '{}',
    raw_llm_extraction      jsonb not null default '{}',

    -- ═══════════════════════════════════════════════════════════════
    -- TIMESTAMPS
    -- ═══════════════════════════════════════════════════════════════
    last_enriched_at        timestamptz,
    created_at              timestamptz not null default now(),
    updated_at              timestamptz not null default now(),

    -- FK to companies table (composite key)
    constraint fk_company_details_company
        foreign key (company_id, sector)
        references public.companies (company_id, sector)
        on delete cascade
);

-- ═══════════════════════════════════════════════════════════════
-- INDEXES
-- ═══════════════════════════════════════════════════════════════

-- Unique: one detail row per (company, sector)
create unique index if not exists company_details_company_sector_idx
    on public.company_details (company_id, sector);

-- Dedup by domain (across all sectors — nullable, so partial index)
create unique index if not exists company_details_domain_idx
    on public.company_details (domain)
    where domain is not null;

-- Fast lookup of pending enrichments by status
create index if not exists company_details_status_idx
    on public.company_details (enrichment_status)
    where enrichment_status not in ('profile_complete', 'failed');

-- Sector + country for multi-sector queries
create index if not exists company_details_sector_country_idx
    on public.company_details (sector, country_code);

-- GIN index on sector_metadata for JSONB queries
create index if not exists company_details_sector_metadata_idx
    on public.company_details using gin (sector_metadata);

-- GIN index on sub_sector_tags for array containment queries
create index if not exists company_details_sub_sector_tags_idx
    on public.company_details using gin (sub_sector_tags);

-- ═══════════════════════════════════════════════════════════════
-- TRIGGERS & RLS
-- ═══════════════════════════════════════════════════════════════

drop trigger if exists company_details_set_updated_at on public.company_details;
create trigger company_details_set_updated_at
    before update on public.company_details
    for each row execute function public.set_updated_at();

alter table public.company_details enable row level security;
create policy "service_role_all" on public.company_details
    for all to service_role using (true) with check (true);
```

---

## Table 2: `company_scores` — Dimension Scoring

**Migration file:** `supabase/migrations/003_add_company_scores.sql`

Fully separate from profiles. Can be dropped and rebuilt without touching `company_details`.

`dimension_scores` uses JSONB rather than named columns so that adding new dimensions (future sectors may need a 6th or 7th) requires zero schema migration. Dimension keys are stable internal IDs from the YAML config; human-readable labels are decoded at the application layer.

```sql
create table if not exists public.company_scores (
    id                      uuid primary key default gen_random_uuid(),

    -- ═══════════════════════════════════════════════════════════════
    -- FOREIGN KEY — links to company_details
    -- ═══════════════════════════════════════════════════════════════
    company_detail_id       uuid not null references public.company_details (id)
                            on delete cascade,

    -- Denormalized for query convenience (avoids join for filtering)
    company_id              text not null,
    sector                  text not null,

    -- ═══════════════════════════════════════════════════════════════
    -- COMPOSITE SCORE — kept as a named column for fast ORDER BY
    -- ═══════════════════════════════════════════════════════════════
    base_score              numeric(5,2),           -- weighted sum, 0–100

    -- ═══════════════════════════════════════════════════════════════
    -- DIMENSION SCORES (JSONB — extensible, no migration to add dims)
    --
    -- Keys are dimension IDs from the sector YAML config.
    -- Standard dimension IDs:
    --   organisational_scale, brand_prominence, leadership_depth,
    --   talent_export_history, sector_fit_confidence
    --
    -- Future sectors may add additional keys without schema changes.
    -- Labels (e.g. "Brand & Institutional Reputation" for Academic)
    -- are decoded from config at query time, not stored here.
    -- ═══════════════════════════════════════════════════════════════
    dimension_scores        jsonb not null default '{}',

    -- ═══════════════════════════════════════════════════════════════
    -- CONFIDENCE BANDS (JSONB — per-dimension + overall)
    -- ═══════════════════════════════════════════════════════════════
    confidence_bands        jsonb not null default '{}',

    -- ═══════════════════════════════════════════════════════════════
    -- SUB-SECTOR GATE RESULT
    -- ═══════════════════════════════════════════════════════════════
    sub_sector_gate_result  text,                   -- 'passed', 'excluded', null (no gate for this sector)
    sub_sector_classified   text,                   -- 'k12', 'higher_education', 'vocational', etc.

    -- ═══════════════════════════════════════════════════════════════
    -- SCORING CONFIG REFERENCE (reproducibility)
    -- ═══════════════════════════════════════════════════════════════
    scoring_config_id       text not null,          -- 'retailers_v2', 'academic_educational_v1', 'default_v1'
    scoring_config_hash     text,                   -- SHA256 of config used
    scoring_weights         jsonb not null,          -- actual weights: {"organisational_scale": 0.25, ...}

    -- ═══════════════════════════════════════════════════════════════
    -- VERSIONING
    -- ═══════════════════════════════════════════════════════════════
    scoring_version         integer not null default 1,
    scored_at               timestamptz not null default now(),

    created_at              timestamptz not null default now(),
    updated_at              timestamptz not null default now()
);

-- ═══════════════════════════════════════════════════════════════
-- INDEXES
-- ═══════════════════════════════════════════════════════════════

-- One score per (detail, config) — allows re-scoring with new config
create unique index if not exists company_scores_detail_config_idx
    on public.company_scores (company_detail_id, scoring_config_id);

-- Fast ranking queries (base_score is a named column, not JSONB)
create index if not exists company_scores_base_score_idx
    on public.company_scores (base_score desc nulls last);

-- Sector + score for leaderboards
create index if not exists company_scores_sector_score_idx
    on public.company_scores (sector, base_score desc nulls last);

-- GIN index on dimension_scores for JSONB path queries
create index if not exists company_scores_dimension_scores_idx
    on public.company_scores using gin (dimension_scores);

-- ═══════════════════════════════════════════════════════════════
-- TRIGGERS & RLS
-- ═══════════════════════════════════════════════════════════════

drop trigger if exists company_scores_set_updated_at on public.company_scores;
create trigger company_scores_set_updated_at
    before update on public.company_scores
    for each row execute function public.set_updated_at();

alter table public.company_scores enable row level security;
create policy "service_role_all" on public.company_scores
    for all to service_role using (true) with check (true);
```

---

## `dimension_scores` JSONB Structure

Each key in `dimension_scores` is a dimension ID from the sector config. The structure per dimension:

```json
{
  "organisational_scale": {
    "score": 9.2,
    "confidence_band": "tight",
    "source_level": "primary",
    "weight_used": 0.25,
    "effective_weight": 0.25,
    "cold_start_active": false,
    "evidence": {
      "estimated_headcount": {
        "value": 50000,
        "source": "linkedin",
        "source_url": "https://linkedin.com/company/...",
        "source_level": "primary",
        "confidence_band": "tight"
      },
      "location_count": {
        "value": 200,
        "source": "company_website",
        "source_url": "https://landmarkgroup.com/stores",
        "source_level": "primary",
        "confidence_band": "tight"
      }
    },
    "rationale": "Large multi-format retailer, 200+ UAE locations"
  },

  "brand_prominence": {
    "score": 8.8,
    "confidence_band": "tight",
    "source_level": "primary",
    "weight_used": 0.20,
    "effective_weight": 0.20,
    "cold_start_active": false,
    "evidence": { ... },
    "rationale": "14 tier-1 press mentions last 12 months, Retailer of the Year ME finalist"
  },

  "leadership_depth": {
    "score": 8.2,
    "confidence_band": "tight",
    "source_level": "primary",
    "weight_used": 0.25,
    "effective_weight": 0.25,
    "cold_start_active": false,
    "evidence": { ... },
    "rationale": "Named CEO, CFO, CCO, COO, CMO confirmed. Director-level across buying, ops, marketing"
  },

  "talent_export_history": {
    "score": 7.5,
    "confidence_band": "medium",
    "source_level": "secondary",
    "weight_used": 0.15,
    "effective_weight": 0.08,
    "cold_start_active": true,
    "evidence": {
      "alumni_in_senior_roles": {
        "value": 8,
        "source": "linkedin_alumni",
        "source_level": "primary",
        "confidence_band": "tight"
      },
      "press_confirmed_export": {
        "value": 3,
        "source": "web_search",
        "source_level": "secondary",
        "confidence_band": "medium"
      }
    },
    "rationale": "8 tracked alumni in VP+ roles at Majid Al Futtaim, Chalhoub, Azadea [Enriching — growing]"
  },

  "sector_fit_confidence": {
    "score": 10.0,
    "confidence_band": "tight",
    "source_level": "primary",
    "weight_used": 0.15,
    "effective_weight": 0.15,
    "cold_start_active": false,
    "evidence": { ... },
    "rationale": "DED trade license confirms retail as primary activity. Direct — multi-format retail operator"
  }
}
```

**Fields per dimension:**

| Field | Type | Description |
|-------|------|-------------|
| `score` | float (0–10) | Dimension score |
| `confidence_band` | string | `"tight"` / `"medium"` / `"wide"` |
| `source_level` | string | `"primary"` / `"secondary"` / `"fallback"` — best level used for this dimension |
| `weight_used` | float | Config weight (0–1) |
| `effective_weight` | float | Actual weight applied (may differ during cold-start) |
| `cold_start_active` | bool | True only for `talent_export_history` at launch |
| `evidence` | dict | Per-signal values with provenance |
| `rationale` | string | One-line human-readable explanation |

---

## `confidence_bands` JSONB Structure

```json
{
  "organisational_scale": {
    "band": "tight",
    "tolerance_pct": 10,
    "source_level_used": "primary"
  },
  "brand_prominence": {
    "band": "tight",
    "tolerance_pct": 10,
    "source_level_used": "primary"
  },
  "leadership_depth": {
    "band": "medium",
    "tolerance_pct": 20,
    "source_level_used": "secondary"
  },
  "talent_export_history": {
    "band": "medium",
    "tolerance_pct": 20,
    "source_level_used": "secondary"
  },
  "sector_fit_confidence": {
    "band": "tight",
    "tolerance_pct": 10,
    "source_level_used": "primary"
  },
  "overall_band": "medium",
  "overall_tolerance_pct": 14
}
```

Confidence band thresholds (from sector YAML config):

| Band | Source Level | Tolerance | UI Behaviour |
|------|-------------|-----------|--------------|
| tight | primary | ±10% | No flag |
| medium | secondary | ±20% | No flag |
| wide | fallback | ±35% | Flagged in UI |

Overall band = worst band among all scored dimensions. Overall tolerance = weighted average.

---

## Querying Dimension Scores

`base_score` is a named column and supports direct SQL ordering:

```sql
-- Standard ranking query
select company_id, name, base_score
from company_scores
where sector = 'Retailers'
order by base_score desc;
```

For per-dimension queries, use Postgres JSONB path expressions or expression indexes:

```sql
-- Ad-hoc filter on leadership depth
select company_id, base_score,
       (dimension_scores -> 'leadership_depth' ->> 'score')::numeric as ld_score
from company_scores
where sector = 'Retailers'
  and (dimension_scores -> 'leadership_depth' ->> 'score')::numeric >= 7.0
order by base_score desc;

-- Expression index for frequent per-dimension queries
create index company_scores_leadership_idx
    on company_scores (((dimension_scores -> 'leadership_depth' ->> 'score')::numeric) desc);
```

For Pinecone vector search, `dimension_scores` is **flattened** at write time into top-level metadata keys (e.g., `organisational_scale_score: 9.2`) to support Pinecone's `$gte` filter operator.
