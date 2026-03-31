# Project Rules — hak-talent-mapping

## Language & Runtime

- Python 3.11+
- Use `pyproject.toml` as the single source for project metadata, dependencies, and tool config
- Use `uv` as the package manager (fallback: `pip` with `requirements.txt` lockfiles)
- Virtual environment must always be used — never install into system Python

## Code Style & Formatting

- Follow PEP 8 strictly
- Use `ruff` for linting and formatting (replaces flake8, isort, black)
- Max line length: 88 characters (ruff/black default)
- Use trailing commas in multi-line collections and function signatures
- Prefer double quotes for strings
- Sort imports: stdlib, third-party, local — enforced by ruff (`isort` rules)

## Type Safety

- All public functions and methods MUST have complete type annotations
- Use `from __future__ import annotations` at the top of every module
- Use modern type syntax: `list[str]`, `dict[str, int]`, `X | None` (not `Optional[X]`)
- Run `mypy --strict` with zero errors — no `type: ignore` without a comment explaining why
- Use `typing.TypeAlias`, `TypeVar`, `Protocol` where appropriate

## Project Structure

```
src/
  hak_talent_mapping/     # main package (underscore, not hyphen)
    __init__.py
    core/                  # domain logic, models, schemas
    services/              # business logic, orchestration
    api/                   # API layer (FastAPI routers, etc.)
    db/                    # database models, migrations, repositories
    utils/                 # shared utilities (keep thin)
    config.py              # settings via pydantic-settings
tests/
  unit/
  integration/
  conftest.py
```

- Every directory that is a Python package MUST have an `__init__.py`
- Keep `utils/` thin — if a utility grows, promote it to its own module
- No circular imports — if two modules need each other, extract shared code into a third

## Naming Conventions

- Modules and packages: `snake_case`
- Classes: `PascalCase`
- Functions, methods, variables: `snake_case`
- Constants: `UPPER_SNAKE_CASE`
- Private/internal: prefix with single underscore `_`
- Avoid abbreviations — prefer `calculate_score` over `calc_scr`

## Error Handling

- Never use bare `except:` — always catch specific exceptions
- Define custom exception classes in `core/exceptions.py` inheriting from a project base exception
- Let unexpected exceptions propagate — don't swallow errors silently
- Use structured logging for errors, not print statements
- API layer must return proper HTTP error responses, never leak tracebacks

## Logging

- Use `structlog` for structured, JSON-formatted logging
- Never use `print()` for operational output — always use the logger
- Log levels: DEBUG for dev diagnostics, INFO for key events, WARNING for recoverable issues, ERROR for failures
- Include correlation/request IDs in all log entries

## Configuration

- Use `pydantic-settings` (BaseSettings) for all configuration
- Load from environment variables — never hardcode secrets or connection strings
- Provide sensible defaults for local development
- Validate all config at startup — fail fast on misconfiguration

## Database

- Use SQLAlchemy 2.0+ with async support if applicable
- Use Alembic for all schema migrations — never modify the DB manually
- Repository pattern: database access goes through repository classes, not directly in services
- All queries must use parameterized statements — no string interpolation in SQL

## Testing

- Use `pytest` as the test runner
- Minimum 80% code coverage — enforce with `pytest-cov`
- Test file naming: `test_<module_name>.py`
- Use fixtures and `conftest.py` for shared test setup
- Unit tests must be fast and isolated — mock external dependencies
- Integration tests in a separate directory, can use real databases via testcontainers or docker
- Use `factory_boy` or fixtures for test data — never hardcode test data inline

## API Design (if applicable)

- Use FastAPI with Pydantic v2 models for request/response schemas
- Version APIs: `/api/v1/...`
- Use dependency injection for services and database sessions
- All endpoints must have OpenAPI descriptions
- Use proper HTTP status codes and consistent error response format

## Dependencies & Security

- Pin all dependencies to exact versions in the lockfile
- Run `pip-audit` or `safety` in CI to check for known vulnerabilities
- Never commit secrets, credentials, or `.env` files — use `.gitignore`
- Use `python-dotenv` only for local development, never in production

## Git & Version Control

- Commit messages: imperative mood, concise (`Add user scoring endpoint`, not `added stuff`)
- One logical change per commit
- Branch naming: `feature/`, `fix/`, `chore/`, `refactor/` prefixes
- Always rebase feature branches onto main before merging

## Documentation

- Docstrings: Google style for all public modules, classes, and functions
- Keep docstrings focused on *why* and *what*, not *how* (the code shows how)
- Maintain a `README.md` with setup instructions, architecture overview, and how to run tests
- API documentation is auto-generated from FastAPI/Pydantic schemas

## CI/CD Expectations

- All of the following must pass before merge:
  - `ruff check .` (lint)
  - `ruff format --check .` (format)
  - `mypy --strict` (type check)
  - `pytest --cov` (tests with coverage)
  - `pip-audit` (dependency security)
- Use pre-commit hooks locally to catch issues before push

## Performance & Reliability

- Use async/await for I/O-bound operations
- Add timeouts to all external HTTP calls and database queries
- Use connection pooling for database connections
- Cache expensive computations where appropriate (redis or in-memory LRU)
- Add health check endpoints for monitoring

## Do NOT

- Do not use `Any` type unless absolutely unavoidable (and document why)
- Do not use mutable default arguments in function signatures
- Do not use wildcard imports (`from module import *`)
- Do not suppress linter warnings without justification
- Do not store state in module-level mutable globals
- Do not write business logic in API route handlers — delegate to services

---

## Project Context — Zawya Company Scraper

### What this project does
Scrapes all UAE Retailers companies from [zawya.com](https://www.zawya.com/en/companies/find-companies?country=AE&sector=Retailers) (6,802 companies) and stores them in Supabase.

### Two-phase scraping pipeline

**Phase 1 — Listing scraper** (`services/listing_scraper.py`)
- Uses `httpx` async + `BeautifulSoup` (lxml)
- Target: `https://www.zawya.com/en/companies/find-companies?country=AE&sector=Retailers&page={n}`
- 681 pages × 10 companies = 6,802 companies
- Concurrency: 5 simultaneous requests, 1–3s random delay between batches
- Extracts per company: `company_id` (from URL), `name`, `slug`, `sector`, `country`, `company_type`, `profile_url`
- Upserts to Supabase in batches of 200

**Phase 2 — Detail scraper** (`services/detail_scraper.py`)
- Uses `Playwright` (headless Chromium) — required because detail pages are client-side rendered
- Extracts `innerText` via `page.evaluate("() => document.body.innerText")` then parses line-by-line
- Zawya renders label/value as consecutive lines in innerText, e.g.:
  ```
  Business Summary
  Emirates Stallions Group PJSC is a UAE-based company…
  Country of Incorporation
  United Arab Emirates
  Incorporation Date
  2008-07-22
  Company Address
  Burj At Tala St,, Al Nahyan 22227, PO Box 3194
  ```
- Extracts: `description`, `founded_year`, `address`, `phone`, `email`, `employees_count`
- Concurrency: 3 simultaneous Playwright tabs, 1–3s random delay
- Fully resumable — skips companies where `detail_scraped_at IS NOT NULL`

### Database — Supabase
- Table: `public.companies`
- Schema defined in `supabase/schema.sql` — run once in the Supabase SQL editor
- Uses `service_role` key (not anon key) for write access
- Upsert on `company_id` — safe to re-run
- Supabase query limit: 1000 rows per request — re-run `details` phase multiple times to process all records

### Running the scraper
```bash
# Activate venv
source .venv/bin/activate

# Phase 1 — listings (fast, ~5-10 min)
python scripts/run_scraper.py listings

# Phase 2 — details (slow, ~3-4 hours total, run multiple times due to 1000-row limit)
python scripts/run_scraper.py details

# Test with N records
python scripts/run_scraper.py details --limit 5

# Run in background with logging
nohup python scripts/run_scraper.py details > logs/details.log 2>&1 &

# Monitor progress
tail -f logs/details.log

# Check how many detail records are done
python - <<'EOF'
import sys; sys.path.insert(0, "src")
from hak_talent_mapping.config import Settings
from supabase import create_client
s = Settings()
c = create_client(s.supabase_url, s.supabase_key)
done = c.table("companies").select("company_id", count="exact").not_.is_("detail_scraped_at", "null").execute()
print(f"Done: {done.count} / 6782")
EOF
```

### Key implementation notes
- **structlog**: Use `PrintLoggerFactory` — do NOT add `add_logger_name` processor (incompatible, causes AttributeError)
- **Supabase 1000-row cap**: `get_pending_detail_companies()` returns at most 1000 rows per call — re-run the details phase multiple times until all records are processed
- **Detail page selectors**: Do not use CSS selectors or `<dl>` tags — Zawya detail pages have no semantic HTML for data fields. Always parse `innerText` line-by-line
- **Rate limiting**: Zawya returns HTTP 429 if hit too hard — keep `LISTING_CONCURRENCY ≤ 5` and `DETAIL_CONCURRENCY ≤ 3`
- **`profile_url`**: Stored during Phase 1; Phase 2 reads it directly from Supabase — no re-crawling of listing pages needed

### Environment variables (`.env`)
```
SUPABASE_URL=https://<project-id>.supabase.co
SUPABASE_KEY=<service_role_key>
```
