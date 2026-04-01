from __future__ import annotations

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
    results_per_page: int = 50

    # Concurrency & rate limiting
    listing_concurrency: int = 5
    detail_concurrency: int = 3
    request_delay_min: float = 1.0
    request_delay_max: float = 3.0
    max_retries: int = 3

    # Feature flags
    scrape_details: bool = True
