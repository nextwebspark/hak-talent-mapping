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

    # -------------------------------------------------------------------
    # Phase 3 — Enrichment pipeline
    # -------------------------------------------------------------------

    # Scoping: only enrich companies flagged as top_company=true in Supabase
    enrich_top_only: bool = True

    # Concurrency for enrichment workers (stages 1-5)
    enrichment_concurrency: int = 3

    # Search provider: "serper" (Google via serper.dev)
    search_provider: str = "serper"
    serper_api_key: str = ""
    search_queries_per_company: int = 17

    # LLM via OpenRouter (OpenAI-compatible SDK)
    # Model string is the OpenRouter model ID, e.g. "anthropic/claude-haiku-4-5"
    openrouter_api_key: str = ""
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    llm_model: str = "anthropic/claude-haiku-4-5"

    # Vector store
    pinecone_api_key: str = ""
    pinecone_index_name: str = "hak-company-profiles"
    # OpenRouter model ID for embeddings (same API key, different endpoint path)
    pinecone_embedding_model: str = "openai/text-embedding-3-small"
    pinecone_upsert_batch_size: int = 100

    # Scoring
    scoring_config_dir: str = "scoring_configs"

    # Website scraper (phase 3)
    website_scrape_timeout: int = 30
