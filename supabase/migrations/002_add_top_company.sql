-- Migration: add top_company flag to companies table
-- Run this in the Supabase SQL editor.

alter table public.companies
    add column if not exists top_company boolean not null default false;

create index if not exists companies_top_company_idx
    on public.companies (top_company)
    where top_company = true;
