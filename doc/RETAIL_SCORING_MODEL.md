# Retail Sector Scoring Model — Claude Code Implementation Brief

> **Purpose:** Implement the Strategic Layer company scoring model for the Retail sector into the HAK talent mapping platform. This document is the single source of truth. Follow the sequence strictly — schema first, then backend, then frontend. Do not proceed to the next part until the current part compiles and runs without errors.

---

## Stack Context

- **Frontend:** React 19, TypeScript, Vite, Tailwind CSS, shadcn/Radix UI, Wouter, TanStack Query, Zustand, Framer Motion
- **Backend:** Node.js/Express, TypeScript via tsx, PostgreSQL, Drizzle ORM
- **AI:** Anthropic SDK (claude-sonnet-4-6 for scoring), Serper for web search
- **Shared types:** `shared/schema.ts`
- **Platform:** Replit

---

## Architectural Principles — Read Before Writing Any Code

These are non-negotiable constraints that shape every implementation decision.

1. **Strategic Layer is role-agnostic.** The scoring model ranks companies. Role-specific filters (seniority, function, skills) belong in the Execution Layer only. Do not conflate them.

2. **Country-agnostic dimensions, country-configurable sources.** The six scoring dimensions never change. What changes per country is the source registry — a lookup table, not logic. New countries are added by inserting config rows, not modifying scoring code.

3. **Web-first discovery, Claude validates.** Claude does not generate the company list. Serper finds companies via web search. Claude scores and validates what Serper returns.

4. **Enrichment is decoupled from search.** The scoring pipeline runs on discovery data. A separate "Enrich" trigger fetches deeper data. Do not mix them.

5. **Brief-adjusted reweighting is a multiplier applied at query time.** Base dimension weights are fixed in config. When a brief (role archetype) is present, weights are overridden from the brief-weight table — no schema changes required.

6. **Confidence bands are first-class outputs.** Every dimension score carries a confidence band (tight/medium/wide) reflecting which fallback level provided the data. Surface this in the UI.

---

## Part 1 — Schema (`shared/schema.ts`)

Add the following. **Do not remove existing tables or columns.**

### 1.1 New enum types

```typescript
export const sectorFitRelevanceType = pgEnum('sector_fit_relevance_type', [
  'direct', 'adjacent', 'inferred'
]);

export const ownershipType = pgEnum('ownership_type', [
  'family_owned', 'pe_backed', 'listed', 'sovereign_linked', 'unknown'
]);

export const confidenceBand = pgEnum('confidence_band', [
  'tight', 'medium', 'wide'
]);

export const retailSubSector = pgEnum('retail_sub_sector', [
  // Direct
  'fashion', 'grocery_fmcg', 'electronics', 'luxury', 'fb_retail',
  'multi_format', 'ecommerce',
  // Adjacent
  'wholesale_distribution', 'franchise_operator', 'retail_real_estate',
  // Inferred
  'holding_with_retail_sub', 'hospitality_with_retail'
]);

export const roleArchetype = pgEnum('role_archetype', [
  'cco', 'coo', 'cfo', 'md_ceo', 'buying_director', 'supply_chain_director', 'base'
]);
```

### 1.2 New table: `scoringDimensionResults`

This stores per-dimension scores for every scored company, allowing full score card rendering without re-scoring.

```typescript
export const scoringDimensionResults = pgTable('scoring_dimension_results', {
  id: serial('id').primaryKey(),
  companyId: integer('company_id').notNull(), // FK to your existing company/result table
  searchSessionId: integer('search_session_id').notNull(),
  createdAt: timestamp('created_at').defaultNow(),

  // D1 — Organisational Scale
  d1Score: numeric('d1_score', { precision: 4, scale: 2 }),
  d1Headcount: text('d1_headcount'),
  d1StoreCount: text('d1_store_count'),
  d1SourceLevel: text('d1_source_level'), // 'primary' | 'secondary' | 'fallback'
  d1ConfidenceBand: confidenceBand('d1_confidence_band'),
  d1Evidence: text('d1_evidence'),

  // D2 — Brand & Market Prominence
  d2Score: numeric('d2_score', { precision: 4, scale: 2 }),
  d2PressCount: integer('d2_press_count'),
  d2AwardCount: integer('d2_award_count'),
  d2SourceLevel: text('d2_source_level'),
  d2ConfidenceBand: confidenceBand('d2_confidence_band'),
  d2Evidence: text('d2_evidence'),

  // D3 — Leadership Depth
  d3Score: numeric('d3_score', { precision: 4, scale: 2 }),
  d3NamedCsuite: integer('d3_named_csuite'),
  d3NamedDirectors: integer('d3_named_directors'),
  d3FunctionalBreadth: boolean('d3_functional_breadth'),
  d3SeniorLeadershipRating: numeric('d3_senior_leadership_rating', { precision: 3, scale: 2 }),
  d3CeoApproval: integer('d3_ceo_approval'), // percentage
  d3SourceLevel: text('d3_source_level'),
  d3ConfidenceBand: confidenceBand('d3_confidence_band'),
  d3Evidence: text('d3_evidence'),

  // D4 — Talent Export History
  d4Score: numeric('d4_score', { precision: 4, scale: 2 }),
  d4TrackedAlumni: integer('d4_tracked_alumni'),
  d4PressExportMentions: integer('d4_press_export_mentions'),
  d4IsEnriching: boolean('d4_is_enriching').default(true), // true at launch
  d4SourceLevel: text('d4_source_level'),
  d4ConfidenceBand: confidenceBand('d4_confidence_band'),
  d4Evidence: text('d4_evidence'),

  // D5 — Sector Fit Confidence
  d5Score: numeric('d5_score', { precision: 4, scale: 2 }),
  d5RelevanceType: sectorFitRelevanceType('d5_relevance_type'),
  d5SubSector: retailSubSector('d5_sub_sector'),
  d5OwnershipType: ownershipType('d5_ownership_type'),
  d5ConfirmationSource: text('d5_confirmation_source'),
  d5ConfidenceBand: confidenceBand('d5_confidence_band'),
  d5Evidence: text('d5_evidence'),

  // D6 — Executive Talent Momentum (NEW)
  d6Score: numeric('d6_score', { precision: 4, scale: 2 }),
  d6OpenRoles: integer('d6_open_roles'), // VP+ open roles count
  d6RecentDepartures: integer('d6_recent_departures'), // C-suite/VP departures last 18m
  d6MaActivity: boolean('d6_ma_activity'), // M&A or restructure last 24m
  d6MaRecency: text('d6_ma_recency'), // 'last_12m' | '12_24m' | null
  d6SourceLevel: text('d6_source_level'),
  d6ConfidenceBand: confidenceBand('d6_confidence_band'),
  d6Evidence: text('d6_evidence'),

  // Composite scores
  baseScore: numeric('base_score', { precision: 5, scale: 2 }),       // weighted 0–100
  briefAdjustedScore: numeric('brief_adjusted_score', { precision: 5, scale: 2 }),
  appliedArchetype: roleArchetype('applied_archetype').default('base'),
  overallConfidenceBand: confidenceBand('overall_confidence_band'),
});
```

### 1.3 New table: `sourceConfigRegistry`

The lookup table that makes scoring portable across countries and sectors. **This is the core portability mechanism — logic never changes, only config rows.**

```typescript
export const sourceConfigRegistry = pgTable('source_config_registry', {
  id: serial('id').primaryKey(),
  country: text('country').notNull(),       // 'UAE' | 'Saudi Arabia' | 'Qatar' | etc.
  sector: text('sector').notNull(),          // 'retail' | 'education' | etc.
  dimension: text('dimension').notNull(),    // 'd1' | 'd2' | 'd3' | 'd4' | 'd5' | 'd6'
  sourceLevel: text('source_level').notNull(), // 'primary' | 'secondary' | 'fallback'
  sourceName: text('source_name').notNull(),
  sourceType: text('source_type').notNull(), // 'api' | 'web_search' | 'platform_db' | 'manual'
  searchTemplate: text('search_template'),   // Serper query template, use {company} and {country} tokens
  confidenceBandAtLevel: confidenceBand('confidence_band_at_level').notNull(),
  isActive: boolean('is_active').default(true),
  notes: text('notes'),
});
```

### 1.4 Add columns to existing company results table

Identify your current company/results table and add these columns if not already present:

```typescript
// Add to existing table:
sectorFitRelevance: sectorFitRelevanceType('sector_fit_relevance'),
subSector: retailSubSector('sub_sector'),
ownershipType: ownershipType('ownership_type'),
baseScore: numeric('base_score', { precision: 5, scale: 2 }),
briefAdjustedScore: numeric('brief_adjusted_score', { precision: 5, scale: 2 }),
scoringSessionId: integer('scoring_session_id'), // FK to scoringDimensionResults
```

### 1.5 Run migration

```bash
npx drizzle-kit generate
npx drizzle-kit migrate
```

Then seed the `sourceConfigRegistry` table using the seed script in Part 2.4.

---

## Part 2 — Backend

### 2.1 File structure

Create the following new files. Do not modify existing search pipeline files until Part 2 is complete.

```
server/
  scoring/
    retail/
      index.ts              ← orchestrator
      dimensions.ts         ← all 6 dimension scoring functions
      weights.ts            ← base weights + brief-adjusted weight table
      sourceResolver.ts     ← country config lookup + fallback chain
      queries.ts            ← Serper query builders per dimension
    engine.ts               ← shared scoring utilities (confidence bands, score capping)
  seeds/
    sourceConfigRetail.ts   ← seed data for source_config_registry
```

### 2.2 `weights.ts` — Weight definitions

```typescript
export type RoleArchetype = 'base' | 'cco' | 'coo' | 'cfo' | 'md_ceo' | 'buying_director' | 'supply_chain_director';

export interface DimensionWeights {
  d1: number; d2: number; d3: number; d4: number; d5: number; d6: number;
}

// D4 launches at 10% reduced weight, tagged "enriching". Restore to 15% post-launch.
// D6 is new. Its 10% is drawn proportionally from D1 and D2.
export const WEIGHT_TABLE: Record<RoleArchetype, DimensionWeights> = {
  base:                  { d1: 0.22, d2: 0.18, d3: 0.25, d4: 0.10, d5: 0.15, d6: 0.10 },
  cco:                   { d1: 0.18, d2: 0.27, d3: 0.25, d4: 0.08, d5: 0.12, d6: 0.10 },
  coo:                   { d1: 0.27, d2: 0.08, d3: 0.25, d4: 0.18, d5: 0.12, d6: 0.10 },
  cfo:                   { d1: 0.22, d2: 0.08, d3: 0.25, d4: 0.23, d5: 0.12, d6: 0.10 },
  md_ceo:                { d1: 0.27, d2: 0.18, d3: 0.25, d4: 0.13, d5: 0.10, d6: 0.07 },
  buying_director:       { d1: 0.13, d2: 0.23, d3: 0.25, d4: 0.18, d5: 0.11, d6: 0.10 },
  supply_chain_director: { d1: 0.27, d2: 0.04, d3: 0.25, d4: 0.22, d5: 0.12, d6: 0.10 },
};

// Validates weights sum to 1.0 (±0.01 rounding tolerance)
export function validateWeights(w: DimensionWeights): boolean {
  const sum = Object.values(w).reduce((a, b) => a + b, 0);
  return Math.abs(sum - 1.0) < 0.01;
}

export function getWeights(archetype: RoleArchetype): DimensionWeights {
  return WEIGHT_TABLE[archetype] ?? WEIGHT_TABLE['base'];
}
```

### 2.3 `sourceResolver.ts` — Country-configurable source lookup

```typescript
import { db } from '../db'; // your drizzle db instance
import { sourceConfigRegistry } from '../../shared/schema';
import { eq, and } from 'drizzle-orm';

export type SourceLevel = 'primary' | 'secondary' | 'fallback';

export interface ResolvedSource {
  sourceName: string;
  sourceType: string;
  searchTemplate: string | null;
  confidenceBandAtLevel: 'tight' | 'medium' | 'wide';
  level: SourceLevel;
}

// Returns sources in priority order for a given country + sector + dimension.
// Falls back down the chain automatically — never returns empty.
export async function resolveSources(
  country: string,
  sector: string,
  dimension: string
): Promise<ResolvedSource[]> {
  const rows = await db
    .select()
    .from(sourceConfigRegistry)
    .where(
      and(
        eq(sourceConfigRegistry.country, country),
        eq(sourceConfigRegistry.sector, sector),
        eq(sourceConfigRegistry.dimension, dimension),
        eq(sourceConfigRegistry.isActive, true)
      )
    )
    .orderBy(sourceConfigRegistry.sourceLevel); // primary → secondary → fallback

  // If no country-specific rows, fall back to global config
  if (rows.length === 0) {
    return resolveSources('global', sector, dimension);
  }

  return rows.map(r => ({
    sourceName: r.sourceName,
    sourceType: r.sourceType,
    searchTemplate: r.searchTemplate,
    confidenceBandAtLevel: r.confidenceBandAtLevel as 'tight' | 'medium' | 'wide',
    level: r.sourceLevel as SourceLevel,
  }));
}

// Build a Serper query from a template, substituting {company} and {country}
export function buildQuery(template: string, company: string, country: string): string {
  return template
    .replace(/\{company\}/g, company)
    .replace(/\{country\}/g, country);
}
```

### 2.4 `seeds/sourceConfigRetail.ts` — Source config seed data

Run this once after migration. This is the data that makes the model country-portable.

```typescript
import { db } from '../db';
import { sourceConfigRegistry } from '../../shared/schema';

const RETAIL_SOURCES = [
  // ── D1: Organisational Scale ──────────────────────────────────────────────
  // UAE
  { country: 'UAE', sector: 'retail', dimension: 'd1', sourceLevel: 'primary',
    sourceName: 'DED trade license + DIFC/ADGM registers', sourceType: 'web_search',
    searchTemplate: 'site:ded.ae OR site:difc.ae "{company}" employees',
    confidenceBandAtLevel: 'tight' },
  { country: 'UAE', sector: 'retail', dimension: 'd1', sourceLevel: 'secondary',
    sourceName: 'LinkedIn headcount + mall operator tenant lists', sourceType: 'web_search',
    searchTemplate: '"{company}" UAE retail employees headcount LinkedIn',
    confidenceBandAtLevel: 'medium' },
  { country: 'UAE', sector: 'retail', dimension: 'd1', sourceLevel: 'fallback',
    sourceName: 'Job posting volume + press mentions', sourceType: 'web_search',
    searchTemplate: '"{company}" UAE store count locations press',
    confidenceBandAtLevel: 'wide' },

  // Saudi Arabia
  { country: 'Saudi Arabia', sector: 'retail', dimension: 'd1', sourceLevel: 'primary',
    sourceName: 'MISA commercial register + CR', sourceType: 'web_search',
    searchTemplate: 'site:misa.gov.sa OR site:cr.gov.sa "{company}"',
    confidenceBandAtLevel: 'tight' },
  { country: 'Saudi Arabia', sector: 'retail', dimension: 'd1', sourceLevel: 'secondary',
    sourceName: 'Tadawul filings + LinkedIn', sourceType: 'web_search',
    searchTemplate: '"{company}" Saudi Arabia employees Tadawul annual report',
    confidenceBandAtLevel: 'medium' },
  { country: 'Saudi Arabia', sector: 'retail', dimension: 'd1', sourceLevel: 'fallback',
    sourceName: 'Press mentions + brand website store locator', sourceType: 'web_search',
    searchTemplate: '"{company}" Saudi Arabia store locations branches',
    confidenceBandAtLevel: 'wide' },

  // Global fallback (used when no country-specific row exists)
  { country: 'global', sector: 'retail', dimension: 'd1', sourceLevel: 'primary',
    sourceName: 'LinkedIn company page headcount', sourceType: 'web_search',
    searchTemplate: '"{company}" employees headcount LinkedIn site:linkedin.com',
    confidenceBandAtLevel: 'medium' },
  { country: 'global', sector: 'retail', dimension: 'd1', sourceLevel: 'fallback',
    sourceName: 'Brand website + press scale mentions', sourceType: 'web_search',
    searchTemplate: '"{company}" {country} employees stores locations',
    confidenceBandAtLevel: 'wide' },

  // ── D2: Brand & Market Prominence ─────────────────────────────────────────
  { country: 'UAE', sector: 'retail', dimension: 'd2', sourceLevel: 'primary',
    sourceName: 'UAE tier-1 business press (last 12 months)', sourceType: 'web_search',
    searchTemplate: '"{company}" retail site:gulfnews.com OR site:thenationalnews.com OR site:arabianbusiness.com after:2024-01-01',
    confidenceBandAtLevel: 'tight' },
  { country: 'UAE', sector: 'retail', dimension: 'd2', sourceLevel: 'secondary',
    sourceName: 'Retail ME + MEED trade press', sourceType: 'web_search',
    searchTemplate: '"{company}" site:retailme.com OR site:meed.com retail',
    confidenceBandAtLevel: 'medium' },
  { country: 'UAE', sector: 'retail', dimension: 'd2', sourceLevel: 'fallback',
    sourceName: 'Awards + general web search', sourceType: 'web_search',
    searchTemplate: '"{company}" UAE retail award recognition 2024 2025',
    confidenceBandAtLevel: 'wide' },
  { country: 'Saudi Arabia', sector: 'retail', dimension: 'd2', sourceLevel: 'primary',
    sourceName: 'Saudi tier-1 business press', sourceType: 'web_search',
    searchTemplate: '"{company}" retail site:arabnews.com OR site:argaam.com OR site:aleqt.com after:2024-01-01',
    confidenceBandAtLevel: 'tight' },
  { country: 'Saudi Arabia', sector: 'retail', dimension: 'd2', sourceLevel: 'secondary',
    sourceName: 'Saudi Retail Forum + MEED', sourceType: 'web_search',
    searchTemplate: '"{company}" site:meed.com Saudi retail',
    confidenceBandAtLevel: 'medium' },
  { country: 'global', sector: 'retail', dimension: 'd2', sourceLevel: 'fallback',
    sourceName: 'Google News general search', sourceType: 'web_search',
    searchTemplate: '"{company}" retail {country} news 2024 2025',
    confidenceBandAtLevel: 'wide' },

  // ── D3: Leadership Depth ──────────────────────────────────────────────────
  { country: 'UAE', sector: 'retail', dimension: 'd3', sourceLevel: 'primary',
    sourceName: 'LinkedIn leadership search', sourceType: 'web_search',
    searchTemplate: '"{company}" UAE CEO CFO COO CMO "head of" director site:linkedin.com',
    confidenceBandAtLevel: 'tight' },
  { country: 'UAE', sector: 'retail', dimension: 'd3', sourceLevel: 'secondary',
    sourceName: 'Company website leadership page', sourceType: 'web_search',
    searchTemplate: '"{company}" UAE "leadership team" OR "executive team" OR "management team"',
    confidenceBandAtLevel: 'medium' },
  { country: 'UAE', sector: 'retail', dimension: 'd3', sourceLevel: 'fallback',
    sourceName: 'Press appointment announcements', sourceType: 'web_search',
    searchTemplate: '"appointed" "{company}" UAE CEO CFO COO director 2023 2024 2025',
    confidenceBandAtLevel: 'wide' },
  // Glassdoor / Ambition Box sub-signal (universal — same query everywhere)
  { country: 'global', sector: 'retail', dimension: 'd3', sourceLevel: 'secondary',
    sourceName: 'Glassdoor senior leadership sub-rating + CEO approval', sourceType: 'web_search',
    searchTemplate: '"{company}" glassdoor OR ambitionbox "senior management" rating review',
    confidenceBandAtLevel: 'medium' },
  { country: 'global', sector: 'retail', dimension: 'd3', sourceLevel: 'fallback',
    sourceName: 'Web search leadership team', sourceType: 'web_search',
    searchTemplate: '"{company}" {country} "leadership team" executives directors',
    confidenceBandAtLevel: 'wide' },

  // ── D4: Talent Export History ─────────────────────────────────────────────
  { country: 'global', sector: 'retail', dimension: 'd4', sourceLevel: 'primary',
    sourceName: 'Platform accumulated candidate database', sourceType: 'platform_db',
    searchTemplate: null, // queried directly from DB, no web search needed
    confidenceBandAtLevel: 'tight' },
  { country: 'global', sector: 'retail', dimension: 'd4', sourceLevel: 'secondary',
    sourceName: 'LinkedIn alumni search', sourceType: 'web_search',
    searchTemplate: '"formerly" OR "ex-" OR "previously at" "{company}" retail director VP CEO site:linkedin.com',
    confidenceBandAtLevel: 'medium' },
  { country: 'UAE', sector: 'retail', dimension: 'd4', sourceLevel: 'fallback',
    sourceName: 'Press appointment mentions', sourceType: 'web_search',
    searchTemplate: '"former {company}" OR "previously at {company}" UAE retail executive appointed',
    confidenceBandAtLevel: 'wide' },
  { country: 'Saudi Arabia', sector: 'retail', dimension: 'd4', sourceLevel: 'fallback',
    sourceName: 'Argaam + Arab News appointments', sourceType: 'web_search',
    searchTemplate: '"former {company}" OR "previously at {company}" Saudi retail executive site:argaam.com OR site:arabnews.com',
    confidenceBandAtLevel: 'wide' },
  { country: 'global', sector: 'retail', dimension: 'd4', sourceLevel: 'fallback',
    sourceName: 'General press alumni search', sourceType: 'web_search',
    searchTemplate: '"formerly" "{company}" {country} retail executive director VP 2023 2024',
    confidenceBandAtLevel: 'wide' },

  // ── D5: Sector Fit Confidence ─────────────────────────────────────────────
  { country: 'UAE', sector: 'retail', dimension: 'd5', sourceLevel: 'primary',
    sourceName: 'DED trade license activity code', sourceType: 'web_search',
    searchTemplate: 'site:ded.ae "{company}" retail trading license',
    confidenceBandAtLevel: 'tight' },
  { country: 'UAE', sector: 'retail', dimension: 'd5', sourceLevel: 'secondary',
    sourceName: 'DIFC/ADGM sector classification', sourceType: 'web_search',
    searchTemplate: '"{company}" site:difc.ae OR site:adgm.com retail sector',
    confidenceBandAtLevel: 'medium' },
  { country: 'Saudi Arabia', sector: 'retail', dimension: 'd5', sourceLevel: 'primary',
    sourceName: 'CR activity code + MISA classification', sourceType: 'web_search',
    searchTemplate: '"{company}" site:cr.gov.sa OR site:misa.gov.sa retail',
    confidenceBandAtLevel: 'tight' },
  { country: 'Saudi Arabia', sector: 'retail', dimension: 'd5', sourceLevel: 'secondary',
    sourceName: 'Tadawul sector classification', sourceType: 'web_search',
    searchTemplate: '"{company}" Tadawul sector retail consumer',
    confidenceBandAtLevel: 'medium' },
  { country: 'global', sector: 'retail', dimension: 'd5', sourceLevel: 'fallback',
    sourceName: 'Company website + press description', sourceType: 'web_search',
    searchTemplate: '"{company}" {country} retail stores "primary business" OR "we are a retailer"',
    confidenceBandAtLevel: 'wide' },

  // ── D6: Executive Talent Momentum ─────────────────────────────────────────
  { country: 'global', sector: 'retail', dimension: 'd6', sourceLevel: 'primary',
    sourceName: 'LinkedIn Jobs VP+ open roles', sourceType: 'web_search',
    searchTemplate: '"{company}" {country} "director" OR "VP" OR "vice president" OR "head of" jobs site:linkedin.com/jobs',
    confidenceBandAtLevel: 'tight' },
  { country: 'UAE', sector: 'retail', dimension: 'd6', sourceLevel: 'secondary',
    sourceName: 'UAE press leadership departures + M&A', sourceType: 'web_search',
    searchTemplate: '"{company}" UAE "steps down" OR "leaves" OR "appointed" OR "merger" OR "acquisition" OR "restructure" 2024 2025 site:gulfnews.com OR site:arabianbusiness.com OR site:thenationalnews.com',
    confidenceBandAtLevel: 'medium' },
  { country: 'Saudi Arabia', sector: 'retail', dimension: 'd6', sourceLevel: 'secondary',
    sourceName: 'Saudi press leadership departures + M&A', sourceType: 'web_search',
    searchTemplate: '"{company}" Saudi "steps down" OR "appointed" OR "acquisition" OR "merger" 2024 2025 site:arabnews.com OR site:argaam.com',
    confidenceBandAtLevel: 'medium' },
  { country: 'global', sector: 'retail', dimension: 'd6', sourceLevel: 'fallback',
    sourceName: 'General web M&A + departures search', sourceType: 'web_search',
    searchTemplate: '"{company}" {country} retail "acquisition" OR "merger" OR "restructure" OR "executive departure" 2024 2025',
    confidenceBandAtLevel: 'wide' },
];

export async function seedSourceConfigRetail() {
  console.log('Seeding retail source config...');
  await db.insert(sourceConfigRegistry).values(
    RETAIL_SOURCES.map(s => ({
      ...s,
      isActive: true,
    }))
  ).onConflictDoNothing(); // safe to re-run
  console.log(`Seeded ${RETAIL_SOURCES.length} retail source config rows.`);
}
```

### 2.5 `dimensions.ts` — Six dimension scoring functions

Each function receives: company name, country, pre-fetched Serper results, and resolved sources. Returns a typed score object.

```typescript
import Anthropic from '@anthropic-ai/sdk';
import { ResolvedSource } from './sourceResolver';

const anthropic = new Anthropic();

// ─── Shared types ────────────────────────────────────────────────────────────

export interface DimensionScore {
  score: number;          // 0–10
  confidenceBand: 'tight' | 'medium' | 'wide';
  sourceLevel: 'primary' | 'secondary' | 'fallback';
  evidence: string;       // one-sentence rationale surfaced in UI
  rawData: Record<string, unknown>;
}

// ─── Scoring prompt helper ────────────────────────────────────────────────────

async function scoreWithClaude(
  systemPrompt: string,
  userContent: string
): Promise<{ score: number; evidence: string; rawData: Record<string, unknown> }> {
  const response = await anthropic.messages.create({
    model: 'claude-sonnet-4-6',
    max_tokens: 500,
    system: systemPrompt,
    messages: [{ role: 'user', content: userContent }],
  });

  const text = response.content[0].type === 'text' ? response.content[0].text : '';

  // Claude must return JSON only. Strip markdown fences if present.
  const clean = text.replace(/```json|```/g, '').trim();
  try {
    return JSON.parse(clean);
  } catch {
    return { score: 0, evidence: 'Scoring parse error', rawData: { raw: text } };
  }
}

// ─── D1: Organisational Scale ─────────────────────────────────────────────────

export async function scoreD1(
  company: string,
  country: string,
  serperResults: string,
  sources: ResolvedSource[]
): Promise<DimensionScore> {
  const usedLevel = sources[0]?.level ?? 'fallback';
  const bandMap: Record<string, 'tight' | 'medium' | 'wide'> = {
    primary: 'tight', secondary: 'medium', fallback: 'wide'
  };

  const result = await scoreWithClaude(
    `You are a company analyst scoring retail companies for executive talent mapping.
     You must return ONLY valid JSON with this exact shape:
     { "score": number (0-10), "evidence": string (one sentence), "rawData": { "headcount": string, "storeCount": string } }
     
     Scoring logic (logarithmic scale):
     - < 100 employees: 1-2
     - 100-500: 3-4
     - 500-2000: 5-6
     - 2000-10000: 7-8
     - 10000+: 9-10
     Store count adds up to 1.5 bonus points (capped at 10).
     If data is unavailable, score 0 and say so in evidence.`,
    `Company: ${company}\nCountry: ${country}\n\nSearch results:\n${serperResults}`
  );

  return {
    ...result,
    confidenceBand: bandMap[usedLevel] ?? 'wide',
    sourceLevel: usedLevel as 'primary' | 'secondary' | 'fallback',
  };
}

// ─── D2: Brand & Market Prominence ───────────────────────────────────────────

export async function scoreD2(
  company: string,
  country: string,
  serperResults: string,
  sources: ResolvedSource[]
): Promise<DimensionScore> {
  const usedLevel = sources[0]?.level ?? 'fallback';
  const bandMap = { primary: 'tight' as const, secondary: 'medium' as const, fallback: 'wide' as const };

  const result = await scoreWithClaude(
    `You are scoring a retail company's brand prominence for executive talent mapping.
     Return ONLY valid JSON:
     { "score": number (0-10), "evidence": string (one sentence), "rawData": { "pressCount12m": number, "awardCount": number, "categoryLeadership": boolean } }
     
     Scoring: Tier-1 press mention <3 months = 1.5pts (max 3). Tier-1 press 3-12m = 1.0pts (max 2).
     Trade press = 0.5pts (max 1.5). Each award = 1.0pts (max 2). Category leadership signal = 1.5pts (once).
     Total capped at 10. Recency matters — recent coverage outweighs historical.`,
    `Company: ${company}\nCountry: ${country}\n\nSearch results:\n${serperResults}`
  );

  return { ...result, confidenceBand: bandMap[usedLevel], sourceLevel: usedLevel as any };
}

// ─── D3: Leadership Depth ─────────────────────────────────────────────────────

export async function scoreD3(
  company: string,
  country: string,
  serperResults: string,
  sources: ResolvedSource[]
): Promise<DimensionScore> {
  const usedLevel = sources[0]?.level ?? 'fallback';
  const bandMap = { primary: 'tight' as const, secondary: 'medium' as const, fallback: 'wide' as const };

  const result = await scoreWithClaude(
    `You are scoring a retail company's leadership depth for executive talent mapping.
     Return ONLY valid JSON:
     { "score": number (0-10), "evidence": string (one sentence), "rawData": { "namedCsuite": number, "namedDirectors": number, "functionalBreadth": boolean, "seniorLeadershipRating": number | null, "ceoApproval": number | null } }
     
     Scoring:
     Named CEO/MD: 2.0pts. Each additional C-suite (CFO/COO/CCO): 1.0pt each (max 3.0).
     Director/Head level: 0.5pts each (max 2.0). 3+ functions covered: 1.0pt bonus.
     Senior leadership rating ≥ 4.0 (Glassdoor): 0.5pt bonus. CEO approval ≥ 70%: 0.5pt bonus.
     Cap at 10. Named headcount and functional breadth are the primary signals.`,
    `Company: ${company}\nCountry: ${country}\n\nSearch results:\n${serperResults}`
  );

  return { ...result, confidenceBand: bandMap[usedLevel], sourceLevel: usedLevel as any };
}

// ─── D4: Talent Export History ────────────────────────────────────────────────

export async function scoreD4(
  company: string,
  country: string,
  serperResults: string,
  sources: ResolvedSource[],
  platformAlumniCount: number = 0  // passed from platform DB query
): Promise<DimensionScore> {
  const usedLevel = platformAlumniCount > 0 ? 'primary' : (sources[0]?.level ?? 'fallback');
  const bandMap = { primary: 'tight' as const, secondary: 'medium' as const, fallback: 'wide' as const };

  // Platform DB alumni count takes precedence over web search
  if (platformAlumniCount > 0) {
    let score = 0;
    if (platformAlumniCount >= 10) score = 10;
    else if (platformAlumniCount >= 6) score = 8.5;
    else if (platformAlumniCount >= 3) score = 6;
    else score = 3.5;

    return {
      score,
      confidenceBand: 'tight',
      sourceLevel: 'primary',
      evidence: `${platformAlumniCount} tracked alumni in VP+ roles at other major retailers (platform database).`,
      rawData: { platformAlumniCount, source: 'platform_db' },
    };
  }

  const result = await scoreWithClaude(
    `You are scoring a retail company's talent export history for executive talent mapping.
     Return ONLY valid JSON:
     { "score": number (0-10), "evidence": string (one sentence), "rawData": { "pressAlumniCount": number, "notableDestinations": string[] } }
     
     Scoring from press signals only (platform data unavailable):
     1-2 press-confirmed alumni in VP+ roles: 3-4pts. 3-5: 5-7pts. 6-10: 8-9pts. 10+: 10pts.
     Max 5pts from press alone (web search is less reliable than platform DB).
     No signal: 0, flag clearly.`,
    `Company: ${company}\nCountry: ${country}\n\nSearch results:\n${serperResults}`
  );

  return { ...result, confidenceBand: bandMap[usedLevel], sourceLevel: usedLevel as any };
}

// ─── D5: Sector Fit Confidence ────────────────────────────────────────────────

export async function scoreD5(
  company: string,
  country: string,
  serperResults: string,
  sources: ResolvedSource[]
): Promise<DimensionScore & {
  relevanceType: 'direct' | 'adjacent' | 'inferred';
  subSector: string;
  ownershipType: 'family_owned' | 'pe_backed' | 'listed' | 'sovereign_linked' | 'unknown';
  confirmationSource: string;
}> {
  const usedLevel = sources[0]?.level ?? 'fallback';
  const bandMap = { primary: 'tight' as const, secondary: 'medium' as const, fallback: 'wide' as const };

  const result = await scoreWithClaude(
    `You are a sector classification expert for executive talent mapping.
     Return ONLY valid JSON:
     {
       "score": number (0-10),
       "evidence": string (one sentence),
       "relevanceType": "direct" | "adjacent" | "inferred",
       "subSector": "fashion" | "grocery_fmcg" | "electronics" | "luxury" | "fb_retail" | "multi_format" | "ecommerce" | "wholesale_distribution" | "franchise_operator" | "retail_real_estate" | "holding_with_retail_sub" | "hospitality_with_retail",
       "ownershipType": "family_owned" | "pe_backed" | "listed" | "sovereign_linked" | "unknown",
       "confirmationSource": string (where you found the confirmation),
       "rawData": {}
     }
     
     Score by confirmation source:
     Regulatory activity code (primary): 9-10. Stock exchange classification: 7-8.
     Company website — primary business: 6-7. Press describes as retailer: 5-6.
     Inferred from holding group: 3-4. Inferred from brand/product only: 1-2.
     If not a retailer at all: 0, relevanceType = "inferred".`,
    `Company: ${company}\nCountry: ${country}\n\nSearch results:\n${serperResults}`
  );

  const parsed = result as any;
  return {
    score: parsed.score ?? 0,
    confidenceBand: bandMap[usedLevel],
    sourceLevel: usedLevel as any,
    evidence: parsed.evidence ?? '',
    rawData: parsed.rawData ?? {},
    relevanceType: parsed.relevanceType ?? 'inferred',
    subSector: parsed.subSector ?? 'multi_format',
    ownershipType: parsed.ownershipType ?? 'unknown',
    confirmationSource: parsed.confirmationSource ?? '',
  };
}

// ─── D6: Executive Talent Momentum ────────────────────────────────────────────

export async function scoreD6(
  company: string,
  country: string,
  serperResults: string,
  sources: ResolvedSource[]
): Promise<DimensionScore & { openRoles: number; recentDepartures: number; maActivity: boolean; maRecency: string | null }> {
  const usedLevel = sources[0]?.level ?? 'fallback';
  const bandMap = { primary: 'tight' as const, secondary: 'medium' as const, fallback: 'wide' as const };

  const result = await scoreWithClaude(
    `You are scoring a retail company's executive talent momentum — whether its talent pool is currently in motion.
     Return ONLY valid JSON:
     {
       "score": number (0-10),
       "evidence": string (one sentence),
       "openRoles": number (VP+ open roles detected),
       "recentDepartures": number (C-suite/VP departures last 18 months),
       "maActivity": boolean (M&A or restructure last 24 months),
       "maRecency": "last_12m" | "12_24m" | null,
       "rawData": {}
     }
     
     Scoring:
     M&A/restructure last 12 months: 3.0pts. M&A/restructure 12-24 months: 1.5pts.
     2+ VP-level open roles: 2.0pts. 1 VP-level open role: 1.0pt.
     3+ C-suite/VP departures (18m): 3.0pts. 1-2 departures: 1.5pts.
     Cap at 10. This is a recency signal — anything over 24 months does not score.`,
    `Company: ${company}\nCountry: ${country}\n\nSearch results:\n${serperResults}`
  );

  const parsed = result as any;
  return {
    score: parsed.score ?? 0,
    confidenceBand: bandMap[usedLevel],
    sourceLevel: usedLevel as any,
    evidence: parsed.evidence ?? '',
    rawData: parsed.rawData ?? {},
    openRoles: parsed.openRoles ?? 0,
    recentDepartures: parsed.recentDepartures ?? 0,
    maActivity: parsed.maActivity ?? false,
    maRecency: parsed.maRecency ?? null,
  };
}
```

### 2.6 `retail/index.ts` — Scoring orchestrator

```typescript
import Serper from 'serper'; // or your existing Serper client
import { resolveSources, buildQuery } from './sourceResolver';
import { getWeights, RoleArchetype } from './weights';
import { scoreD1, scoreD2, scoreD3, scoreD4, scoreD5, scoreD6 } from './dimensions';
import { db } from '../db';
import { scoringDimensionResults } from '../../shared/schema';

export interface ScoringInput {
  companyName: string;
  country: string;
  archetype?: RoleArchetype;
  searchSessionId: number;
  companyId: number;
  platformAlumniCount?: number; // from platform DB lookup before calling this
}

export interface ScoringOutput {
  companyId: number;
  baseScore: number;
  briefAdjustedScore: number;
  appliedArchetype: RoleArchetype;
  dimensions: {
    d1: ReturnType<typeof scoreD1> extends Promise<infer T> ? T : never;
    d2: any; d3: any; d4: any; d5: any; d6: any;
  };
}

export async function scoreRetailCompany(input: ScoringInput): Promise<ScoringOutput> {
  const { companyName, country, archetype = 'base', searchSessionId, companyId, platformAlumniCount = 0 } = input;
  const weights = getWeights(archetype);

  // Run all source resolutions and Serper queries in parallel where possible
  const [d1Sources, d2Sources, d3Sources, d4Sources, d5Sources, d6Sources] = await Promise.all([
    resolveSources(country, 'retail', 'd1'),
    resolveSources(country, 'retail', 'd2'),
    resolveSources(country, 'retail', 'd3'),
    resolveSources(country, 'retail', 'd4'),
    resolveSources(country, 'retail', 'd5'),
    resolveSources(country, 'retail', 'd6'),
  ]);

  // Build and run Serper queries for each dimension
  // Use the first non-platform source's search template
  const serperSearch = async (sources: any[], fallbackQuery: string): Promise<string> => {
    const webSource = sources.find(s => s.sourceType === 'web_search' && s.searchTemplate);
    if (!webSource) return '';
    const query = buildQuery(webSource.searchTemplate, companyName, country);
    try {
      // Replace with your actual Serper client call
      const results = await fetch(`https://google.serper.dev/search`, {
        method: 'POST',
        headers: { 'X-API-KEY': process.env.SERPER_API_KEY!, 'Content-Type': 'application/json' },
        body: JSON.stringify({ q: query, num: 5 })
      }).then(r => r.json());
      return JSON.stringify(results.organic?.slice(0, 5) ?? []);
    } catch {
      return '';
    }
  };

  // Fetch all search results (5-6 actual web calls — one per dimension with non-platform source)
  const [d1Results, d2Results, d3Results, d4Results, d5Results, d6Results] = await Promise.all([
    serperSearch(d1Sources, `${companyName} ${country} employees headcount`),
    serperSearch(d2Sources, `${companyName} ${country} retail news press`),
    serperSearch(d3Sources, `${companyName} ${country} leadership team executives`),
    platformAlumniCount > 0 ? Promise.resolve('') : serperSearch(d4Sources, `formerly ${companyName} retail executive`),
    serperSearch(d5Sources, `${companyName} ${country} retail business activity`),
    serperSearch(d6Sources, `${companyName} ${country} jobs departures acquisition restructure`),
  ]);

  // Score all dimensions in parallel
  const [d1, d2, d3, d4, d5, d6] = await Promise.all([
    scoreD1(companyName, country, d1Results, d1Sources),
    scoreD2(companyName, country, d2Results, d2Sources),
    scoreD3(companyName, country, d3Results, d3Sources),
    scoreD4(companyName, country, d4Results, d4Sources, platformAlumniCount),
    scoreD5(companyName, country, d5Results, d5Sources),
    scoreD6(companyName, country, d6Results, d6Sources),
  ]);

  // Compute weighted composite scores
  const baseScore = Math.round(
    (d1.score * weights.d1 +
     d2.score * weights.d2 +
     d3.score * weights.d3 +
     d4.score * weights.d4 +
     d5.score * weights.d5 +
     d6.score * weights.d6) * 10
  ); // 0–100

  // Brief-adjusted score uses the same raw dimension scores with archetype weights
  // Base score already uses archetype weights — they're the same when archetype != 'base'
  // For 'base', brief-adjusted = base. For specific archetypes, the weights already differ.
  const briefAdjustedScore = baseScore; // weights already applied above

  // Persist to DB
  await db.insert(scoringDimensionResults).values({
    companyId,
    searchSessionId,
    d1Score: String(d1.score), d1Headcount: String(d1.rawData.headcount ?? ''), d1StoreCount: String(d1.rawData.storeCount ?? ''),
    d1SourceLevel: d1.sourceLevel, d1ConfidenceBand: d1.confidenceBand, d1Evidence: d1.evidence,
    d2Score: String(d2.score), d2PressCount: Number(d2.rawData.pressCount12m ?? 0), d2AwardCount: Number(d2.rawData.awardCount ?? 0),
    d2SourceLevel: d2.sourceLevel, d2ConfidenceBand: d2.confidenceBand, d2Evidence: d2.evidence,
    d3Score: String(d3.score), d3NamedCsuite: Number(d3.rawData.namedCsuite ?? 0), d3NamedDirectors: Number(d3.rawData.namedDirectors ?? 0),
    d3FunctionalBreadth: Boolean(d3.rawData.functionalBreadth), d3SeniorLeadershipRating: d3.rawData.seniorLeadershipRating ? String(d3.rawData.seniorLeadershipRating) : null,
    d3CeoApproval: d3.rawData.ceoApproval ? Number(d3.rawData.ceoApproval) : null,
    d3SourceLevel: d3.sourceLevel, d3ConfidenceBand: d3.confidenceBand, d3Evidence: d3.evidence,
    d4Score: String(d4.score), d4TrackedAlumni: platformAlumniCount, d4PressExportMentions: Number(d4.rawData.pressAlumniCount ?? 0),
    d4IsEnriching: platformAlumniCount === 0,
    d4SourceLevel: d4.sourceLevel, d4ConfidenceBand: d4.confidenceBand, d4Evidence: d4.evidence,
    d5Score: String(d5.score), d5RelevanceType: (d5 as any).relevanceType, d5SubSector: (d5 as any).subSector,
    d5OwnershipType: (d5 as any).ownershipType, d5ConfirmationSource: (d5 as any).confirmationSource,
    d5ConfidenceBand: d5.confidenceBand, d5Evidence: d5.evidence,
    d6Score: String(d6.score), d6OpenRoles: (d6 as any).openRoles, d6RecentDepartures: (d6 as any).recentDepartures,
    d6MaActivity: (d6 as any).maActivity, d6MaRecency: (d6 as any).maRecency,
    d6SourceLevel: d6.sourceLevel, d6ConfidenceBand: d6.confidenceBand, d6Evidence: d6.evidence,
    baseScore: String(baseScore / 10), // stored 0-10 internally
    briefAdjustedScore: String(briefAdjustedScore / 10),
    appliedArchetype: archetype,
    overallConfidenceBand: [d1, d2, d3, d4, d5, d6].some(d => d.confidenceBand === 'wide') ? 'wide' :
                           [d1, d2, d3, d4, d5, d6].some(d => d.confidenceBand === 'medium') ? 'medium' : 'tight',
  });

  return { companyId, baseScore, briefAdjustedScore, appliedArchetype: archetype, dimensions: { d1, d2, d3, d4, d5, d6 } };
}
```

### 2.7 API route

Add a scoring endpoint to your existing Express router:

```typescript
// POST /api/search/score-companies
// Body: { companyIds: number[], country: string, archetype?: string, searchSessionId: number }
router.post('/search/score-companies', async (req, res) => {
  const { companyIds, country, archetype = 'base', searchSessionId } = req.body;

  // SSE streaming — client sees scores appear as each company is processed
  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');

  for (const companyId of companyIds) {
    try {
      // Look up company name from your existing table
      const company = await db.query.companies.findFirst({ where: eq(companies.id, companyId) });
      if (!company) continue;

      // Check platform DB for alumni count before scoring
      const alumniCount = await db.select({ count: count() })
        .from(candidates)
        .where(eq(candidates.formerCompany, company.name));

      const result = await scoreRetailCompany({
        companyName: company.name,
        country,
        archetype: archetype as RoleArchetype,
        searchSessionId,
        companyId,
        platformAlumniCount: Number(alumniCount[0]?.count ?? 0),
      });

      res.write(`data: ${JSON.stringify({ type: 'company_scored', payload: result })}\n\n`);
    } catch (err) {
      res.write(`data: ${JSON.stringify({ type: 'error', companyId, message: String(err) })}\n\n`);
    }
  }

  res.write(`data: ${JSON.stringify({ type: 'scoring_complete' })}\n\n`);
  res.end();
});
```

---

## Part 3 — Frontend

### 3.1 Score card component

Create `client/src/components/scoring/CompanyScoreCard.tsx`:

```typescript
// Props
interface CompanyScoreCardProps {
  companyName: string;
  country: string;
  subSector: string;
  relevanceType: 'direct' | 'adjacent' | 'inferred';
  ownershipType: string;
  baseScore: number;         // 0–100
  briefAdjustedScore: number; // 0–100
  appliedArchetype: string;
  confidenceBand: 'tight' | 'medium' | 'wide';
  dimensions: {
    d1: { score: number; evidence: string; confidenceBand: string };
    d2: { score: number; evidence: string; confidenceBand: string };
    d3: { score: number; evidence: string; confidenceBand: string; seniorLeadershipRating?: number; ceoApproval?: number };
    d4: { score: number; evidence: string; isEnriching: boolean };
    d5: { score: number; evidence: string; confirmationSource: string };
    d6: { score: number; evidence: string; openRoles: number; recentDepartures: number; maActivity: boolean };
  };
}
```

Render requirements:
- Header bar: company name, country, sub-sector pill, relevance type pill (green=direct, amber=adjacent, grey=inferred), ownership type tag
- Two score columns: Base Score (large number) and Brief-Adjusted Score (large number, highlighted) with confidence band indicator (± % based on band)
- Dimension rows: D1–D6 each showing label, score out of 10, one-line evidence, confidence band dot
- D4 shows "Enriching" badge when `isEnriching = true`
- D6 shows open roles count + M&A indicator inline
- Confidence band visual: tight = green dot, medium = amber dot, wide = red dot

### 3.2 Results list integration

In the existing search results list:
- Add score column showing `briefAdjustedScore` as a pill
- Sort by `briefAdjustedScore` descending by default
- Allow toggling to sort by any individual dimension score
- Clicking a row expands the full `CompanyScoreCard`

### 3.3 Archetype selector

Add a role archetype dropdown to the search brief panel:

```typescript
const ARCHETYPES = [
  { value: 'base', label: 'No brief (base weights)' },
  { value: 'cco', label: 'Chief Commercial Officer' },
  { value: 'coo', label: 'Chief Operating Officer' },
  { value: 'cfo', label: 'CFO / Finance' },
  { value: 'md_ceo', label: 'MD / Group CEO' },
  { value: 'buying_director', label: 'Buying & Merchandising Director' },
  { value: 'supply_chain_director', label: 'Supply Chain Director' },
];
```

When archetype changes, trigger a re-score with the new archetype (weights only — no new Serper calls needed since dimension raw scores are cached in DB).

---

## Part 4 — Testing

Before marking complete, verify the following manually:

1. **Seed runs without error** — `sourceConfigRegistry` has rows for UAE and Saudi Arabia across all 6 dimensions
2. **Score endpoint returns valid JSON** for a known UAE retailer (e.g. "Landmark Group")
3. **D4 `isEnriching = true`** when platform alumni count is 0 (cold start)
4. **Archetype switching** changes `briefAdjustedScore` without triggering new Serper calls
5. **Confidence bands** surface correctly — a company scored via fallback sources only shows "wide" band
6. **D5 gate** — a non-retailer (e.g. a construction firm accidentally in results) scores ≤ 3 on D5 and is flagged
7. **No role-specific filters in scoring pipeline** — the scoring model is purely company-level

---

## Key Invariants — Do Not Violate

| Rule | Why |
|---|---|
| Never hardcode country-specific logic in dimension scoring functions | Breaks portability — add a source config row instead |
| Never merge Execution Layer filters into dimension scores | Architectural debt — keep Strategic and Execution layers strictly separate |
| D4 must launch with `isEnriching: true` and reduced weight | Platform has no alumni data at launch; false precision is worse than flagged uncertainty |
| Claude scores what Serper finds — Claude never generates the company list | Claude-first seed generation causes category drift |
| Confidence bands must be persisted and surfaced in UI | Users need to know how much to trust each score |
| Weights must sum to 1.0 — enforce with `validateWeights()` | Silent rounding errors corrupt composite scores |

---

## Adding a New Country Later

When expanding beyond the initial GCC markets:

1. Insert rows into `source_config_registry` for the new country across all 6 dimensions and 3 source levels
2. Map to the appropriate regulatory body, press sources, and stock exchange for that country
3. Set `confidence_band_at_level` appropriately — new markets with thin data should start at `medium` not `tight`
4. No code changes required — the `sourceResolver` picks up new rows automatically

This is the only step required for a new country. Do not modify dimension scoring functions or the orchestrator.
