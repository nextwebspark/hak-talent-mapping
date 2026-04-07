from __future__ import annotations

import json
from typing import Any


SYSTEM_PROMPT = """\
You are a company research analyst. Your task is to extract structured information \
about a company from web search snippets and website text.

Return ONLY a valid JSON object matching the schema below. Do not include any \
explanation, markdown, or code fences — just the raw JSON.

JSON Schema:
{
  "name": "string — canonical company name",
  "domain": "string | null — primary website domain (e.g. landmark.ae), no https://",
  "description_clean": "string — 2-4 sentence factual description of what the company does",
  "city": "string | null — primary city of operations",
  "region": "string | null — region/emirate/state (e.g. Dubai, Abu Dhabi, Riyadh)",
  "sub_sector": "string | null — specific sub-sector within the main sector",
  "sub_sector_tags": ["list of relevant sub-sector tags"],
  "funding_stage": "string | null — e.g. bootstrapped, seed, series_a, ipo, private",
  "funding_total_usd": "integer | null — total funding in USD if known",
  "headcount_range": "string | null — one of: 1-10, 11-50, 51-200, 201-500, 501-1000, 1001-5000, 5001+",
  "headcount_exact": "integer | null — exact employee count if mentioned",
  "founded_year": "integer | null — year the company was founded",
  "ownership_type": "string | null — one of: family_owned, pe_backed, listed, sovereign_linked, unknown",
  "relevance_type": "string | null — one of: direct, adjacent, inferred",
  "sector_metadata": {object — sector-specific fields, see instructions below},
  "alumni_signals": ["list of named people who previously worked here and are now in senior roles elsewhere — format: 'Name, Title at Company'"],
  "leadership_names": [
    {
      "name": "string — full name",
      "title": "string — job title (e.g. Chief Executive Officer, CFO, VP Operations)",
      "function": "string — one of: commercial, operations, finance, marketing, supply_chain, hr, technology, strategy, general_management, other"
    }
  ],
  "extraction_confidence": "float 0.0-1.0 — how confident you are in this extraction"
}

Leadership extraction rules:
- Only include currently active executives/directors (not board members unless they are exec directors)
- For each person: always provide name, title, and function
- function must be one of: commercial, operations, finance, marketing, supply_chain, hr, technology, strategy, general_management, other
- If you cannot determine the function, use "other"
- Titles: use the exact title as stated in sources (e.g. "Chief Financial Officer" not "CFO")

Ownership type rules:
- family_owned: privately held by a founding family
- pe_backed: majority-owned by private equity
- listed: publicly traded on a stock exchange
- sovereign_linked: government/sovereign wealth fund ownership
- unknown: cannot be determined from available sources

Relevance type rules:
- direct: primary business activity is clearly in this sector
- adjacent: partial or secondary activity in this sector
- inferred: sector membership inferred from holding structure or brand description

Glassdoor/AmbitionBox rules (for sector_metadata):
- glassdoor_senior_leadership_rating: extract the "Senior Management" or "Leadership" rating if present (0-5 float)
- ceo_approval_pct: extract the CEO approval percentage (0-100 integer) if present
- If only an overall company rating is available (not specifically senior management), use null

M&A recency rules (for sector_metadata.ma_restructure_recency):
- "last_12m": M&A, merger, acquisition, or restructure announced/completed within the last 12 months
- "12_24m": announced/completed 12–24 months ago
- null: no signal found, or signal is older than 24 months (do not score)

For sector_metadata, include any sector-specific structured data you can extract \
per the schema provided in the instructions. If a field cannot be determined from \
the provided data, use null.
"""


def build_user_prompt(
    company_name: str,
    sector: str,
    search_results: list[dict[str, Any]],
    website_text: str,
    sector_metadata_schema: dict[str, Any] | None = None,
) -> str:
    """Build the user message for a profile extraction call."""
    parts: list[str] = [
        f"Company: {company_name}",
        f"Sector: {sector}",
        "",
    ]

    if sector_metadata_schema:
        parts += [
            "Sector metadata schema to populate:",
            json.dumps(sector_metadata_schema, indent=2),
            "",
        ]

    # Flatten search snippets
    if search_results:
        parts.append("## Web Search Results")
        for item in search_results:
            query = item.get("query", "")
            results = item.get("results", [])
            if not results:
                continue
            parts.append(f"\n### Query: {query}")
            for r in results[:5]:  # top 5 per query
                title = r.get("title", "")
                snippet = r.get("snippet", "")
                link = r.get("link", "")
                if snippet:
                    parts.append(f"- [{title}]({link}): {snippet}")

    if website_text:
        parts += [
            "",
            "## Website Content",
            website_text[:4000],  # cap to keep total tokens manageable
        ]

    parts += [
        "",
        "Extract structured company profile as JSON:",
    ]

    return "\n".join(parts)
