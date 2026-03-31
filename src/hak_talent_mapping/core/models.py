from __future__ import annotations

from datetime import datetime
from typing import TypedDict

from pydantic import BaseModel, Field


class Company(BaseModel):
    """Represents a company scraped from Zawya."""

    company_id: str
    name: str
    slug: str
    sector: str
    country: str
    company_type: str
    profile_url: str

    # Detail fields — populated in Phase 2
    description: str | None = None
    website: str | None = None
    founded_year: int | None = None
    address: str | None = None
    phone: str | None = None
    email: str | None = None
    employees_count: str | None = None
    executives: list[dict[str, str]] | None = None

    listing_scraped_at: datetime | None = None
    detail_scraped_at: datetime | None = None


class CompanyDetail(TypedDict, total=False):
    """Fields extracted from a company detail page (all optional)."""

    description: str
    website: str
    founded_year: int
    address: str
    phone: str
    email: str
    employees_count: str
    executives: list[dict[str, str]]
    detail_scraped_at: str
