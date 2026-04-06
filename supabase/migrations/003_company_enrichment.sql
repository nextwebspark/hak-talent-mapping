-- Migration: Phase 3 enrichment tables
-- Run this in the Supabase SQL editor.

-- -------------------------------------------------------------------------
-- company_details: rich profile for each enriched company
-- -------------------------------------------------------------------------
create table if not exists public.company_details (
    id              uuid primary key default gen_random_uuid(),
    companies_id    bigint references public.companies(id) on delete set null,
    company_id      text not null,
    sector          text not null,
    country_code    text not null default '',

    -- Core identity
    name            text not null default '',
    domain          text,
    description_clean text,

    -- Location
    country         text,
    city            text,
    region          text,

    -- Sector classification
    sub_sector      text,
    sub_sector_tags text[] not null default '{}',

    -- Firmographics
    funding_stage       text,
    funding_total_usd   bigint,
    headcount_range     text,
    headcount_exact     int,
    founded_year        int,

    -- Sector-specific extracted data (schema varies per sector)
    sector_metadata     jsonb not null default '{}',

    -- Raw pipeline audit trail
    raw_search_results  jsonb,
    raw_website_data    jsonb,
    raw_llm_extraction  jsonb,

    -- Pipeline state
    enrichment_status   text not null default 'pending',
    enrichment_error    text,
    enrichment_version  int not null default 1,
    data_quality_score  float,
    content_hash        text,

    -- Vector sync
    pinecone_synced_at  timestamptz,
    embedding_model     text,

    created_at      timestamptz not null default now(),
    updated_at      timestamptz not null default now(),

    -- One profile per (company_id, sector) pair
    constraint company_details_company_sector_uq
        unique (company_id, sector)
);

create index if not exists company_details_status_idx
    on public.company_details (enrichment_status);

create index if not exists company_details_country_sector_idx
    on public.company_details (country_code, sector);

create index if not exists company_details_pinecone_sync_idx
    on public.company_details (pinecone_synced_at)
    where pinecone_synced_at is null;

-- Auto-update updated_at
create or replace function public.set_updated_at()
returns trigger language plpgsql as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

create trigger company_details_updated_at
    before update on public.company_details
    for each row execute function public.set_updated_at();

-- -------------------------------------------------------------------------
-- company_scores: scoring output, decoupled from profile
-- Can be dropped and rebuilt without touching company_details
-- -------------------------------------------------------------------------
create table if not exists public.company_scores (
    id                      uuid primary key default gen_random_uuid(),
    company_detail_id       uuid not null,

    -- Final ranking score (named column for fast ORDER BY)
    base_score              float not null,

    -- Per-dimension scores with evidence, rationale, confidence
    dimension_scores        jsonb not null default '{}',

    -- Confidence bands per dimension + overall
    confidence_bands        jsonb not null default '{}',
    overall_confidence_band text not null default 'wide',
    overall_tolerance_pct   float not null default 35.0,

    -- Sub-sector gate result (null = not applicable)
    sub_sector_gate_result  text,
    sub_sector_classified   text,

    -- Config reproducibility
    scoring_config_id       text not null default '',
    config_hash             text not null default '',

    created_at  timestamptz not null default now(),
    updated_at  timestamptz not null default now(),

    constraint company_scores_detail_fk
        foreign key (company_detail_id)
        references public.company_details (id)
        on delete cascade,

    -- Allow re-scoring with different configs
    constraint company_scores_detail_config_uq
        unique (company_detail_id, scoring_config_id)
);

create index if not exists company_scores_base_score_idx
    on public.company_scores (base_score desc);

create index if not exists company_scores_detail_id_idx
    on public.company_scores (company_detail_id);

create trigger company_scores_updated_at
    before update on public.company_scores
    for each row execute function public.set_updated_at();
