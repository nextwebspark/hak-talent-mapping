from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
from pathlib import Path
from typing import Any

import structlog

from hak_talent_mapping.core.exceptions import DatabaseError
from hak_talent_mapping.core.models import CompanyProfile, CompanyScoreRecord, EnrichmentStatus

logger = structlog.get_logger()

_DEFAULT_DB_PATH = "local_test.db"

_DDL = """
CREATE TABLE IF NOT EXISTS companies (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id      TEXT NOT NULL,
    name            TEXT NOT NULL DEFAULT '',
    slug            TEXT NOT NULL DEFAULT '',
    sector          TEXT NOT NULL DEFAULT '',
    country         TEXT NOT NULL DEFAULT '',
    company_type    TEXT NOT NULL DEFAULT '',
    profile_url     TEXT NOT NULL DEFAULT '',
    description     TEXT,
    website         TEXT,
    founded_year    INTEGER,
    address         TEXT,
    phone           TEXT,
    email           TEXT,
    employees_count TEXT,
    executives      TEXT,
    top_company     INTEGER NOT NULL DEFAULT 0,
    listing_scraped_at  TEXT,
    detail_scraped_at   TEXT,
    created_at      TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(company_id, sector)
);

CREATE TABLE IF NOT EXISTS company_details (
    id                  TEXT PRIMARY KEY,
    companies_id        INTEGER,
    company_id          TEXT NOT NULL,
    sector              TEXT NOT NULL DEFAULT '',
    country_code        TEXT NOT NULL DEFAULT '',
    name                TEXT NOT NULL DEFAULT '',
    domain              TEXT,
    description_clean   TEXT,
    country             TEXT,
    city                TEXT,
    region              TEXT,
    sub_sector          TEXT,
    sub_sector_tags     TEXT NOT NULL DEFAULT '[]',
    funding_stage       TEXT,
    funding_total_usd   INTEGER,
    headcount_range     TEXT,
    headcount_exact     INTEGER,
    founded_year        INTEGER,
    sector_metadata     TEXT NOT NULL DEFAULT '{}',
    raw_search_results  TEXT,
    raw_website_data    TEXT,
    raw_llm_extraction  TEXT,
    enrichment_status   TEXT NOT NULL DEFAULT 'pending',
    enrichment_error    TEXT,
    enrichment_version  INTEGER NOT NULL DEFAULT 1,
    data_quality_score  REAL,
    content_hash        TEXT,
    pinecone_synced_at  TEXT,
    embedding_model     TEXT,
    created_at          TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at          TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(company_id, sector)
);

CREATE TABLE IF NOT EXISTS company_scores (
    id                      TEXT PRIMARY KEY,
    company_detail_id       TEXT NOT NULL,
    base_score              REAL NOT NULL,
    dimension_scores        TEXT NOT NULL DEFAULT '{}',
    confidence_bands        TEXT NOT NULL DEFAULT '{}',
    overall_confidence_band TEXT NOT NULL DEFAULT 'wide',
    overall_tolerance_pct   REAL NOT NULL DEFAULT 35.0,
    sub_sector_gate_result  TEXT,
    sub_sector_classified   TEXT,
    scoring_config_id       TEXT NOT NULL DEFAULT '',
    config_hash             TEXT NOT NULL DEFAULT '',
    created_at              TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at              TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(company_detail_id, scoring_config_id)
);

CREATE TABLE IF NOT EXISTS enrichment_audit (
    id                  TEXT PRIMARY KEY,
    company_detail_id   TEXT,
    stage               TEXT NOT NULL,
    event_type          TEXT NOT NULL,
    request_data        TEXT NOT NULL DEFAULT '{}',
    response_data       TEXT NOT NULL DEFAULT '{}',
    created_at          TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def _new_id() -> str:
    return str(uuid.uuid4())


def _j(value: Any) -> str:
    """Serialize to JSON string for storage."""
    return json.dumps(value, default=str)


def _uj(value: str | None) -> Any:
    """Deserialize from JSON string."""
    if value is None:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


def _row_to_dict(cursor: sqlite3.Cursor, row: sqlite3.Row) -> dict[str, Any]:
    """Convert sqlite3.Row to dict, deserializing JSON columns."""
    _json_cols = {
        "sub_sector_tags", "sector_metadata", "raw_search_results",
        "raw_website_data", "raw_llm_extraction", "dimension_scores",
        "confidence_bands", "executives", "request_data", "response_data",
    }
    result: dict[str, Any] = {}
    for idx, col in enumerate(cursor.description):
        name = col[0]
        val = row[idx]
        result[name] = _uj(val) if name in _json_cols else val
    return result


class LocalDetailRepository:
    """Drop-in replacement for DetailRepository backed by a local SQLite file.

    Used when --test flag is passed to avoid writing to Supabase.
    Implements the same sync + async interface as DetailRepository.
    """

    def __init__(self, db_path: str = _DEFAULT_DB_PATH) -> None:
        self._db_path = str(Path(db_path).resolve())
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self._db_path) as conn:
            conn.executescript(_DDL)
            conn.commit()
        logger.info("local_db_ready", path=self._db_path)

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ------------------------------------------------------------------ #
    # Write operations (mirror DetailRepository interface)                 #
    # ------------------------------------------------------------------ #

    def create(self, profile: CompanyProfile) -> CompanyProfile:
        new_id = _new_id()
        with self._conn() as conn:
            cur = conn.execute(
                """
                INSERT INTO company_details
                    (id, companies_id, company_id, sector, country_code, name,
                     enrichment_status, enrichment_version)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(company_id, sector) DO UPDATE SET
                    updated_at = datetime('now')
                RETURNING id
                """,
                (
                    new_id,
                    profile.companies_id,
                    profile.company_id,
                    profile.sector,
                    profile.country_code,
                    profile.name,
                    EnrichmentStatus.PENDING.value,
                    profile.enrichment_version,
                ),
            )
            row = cur.fetchone()
            returned_id = row[0] if row else new_id
        return profile.model_copy(update={"id": returned_id})

    def update_status(
        self,
        detail_id: str,
        status: EnrichmentStatus,
        error: str | None = None,
    ) -> None:
        patch: dict[str, Any] = {
            "enrichment_status": status.value,
            "enrichment_error": error if status == EnrichmentStatus.FAILED else None,
        }
        with self._conn() as conn:
            conn.execute(
                """UPDATE company_details
                   SET enrichment_status=?, enrichment_error=?, updated_at=datetime('now')
                   WHERE id=?""",
                (patch["enrichment_status"], patch["enrichment_error"], detail_id),
            )

    def upsert_raw_search(self, detail_id: str, results: list[dict[str, Any]]) -> None:
        with self._conn() as conn:
            conn.execute(
                """UPDATE company_details
                   SET raw_search_results=?, enrichment_status=?, updated_at=datetime('now')
                   WHERE id=?""",
                (_j(results), EnrichmentStatus.WEB_SEARCH_DONE.value, detail_id),
            )

    def upsert_raw_website(self, detail_id: str, data: dict[str, Any]) -> None:
        with self._conn() as conn:
            conn.execute(
                """UPDATE company_details
                   SET raw_website_data=?, enrichment_status=?, updated_at=datetime('now')
                   WHERE id=?""",
                (_j(data), EnrichmentStatus.WEBSITE_SCRAPED.value, detail_id),
            )

    def upsert_profile(self, profile: CompanyProfile) -> None:
        with self._conn() as conn:
            conn.execute(
                """UPDATE company_details SET
                    name=?, domain=?, description_clean=?, country_code=?, country=?,
                    city=?, region=?, sub_sector=?, sub_sector_tags=?,
                    funding_stage=?, funding_total_usd=?, headcount_range=?,
                    headcount_exact=?, founded_year=?, sector_metadata=?,
                    raw_llm_extraction=?, enrichment_status=?, updated_at=datetime('now')
                   WHERE id=?""",
                (
                    profile.name,
                    profile.domain,
                    profile.description_clean,
                    profile.country_code,
                    profile.country,
                    profile.city,
                    profile.region,
                    profile.sub_sector,
                    _j(profile.sub_sector_tags),
                    profile.funding_stage,
                    profile.funding_total_usd,
                    profile.headcount_range,
                    profile.headcount_exact,
                    profile.founded_year,
                    _j(profile.sector_metadata),
                    _j(profile.raw_llm_extraction),
                    EnrichmentStatus.LLM_EXTRACTED.value,
                    profile.id,
                ),
            )

    def mark_profile_complete(
        self,
        detail_id: str,
        quality_score: float,
        content_hash: str,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """UPDATE company_details
                   SET data_quality_score=?, content_hash=?, enrichment_status=?,
                       updated_at=datetime('now')
                   WHERE id=?""",
                (
                    quality_score,
                    content_hash,
                    EnrichmentStatus.PROFILE_COMPLETE.value,
                    detail_id,
                ),
            )

    def mark_pinecone_synced(
        self,
        detail_id: str,
        embedding_model: str,
        synced_at: str,
    ) -> None:
        with self._conn() as conn:
            conn.execute(
                """UPDATE company_details
                   SET pinecone_synced_at=?, embedding_model=?, updated_at=datetime('now')
                   WHERE id=?""",
                (synced_at, embedding_model, detail_id),
            )

    # ------------------------------------------------------------------ #
    # Read operations                                                      #
    # ------------------------------------------------------------------ #

    def get_companies_to_enrich(
        self,
        sector: str,
        country_code: str,
        top_only: bool = True,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return companies from local companies table needing enrichment."""
        sector = sector.title()
        with self._conn() as conn:
            done_cur = conn.execute(
                "SELECT company_id FROM company_details WHERE sector=? AND enrichment_status=?",
                (sector, EnrichmentStatus.PROFILE_COMPLETE.value),
            )
            done_ids = {r[0] for r in done_cur.fetchall()}

            query = "SELECT id, company_id, name, sector, country, website, slug FROM companies WHERE sector=?"
            params: list[Any] = [sector]
            if top_only:
                query += " AND top_company=1"
            cur = conn.execute(query, params)
            cols = [d[0] for d in cur.description]
            results = [
                dict(zip(cols, row))
                for row in cur.fetchall()
                if row[1] not in done_ids
            ]

        if limit is not None:
            return results[:limit]
        return results

    def get_by_id(self, detail_id: str) -> dict[str, Any] | None:
        with self._conn() as conn:
            cur = conn.execute(
                "SELECT * FROM company_details WHERE id=?", (detail_id,)
            )
            row = cur.fetchone()
            return _row_to_dict(cur, row) if row else None

    def get_by_company_sector(
        self, company_id: str, sector: str
    ) -> dict[str, Any] | None:
        with self._conn() as conn:
            cur = conn.execute(
                "SELECT * FROM company_details WHERE company_id=? AND sector=?",
                (company_id, sector),
            )
            row = cur.fetchone()
            return _row_to_dict(cur, row) if row else None

    def get_profile_complete(
        self,
        sector: str,
        country_code: str,
        unsynced_only: bool = False,
    ) -> list[dict[str, Any]]:
        query = (
            "SELECT * FROM company_details "
            "WHERE sector=? AND country_code=? AND enrichment_status=?"
        )
        params: list[Any] = [sector, country_code, EnrichmentStatus.PROFILE_COMPLETE.value]
        if unsynced_only:
            query += " AND pinecone_synced_at IS NULL"
        with self._conn() as conn:
            cur = conn.execute(query, params)
            rows = cur.fetchall()
            return [_row_to_dict(cur, r) for r in rows]

    # ------------------------------------------------------------------ #
    # Seed helpers (test mode only)                                        #
    # ------------------------------------------------------------------ #

    def seed_company(self, company: dict[str, Any]) -> None:
        """Insert a company row so get_companies_to_enrich has something to return."""
        with self._conn() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO companies
                   (company_id, name, slug, sector, country, company_type, profile_url,
                    website, top_company)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    company.get("company_id", ""),
                    company.get("name", ""),
                    company.get("slug", ""),
                    company.get("sector", ""),
                    company.get("country", ""),
                    company.get("company_type", ""),
                    company.get("profile_url", ""),
                    company.get("website"),
                    1 if company.get("top_company") else 0,
                ),
            )

    # ------------------------------------------------------------------ #
    # Async wrappers                                                       #
    # ------------------------------------------------------------------ #

    async def create_async(self, profile: CompanyProfile) -> CompanyProfile:
        return await asyncio.to_thread(self.create, profile)

    async def update_status_async(
        self, detail_id: str, status: EnrichmentStatus, error: str | None = None
    ) -> None:
        await asyncio.to_thread(self.update_status, detail_id, status, error)

    async def upsert_raw_search_async(
        self, detail_id: str, results: list[dict[str, Any]]
    ) -> None:
        await asyncio.to_thread(self.upsert_raw_search, detail_id, results)

    async def upsert_raw_website_async(
        self, detail_id: str, data: dict[str, Any]
    ) -> None:
        await asyncio.to_thread(self.upsert_raw_website, detail_id, data)

    async def upsert_profile_async(self, profile: CompanyProfile) -> None:
        await asyncio.to_thread(self.upsert_profile, profile)

    async def mark_profile_complete_async(
        self, detail_id: str, quality_score: float, content_hash: str
    ) -> None:
        await asyncio.to_thread(
            self.mark_profile_complete, detail_id, quality_score, content_hash
        )

    async def mark_pinecone_synced_async(
        self, detail_id: str, embedding_model: str, synced_at: str
    ) -> None:
        await asyncio.to_thread(
            self.mark_pinecone_synced, detail_id, embedding_model, synced_at
        )

    async def get_companies_to_enrich_async(
        self,
        sector: str,
        country_code: str,
        top_only: bool = True,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self.get_companies_to_enrich, sector, country_code, top_only, limit
        )

    async def get_profile_complete_async(
        self,
        sector: str,
        country_code: str,
        unsynced_only: bool = False,
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self.get_profile_complete, sector, country_code, unsynced_only
        )


class LocalAuditRepository:
    """Drop-in replacement for AuditRepository backed by SQLite."""

    def __init__(self, db_path: str = _DEFAULT_DB_PATH) -> None:
        self._db_path = str(Path(db_path).resolve())

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def log_event(
        self,
        company_detail_id: str,
        stage: str,
        event_type: str,
        request_data: dict[str, Any],
        response_data: dict[str, Any],
    ) -> None:
        try:
            with self._conn() as conn:
                conn.execute(
                    """INSERT INTO enrichment_audit
                       (id, company_detail_id, stage, event_type, request_data, response_data)
                       VALUES (?,?,?,?,?,?)""",
                    (
                        _new_id(),
                        company_detail_id,
                        stage,
                        event_type,
                        _j(request_data),
                        _j(response_data),
                    ),
                )
        except Exception as exc:
            logger.warning("local_audit_log_failed", stage=stage, error=str(exc))

    async def log_event_async(
        self,
        company_detail_id: str,
        stage: str,
        event_type: str,
        request_data: dict[str, Any],
        response_data: dict[str, Any],
    ) -> None:
        await asyncio.to_thread(
            self.log_event,
            company_detail_id,
            stage,
            event_type,
            request_data,
            response_data,
        )


class LocalScoreRepository:
    """Drop-in replacement for ScoreRepository backed by SQLite."""

    def __init__(self, db_path: str = _DEFAULT_DB_PATH) -> None:
        self._db_path = str(Path(db_path).resolve())

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def upsert_scores(self, record: CompanyScoreRecord) -> CompanyScoreRecord:
        record_id = record.id or _new_id()
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO company_scores
                   (id, company_detail_id, base_score, dimension_scores, confidence_bands,
                    overall_confidence_band, overall_tolerance_pct, sub_sector_gate_result,
                    sub_sector_classified, scoring_config_id, config_hash, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,datetime('now'))
                   ON CONFLICT(company_detail_id, scoring_config_id) DO UPDATE SET
                     base_score=excluded.base_score,
                     dimension_scores=excluded.dimension_scores,
                     confidence_bands=excluded.confidence_bands,
                     overall_confidence_band=excluded.overall_confidence_band,
                     overall_tolerance_pct=excluded.overall_tolerance_pct,
                     sub_sector_gate_result=excluded.sub_sector_gate_result,
                     sub_sector_classified=excluded.sub_sector_classified,
                     config_hash=excluded.config_hash,
                     updated_at=datetime('now')""",
                (
                    record_id,
                    record.company_detail_id,
                    record.base_score,
                    _j({k: v.model_dump() for k, v in record.dimension_scores.items()}),
                    _j({k: v.model_dump() for k, v in record.confidence_bands.items()}),
                    record.overall_confidence_band,
                    record.overall_tolerance_pct,
                    record.sub_sector_gate_result,
                    record.sub_sector_classified,
                    record.scoring_config_id,
                    record.config_hash,
                ),
            )
        return record.model_copy(update={"id": record_id})

    async def upsert_scores_async(self, record: CompanyScoreRecord) -> CompanyScoreRecord:
        return await asyncio.to_thread(self.upsert_scores, record)
