# Phase 3: Vector Search (Pinecone)

---

## Index Configuration

| Setting | Value |
|---------|-------|
| Index name | `hak-company-profiles` |
| Dimensions | 1536 |
| Metric | cosine |
| Embedding model | OpenAI `text-embedding-3-small` |
| Pod type | Serverless (s1) |

---

## What Gets Embedded

A single rich profile document per company — not just scores. This enables semantic search to match descriptive qualities ("strong commercial leadership in fashion retail").

```
Company: Landmark Group — Retail Division
Sector: Retailers | Sub-sector: Multi-format Retail
Tags: premium, multi-format, omnichannel, loyalty-program
Country: United Arab Emirates | City: Dubai | Region: GCC

Description: One of the largest retail and hospitality conglomerates in the
Middle East, Africa and India. Operates 20+ retail brands across fashion,
electronics, food and beverage through 200+ outlets in the UAE.

Size: 50,000+ employees | Founded: 1973 | Stage: Private
Headcount: 50,000+ (UAE operations)

Sector Signals: 200+ UAE stores, premium brand tier, omnichannel presence,
loyalty program (Shukran), franchise model active

Organisational Scale: 8.5/10 — ~50,000 UAE employees, 200+ locations
Brand & Market Prominence: 8.8/10 — 14 tier-1 press mentions last 12 months, Retailer of the Year ME finalist
Leadership Depth: 8.2/10 — Named CEO, CFO, CCO, COO, CMO confirmed
Talent Export History: 7.5/10 — 8 tracked alumni in VP+ roles [Enriching]
Sector Fit Confidence: 10.0/10 — DED trade license confirms retail, direct classification

Base Score: 84/100
Confidence Band: ±8% (primary sources across 4 of 5 dimensions)
```

**Why rich text, not just scores:** Semantic search can match qualitative aspects ("strong commercial leadership" matches a company with high leadership depth in commercial functions). Scores alone lose this nuance.

---

## Metadata per Vector

All filterable fields from `company_details` + scores derived from `company_scores.dimension_scores`. At write time, the JSONB `dimension_scores` is **flattened** into top-level metadata keys to support Pinecone's `$gte` / `$lte` filter operators.

```python
{
    # Identity
    "company_id": "landmark-group",
    "company_detail_id": "550e8400-e29b-41d4-a716-446655440000",
    "name": "Landmark Group",
    "domain": "landmarkgroup.com",

    # Location (filterable)
    "sector": "Retailers",
    "sub_sector": "multi_format_retail",
    "country_code": "AE",
    "city": "Dubai",
    "region": "GCC",

    # Size (filterable)
    "headcount_range": "10001+",
    "funding_stage": "private",
    "founded_year": 1973,

    # Tags (filterable via $in operator)
    "sub_sector_tags": ["premium", "multi-format", "omnichannel", "loyalty-program"],

    # Scores — flattened from dimension_scores JSONB for $gte filter support
    "base_score": 84.0,
    "organisational_scale_score": 8.5,
    "brand_prominence_score": 8.8,
    "leadership_depth_score": 8.2,
    "talent_export_history_score": 7.5,
    "sector_fit_confidence_score": 10.0,
    "scoring_config_id": "retailers_v2",

    # Cold-start flags (for UI badge rendering)
    "talent_export_history_cold_start": True,
    "talent_export_history_effective_weight": 0.08,

    # Confidence
    "confidence_band_overall": "tight",
    "confidence_band_tolerance_pct": 8,

    # Sub-sector gate
    "sub_sector_gate_result": None,        # null = no gate for this sector
    "sub_sector_classified": None,

    # Quality
    "data_quality_score": 0.85,
    "enrichment_version": 1,
}
```

**Flattening rationale:** Pinecone metadata filters require top-level scalar keys. The `dimension_scores` JSONB in Supabase is the source of truth; Pinecone holds a read-only flat copy for vector + filter queries. The two stay in sync via Stage 7 (Vectorize).

---

## Query Patterns

### 1. Semantic Search (general)

```python
# "Find companies in UAE with strong commercial leadership in retail"
results = index.query(
    vector=embed("strong commercial leadership in retail"),
    top_k=20,
    filter={"country_code": {"$eq": "AE"}},
    include_metadata=True,
)
```

### 2. Filtered + Semantic

```python
# "Large tech companies in Dubai"
results = index.query(
    vector=embed("large technology company software engineering"),
    top_k=20,
    filter={
        "country_code": {"$eq": "AE"},
        "city": {"$eq": "Dubai"},
        "sector": {"$in": ["Software & IT Services", "Technology Equipment"]},
        "headcount_range": {"$in": ["201-500", "501-1000", "1001-5000", "5001+"]},
    },
    include_metadata=True,
)
```

### 3. Score-Based Reweighting (after retrieval)

After Pinecone returns candidates, client-side reweighting uses the flattened dimension scores from metadata. The loop is **dynamic** — it iterates over the sector config's dimension list rather than hardcoded names, so it works for any sector:

```python
# Load role archetype weights from sector config
archetype_weights = sector_config.brief_reweighting.get_archetype("cco").weights

for match in results.matches:
    meta = match.metadata
    brief_score = sum(
        meta.get(f"{dim_id}_score", 0.0) * weight
        for dim_id, weight in archetype_weights.items()
    ) * 10
    match.brief_adjusted_score = brief_score

# Re-sort by brief-adjusted score
results.matches.sort(key=lambda m: m.brief_adjusted_score, reverse=True)
```

### 4. Cross-Sector Discovery

```python
# "Companies with strong leadership across any sector in GCC"
results = index.query(
    vector=embed("strong executive team diverse leadership pipeline"),
    top_k=50,
    filter={
        "region": {"$eq": "GCC"},
        "leadership_depth_score": {"$gte": 7.0},
        "confidence_band_overall": {"$in": ["tight", "medium"]},  # exclude wide-band results
    },
    include_metadata=True,
)
```

### 5. Sub-Sector Filtered (Academic)

```python
# "Top K-12 schools in UAE for Head of School search"
results = index.query(
    vector=embed("k12 school outstanding rated strong academic leadership"),
    top_k=20,
    filter={
        "country_code": {"$eq": "AE"},
        "sector": {"$eq": "Academic & Educational Services"},
        "sub_sector_classified": {"$eq": "k12"},
        "sub_sector_gate_result": {"$eq": "passed"},
    },
    include_metadata=True,
)
```

---

## Design Rationale

| Choice | Why |
|--------|-----|
| **Single vector per company** | Semantic search matches the holistic profile, not individual dimensions |
| **Rich text, not just scores** | Enables qualitative matching ("luxury fashion brand" vs "discount grocery") |
| **All scores flattened in metadata** | Brief-adjusted reweighting at query time without re-embedding; `$gte` filter support |
| **Sub-sector fields in metadata** | Enables pre-filtered academic sub-sector queries (K-12 vs HE) |
| **Cold-start flags in metadata** | UI can render `[Enriching]` badge without re-querying Supabase |
| **Confidence band in metadata** | Enables UI to surface data quality warnings (exclude wide-band from results) |
| **Sub-sector tags as array** | Filterable via Pinecone's `$in` operator for precise sector queries |
| **Reweighting loop is dynamic** | Iterates over sector config dimension list — works for any sector without code changes |
| **Pinecone is a derived index** | Can be fully rebuilt from `company_details` + `company_scores` at any time |
