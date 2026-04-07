# Retail Sector Scoring Model — Claude Code Implementation Brief
## Version 3.0 — D4 Removed, Serper Clustered to 3 Calls

> Follow this sequence strictly: schema → backend → frontend → testing.
> Do not proceed to the next part until the current part compiles and runs without errors.

---

## What Changed from v2

- **D4 (Talent Export History) removed entirely.** It depended on platform alumni data that does not exist at launch. Removed rather than carried as dead weight.
- **6 Serper calls reduced to 3** via source clustering. D1 + D5 share Serper A. D2 + D6 share Serper B. D3 keeps Serper C alone.
- **5 Claude calls kept separate** — one per dimension. Collapsing into one call risks diluting scoring precision.
- **Dimensions renumbered.** Old D5 (Sector Fit) → D4. Old D6 (Momentum) → D5. Code and schema must reflect new numbering.
- **Weights redistributed.** D4's former 15% base weight redistributed across D2 and D5 proportionally.
- **Total calls per company: 8** (3 Serper + 5 Claude), down from 12.

---

## Stack

- **Frontend:** React 19, TypeScript, Vite, Tailwind CSS, shadcn/Radix UI, Wouter, TanStack Query, Zustand, Framer Motion
- **Backend:** Node.js/Express, TypeScript via tsx, PostgreSQL, Drizzle ORM
- **AI:** Anthropic SDK (`claude-sonnet-4-6`), Serper for web search
- **Shared types:** `shared/schema.ts`
- **Platform:** Replit

---

## Architectural Principles — Non-Negotiable

1. **Strategic Layer is role-agnostic.** Scoring ranks companies. Role filters belong in the Execution Layer only.
2. **Country-agnostic dimensions, country-configurable sources.** Dimensions never change. Sources are a config lookup table — add countries by inserting rows, not modifying logic.
3. **Web-first, Claude validates.** Serper finds companies. Claude scores what Serper returns. Claude never generates the company list.
4. **Enrichment is decoupled from search.** Scoring runs on discovery data. Deeper enrichment is a separate trigger.
5. **Archetype reweighting costs zero.** Switching archetypes re-multiplies cached dimension scores from DB. No new Serper or Claude calls.
6. **Confidence bands are first-class outputs.** Every dimension score carries a band (tight / medium / wide). Surface in UI.

---

## Serper Query Architecture

Each company triggers exactly 3 Serper calls, fired in parallel.

| Call | Feeds | Query focus |
|---|---|---|
| Serper A | D1 + D4 | Company profile — scale, headcount, store count, regulatory classification, sector, ownership |
| Serper B | D2 + D5 | Press and news — media mentions, awards, departures, M&A, open senior roles |
| Serper C | D3 only | Leadership — named executives, org structure, Glassdoor senior leadership rating |

After Serper returns, 5 Claude calls fire in parallel — each receives its designated result set and scores one dimension.

**Total latency = 2 round trips** regardless of call count: Serper parallel → Claude parallel.

---

## Part 1 — Schema (`shared/schema.ts`)

Add the following. Do not remove existing tables or columns.

### 1.1 Enums

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
  'fashion', 'grocery_fmcg', 'electronics', 'luxury', 'fb_retail',
  'multi_format', 'ecommerce',
  'wholesale_distribution', 'franchise_operator', 'retail_real_estate',
  'holding_with_retail_sub', 'hospitality_with_retail'
]);

export const roleArchetype = pgEnum('role_archetype', [
  'base', 'cco', 'coo', 'cfo', 'md_ceo', 'buying_director', 'supply_chain_director'
]);
```

### 1.2 `scoringDimensionResults` table

Stores per-dimension scores for every scored company. Enables full score card rendering without re-scoring.

```typescript
export const scoringDimensionResults = pgTable('scoring_dimension_results', {
  id: serial('id').primaryKey(),
  companyId: integer('company_id').notNull(),
  searchSessionId: integer('search_session_id').notNull(),
  createdAt: timestamp('created_at').defaultNow(),

  // D1 — Organisational Scale (Serper A)
  d1Score: numeric('d1_score', { precision: 4, scale: 2 }),
  d1Headcount: text('d1_headcount'),
  d1StoreCount: text('d1_store_count'),
  d1SourceLevel: text('d1_source_level'),       // 'primary' | 'secondary' | 'fallback'
  d1ConfidenceBand: confidenceBand('d1_confidence_band'),
  d1Evidence: text('d1_evidence'),

  // D2 — Brand & Market Prominence (Serper B)
  d2Score: numeric('d2_score', { precision: 4, scale: 2 }),
  d2PressCount: integer('d2_press_count'),
  d2AwardCount: integer('d2_award_count'),
  d2SourceLevel: text('d2_source_level'),
  d2ConfidenceBand: confidenceBand('d2_confidence_band'),
  d2Evidence: text('d2_evidence'),

  // D3 — Leadership Depth (Serper C)
  d3Score: numeric('d3_score', { precision: 4, scale: 2 }),
  d3NamedCsuite: integer('d3_named_csuite'),
  d3NamedDirectors: integer('d3_named_directors'),
  d3FunctionalBreadth: boolean('d3_functional_breadth'),
  d3SeniorLeadershipRating: numeric('d3_senior_leadership_rating', { precision: 3, scale: 2 }),
  d3CeoApproval: integer('d3_ceo_approval'),
  d3SourceLevel: text('d3_source_level'),
  d3ConfidenceBand: confidenceBand('d3_confidence_band'),
  d3Evidence: text('d3_evidence'),

  // D4 — Sector Fit Confidence (Serper A — shared with D1)
  d4Score: numeric('d4_score', { precision: 4, scale: 2 }),
  d4RelevanceType: sectorFitRelevanceType('d4_relevance_type'),
  d4SubSector: retailSubSector('d4_sub_sector'),
  d4OwnershipType: ownershipType('d4_ownership_type'),
  d4ConfirmationSource: text('d4_confirmation_source'),
  d4ConfidenceBand: confidenceBand('d4_confidence_band'),
  d4Evidence: text('d4_evidence'),

  // D5 — Executive Talent Momentum (Serper B — shared with D2)
  d5Score: numeric('d5_score', { precision: 4, scale: 2 }),
  d5OpenRoles: integer('d5_open_roles'),
  d5RecentDepartures: integer('d5_recent_departures'),
  d5MaActivity: boolean('d5_ma_activity'),
  d5MaRecency: text('d5_ma_recency'),           // 'last_12m' | '12_24m' | null
  d5SourceLevel: text('d5_source_level'),
  d5ConfidenceBand: confidenceBand('d5_confidence_band'),
  d5Evidence: text('d5_evidence'),

  // Composite
  baseScore: numeric('base_score', { precision: 5, scale: 2 }),
  briefAdjustedScore: numeric('brief_adjusted_score', { precision: 5, scale: 2 }),
  appliedArchetype: roleArchetype('applied_archetype').default('base'),
  overallConfidenceBand: confidenceBand('overall_confidence_band'),
});
```

### 1.3 `sourceConfigRegistry` table

The lookup table that makes scoring portable. Logic never changes — only config rows.

```typescript
export const sourceConfigRegistry = pgTable('source_config_registry', {
  id: serial('id').primaryKey(),
  country: text('country').notNull(),
  sector: text('sector').notNull(),
  dimension: text('dimension').notNull(),        // 'd1' | 'd2' | 'd3' | 'd4' | 'd5'
  serperCluster: text('serper_cluster').notNull(), // 'A' | 'B' | 'C'
  sourceLevel: text('source_level').notNull(),   // 'primary' | 'secondary' | 'fallback'
  sourceName: text('source_name').notNull(),
  sourceType: text('source_type').notNull(),     // 'web_search' | 'platform_db' | 'manual'
  searchTemplate: text('search_template'),       // use {company} and {country} tokens
  confidenceBandAtLevel: confidenceBand('confidence_band_at_level').notNull(),
  isActive: boolean('is_active').default(true),
  notes: text('notes'),
});
```

### 1.4 Columns to add to existing company results table

```typescript
// Add to existing company/results table if not present:
sectorFitRelevance: sectorFitRelevanceType('sector_fit_relevance'),
subSector: retailSubSector('sub_sector'),
ownershipType: ownershipType('ownership_type'),
baseScore: numeric('base_score', { precision: 5, scale: 2 }),
briefAdjustedScore: numeric('brief_adjusted_score', { precision: 5, scale: 2 }),
scoringSessionId: integer('scoring_session_id'),
```

### 1.5 Run migration

```bash
npx drizzle-kit generate
npx drizzle-kit migrate
```

Then run the seed script from Part 2.3.

---

## Part 2 — Backend

### 2.1 File structure

```
server/
  scoring/
    retail/
      index.ts          ← orchestrator
      dimensions.ts     ← 5 dimension scoring functions
      weights.ts        ← base weights + brief-adjusted table
      sourceResolver.ts ← country config lookup + fallback chain
    engine.ts           ← shared utilities
  seeds/
    sourceConfigRetail.ts ← seed data for source_config_registry
```

### 2.2 `weights.ts`

```typescript
export type RoleArchetype =
  'base' | 'cco' | 'coo' | 'cfo' | 'md_ceo' | 'buying_director' | 'supply_chain_director';

export interface DimensionWeights {
  d1: number; d2: number; d3: number; d4: number; d5: number;
}

// Weights must sum to 1.0 per archetype.
// D3 is constant at 0.25 across all archetypes — role-agnostic by design.
// D5 (Momentum) weight is lower for MD/CEO — board-level searches are longer horizon.
export const WEIGHT_TABLE: Record<RoleArchetype, DimensionWeights> = {
  base:                  { d1: 0.25, d2: 0.20, d3: 0.25, d4: 0.20, d5: 0.10 },
  cco:                   { d1: 0.20, d2: 0.30, d3: 0.25, d4: 0.15, d5: 0.10 },
  coo:                   { d1: 0.32, d2: 0.10, d3: 0.25, d4: 0.18, d5: 0.15 },
  cfo:                   { d1: 0.27, d2: 0.10, d3: 0.25, d4: 0.18, d5: 0.20 },
  md_ceo:                { d1: 0.32, d2: 0.20, d3: 0.25, d4: 0.13, d5: 0.10 },
  buying_director:       { d1: 0.15, d2: 0.28, d3: 0.25, d4: 0.17, d5: 0.15 },
  supply_chain_director: { d1: 0.32, d2: 0.05, d3: 0.25, d4: 0.18, d5: 0.20 },
};

export function validateWeights(w: DimensionWeights): boolean {
  const sum = Object.values(w).reduce((a, b) => a + b, 0);
  return Math.abs(sum - 1.0) < 0.01;
}

export function getWeights(archetype: RoleArchetype): DimensionWeights {
  return WEIGHT_TABLE[archetype] ?? WEIGHT_TABLE['base'];
}
```

### 2.3 `seeds/sourceConfigRetail.ts`

Run once after migration. Safe to re-run (uses `onConflictDoNothing`).

```typescript
import { db } from '../db';
import { sourceConfigRegistry } from '../../shared/schema';

// Serper cluster A: feeds D1 (scale) and D4 (sector fit)
// Serper cluster B: feeds D2 (brand) and D5 (momentum)
// Serper cluster C: feeds D3 (leadership) only

const RETAIL_SOURCES = [

  // ── SERPER CLUSTER A — D1 + D4 ───────────────────────────────────────────
  // One query per country. Results passed to both D1 and D4 Claude scorers.

  { country: 'UAE', sector: 'retail', dimension: 'cluster_a', serperCluster: 'A',
    sourceLevel: 'primary', sourceName: 'DED + DIFC/ADGM + company profile',
    sourceType: 'web_search',
    searchTemplate: '"{company}" UAE retail employees stores locations "trade license" OR "DED" OR "DIFC" site:ded.ae OR site:linkedin.com OR "{company}" UAE annual report',
    confidenceBandAtLevel: 'tight' },

  { country: 'Saudi Arabia', sector: 'retail', dimension: 'cluster_a', serperCluster: 'A',
    sourceLevel: 'primary', sourceName: 'MISA + CR + Tadawul + company profile',
    sourceType: 'web_search',
    searchTemplate: '"{company}" Saudi Arabia retail employees stores "Commercial Registration" OR "Tadawul" OR site:misa.gov.sa OR site:linkedin.com',
    confidenceBandAtLevel: 'tight' },

  { country: 'Qatar', sector: 'retail', dimension: 'cluster_a', serperCluster: 'A',
    sourceLevel: 'primary', sourceName: 'Ministry of Commerce + QSE + company profile',
    sourceType: 'web_search',
    searchTemplate: '"{company}" Qatar retail employees stores QSE OR "Ministry of Commerce" OR site:linkedin.com',
    confidenceBandAtLevel: 'tight' },

  { country: 'Kuwait', sector: 'retail', dimension: 'cluster_a', serperCluster: 'A',
    sourceLevel: 'primary', sourceName: 'MOCI + KSE + company profile',
    sourceType: 'web_search',
    searchTemplate: '"{company}" Kuwait retail employees stores KSE OR "Ministry of Commerce" OR site:linkedin.com',
    confidenceBandAtLevel: 'tight' },

  { country: 'Egypt', sector: 'retail', dimension: 'cluster_a', serperCluster: 'A',
    sourceLevel: 'primary', sourceName: 'GAFI + EGX + company profile',
    sourceType: 'web_search',
    searchTemplate: '"{company}" Egypt retail employees stores EGX OR GAFI OR site:linkedin.com',
    confidenceBandAtLevel: 'tight' },

  { country: 'global', sector: 'retail', dimension: 'cluster_a', serperCluster: 'A',
    sourceLevel: 'fallback', sourceName: 'LinkedIn + brand website + press',
    sourceType: 'web_search',
    searchTemplate: '"{company}" {country} retail employees stores locations headcount',
    confidenceBandAtLevel: 'wide' },

  // ── SERPER CLUSTER B — D2 + D5 ───────────────────────────────────────────
  // One query per country. Results passed to both D2 and D5 Claude scorers.

  { country: 'UAE', sector: 'retail', dimension: 'cluster_b', serperCluster: 'B',
    sourceLevel: 'primary', sourceName: 'UAE tier-1 press + retail trade press',
    sourceType: 'web_search',
    searchTemplate: '"{company}" retail (site:gulfnews.com OR site:thenationalnews.com OR site:arabianbusiness.com OR site:retailme.com OR site:meed.com) OR ("{company}" UAE retail award OR appointed OR "steps down" OR acquisition OR merger OR restructure) 2024 2025',
    confidenceBandAtLevel: 'tight' },

  { country: 'Saudi Arabia', sector: 'retail', dimension: 'cluster_b', serperCluster: 'B',
    sourceLevel: 'primary', sourceName: 'Saudi tier-1 press + trade press',
    sourceType: 'web_search',
    searchTemplate: '"{company}" retail (site:arabnews.com OR site:argaam.com OR site:aleqt.com OR site:meed.com) OR ("{company}" Saudi retail award OR appointed OR "steps down" OR acquisition OR merger) 2024 2025',
    confidenceBandAtLevel: 'tight' },

  { country: 'global', sector: 'retail', dimension: 'cluster_b', serperCluster: 'B',
    sourceLevel: 'fallback', sourceName: 'General press + news search',
    sourceType: 'web_search',
    searchTemplate: '"{company}" {country} retail news award recognition appointed departure acquisition merger 2024 2025',
    confidenceBandAtLevel: 'wide' },

  // ── SERPER CLUSTER C — D3 only ────────────────────────────────────────────
  // LinkedIn-heavy. Glassdoor sub-signal baked into same query.

  { country: 'UAE', sector: 'retail', dimension: 'cluster_c', serperCluster: 'C',
    sourceLevel: 'primary', sourceName: 'LinkedIn + company website + Glassdoor/AmbitionBox',
    sourceType: 'web_search',
    searchTemplate: '"{company}" UAE (CEO OR CFO OR COO OR CMO OR "head of" OR director OR "VP") site:linkedin.com OR ("{company}" "leadership team" OR "management team") OR ("{company}" site:glassdoor.com OR site:ambitionbox.com "senior management")',
    confidenceBandAtLevel: 'tight' },

  { country: 'Saudi Arabia', sector: 'retail', dimension: 'cluster_c', serperCluster: 'C',
    sourceLevel: 'primary', sourceName: 'LinkedIn + Tadawul board disclosures + Glassdoor',
    sourceType: 'web_search',
    searchTemplate: '"{company}" Saudi (CEO OR CFO OR COO OR "head of" OR director) site:linkedin.com OR ("{company}" "board of directors" Tadawul) OR ("{company}" site:glassdoor.com OR site:ambitionbox.com)',
    confidenceBandAtLevel: 'medium' },

  { country: 'global', sector: 'retail', dimension: 'cluster_c', serperCluster: 'C',
    sourceLevel: 'fallback', sourceName: 'Web search leadership + Glassdoor',
    sourceType: 'web_search',
    searchTemplate: '"{company}" {country} "leadership team" executives directors CEO CFO OR site:glassdoor.com "{company}" "senior management"',
    confidenceBandAtLevel: 'wide' },
];

export async function seedSourceConfigRetail() {
  console.log('Seeding retail source config v3...');
  await db.insert(sourceConfigRegistry).values(
    RETAIL_SOURCES.map(s => ({ ...s, isActive: true }))
  ).onConflictDoNothing();
  console.log(`Seeded ${RETAIL_SOURCES.length} rows.`);
}
```

### 2.4 `sourceResolver.ts`

```typescript
import { db } from '../db';
import { sourceConfigRegistry } from '../../shared/schema';
import { eq, and } from 'drizzle-orm';

export interface ResolvedSource {
  sourceName: string;
  sourceType: string;
  searchTemplate: string | null;
  confidenceBandAtLevel: 'tight' | 'medium' | 'wide';
  level: 'primary' | 'secondary' | 'fallback';
  serperCluster: 'A' | 'B' | 'C';
}

// Returns the best available source for a given cluster + country.
// Falls back to global config if no country-specific row exists.
export async function resolveClusterSource(
  country: string,
  sector: string,
  cluster: 'A' | 'B' | 'C'
): Promise<ResolvedSource> {
  const rows = await db
    .select()
    .from(sourceConfigRegistry)
    .where(
      and(
        eq(sourceConfigRegistry.country, country),
        eq(sourceConfigRegistry.sector, sector),
        eq(sourceConfigRegistry.serperCluster, cluster),
        eq(sourceConfigRegistry.isActive, true)
      )
    )
    .limit(1);

  if (rows.length === 0) {
    // Fall through to global
    const global = await db
      .select()
      .from(sourceConfigRegistry)
      .where(
        and(
          eq(sourceConfigRegistry.country, 'global'),
          eq(sourceConfigRegistry.sector, sector),
          eq(sourceConfigRegistry.serperCluster, cluster),
          eq(sourceConfigRegistry.isActive, true)
        )
      )
      .limit(1);

    if (global.length === 0) throw new Error(`No source config found for cluster ${cluster}`);
    return mapRow(global[0]);
  }

  return mapRow(rows[0]);
}

function mapRow(r: any): ResolvedSource {
  return {
    sourceName: r.sourceName,
    sourceType: r.sourceType,
    searchTemplate: r.searchTemplate,
    confidenceBandAtLevel: r.confidenceBandAtLevel,
    level: r.sourceLevel,
    serperCluster: r.serperCluster,
  };
}

export function buildQuery(template: string, company: string, country: string): string {
  return template
    .replace(/\{company\}/g, company)
    .replace(/\{country\}/g, country);
}
```

### 2.5 `dimensions.ts`

Five focused Claude scoring functions. Each receives a pre-fetched Serper result string and returns a typed score object.

```typescript
import Anthropic from '@anthropic-ai/sdk';

const anthropic = new Anthropic();

export interface DimensionScore {
  score: number;
  confidenceBand: 'tight' | 'medium' | 'wide';
  sourceLevel: 'primary' | 'secondary' | 'fallback';
  evidence: string;
  rawData: Record<string, unknown>;
}

async function callClaude(system: string, user: string): Promise<any> {
  const res = await anthropic.messages.create({
    model: 'claude-sonnet-4-6',
    max_tokens: 500,
    system,
    messages: [{ role: 'user', content: user }],
  });
  const text = res.content[0].type === 'text' ? res.content[0].text : '';
  const clean = text.replace(/```json|```/g, '').trim();
  try { return JSON.parse(clean); }
  catch { return { score: 0, evidence: 'Parse error', rawData: {} }; }
}

// ── D1: Organisational Scale (from Serper A) ──────────────────────────────

export async function scoreD1(
  company: string, country: string,
  serperA: string, sourceBand: 'tight' | 'medium' | 'wide', sourceLevel: 'primary' | 'secondary' | 'fallback'
): Promise<DimensionScore> {
  const result = await callClaude(
    `You score retail companies on Organisational Scale for executive talent mapping.
Return ONLY valid JSON: { "score": number (0-10), "evidence": string (one sentence max), "rawData": { "headcount": string, "storeCount": string } }

Scoring — logarithmic scale:
< 100 employees: 1-2. 100-500: 3-4. 500-2000: 5-6. 2000-10000: 7-8. 10000+: 9-10.
Store count adds up to 1.5 bonus points, capped at 10.
If data unavailable, score 0 and state so in evidence.`,
    `Company: ${company}\nCountry: ${country}\n\nSerper results:\n${serperA}`
  );
  return { ...result, confidenceBand: sourceBand, sourceLevel };
}

// ── D2: Brand & Market Prominence (from Serper B) ─────────────────────────

export async function scoreD2(
  company: string, country: string,
  serperB: string, sourceBand: 'tight' | 'medium' | 'wide', sourceLevel: 'primary' | 'secondary' | 'fallback'
): Promise<DimensionScore> {
  const result = await callClaude(
    `You score retail companies on Brand & Market Prominence for executive talent mapping.
Return ONLY valid JSON: { "score": number (0-10), "evidence": string (one sentence max), "rawData": { "pressCount12m": number, "awardCount": number, "categoryLeadership": boolean } }

Scoring:
Tier-1 press mention < 3 months: 1.5pts (max 3.0).
Tier-1 press mention 3-12 months: 1.0pts (max 2.0).
Trade press mention: 0.5pts (max 1.5).
Award or recognition: 1.0pt per (max 2.0).
Category leadership signal: 1.5pts (once only).
Cap at 10. Recency matters — older coverage scores less.`,
    `Company: ${company}\nCountry: ${country}\n\nSerper results:\n${serperB}`
  );
  return { ...result, confidenceBand: sourceBand, sourceLevel };
}

// ── D3: Leadership Depth (from Serper C) ──────────────────────────────────

export async function scoreD3(
  company: string, country: string,
  serperC: string, sourceBand: 'tight' | 'medium' | 'wide', sourceLevel: 'primary' | 'secondary' | 'fallback'
): Promise<DimensionScore> {
  const result = await callClaude(
    `You score retail companies on Leadership Depth for executive talent mapping.
Return ONLY valid JSON: { "score": number (0-10), "evidence": string (one sentence max), "rawData": { "namedCsuite": number, "namedDirectors": number, "functionalBreadth": boolean, "seniorLeadershipRating": number | null, "ceoApproval": number | null } }

Scoring:
Named CEO/MD confirmed: 2.0pts.
Each additional C-suite named (CFO, COO, CCO, CMO): 1.0pt each, max 3.0pts total.
Director/Head level confirmed (any function): 0.5pts each, max 2.0pts total.
3+ functions covered (commercial, ops, finance, marketing): 1.0pt bonus.
Glassdoor/AmbitionBox senior leadership sub-rating >= 4.0: 0.5pt bonus.
CEO Approval >= 70%: 0.5pt bonus.
Cap at 10.
Focus on named headcount and functional breadth — these are the primary signals.`,
    `Company: ${company}\nCountry: ${country}\n\nSerper results:\n${serperC}`
  );
  return { ...result, confidenceBand: sourceBand, sourceLevel };
}

// ── D4: Sector Fit Confidence (from Serper A — shared with D1) ────────────

export async function scoreD4(
  company: string, country: string,
  serperA: string, sourceBand: 'tight' | 'medium' | 'wide', sourceLevel: 'primary' | 'secondary' | 'fallback'
): Promise<DimensionScore & {
  relevanceType: 'direct' | 'adjacent' | 'inferred';
  subSector: string;
  ownershipType: string;
  confirmationSource: string;
}> {
  const result = await callClaude(
    `You classify retail companies for executive talent mapping — sector fit, sub-sector, and ownership.
Return ONLY valid JSON:
{
  "score": number (0-10),
  "evidence": string (one sentence max),
  "relevanceType": "direct" | "adjacent" | "inferred",
  "subSector": "fashion" | "grocery_fmcg" | "electronics" | "luxury" | "fb_retail" | "multi_format" | "ecommerce" | "wholesale_distribution" | "franchise_operator" | "retail_real_estate" | "holding_with_retail_sub" | "hospitality_with_retail",
  "ownershipType": "family_owned" | "pe_backed" | "listed" | "sovereign_linked" | "unknown",
  "confirmationSource": string,
  "rawData": {}
}

Scoring by confirmation source:
Regulatory activity code confirms retail as primary: 9-10.
Stock exchange sector classification confirms retail: 7-8.
Company website clearly describes retail as primary business: 6-7.
Press consistently describes as retailer: 5-6.
Retail inferred from holding group structure: 3-4.
Retail inferred from brand/product description only: 1-2.
Not a retailer: 0.`,
    `Company: ${company}\nCountry: ${country}\n\nSerper results:\n${serperA}`
  );
  return {
    score: result.score ?? 0,
    confidenceBand: sourceBand,
    sourceLevel,
    evidence: result.evidence ?? '',
    rawData: result.rawData ?? {},
    relevanceType: result.relevanceType ?? 'inferred',
    subSector: result.subSector ?? 'multi_format',
    ownershipType: result.ownershipType ?? 'unknown',
    confirmationSource: result.confirmationSource ?? '',
  };
}

// ── D5: Executive Talent Momentum (from Serper B — shared with D2) ────────

export async function scoreD5(
  company: string, country: string,
  serperB: string, sourceBand: 'tight' | 'medium' | 'wide', sourceLevel: 'primary' | 'secondary' | 'fallback'
): Promise<DimensionScore & {
  openRoles: number; recentDepartures: number; maActivity: boolean; maRecency: string | null;
}> {
  const result = await callClaude(
    `You score retail companies on Executive Talent Momentum — whether the talent pool is currently in motion.
Return ONLY valid JSON:
{
  "score": number (0-10),
  "evidence": string (one sentence max),
  "openRoles": number (VP+ open roles detected),
  "recentDepartures": number (C-suite or VP departures last 18 months),
  "maActivity": boolean (M&A or restructure confirmed last 24 months),
  "maRecency": "last_12m" | "12_24m" | null,
  "rawData": {}
}

Scoring:
M&A or restructure last 12 months: 3.0pts.
M&A or restructure 12-24 months: 1.5pts.
2+ VP-level open roles confirmed: 2.0pts.
1 VP-level open role confirmed: 1.0pt.
3+ C-suite/VP departures in last 18 months: 3.0pts.
1-2 departures in last 18 months: 1.5pts.
Cap at 10. Anything older than 24 months does not score — this is a recency signal only.`,
    `Company: ${company}\nCountry: ${country}\n\nSerper results:\n${serperB}`
  );
  return {
    score: result.score ?? 0,
    confidenceBand: sourceBand,
    sourceLevel,
    evidence: result.evidence ?? '',
    rawData: result.rawData ?? {},
    openRoles: result.openRoles ?? 0,
    recentDepartures: result.recentDepartures ?? 0,
    maActivity: result.maActivity ?? false,
    maRecency: result.maRecency ?? null,
  };
}
```

### 2.6 `retail/index.ts` — Orchestrator

```typescript
import { resolveClusterSource, buildQuery } from './sourceResolver';
import { getWeights, RoleArchetype } from './weights';
import { scoreD1, scoreD2, scoreD3, scoreD4, scoreD5 } from './dimensions';
import { db } from '../db';
import { scoringDimensionResults } from '../../shared/schema';

export interface ScoringInput {
  companyName: string;
  country: string;
  archetype?: RoleArchetype;
  searchSessionId: number;
  companyId: number;
}

async function serperFetch(query: string): Promise<string> {
  try {
    const res = await fetch('https://google.serper.dev/search', {
      method: 'POST',
      headers: {
        'X-API-KEY': process.env.SERPER_API_KEY!,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({ q: query, num: 5 }),
    });
    const data = await res.json();
    return JSON.stringify(data.organic?.slice(0, 5) ?? []);
  } catch {
    return '';
  }
}

export async function scoreRetailCompany(input: ScoringInput) {
  const { companyName, country, archetype = 'base', searchSessionId, companyId } = input;
  const weights = getWeights(archetype);

  // ── Round trip 1: resolve sources + fire 3 Serper calls in parallel ───────
  const [srcA, srcB, srcC] = await Promise.all([
    resolveClusterSource(country, 'retail', 'A'),
    resolveClusterSource(country, 'retail', 'B'),
    resolveClusterSource(country, 'retail', 'C'),
  ]);

  const [serperA, serperB, serperC] = await Promise.all([
    serperFetch(buildQuery(srcA.searchTemplate!, companyName, country)),
    serperFetch(buildQuery(srcB.searchTemplate!, companyName, country)),
    serperFetch(buildQuery(srcC.searchTemplate!, companyName, country)),
  ]);

  // ── Round trip 2: fire 5 Claude calls in parallel ─────────────────────────
  const [d1, d2, d3, d4, d5] = await Promise.all([
    scoreD1(companyName, country, serperA, srcA.confidenceBandAtLevel, srcA.level),
    scoreD2(companyName, country, serperB, srcB.confidenceBandAtLevel, srcB.level),
    scoreD3(companyName, country, serperC, srcC.confidenceBandAtLevel, srcC.level),
    scoreD4(companyName, country, serperA, srcA.confidenceBandAtLevel, srcA.level), // shares Serper A
    scoreD5(companyName, country, serperB, srcB.confidenceBandAtLevel, srcB.level), // shares Serper B
  ]);

  // ── Compute composite scores ───────────────────────────────────────────────
  const rawComposite =
    d1.score * weights.d1 +
    d2.score * weights.d2 +
    d3.score * weights.d3 +
    d4.score * weights.d4 +
    d5.score * weights.d5;

  const baseScore = Math.round(rawComposite * 10); // 0–100

  // Overall confidence band — worst band wins
  const bands = [d1, d2, d3, d4, d5].map(d => d.confidenceBand);
  const overallBand = bands.includes('wide') ? 'wide' : bands.includes('medium') ? 'medium' : 'tight';

  // ── Persist to DB ──────────────────────────────────────────────────────────
  await db.insert(scoringDimensionResults).values({
    companyId,
    searchSessionId,
    d1Score: String(d1.score), d1Headcount: String(d1.rawData.headcount ?? ''),
    d1StoreCount: String(d1.rawData.storeCount ?? ''), d1SourceLevel: d1.sourceLevel,
    d1ConfidenceBand: d1.confidenceBand, d1Evidence: d1.evidence,
    d2Score: String(d2.score), d2PressCount: Number(d2.rawData.pressCount12m ?? 0),
    d2AwardCount: Number(d2.rawData.awardCount ?? 0), d2SourceLevel: d2.sourceLevel,
    d2ConfidenceBand: d2.confidenceBand, d2Evidence: d2.evidence,
    d3Score: String(d3.score), d3NamedCsuite: Number(d3.rawData.namedCsuite ?? 0),
    d3NamedDirectors: Number(d3.rawData.namedDirectors ?? 0),
    d3FunctionalBreadth: Boolean(d3.rawData.functionalBreadth),
    d3SeniorLeadershipRating: d3.rawData.seniorLeadershipRating != null ? String(d3.rawData.seniorLeadershipRating) : null,
    d3CeoApproval: d3.rawData.ceoApproval != null ? Number(d3.rawData.ceoApproval) : null,
    d3SourceLevel: d3.sourceLevel, d3ConfidenceBand: d3.confidenceBand, d3Evidence: d3.evidence,
    d4Score: String(d4.score), d4RelevanceType: (d4 as any).relevanceType,
    d4SubSector: (d4 as any).subSector, d4OwnershipType: (d4 as any).ownershipType,
    d4ConfirmationSource: (d4 as any).confirmationSource,
    d4ConfidenceBand: d4.confidenceBand, d4Evidence: d4.evidence,
    d5Score: String(d5.score), d5OpenRoles: (d5 as any).openRoles,
    d5RecentDepartures: (d5 as any).recentDepartures, d5MaActivity: (d5 as any).maActivity,
    d5MaRecency: (d5 as any).maRecency, d5SourceLevel: d5.sourceLevel,
    d5ConfidenceBand: d5.confidenceBand, d5Evidence: d5.evidence,
    baseScore: String(baseScore / 10),
    briefAdjustedScore: String(baseScore / 10), // same — weights already archetype-adjusted above
    appliedArchetype: archetype,
    overallConfidenceBand: overallBand,
  });

  return { companyId, baseScore, appliedArchetype: archetype, dimensions: { d1, d2, d3, d4, d5 } };
}
```

### 2.7 API route (SSE streaming)

```typescript
// POST /api/search/score-companies
// Body: { companyIds: number[], country: string, archetype?: string, searchSessionId: number }
router.post('/search/score-companies', async (req, res) => {
  const { companyIds, country, archetype = 'base', searchSessionId } = req.body;

  res.setHeader('Content-Type', 'text/event-stream');
  res.setHeader('Cache-Control', 'no-cache');
  res.setHeader('Connection', 'keep-alive');

  for (const companyId of companyIds) {
    try {
      const company = await db.query.companies.findFirst({
        where: eq(companies.id, companyId)
      });
      if (!company) continue;

      const result = await scoreRetailCompany({
        companyName: company.name,
        country,
        archetype: archetype as RoleArchetype,
        searchSessionId,
        companyId,
      });

      res.write(`data: ${JSON.stringify({ type: 'company_scored', payload: result })}\n\n`);
    } catch (err) {
      res.write(`data: ${JSON.stringify({ type: 'error', companyId, message: String(err) })}\n\n`);
    }
  }

  res.write(`data: ${JSON.stringify({ type: 'scoring_complete' })}\n\n`);
  res.end();
});

// POST /api/search/rescore — archetype switch, no new Serper/Claude calls
// Body: { scoringSessionId: number, archetype: string }
router.post('/search/rescore', async (req, res) => {
  const { scoringSessionId, archetype } = req.body;
  const weights = getWeights(archetype as RoleArchetype);

  const rows = await db.select().from(scoringDimensionResults)
    .where(eq(scoringDimensionResults.searchSessionId, scoringSessionId));

  const updated = rows.map(r => {
    const composite =
      Number(r.d1Score) * weights.d1 +
      Number(r.d2Score) * weights.d2 +
      Number(r.d3Score) * weights.d3 +
      Number(r.d4Score) * weights.d4 +
      Number(r.d5Score) * weights.d5;
    return { companyId: r.companyId, briefAdjustedScore: Math.round(composite * 10) };
  });

  res.json({ archetype, scores: updated });
});
```

---

## Part 3 — Frontend

### 3.1 Score card component props

```typescript
interface CompanyScoreCardProps {
  companyName: string;
  country: string;
  subSector: string;
  relevanceType: 'direct' | 'adjacent' | 'inferred';
  ownershipType: string;
  baseScore: number;            // 0–100
  briefAdjustedScore: number;   // 0–100
  appliedArchetype: string;
  overallConfidenceBand: 'tight' | 'medium' | 'wide';
  dimensions: {
    d1: { score: number; evidence: string; confidenceBand: string; headcount: string; storeCount: string };
    d2: { score: number; evidence: string; confidenceBand: string; pressCount: number; awardCount: number };
    d3: { score: number; evidence: string; confidenceBand: string; namedCsuite: number; namedDirectors: number; seniorLeadershipRating: number | null; ceoApproval: number | null };
    d4: { score: number; evidence: string; confidenceBand: string; relevanceType: string; subSector: string; ownershipType: string };
    d5: { score: number; evidence: string; confidenceBand: string; openRoles: number; recentDepartures: number; maActivity: boolean };
  };
}
```

Render requirements:
- Header: company name, country, sub-sector pill, relevance type pill (green=direct, amber=adjacent, grey=inferred), ownership tag
- Two score panels: Base Score and Brief-Adjusted Score (highlighted), with overall confidence band
- Five dimension rows: label, score out of 10, one-line evidence, confidence dot (green=tight, amber=medium, red=wide)
- D5 shows open roles count and M&A flag inline

### 3.2 Results list

- Sort by `briefAdjustedScore` descending by default
- Allow toggling sort by any individual dimension score
- Click row to expand full score card
- Confidence band dot visible in collapsed list view

### 3.3 Archetype selector

```typescript
const ARCHETYPES = [
  { value: 'base',                  label: 'No brief (base weights)' },
  { value: 'cco',                   label: 'Chief Commercial Officer' },
  { value: 'coo',                   label: 'Chief Operating Officer' },
  { value: 'cfo',                   label: 'CFO / Finance' },
  { value: 'md_ceo',                label: 'MD / Group CEO' },
  { value: 'buying_director',       label: 'Buying & Merchandising Director' },
  { value: 'supply_chain_director', label: 'Supply Chain Director' },
];
```

On archetype change: call `/api/search/rescore` with cached session ID. No Serper or Claude calls. Update `briefAdjustedScore` display only.

---

## Part 4 — Testing Checklist

Verify manually before marking complete:

1. **Seed runs cleanly** — `sourceConfigRegistry` has rows for UAE, Saudi Arabia, and global across all 3 clusters
2. **3 Serper calls fire per company** — confirm in logs; not 5 or 6
3. **5 Claude calls fire per company** — one per dimension, separate prompts
4. **D4 receives Serper A results** (same as D1) — confirmed in orchestrator logs
5. **D5 receives Serper B results** (same as D2) — confirmed in orchestrator logs
6. **Archetype switch costs zero calls** — toggle from CCO to COO, confirm no Serper/Claude calls in logs
7. **Confidence band propagates** — a company scored via fallback sources shows `wide` band in UI
8. **D4 gate works** — a non-retailer scores ≤ 3 on D4 and is flagged with `relevanceType: 'inferred'`
9. **Weights sum to 1.0** — run `validateWeights()` for all 7 archetypes in a test
10. **No role-specific filters in scoring pipeline** — confirm scoring functions receive no seniority or function parameters

---

## Key Invariants

| Rule | Why |
|---|---|
| Never hardcode country-specific logic in dimension functions | Add a source config row instead — logic must stay country-agnostic |
| Serper A feeds both D1 and D4 — never fetch separately | 8 calls per company is the ceiling; fetching A twice breaks the architecture |
| Serper B feeds both D2 and D5 — same rule | |
| D3 gets its own Serper C call — LinkedIn needs a focused query | Broad queries return shallow leadership data; D3 precision justifies the dedicated call |
| Claude calls stay separate — one per dimension | Collapsing into one call risks diluting scoring precision |
| Archetype switching never triggers Serper or Claude | Re-multiply cached scores from DB only |
| Worst confidence band wins for overall band | Never average bands — a single wide dimension makes the whole score uncertain |
| Weights must sum to 1.0 — enforce with validateWeights() | Silent rounding errors corrupt composite scores |

---

## Adding a New Country

1. Insert rows into `source_config_registry` for clusters A, B, C with the new country value
2. Set `search_template` using the appropriate regulatory body, press sources, and stock exchange for that country
3. Set `confidence_band_at_level` conservatively for new markets (`medium` not `tight` until sources are validated)
4. No code changes required — `resolveClusterSource` picks up new rows automatically
