# hak-talent-mapping

Company data scraping and enrichment pipeline for the HAK AI executive search platform. Scrapes Zawya company listings, enriches them via LLM, scores profiles, and indexes them in Pinecone.

---

## Architecture

```
Phase 1 — Listings    → Zawya scraper (httpx + BeautifulSoup) → Supabase companies table
Phase 2 — Details     → Playwright headless browser → Supabase companies table
Phase 3 — Enrichment  → LLM extraction → Supabase company_details table
Phase 3 — Scoring     → ScoringEngine → Supabase company_scores table
Phase 3 — Vectorize   → OpenAI embeddings → Pinecone
```

Two enrichment providers are supported:

| Provider | How it works | When to use |
|---|---|---|
| **Perplexity** | Single API: grounded web search + LLM extraction in one call | Faster, fewer API keys needed |
| **Web + LLM** | Serper (Google search) + OpenRouter (LLM) — two separate services | More control, any model |

---

## Setup

### Requirements
- Python 3.11+
- [`uv`](https://github.com/astral-sh/uv) package manager
- Playwright browsers

```bash
# Install dependencies
uv sync

# Install Playwright Chromium
uv run playwright install chromium
```

### Environment variables

Copy `.env.example` to `.env` and fill in your credentials:

```bash
cp .env.example .env
```

| Variable | Required for | Description |
|---|---|---|
| `SUPABASE_URL` | All phases | Supabase project URL |
| `SUPABASE_KEY` | All phases | Service role key (not anon key) |
| `PERPLEXITY_API_KEY` | Perplexity enrichment | Perplexity sonar-pro access |
| `SERPER_API_KEY` | Web+LLM enrichment | Google search via serper.dev |
| `OPENROUTER_API_KEY` | Web+LLM enrichment + vectorize | OpenRouter LLM + embedding API |
| `PINECONE_API_KEY` | Vectorize | Pinecone index access |

---

## Running

### Phase 1 — Scrape company listings

```bash
# All UAE retailers (681 pages, ~6800 companies)
python scripts/run_scraper.py listings --country AE --sector Retailers

# Single country + sector
python scripts/run_scraper.py listings --country SA --sector "Food & Beverages"
```

### Phase 2 — Scrape company detail pages

```bash
# Scrape all pending detail pages (slow, ~3-4 hours, re-run as needed)
python scripts/run_scraper.py details --country AE --sector Retailers

# Test with 5 records
python scripts/run_scraper.py details --country AE --sector Retailers --limit 5

# Run in background
nohup python scripts/run_scraper.py details --country AE --sector Retailers \
  > logs/details.log 2>&1 &
```

### Phase 3 — Enrich company profiles

**Option A — Perplexity** (grounded search + LLM, one provider):

```bash
# Production — writes to Supabase
python scripts/run_enrich_perplexity.py --country AE --sector Retailers

# Local dev — writes to SQLite, no Supabase writes
python scripts/run_enrich_perplexity.py --country AE --sector Retailers --test --limit 5

# Re-enrich already-complete companies
python scripts/run_enrich_perplexity.py --country AE --sector Retailers --re-enrich
```

**Option B — Web + LLM** (Serper search + OpenRouter):

```bash
# Production
python scripts/run_enrich_web.py --country AE --sector Retailers

# Local dev
python scripts/run_enrich_web.py --country AE --sector Retailers --test --limit 5

# Override model
python scripts/run_enrich_web.py --country AE --sector Retailers \
  --model anthropic/claude-opus-4-7
```

### Phase 3 — Score enriched profiles

```bash
python scripts/run_scraper.py score --country AE --sector Retailers
```

### Phase 3 — Vectorize to Pinecone

```bash
python scripts/run_scraper.py vectorize --country AE --sector Retailers
```

---

## Local vs Production

| Mode | Flag | DB | Use for |
|---|---|---|---|
| **Local** | `--test` | SQLite (`local_test.db`) | Dev iteration, no Supabase writes |
| **Production** | *(no flag)* | Supabase (Postgres) | Real data |

In `--test` mode, the script syncs `top_company=true` rows from Supabase into a local SQLite file first, then runs enrichment entirely locally. Results stay in SQLite and are not pushed back to Supabase.

---

## Project structure

```
src/hak_talent_mapping/
  config.py                    # pydantic-settings config (loaded from .env)
  core/
    models.py                  # domain models (CompanyProfile, EnrichmentStatus, ...)
    exceptions.py              # custom exception hierarchy
  db/
    repository.py              # CompanyRepository (listings, details — Supabase)
    detail_repository.py       # DetailRepository (enrichment rows — Supabase)
    local_repository.py        # LocalDetailRepository (SQLite, --test mode)
    audit_repository.py        # AuditRepository (prompt/response audit log)
    score_repository.py        # ScoreRepository (scoring results)
  services/
    listing_scraper.py         # Phase 1: httpx + BeautifulSoup
    detail_scraper.py          # Phase 2: Playwright
    enrichment/
      pipeline.py              # EnrichmentPipeline (stages 1-5), EnrichmentRunner
      web_search.py            # SerperSearchService
      website_scraper.py       # WebsiteScraper (Playwright)
      scoring/
        engine.py              # ScoringEngine
        config_loader.py       # YAML sector config loader
    llm/
      base.py                  # LLMProvider ABC
      perplexity_provider.py   # Perplexity sonar-pro (3 parallel calls)
      openrouter_provider.py   # OpenRouter (OpenAI-compatible)
      claude_provider.py       # Direct Anthropic SDK
      perplexity_prompts.py    # Prompt builders for Perplexity
      prompts.py               # Prompt builders for OpenRouter/Claude
    vector/
      embeddings.py            # OpenAIEmbeddingProvider
      pinecone_store.py        # PineconeStore, VectorizationRunner

scripts/
  run_scraper.py               # Phases 1, 2, score, vectorize
  run_enrich_perplexity.py     # Phase 3 enrichment — Perplexity provider
  run_enrich_web.py            # Phase 3 enrichment — Serper + OpenRouter
  _enrich_common.py            # Shared helpers (logging, repos, preflight)
  export_to_excel.py           # Export results to Excel

scoring_configs/
  retailers.yaml               # Sector-specific scoring weights + LLM guidance

supabase/
  schema.sql                   # Run once in Supabase SQL editor to create tables
```

---

## Database

Tables in Supabase:

| Table | Purpose |
|---|---|
| `companies` | Raw scraped company listings + detail fields |
| `company_details` | Enriched profiles (one row per company + sector) |
| `company_scores` | Scoring results per company |
| `enrichment_audit` | Prompt/response audit log per enrichment stage |

Run `supabase/schema.sql` once in the Supabase SQL editor to create all tables.

---

## Resumability

All phases are safe to re-run:
- **Listings**: upserts on `company_id`
- **Details**: skips companies where `detail_scraped_at IS NOT NULL`
- **Enrichment**: skips companies where status is `profile_complete`; use `--re-enrich` to reset

---

## Production checklist

Before running enrichment in production:

- [ ] `.env` contains all required API keys
- [ ] `supabase/schema.sql` has been applied to the Supabase project
- [ ] `top_company=true` is set on the companies you want to enrich
- [ ] Run a test batch first: `--test --limit 5`
- [ ] Scripts run preflight connectivity checks automatically — watch for failures at startup
- [ ] Monitor rate limits: Zawya (Phase 1-2), Serper, OpenRouter, Perplexity all have quotas
- [ ] Enrichment concurrency is controlled by `ENRICHMENT_CONCURRENCY` (default: 3)
- [ ] Run in background with `nohup` and monitor via `tail -f logs/`

---

## Development

```bash
# Lint
uv run ruff check .

# Format
uv run ruff format .

# Type check
uv run mypy --strict src/

# Tests
uv run pytest --cov

# Check dependency security
uv run pip-audit
```

---

## Security notes

- Never commit `.env` — it is in `.gitignore`
- Use Supabase `service_role` key for write access; never expose it client-side
- Website scraper blocks requests to private/internal IP ranges (SSRF protection)
- All external HTTP calls use explicit timeouts
- YAML sector configs are loaded with `yaml.safe_load` (no code execution)
