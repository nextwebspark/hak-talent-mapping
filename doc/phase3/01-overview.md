# Phase 3: Overview & Goals

> HAK Platform — Company Enrichment, Scoring & Vector Search · April 2026

---

## Executive Summary

Phase 3 transforms raw company data (scraped from Zawya in Phases 1–2) into **searchable, scored intelligence**. For each company in Supabase, we:

1. **Enrich** — gather deep signals via web search APIs + targeted website scraping
2. **Extract** — use an LLM to produce a rich structured profile from raw data
3. **Store** — persist profiles in Supabase `company_details` table
4. **Score** — compute **5 scoring dimensions** (0–10 each) with evidence, confidence bands, and source provenance → `company_scores` table
5. **Embed** — store vector embeddings in Pinecone for semantic search against user briefs
6. **Enable** — brief-adjusted reweighting at query time (no re-embedding needed)

The pipeline is **fully resumable** (crash-safe), **LLM-agnostic** (Claude or OpenAI), **multi-sector** (all 30 Zawya sectors), and **country-portable** — scoring sources adapt per country via config, no UAE hardcoding.

---

## What Changed from the Previous Plan

| Aspect | Old Plan | New Plan |
|--------|----------|----------|
| Tables | 1 table (`company_enrichments`) | 2 tables: `company_details` (profile) + `company_scores` (scoring) |
| Pipeline stages | 6 (LLM extracts per-dimension signals) | 7 (LLM extracts full profile; scoring is separate) |
| LLM calls | 4 per company (one per dimension) | 1-2 per company (single profile extraction) |
| Sector scope | UAE Retailers only | Multi-sector UAE (all 30 sectors) |
| Sector-specific data | Fixed columns | Core columns + `sector_metadata` JSONB |
| Scoring config | Hardcoded weights | YAML config files per sector, versioned + auditable |
| Re-scoring | Requires re-enrichment | Decoupled — re-score from profile without re-enriching |
| Basic search | Only works for scored companies | Works for all profiled companies, even without scoring config |
| **Dimensions** | **4 (Talent Export History deferred to Phase 4)** | **5 (cold-start handling built in from day 1)** |
| **Country scope** | **UAE hardcoded in search queries** | **Country-portable — source configs resolve per company's country** |
| **Confidence model** | **Numeric 0–1** | **Structured bands (tight/medium/wide) tied to source quality** |
| **Sub-sector gating** | **Not supported** | **Optional per-sector config (e.g., Academic K-12 vs HE)** |
| **Brief reweighting** | **3 generic archetypes hardcoded** | **Sector-specific role archetype tables defined in YAML config** |
| **Score DB columns** | **Named columns per dimension** | **`dimension_scores` JSONB — extensible without migration** |

---

## Current State (Phases 1–2)

```
Phase 1 (Listing Scraper)          Phase 2 (Detail Scraper)
─────────────────────────          ─────────────────────────
httpx + BeautifulSoup              Playwright (headless Chromium)
Zawya listing pages                Zawya detail pages
28 countries × 30 sectors          Client-side rendered content
~6,800+ UAE Retailers scraped      innerText line-by-line parsing

Extracted:                         Extracted (SPARSE — often empty):
  company_id                         description
  name, slug                         website
  sector, country                    founded_year
  company_type                       address, phone, email
  profile_url                        employees_count
```

### What's Missing

- No rich company profiles (Phase 2 data is very sparse/inconsistent)
- No scoring or ranking of companies
- No semantic search capability
- No evidence or rationale for why a company is relevant
- No way to match companies against a hiring brief
- Only UAE Retailers scraped — 29 other sectors untouched

---

## Phase 3 Goals

| Goal | Description |
|------|-------------|
| **Rich profiles** | 20+ structured fields per company from web search + website scraping + LLM extraction |
| **Multi-sector** | Scrape and enrich all 30 UAE sectors, not just Retailers |
| **5-dimension scoring** | Score each company on Organisational Scale, Brand Prominence, Leadership Depth, Talent Export History (with cold-start handling), and Sector Fit Confidence |
| **Country-portable** | Per-country source configs with Primary/Secondary/Fallback hierarchies — scoring works for any country without code changes |
| **Sector-specific configs** | YAML scoring configs per sector — different weights, signals, formulas, and brief reweighting tables |
| **Sub-sector gating** | Optional pre-scoring gate for sectors with incompatible talent pools (e.g., K-12 vs Higher Education vs Vocational) |
| **Structured confidence** | Every score carries a confidence band (tight ±10% / medium ±20% / wide ±35%) reflecting data source quality |
| **Evidence trail** | Every score has sources, source level (primary/secondary/fallback), and a one-line rationale |
| **Vector search** | Embed rich company profiles in Pinecone for semantic similarity against user briefs |
| **Resumability** | Pipeline can crash and resume from the last completed stage per company |
| **LLM-agnostic** | Swap between Claude and OpenAI via config, no code changes |
| **Decoupled scoring** | Re-score with new weights without re-enriching |
| **Brief-adjusted ranking** | At query time, reweight scores based on sector-specific role archetypes (defined in YAML, not hardcoded) |

---

## Related Documents

| Document | Content |
|----------|---------|
| [02-architecture.md](02-architecture.md) | System architecture, pipeline stages, concurrency model, sub-sector gating flow |
| [03-database-schema.md](03-database-schema.md) | `company_details` + `company_scores` tables, JSONB dimension scores schema |
| [04-scoring-model.md](04-scoring-model.md) | 5 dimensions, universal framework, country-portable source configs, sector YAML schema, confidence bands |
| [05-vector-search.md](05-vector-search.md) | Pinecone schema, embedding text, metadata, query patterns |
| [06-implementation.md](06-implementation.md) | File structure, data models, config, CLI, dependencies, implementation order |
| [phase3-architecture.drawio](../phase3-architecture.drawio) | Visual architecture diagrams (5 pages) |
| [../Retailers.md](../Retailers.md) | Reference scoring model for the Retail sector (country-portable design) |
| [../Academic_Educational_Services.md](../Academic_Educational_Services.md) | Reference scoring model for Academic & Educational Services (sub-sector gating, regulatory ratings) |
| [../issue-country-specific.md](../issue-country-specific.md) | Country-portable design rationale and source config tables |
