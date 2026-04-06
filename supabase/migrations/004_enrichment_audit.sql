-- Migration: Enrichment audit log
-- Run this in the Supabase SQL editor.

create table if not exists public.enrichment_audit (
    id                  uuid primary key default gen_random_uuid(),
    company_detail_id   uuid references public.company_details(id) on delete cascade,
    stage               text not null,       -- 'web_search' | 'llm_extraction'
    event_type          text not null,       -- 'serper_query' | 'llm_call'
    request_data        jsonb not null default '{}',
    response_data       jsonb not null default '{}',
    created_at          timestamptz not null default now()
);

create index if not exists enrichment_audit_detail_id_idx
    on public.enrichment_audit (company_detail_id);

create index if not exists enrichment_audit_stage_idx
    on public.enrichment_audit (stage);
