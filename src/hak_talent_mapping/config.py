from __future__ import annotations

import math

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Supabase
    supabase_url: str
    supabase_key: str

    # Target site
    base_url: str = "https://www.zawya.com"
    country: str = "AE"
    sector: str = "Retailers"
    total_companies: int = 6802
    results_per_page: int = 10

    # Concurrency & rate limiting
    listing_concurrency: int = 5
    detail_concurrency: int = 3
    request_delay_min: float = 1.0
    request_delay_max: float = 3.0
    max_retries: int = 3

    # Feature flags
    scrape_details: bool = True

    @property
    def total_pages(self) -> int:
        return math.ceil(self.total_companies / self.results_per_page)
