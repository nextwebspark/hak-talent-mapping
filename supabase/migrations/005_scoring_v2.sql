-- Migration: Scoring model v2 additions
-- Adds brief-adjusted score, applied archetype, and D4 enriching flag to company_scores.
-- Run this in the Supabase SQL editor after 003_company_enrichment.sql.

alter table public.company_scores
    add column if not exists brief_adjusted_score  float,
    add column if not exists applied_archetype      text,
    add column if not exists d4_is_enriching        boolean not null default false;

-- Index for ranking by brief-adjusted score (used in brief-aware search results)
create index if not exists company_scores_brief_adj_idx
    on public.company_scores (brief_adjusted_score desc)
    where brief_adjusted_score is not null;

comment on column public.company_scores.brief_adjusted_score is
    'Score recomputed with archetype-specific weights. Null when no archetype was applied.';
comment on column public.company_scores.applied_archetype is
    'Archetype used for brief_adjusted_score (e.g. base, cco, coo, cfo, md_ceo).';
comment on column public.company_scores.d4_is_enriching is
    'True when D4 talent_export_history is in cold-start mode (platform alumni data not yet populated).';
