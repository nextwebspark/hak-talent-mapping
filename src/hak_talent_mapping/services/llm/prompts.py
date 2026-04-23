from __future__ import annotations

import json
from typing import Any


_BASE_SYSTEM_PROMPT = """\
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
  "sector_metadata": {object — sector-specific fields, see <sector-metadata-schema>},
  "alumni_signals": ["list of named people who worked here and moved to other companies"],
  "leadership_names": [{"name": "string — executive full name", "title": "string | null — their role/title e.g. CEO, CFO, VP of Retail"}],
  "extraction_confidence": "float 0.0-1.0 — how confident you are in this extraction"
}

If a field cannot be determined from the provided data, use null.\
"""


def build_system_prompt(
    sector_metadata_schema: dict[str, Any] | None = None,
    llm_guidance: str | None = None,
) -> str:
    """Build the full system prompt, injecting sector schema and guidance when present."""
    parts = [_BASE_SYSTEM_PROMPT]

    if sector_metadata_schema:
        parts += [
            "",
            "<sector-metadata-schema>",
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


def build_user_prompt(
    company_name: str,
    sector: str,
    search_results: list[dict[str, Any]],
    website_text: str,
) -> str:
    """Build the user message — just company identity and raw data sections."""
    parts: list[str] = [
        f"Company: {company_name}",
        f"Sector: {sector}",
    ]

    if search_results:
        parts += ["", "<web-search-results>"]
        for item in search_results:
            query = item.get("query", "")
            results = item.get("results", [])
            if not results:
                continue
            parts.append(f"\n### Query: {query}")
            for r in results[:5]:
                title = r.get("title", "")
                snippet = r.get("snippet", "")
                link = r.get("link", "")
                if snippet:
                    parts.append(f"- [{title}]({link}): {snippet}")
        parts.append("</web-search-results>")

    if website_text:
        parts += [
            "",
            "<website-content>",
            website_text[:4000],
            "</website-content>",
        ]

    parts += ["", "Extract structured company profile as JSON:"]

    return "\n".join(parts)
