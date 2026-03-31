-- Supabase schema for hak-talent-mapping
-- Run this in the Supabase SQL editor to create the required table.

create table if not exists public.companies (
    -- Primary key
    id             bigserial primary key,

    -- Listing fields (populated in Phase 1)
    company_id     text        not null unique,
    name           text        not null,
    slug           text        not null,
    sector         text        not null,
    country        text        not null,
    company_type   text        not null,
    profile_url    text        not null,

    -- Detail fields (populated in Phase 2 via Playwright)
    description    text,
    website        text,
    founded_year   integer,
    address        text,
    phone          text,
    email          text,
    employees_count text,
    executives     jsonb,

    -- Timestamps
    listing_scraped_at  timestamptz,
    detail_scraped_at   timestamptz,
    created_at          timestamptz not null default now(),
    updated_at          timestamptz not null default now()
);

-- Index for fast lookups by company_id (already covered by UNIQUE, but explicit)
create index if not exists companies_company_id_idx on public.companies (company_id);

-- Index for querying companies that still need detail scraping
create index if not exists companies_detail_pending_idx
    on public.companies (detail_scraped_at)
    where detail_scraped_at is null;

-- Auto-update updated_at on every row change
create or replace function public.set_updated_at()
returns trigger
language plpgsql
as $$
begin
    new.updated_at = now();
    return new;
end;
$$;

drop trigger if exists companies_set_updated_at on public.companies;
create trigger companies_set_updated_at
    before update on public.companies
    for each row execute function public.set_updated_at();

-- Enable Row Level Security (recommended for Supabase)
alter table public.companies enable row level security;

-- Allow the service role full access (used by the scraper)
create policy "service_role_all" on public.companies
    for all
    to service_role
    using (true)
    with check (true);
