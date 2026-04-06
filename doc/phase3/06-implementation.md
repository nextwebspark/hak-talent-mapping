# Phase 3: Implementation Plan

---

## File Structure

```
src/hak_talent_mapping/
├── config.py                              # MODIFY: add ~20 new settings
│
├── core/
│   ├── models.py                          # MODIFY: add CompanyProfile, CompanyScoreRecord,
│   │                                      #   EnrichmentStatus, DimensionScore, ConfidenceBand,
│   │                                      #   SectorScoringConfig, RoleArchetype, etc.
│   ├── constants.py                       # MODIFY: add COUNTRY_CODE_MAP, REGION_MAP
│   └── exceptions.py                      # MODIFY: add EnrichmentError, SearchAPIError,
│                                          #   LLMError, VectorStoreError, ScoringError
│
├── scoring_configs/                       # NEW DIRECTORY
│   ├── __init__.py
│   ├── retailers_v2.yaml                  # full config: 5 dims, 7 countries, 6 role archetypes
│   ├── academic_educational_v1.yaml       # sub-sector gate, regulatory_rating signal
│   ├── default_v1.yaml                    # fallback for any sector without a custom config
│   └── (healthcare_v1.yaml, etc.)         # added incrementally per sector
│
├── services/
│   ├── listing_scraper.py                 # EXISTING (no changes)
│   ├── detail_scraper.py                  # EXISTING (no changes)
│   │
│   ├── enrichment/                        # NEW PACKAGE
│   │   ├── __init__.py
│   │   ├── pipeline.py                    # EnrichmentPipeline (Stages 1-5)
│   │   ├── web_search.py                  # SearchProvider ABC + Google/Bing
│   │   ├── website_scraper.py             # Playwright company website scraper
│   │   ├── scoring.py                     # ScoringEngine (Stage 6)
│   │   ├── scoring_config.py              # ScoringConfig, ScoringConfigRegistry
│   │   ├── country_source_resolver.py     # NEW: resolves primary/secondary/fallback per country
│   │   ├── confidence.py                  # NEW: ConfidenceBandCalculator
│   │   ├── sub_sector_gate.py             # NEW: SubSectorGate (optional, per sector config)
│   │   └── vectorizer.py                  # Vectorizer (Stage 7)
│   │
│   ├── llm/                               # NEW PACKAGE
│   │   ├── __init__.py
│   │   ├── base.py                        # LLMProvider ABC
│   │   ├── claude_provider.py             # Anthropic Claude implementation
│   │   ├── openai_provider.py             # OpenAI GPT implementation
│   │   └── prompts.py                     # Profile extraction prompt templates
│   │
│   └── vector/                            # NEW PACKAGE
│       ├── __init__.py
│       ├── embeddings.py                  # OpenAI embedding generation
│       └── pinecone_store.py              # Pinecone upsert/query/delete + metadata flattening
│
├── db/
│   ├── repository.py                      # EXISTING (no changes)
│   ├── detail_repository.py               # NEW: CRUD for company_details
│   └── score_repository.py                # NEW: CRUD for company_scores

scripts/
├── run_scraper.py                         # MODIFY: add enrich, score, vectorize + --sub-sector flag

supabase/migrations/
├── 002_add_company_details.sql            # NEW
└── 003_add_company_scores.sql             # NEW

tests/unit/
├── test_scoring.py                        # NEW
├── test_scoring_config.py                 # NEW
├── test_confidence_bands.py               # NEW
├── test_sub_sector_gate.py                # NEW
├── test_country_source_resolver.py        # NEW
└── test_profile_models.py                 # NEW
```

---

## Key Pydantic Models

```python
class EnrichmentStatus(StrEnum):
    PENDING = "pending"
    WEB_SEARCH_DONE = "web_search_done"
    WEBSITE_SCRAPED = "website_scraped"
    LLM_EXTRACTED = "llm_extracted"
    PROFILE_COMPLETE = "profile_complete"
    FAILED = "failed"


class ConfidenceBand(BaseModel):
    band: str                           # 'tight' | 'medium' | 'wide'
    tolerance_pct: int                  # 10 | 20 | 35
    source_level_used: str              # 'primary' | 'secondary' | 'fallback'


class SignalValue(BaseModel):
    value: str | int | float | list[str] | bool | None
    source: str                         # 'web_search' | 'company_website' | 'zawya' | 'llm'
    source_url: str | None = None
    source_level: str = "fallback"      # 'primary' | 'secondary' | 'fallback'
    confidence_band: str = "wide"       # 'tight' | 'medium' | 'wide'


class DimensionScore(BaseModel):
    score: float                        # 0.0-10.0
    confidence_band: str                # 'tight' | 'medium' | 'wide'
    source_level: str                   # best source level used for this dimension
    weight_used: float                  # config weight (0-1)
    effective_weight: float             # actual weight (may differ during cold-start)
    cold_start_active: bool = False     # True only for talent_export_history at launch
    evidence: dict[str, SignalValue]
    rationale: str


class CompanyScoreRecord(BaseModel):
    """Maps to company_scores table.

    dimension_scores is a dict keyed by dimension ID from the sector YAML config.
    Standard keys: organisational_scale, brand_prominence, leadership_depth,
                   talent_export_history, sector_fit_confidence
    Future sectors may add additional keys without any model or schema changes.
    """
    company_detail_id: str
    company_id: str
    sector: str
    base_score: float | None = None
    dimension_scores: dict[str, DimensionScore] = Field(default_factory=dict)
    confidence_bands: dict[str, ConfidenceBand] = Field(default_factory=dict)
    sub_sector_gate_result: str | None = None   # 'passed' | 'excluded' | None
    sub_sector_classified: str | None = None
    scoring_config_id: str
    scoring_config_hash: str | None = None
    scoring_weights: dict[str, float]           # actual weights used (incl. cold-start adjustments)


class SearchResult(BaseModel):
    title: str
    snippet: str
    url: str
    date_published: str | None = None


class ProfileExtractionResult(BaseModel):
    """Structured output from LLM profile extraction (Stage 4)."""
    description_clean: str | None = None
    city: str | None = None
    region: str | None = None
    sub_sector: str | None = None
    sub_sector_tags: list[str] = Field(default_factory=list)
    funding_stage: str | None = None
    funding_total_usd: int | None = None
    headcount_range: str | None = None
    headcount_exact: int | None = None
    founded_year: int | None = None
    sector_metadata: dict = Field(default_factory=dict)
    linkedin_url: str | None = None
    crunchbase_url: str | None = None
    logo_url: str | None = None
    domain: str | None = None


class CompanyProfile(BaseModel):
    """Maps to company_details table."""
    id: str | None = None
    company_id: str
    sector: str
    name: str
    domain: str | None = None
    description: str | None = None
    description_clean: str | None = None
    country: str | None = None
    country_code: str | None = None
    city: str | None = None
    region: str | None = None
    sub_sector: str | None = None
    sub_sector_tags: list[str] = Field(default_factory=list)
    funding_stage: str | None = None
    funding_total_usd: int | None = None
    headcount_range: str | None = None
    headcount_exact: int | None = None
    founded_year: int | None = None
    sector_metadata: dict = Field(default_factory=dict)
    data_quality_score: float | None = None
    sources_used: list[str] = Field(default_factory=list)
    enrichment_status: EnrichmentStatus = EnrichmentStatus.PENDING
```

### Sector Config Models

```python
class SignalSourceConfig(BaseModel):
    primary: str
    secondary: str | None = None
    fallback: str


class SignalDefinition(BaseModel):
    name: str
    type: str                                         # 'integer' | 'boolean' | 'string' | 'string_list'
    source_config: dict[str, SignalSourceConfig]      # country_code → sources; '_default' always present
    search_queries: list[str] = Field(default_factory=list)
    scoring_thresholds: list[dict] | None = None
    scoring_logic: dict | None = None
    scoring_points: dict | None = None
    primary_proxy: bool = False


class DimensionConfig(BaseModel):
    weight: float
    cold_start_weight: float | None = None            # if set, used at launch instead of weight
    cold_start_redistribution: dict[str, float] | None = None
    cold_start_ui_flag: str | None = None
    label: str
    sector_label: str | None = None                   # overrides display name for this sector
    signals: list[SignalDefinition]
    linkedin_confidence_adjustments: dict[str, float] | None = None
    sector_flags: list[str] = Field(default_factory=list)
    sector_extensions: dict | None = None
    fallback_hierarchy: list[dict] | None = None
    gate: bool = False


class SubSectorGateConfig(BaseModel):
    enabled: bool = False
    sub_sectors: list[dict] = Field(default_factory=list)
    cross_sub_sector_allowed: bool = True
    cross_sub_sector_warning: str | None = None


class RoleArchetype(BaseModel):
    id: str
    label: str
    weights: dict[str, float]                         # dimension_id → weight; must sum to 1.0
    rationale: str | None = None


class SectorScoringConfig(BaseModel):
    config_id: str
    sector_match: str
    version: int
    sub_sector_gate: SubSectorGateConfig | None = None
    dimensions: dict[str, DimensionConfig]            # dimension_id → config
    confidence_bands: dict[str, dict]
    sector_metadata_schema: list[dict] = Field(default_factory=list)
    brief_reweighting: dict[str, list[RoleArchetype]] = Field(default_factory=dict)
```

---

## LLM Abstraction

```python
class LLMProvider(ABC):
    """Abstract interface — swap Claude/OpenAI via config."""

    @abstractmethod
    async def extract_profile(
        self,
        company_name: str,
        sector: str,
        country_code: str,
        raw_search_results: list[dict],
        raw_website_data: dict[str, str],
        existing_data: dict[str, str | None],
        sector_metadata_schema: list[dict],     # from YAML config, guides extraction
    ) -> ProfileExtractionResult:
        """Extract full structured profile from raw data."""
        ...
```

Provider selected via `settings.llm_provider` ("claude" | "openai").

---

## Web Search — Queries Per Dimension

All queries use `{company_name}`, `{country}`, `{sector}`, and `{year}` placeholders resolved at runtime from the company's profile and the current date. No hardcoded country strings.

Queries come from the YAML config's `search_queries` field per signal. The defaults below are illustrative:

```
Dimension: Organisational Scale
├── "{company_name}" {country} employees headcount
├── "{company_name}" number of stores locations {country}
├── "{company_name}" revenue annual report
└── "{company_name}" registration signals {country}

Dimension: Brand & Market Prominence
├── "{company_name}" {country} {sector} news {year}
├── "{company_name}" "leading" OR "largest" OR "award" {sector}
└── "{company_name}" expansion news {country}

Dimension: Leadership Depth
├── "{company_name}" CEO OR CFO OR COO OR "managing director" OR CCO
├── "{company_name}" executive team leadership
└── "{company_name}" appointed VP director {country}

Dimension: Talent Export History
├── "{company_name}" "former" OR "previously" OR "ex-" executive appointed {sector}
└── "{company_name}" alumni senior roles

Dimension: Sector Fit Confidence
├── "{company_name}" {sector} operations {country}
└── "{company_name}" company profile industry
```

~12-14 queries per company total. Exact queries and count come from the sector YAML config.

---

## Key New Services

### `country_source_resolver.py`

```python
class CountrySourceResolver:
    """Resolves primary/secondary/fallback source for a signal given a country code."""

    def resolve(
        self,
        signal: SignalDefinition,
        country_code: str,
    ) -> tuple[SignalSourceConfig, str]:
        """Returns (source_config, source_level_key).

        source_level_key = 'primary' | 'secondary' | 'fallback'
        Falls back to '_default' if country_code not in signal.source_config.
        """
        ...
```

### `confidence.py`

```python
class ConfidenceBandCalculator:
    """Translates source level used into a confidence band."""

    def for_source_level(self, source_level: str, config: dict) -> ConfidenceBand:
        """primary → tight, secondary → medium, fallback → wide."""
        ...

    def overall(self, dimension_bands: dict[str, ConfidenceBand]) -> ConfidenceBand:
        """Worst band across all dimensions (weighted average tolerance)."""
        ...
```

### `sub_sector_gate.py`

```python
class SubSectorGate:
    """Classifies a company into a sub-sector and checks compatibility with user intent.

    Only runs when sector_config.sub_sector_gate.enabled is True.
    """

    def classify(
        self,
        profile: CompanyProfile,
        gate_config: SubSectorGateConfig,
    ) -> str | None:
        """Returns sub-sector ID or None if unclassifiable."""
        ...

    def check(
        self,
        classified: str | None,
        user_target_sub_sector: str | None,
    ) -> str:
        """Returns 'passed' | 'excluded'."""
        ...
```

---

## Exception Hierarchy

```
HakTalentError (base)
├── ScrapingError
│   ├── RateLimitError
│   └── ParseError
├── DatabaseError
└── EnrichmentError              ★ NEW
    ├── SearchAPIError
    ├── LLMError
    ├── VectorStoreError
    ├── WebsiteScrapeError
    └── ScoringError
```

---

## Configuration

### New Settings (add to `config.py`)

```python
# Enrichment pipeline
enrichment_concurrency: int = 3
enrichment_batch_size: int = 50

# Web Search
search_provider: str = "google"          # 'google' | 'bing'
google_search_api_key: str = ""
google_search_cx: str = ""
search_qps: float = 1.0

# LLM
llm_provider: str = "claude"             # 'claude' | 'openai'
anthropic_api_key: str = ""
openai_api_key: str = ""
llm_model: str = "claude-sonnet-4-6"
llm_temperature: float = 0.0

# Embeddings
embedding_model: str = "text-embedding-3-small"

# Pinecone
pinecone_api_key: str = ""
pinecone_index_name: str = "hak-company-profiles"
pinecone_environment: str = ""

# Website scraping
website_scrape_timeout: float = 30.0
website_max_pages: int = 5

# Scoring configs
scoring_config_dir: str = "src/hak_talent_mapping/scoring_configs"

# Confidence bands
confidence_band_primary_tolerance: int = 10
confidence_band_secondary_tolerance: int = 20
confidence_band_fallback_tolerance: int = 35

# Cold start
talent_export_cold_start: bool = True    # set False when platform data accumulates
```

### Environment Variables (`.env`)

```env
# Existing
SUPABASE_URL=https://<project>.supabase.co
SUPABASE_KEY=<service_role_key>

# Phase 3: Web Search
SEARCH_PROVIDER=google
GOOGLE_SEARCH_API_KEY=<key>
GOOGLE_SEARCH_CX=<cx>

# Phase 3: LLM
LLM_PROVIDER=claude
ANTHROPIC_API_KEY=<key>
OPENAI_API_KEY=<key>

# Phase 3: Pinecone
PINECONE_API_KEY=<key>
PINECONE_INDEX_NAME=hak-company-profiles
PINECONE_ENVIRONMENT=us-east-1-aws
```

---

## CLI Entry Point

```bash
# Phase 1 — Scrape all 30 UAE sectors
python scripts/run_scraper.py listings --country AE --sector all

# Phase 2 — Detail scraping (optional, sparse data)
python scripts/run_scraper.py details --limit 100

# Phase 3a — Build rich profiles
python scripts/run_scraper.py enrich --country AE --sector Retailers --limit 10
python scripts/run_scraper.py enrich --country AE --sector all
python scripts/run_scraper.py enrich --country SA --sector Retailers --limit 10

# Phase 3b — Score from profiles (decoupled, re-runnable)
python scripts/run_scraper.py score --country AE --sector Retailers
python scripts/run_scraper.py score --country AE --sector Retailers --re-score

# Score with sub-sector gate (for Academic)
python scripts/run_scraper.py score --country AE --sector "Academic & Educational Services" --sub-sector k12

# Phase 3c — Embed + Pinecone sync
python scripts/run_scraper.py vectorize --country AE --sector all

# Re-enrich (bump version, reprocess)
python scripts/run_scraper.py enrich --country AE --sector Retailers --re-enrich

# Full pipeline
python scripts/run_scraper.py all --country AE --sector Retailers --limit 10
```

---

## Implementation Order

| Step | What | Files | Depends On |
|------|------|-------|------------|
| 1 | Foundation — models, exceptions, constants | `core/models.py`, `core/exceptions.py`, `core/constants.py` | — |
| 2 | Config updates | `config.py` | Step 1 |
| 3 | DB migrations | `supabase/migrations/002_*.sql`, `003_*.sql` | Steps 1-2 |
| 4 | Repository layer | `db/detail_repository.py`, `db/score_repository.py` | Steps 1-3 |
| 5 | Scoring config YAML + loader | `scoring_configs/*.yaml`, `enrichment/scoring_config.py` | Step 1 |
| 5b | Country source resolver + confidence band calculator | `enrichment/country_source_resolver.py`, `enrichment/confidence.py` | Step 5 |
| 5c | Sub-sector gate | `enrichment/sub_sector_gate.py` | Step 5 |
| 6 | LLM abstraction + providers | `services/llm/*` | Step 1 |
| 7 | Web search service | `services/enrichment/web_search.py` | Steps 1-2 |
| 8 | Website scraper | `services/enrichment/website_scraper.py` | Steps 1-2 |
| 9 | Enrichment pipeline (Stages 1-5) | `services/enrichment/pipeline.py` | Steps 4, 6, 7, 8 |
| 10 | Scoring engine (Stage 6) — 5 dims + confidence bands + cold-start + sub-sector gate | `services/enrichment/scoring.py` | Steps 4, 5, 5b, 5c |
| 11 | Vector layer (Stage 7) — includes metadata flattening | `services/vector/*`, `enrichment/vectorizer.py` | Steps 1-2 |
| 12 | CLI updates | `scripts/run_scraper.py` | Steps 9, 10, 11 |
| 13 | Multi-sector + multi-country listings (`--sector all`, `--country SA`) | `scripts/run_scraper.py` | Step 12 |
| 14 | Unit tests | `tests/unit/*` | Steps 5, 5b, 5c, 10 |
| 15 | Additional scoring configs | `scoring_configs/*.yaml` | Step 5 |

**Fastest path to demo:** Steps 1-4, then 5+5b+6+7+8 in parallel, then 9, 10, 12. Vectorize (11) can come after.

---

## Dependencies

### New (add to `pyproject.toml`)

```toml
anthropic>=0.30.0          # Claude SDK (LLM provider)
openai>=1.30.0             # OpenAI SDK (LLM + embeddings)
pinecone-client>=3.0.0     # Pinecone vector DB
tiktoken>=0.7.0            # Token counting for embedding text
pyyaml>=6.0                # Scoring config YAML loading
```

---

## Cost Estimates

### Per Company (12-14 queries + 1-2 LLM calls + 1 embedding)

| Service | Calls | Cost per Call | Cost per Company |
|---------|-------|--------------|------------------|
| Google Custom Search | 12-14 | $0.005 | ~$0.07 |
| LLM (profile extraction) | 1-2 | ~$0.03 | ~$0.04 |
| OpenAI Embeddings | 1 | ~$0.0001 | ~$0.0001 |
| **Total** | | | **~$0.11–0.12** |

The extra 2 queries (vs. original 10-12) come from the Talent Export History dimension.

### At Scale

| Companies | Google Search | LLM | Embeddings | Total |
|-----------|--------------|-----|------------|-------|
| 100 | $7 | $4 | $0.01 | ~$11 |
| 1,000 | $70 | $40 | $0.10 | ~$110 |
| 6,800 (UAE Retailers) | $476 | $272 | $0.68 | ~$749 |
| 20,000+ (all UAE sectors) | $1,400 | $800 | $2.00 | ~$2,202 |

**Multi-country note:** Enriching the same 30 sectors across multiple countries multiplies the total linearly (e.g., UAE + Saudi Arabia + Egypt = 3× the per-company cost for each sector's population).

---

## Verification

```bash
# 1. Run migrations in Supabase SQL editor (002 then 003)

# 2. Test with 5 companies — UAE Retailers
python scripts/run_scraper.py enrich --country AE --sector Retailers --limit 5

# 3. Verify company_details populated (5 rows, profile_complete status)

# 4. Score
python scripts/run_scraper.py score --country AE --sector Retailers

# 5. Verify company_scores populated
#    Check dimension_scores JSONB has all 5 dimensions
#    Check talent_export_history.cold_start_active = true
#    Check confidence_bands JSONB populated

# 6. Vectorize
python scripts/run_scraper.py vectorize --country AE --sector Retailers

# 7. Verify Pinecone vectors
#    Check metadata has flattened dimension scores (e.g. leadership_depth_score)
#    Check talent_export_history_cold_start = True

# 8. Re-run enrich — should skip already-complete (resumability test)

# 9. Run --re-score — should update scores without re-enriching

# 10. Test Academic sub-sector gate
python scripts/run_scraper.py enrich --country AE --sector "Academic & Educational Services" --limit 5
python scripts/run_scraper.py score --country AE --sector "Academic & Educational Services" --sub-sector k12
#    Verify sub_sector_gate_result populated in company_scores

# 11. Test Saudi Arabia (different country source resolution)
python scripts/run_scraper.py enrich --country SA --sector Retailers --limit 5
#    Verify confidence_bands use SA-specific source levels (MISA → tight band)
```

---

## Future: Phase 4+ Roadmap

```
Phase 3 (Current)          Phase 4                    Phase 5
─────────────────          ─────────────────          ─────────────────
Company Enrichment         Brief Engine               Full Platform
+ Rich Profiles            + Search API               + Outreach
+ 5-dim Scoring            + Query Interface          + Analysis
  (country-portable)       + Reweighting UI           + Recommendation
+ Vector Storage

• Web search signals       • Brief ingestion          • Candidate discovery
• LLM profile extraction   • Role archetype detect    • AI outreach drafts
• 5-dim scoring (YAML)     • Weight rebalancing       • Multi-dim assessment
• Country source configs   • Pinecone semantic search • Search Command Centre
• Confidence bands         • 9-box talent map         • Living profiles
• Sub-sector gating        • Company scorecard UI     • Pipeline management
• Supabase 2 tables        • User weight sliders
• Pinecone embedding       • Talent Export weight
• Multi-sector UAE           restoration (cold-start
• Multi-country support      → full 15% as data grows)
```
