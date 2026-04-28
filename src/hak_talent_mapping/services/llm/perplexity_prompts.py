from __future__ import annotations

import json
from typing import Any


# ---------------------------------------------------------------------------
# Call 1 — Main profile
# ---------------------------------------------------------------------------

_MAIN_SYSTEM = """\
You are a company intelligence analyst. Search the web right now for the company \
described in the user message, then return a single valid JSON object matching the \
schema below. Do not include any explanation, markdown, or code fences — just raw JSON.

IMPORTANT rules:
- Do NOT return null for a field if the information exists anywhere on the web. \
  Search actively before giving up.
- For major UAE/GCC brands (Al Futtaim, Emaar, Alshaya, LuLu, Landmark, etc.) you have \
  training knowledge — use it directly, do not wait for search confirmation.
- For domain: if the official website cannot be confirmed via search, infer it from the \
  company name (e.g. "Al Futtaim Group" → alfuttaim.com, "Paris Gallery" → parisgallery.com). \
  Return your best inference rather than null.
- For founded_year: check Wikipedia, Zawya company profile, official About/History page, \
  Crunchbase, and Arabic-language sources. For private UAE holding companies, check trade \
  registry announcements. Return a decade estimate if exact year is unknown (e.g. 1930 for \
  Al Futtaim). A rough year beats null.
- For headcount_range: use LinkedIn company size badge, Wikipedia, annual reports, Gulf News, \
  or news estimates ("employs ~X"). Map any estimate to the nearest bucket. Never return null \
  if any estimate exists anywhere.
- For annual_revenue_usd: check annual reports, investor relations, Bloomberg, Forbes, \
  Gulf News, Arabian Business. Convert non-USD using current exchange rates. \
  A stale estimate beats null.
- For alumni_signals: name specific people who left this company and moved elsewhere.

JSON Schema:
{
  "name": "string — canonical company name",
  "domain": "string | null — primary website domain (e.g. jumbo.ae), no https://",
  "description_clean": "string — 2-4 sentence factual description of what the company does",
  "city": "string | null — primary city of operations",
  "region": "string | null — region/emirate/state (e.g. Dubai, Abu Dhabi)",
  "sub_sector": "string | null — specific sub-sector within the main sector",
  "sub_sector_tags": ["list of relevant sub-sector tags"],
  "funding_stage": "string | null — bootstrapped, seed, series_a, ipo, private, pe_backed",
  "funding_total_usd": "integer | null — total funding in USD if known",
  "headcount_range": "string | null — one of: 1-10, 11-50, 51-200, 201-500, 501-1000, 1001-5000, 5001+",
  "headcount_exact": "integer | null — exact employee count if mentioned",
  "founded_year": "integer | null — year the company was founded",
  "leadership_names": [],
  "alumni_signals": ["list of named people who left this company and moved to other firms"],
  "sector_metadata": {},
  "extraction_confidence": "float 0.0-1.0 — how confident you are in this extraction"
}

Note: leadership_names and sector_metadata will be filled separately — leave them as \
empty array/object. Focus tokens on the core profile fields above.\
"""


def build_perplexity_main_user(
    company_name: str,
    sector: str,
    country: str,
    query_templates: list[str] | None = None,
) -> str:
    """User prompt for Call 1 — core profile fields only."""
    intents = [
        f"What does {company_name} do? 2-4 sentence factual description of the business.",
        f"What is {company_name}'s primary website domain (e.g. jumbo.ae)?",
        f"What city and emirate/region is {company_name} headquartered in?",
        f"What year was {company_name} founded or incorporated?",
        f"How many employees does {company_name} have? Check LinkedIn company size badge, Wikipedia, annual reports, Gulf News. Accept approximation and map to the nearest range bucket (1-10, 11-50, 51-200, 201-500, 501-1000, 1001-5000, 5001+).",
        f"What specific sub-sector within {sector} does {company_name} operate in?",
        f"Is {company_name} bootstrapped, private, publicly listed, or PE-backed? Any funding info?",
        f"Has anyone notable left {company_name} to join another company? Name them and their new employer.",
    ]

    if query_templates:
        for tmpl in query_templates:
            rendered = tmpl.format(name=company_name, sector=sector, country=country)
            if rendered not in intents:
                intents.append(rendered)

    lines = [
        f"Research target: {company_name} ({sector} sector, {country})",
        "",
        "Search the web now and answer each question below, then output the JSON schema "
        "from the system prompt. Populate every field you can find — do not return null "
        "if the answer exists. Leave leadership_names=[] and sector_metadata={{}} as-is.",
        "",
        "Research questions:",
        *[f"{i+1}. {intent}" for i, intent in enumerate(intents)],
        "",
        "Sources: official website (/about, /investors), LinkedIn, annual reports, "
        "Bloomberg, Reuters, Forbes, Gulf News, Arabian Business, Zawya.",
        "",
        "Output the JSON now:",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Call 1 — system prompt builder (injects sector schema + guidance)
# ---------------------------------------------------------------------------

def build_perplexity_system_prompt(
    sector_metadata_schema: dict[str, Any] | None = None,
    llm_guidance: str | None = None,
) -> str:
    """Full system prompt for Call 1. Sector schema injected for reference only."""
    parts = [_MAIN_SYSTEM]

    if sector_metadata_schema:
        parts += [
            "",
            "<sector-metadata-schema for reference — filled by a separate call>",
            json.dumps(sector_metadata_schema, indent=2),
            "</sector-metadata-schema>",
        ]

    if llm_guidance:
        parts += [
            "",
            "<extraction-guidance>",
            llm_guidance.strip(),
            "</extraction-guidance>",
        ]

    return "\n".join(parts)


# kept for backward compat — same as build_perplexity_main_user
def build_perplexity_user_prompt(
    company_name: str,
    sector: str,
    country: str,
    query_templates: list[str] | None = None,
) -> str:
    return build_perplexity_main_user(company_name, sector, country, query_templates)


# ---------------------------------------------------------------------------
# Call 2 — Leadership
# ---------------------------------------------------------------------------

LEADERSHIP_SYSTEM = (
    "You are a company researcher. Return only a JSON object with one key: "
    "\"leadership_names\" — an array of objects each with \"name\" (string) and "
    "\"title\" (string) fields. No markdown, no explanation, just raw JSON."
)


def build_leadership_user(company_name: str, country: str) -> str:
    """User prompt for Call 2 — dedicated C-suite + VP search."""
    return (
        f"Search LinkedIn, {company_name}'s official website (/about, /team, /leadership), "
        f"press releases, Gulf News, Arabian Business, and Zawya for every C-suite and "
        f"VP-level executive currently at {company_name} ({country}).\n"
        f"Include: CEO, MD, CFO, COO, CTO, CIO, CHRO, General Counsel, EVP, SVP, VP, "
        f"Group Director, and equivalent titles.\n"
        f"Return JSON: {{\"leadership_names\": ["
        f"{{\"name\": \"Full Name\", \"title\": \"Exact Title\"}}]}}"
    )


# ---------------------------------------------------------------------------
# Call 3 — Sector metadata
# ---------------------------------------------------------------------------

SECTOR_META_SYSTEM = (
    "You are a company researcher. Return only a JSON object with exactly the keys "
    "listed in the user message. No markdown, no explanation, just raw JSON."
)


def build_sector_meta_user(
    company_name: str,
    country: str,
    sector_metadata_schema: dict[str, Any],
) -> str:
    """User prompt for Call 3 — sector-specific fields derived from schema keys."""
    schema_keys = ", ".join(f'"{k}"' for k in sector_metadata_schema)
    schema_json = json.dumps(sector_metadata_schema, indent=2)

    # Build one research question per schema key
    questions = _schema_to_questions(company_name, sector_metadata_schema)
    q_lines = "\n".join(f"{i+1}. {q}" for i, q in enumerate(questions))

    return (
        f"Search the web for {company_name} ({country}) and answer these questions:\n"
        f"{q_lines}\n\n"
        f"Return JSON with exactly these keys: {schema_keys}\n\n"
        f"Schema (types and descriptions):\n{schema_json}"
    )


def _schema_to_questions(
    company_name: str,
    schema: dict[str, Any],
) -> list[str]:
    """Generate a research question for each schema key.

    Falls back to a generic question for unknown keys so this works for any sector.
    """
    _known: dict[str, str] = {
        "store_count": (
                f"How many retail stores or locations does {company_name} operate total across all brands? "
                f"Use best estimate — if source says 'over 2000' use 2000, 'around 300' use 300. "
                f"Do NOT return null just because the number is approximate. Return integer."
            ),
        "store_formats": f"What store formats does {company_name} use — e.g. hypermarket, supermarket, specialty, online?",
        "brands_owned": f"What brands does {company_name} own or officially operate under?",
        "ded_license_confirmed": f"Is there a confirmed DED (Dubai Economic Department) trade license for {company_name}?",
        "mall_presence": f"Which specific shopping malls does {company_name} have stores in?",
        "annual_revenue_usd": f"What is {company_name}'s most recent annual revenue or turnover? Give USD figure; convert from local currency if needed.",
        "sector_concentration": f"Is {company_name} primarily a retail company (primary), or does it also operate significantly in other sectors (secondary/diversified)?",
        "other_sectors": f"What other major business sectors does {company_name} significantly operate in beyond retail?",
        "press_mentions_count": f"Count distinct third-party news or media articles mentioning {company_name} (exclude the company's own press releases). Return integer.",
        "award_mentions_count": f"Has {company_name} won industry awards, appeared in formal rankings (Forbes, Retail ME Top 50), or received government recognition? Count distinct awards as integer.",
    }
    questions = []
    for key in schema:
        if key in _known:
            questions.append(_known[key])
        else:
            desc = schema[key] if isinstance(schema[key], str) else key
            questions.append(f"Find the value for '{key}' about {company_name}: {desc}")
    return questions


# ---------------------------------------------------------------------------

__all__ = [
    "build_perplexity_system_prompt",
    "build_perplexity_user_prompt",
    "build_perplexity_main_user",
    "build_leadership_user",
    "build_sector_meta_user",
    "LEADERSHIP_SYSTEM",
    "SECTOR_META_SYSTEM",
]
