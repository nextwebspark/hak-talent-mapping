#!/usr/bin/env python
"""
Flag top companies in Supabase based on a curated slug list.

Usage:
    # Dry run — print matches without writing to DB
    python scripts/flag_top_companies.py --dry-run

    # Apply flags
    python scripts/flag_top_companies.py

    # Custom list / scope
    python scripts/flag_top_companies.py \
        --list doc/top_200_retailers_uae.md \
        --country "United Arab Emirates" \
        --sector "Retailers"
"""
from __future__ import annotations

import argparse
import logging
import re
import sys
from pathlib import Path

import structlog
from rapidfuzz import fuzz, process
from supabase import create_client

sys.path.insert(0, "src")

from hak_talent_mapping.config import Settings

# Suffixes to strip before fuzzy name comparison
_STRIP_SUFFIXES = re.compile(
    r"\b(PJSC|LLC|L\.L\.C|FZE|FZC|LTD|Ltd|CO\.|Co\.|Group|Holding|Holdings|"
    r"International|Establishment|Est\.?|Corporation|Corp\.?|Inc\.?)\b",
    re.IGNORECASE,
)

_PAGE_SIZE = 1000


def _configure_logging() -> None:
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )
    logging.basicConfig(level=logging.WARNING)


def _parse_slug_list(list_path: Path) -> list[str]:
    """Extract slugs from a markdown file formatted as '1. slug-name'."""
    slugs: list[str] = []
    for line in list_path.read_text().splitlines():
        line = line.strip()
        if not line:
            continue
        # Strip leading "N. " rank prefix
        match = re.match(r"^\d+\.\s+(.+)$", line)
        if match:
            slugs.append(match.group(1).strip())
    return slugs


def _normalize_name(name: str) -> str:
    """Strip legal suffixes and extra whitespace for fuzzy comparison."""
    cleaned = _STRIP_SUFFIXES.sub("", name)
    return re.sub(r"\s+", " ", cleaned).strip().lower()


def _slug_to_display_name(slug: str) -> str:
    """Convert 'landmark-group' → 'Landmark Group' for fuzzy matching."""
    return slug.replace("-", " ").title()


def _fetch_companies(
    client: object,
    country: str,
    sector: str | None,
) -> list[dict[str, str]]:
    """Fetch all companies for the given country, optionally filtered by sector (paginated)."""
    from supabase import Client

    supabase: Client = client  # type: ignore[assignment]
    results: list[dict[str, str]] = []
    offset = 0
    while True:
        query = (
            supabase.table("companies")
            .select("id,slug,name,sector")
            .eq("country", country)
        )
        if sector:
            query = query.eq("sector", sector)
        response = query.range(offset, offset + _PAGE_SIZE - 1).execute()
        if not response.data:
            break
        results.extend(response.data)
        if len(response.data) < _PAGE_SIZE:
            break
        offset += _PAGE_SIZE
    return results


def _flag_companies(
    client: object,
    matched_ids: list[int],
) -> None:
    """Set top_company = true for the given row IDs."""
    from supabase import Client

    supabase: Client = client  # type: ignore[assignment]
    # Supabase .in_() supports up to ~1000 values; our list is at most 200
    supabase.table("companies").update({"top_company": True}).in_(
        "id", matched_ids
    ).execute()


def main() -> None:
    _configure_logging()
    log = structlog.get_logger()

    parser = argparse.ArgumentParser(
        description="Flag top companies in Supabase from a curated slug list"
    )
    parser.add_argument(
        "--list",
        type=Path,
        default=Path("doc/top_200_retailers_uae.md"),
        metavar="FILE",
        help="Markdown file with ranked slugs (default: doc/top_200_retailers_uae.md)",
    )
    parser.add_argument(
        "--country",
        type=str,
        default="United Arab Emirates",
        metavar="COUNTRY",
        help="Full country name to filter (default: United Arab Emirates)",
    )
    parser.add_argument(
        "--sector",
        type=str,
        default=None,
        metavar="SECTOR",
        help="Sector name to filter (omit to search all sectors)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print matches without writing to Supabase",
    )
    args = parser.parse_args()

    # --- Load curated slug list ---
    if not args.list.exists():
        log.error("list_file_not_found", path=str(args.list))
        sys.exit(1)
    target_slugs = _parse_slug_list(args.list)
    log.info("list_loaded", slug_count=len(target_slugs), path=str(args.list))

    # --- Connect to Supabase ---
    try:
        settings = Settings()  # type: ignore[call-arg]
    except Exception as exc:
        log.error("config_error", error=str(exc))
        sys.exit(1)
    client = create_client(settings.supabase_url, settings.supabase_key)

    # --- Fetch DB companies ---
    scope = args.sector or "all sectors"
    log.info("fetching_companies", country=args.country, sector=scope)
    db_companies = _fetch_companies(client, args.country, args.sector)
    log.info("companies_fetched", count=len(db_companies))

    if not db_companies:
        log.error("no_companies_found", country=args.country, sector=args.sector)
        sys.exit(1)

    # Build lookup structures
    slug_to_id: dict[str, int] = {row["slug"]: int(row["id"]) for row in db_companies}
    db_norm_names: list[str] = [_normalize_name(row["name"]) for row in db_companies]

    target_slug_set = set(target_slugs)
    matched_ids: list[int] = []
    exact_matches: list[str] = []
    fuzzy_matches: list[tuple[str, str, str, float]] = []  # (list_slug, db_name, sector, score)
    unmatched: list[str] = []

    for slug in target_slugs:
        # Pass 1: exact slug match
        if slug in slug_to_id:
            matched_ids.append(slug_to_id[slug])
            exact_matches.append(slug)
            continue

        # Pass 2: fuzzy name match
        display_name = _slug_to_display_name(slug)
        query_norm = _normalize_name(display_name)
        result = process.extractOne(
            query_norm,
            db_norm_names,
            scorer=fuzz.token_sort_ratio,
            score_cutoff=80,
        )
        if result is not None:
            best_name, score, idx = result
            db_row = db_companies[idx]
            matched_ids.append(int(db_row["id"]))
            fuzzy_matches.append((slug, db_row["name"], db_row.get("sector", ""), score))
        else:
            unmatched.append(slug)

    # --- Report ---
    print(f"\n{'='*60}")
    print(f"  Match report  ({args.sector or 'all sectors'} / {args.country})")
    print(f"{'='*60}")
    print(f"  List slugs   : {len(target_slugs)}")
    print(f"  Exact matches: {len(exact_matches)}")
    print(f"  Fuzzy matches: {len(fuzzy_matches)}")
    print(f"  Unmatched    : {len(unmatched)}")
    print(f"  Total to flag: {len(matched_ids)}")

    if fuzzy_matches:
        print(f"\n  Fuzzy matches (score ≥ 80):")
        for list_slug, db_name, sector, score in fuzzy_matches:
            print(f"    {list_slug!r:45s} → {db_name!r}  [{score:.0f}]  ({sector})")

    if unmatched:
        print(f"\n  Unmatched slugs (no DB match found):")
        for slug in unmatched:
            print(f"    - {slug}")

    print(f"{'='*60}\n")

    if not matched_ids:
        log.info("nothing_to_flag")
        return

    if args.dry_run:
        log.info("dry_run_complete", would_flag=len(matched_ids))
        return

    # --- Write to Supabase ---
    _flag_companies(client, matched_ids)
    log.info("flagged_complete", flagged=len(matched_ids))


if __name__ == "__main__":
    main()
