from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hak_talent_mapping.core.exceptions import LLMExtractionError
from hak_talent_mapping.core.models import ProfileExtractionResult
from hak_talent_mapping.services.llm.claude_provider import ClaudeProvider, _parse_extraction
from hak_talent_mapping.services.llm.prompts import SYSTEM_PROMPT, build_user_prompt


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


VALID_EXTRACTION_JSON: dict[str, Any] = {
    "name": "Landmark Group",
    "domain": "landmark.ae",
    "description_clean": "A leading retail group in the Middle East and Africa.",
    "city": "Dubai",
    "region": "Dubai",
    "sub_sector": "Fashion Retail",
    "sub_sector_tags": ["fashion", "home", "food"],
    "funding_stage": "private",
    "funding_total_usd": None,
    "headcount_range": "5001+",
    "headcount_exact": 55000,
    "founded_year": 1973,
    "sector_metadata": {"store_count": 200, "ded_license_confirmed": True},
    "alumni_signals": ["CEO of Noon.com previously at Landmark"],
    "leadership_names": ["CEO Renjan John", "CFO Sanjay Rao"],
    "extraction_confidence": 0.88,
}

SAMPLE_SEARCH_RESULTS: list[dict[str, Any]] = [
    {
        "query": "Landmark Group retail overview UAE",
        "results": [
            {
                "title": "Landmark Group - About",
                "link": "https://landmark.ae/about",
                "snippet": "Landmark Group is a leading retail conglomerate...",
                "position": 1,
            }
        ],
    }
]

SAMPLE_WEBSITE_TEXT = "Landmark Group | About\nWe are a leading retail group in the Middle East."


# ---------------------------------------------------------------------------
# _parse_extraction (pure function, no I/O)
# ---------------------------------------------------------------------------


def test_parse_extraction_valid_json() -> None:
    raw = json.dumps(VALID_EXTRACTION_JSON)
    result = _parse_extraction(raw, "Landmark Group")
    assert isinstance(result, ProfileExtractionResult)
    assert result.name == "Landmark Group"
    assert result.domain == "landmark.ae"
    assert result.headcount_exact == 55000
    assert result.extraction_confidence == 0.88


def test_parse_extraction_strips_markdown_fences() -> None:
    raw = f"```json\n{json.dumps(VALID_EXTRACTION_JSON)}\n```"
    result = _parse_extraction(raw, "Landmark Group")
    assert result.name == "Landmark Group"


def test_parse_extraction_strips_plain_code_fences() -> None:
    raw = f"```\n{json.dumps(VALID_EXTRACTION_JSON)}\n```"
    result = _parse_extraction(raw, "Landmark Group")
    assert result.name == "Landmark Group"


def test_parse_extraction_invalid_json_raises() -> None:
    with pytest.raises(LLMExtractionError, match="invalid JSON"):
        _parse_extraction("not json at all", "Test Co")


def test_parse_extraction_null_optional_fields() -> None:
    minimal = {
        "name": "Small Shop",
        "domain": None,
        "description_clean": "",
        "city": None,
        "region": None,
        "sub_sector": None,
        "sub_sector_tags": [],
        "funding_stage": None,
        "funding_total_usd": None,
        "headcount_range": None,
        "headcount_exact": None,
        "founded_year": None,
        "sector_metadata": {},
        "alumni_signals": [],
        "leadership_names": [],
        "extraction_confidence": 0.1,
    }
    result = _parse_extraction(json.dumps(minimal), "Small Shop")
    assert result.domain is None
    assert result.city is None


# ---------------------------------------------------------------------------
# build_user_prompt (pure function, no I/O)
# ---------------------------------------------------------------------------


def test_build_user_prompt_contains_company_name() -> None:
    prompt = build_user_prompt(
        company_name="Landmark Group",
        sector="Retailers",
        search_results=[],
        website_text="",
    )
    assert "Landmark Group" in prompt
    assert "Retailers" in prompt


def test_build_user_prompt_includes_search_snippets() -> None:
    prompt = build_user_prompt(
        company_name="Landmark Group",
        sector="Retailers",
        search_results=SAMPLE_SEARCH_RESULTS,
        website_text="",
    )
    assert "leading retail conglomerate" in prompt
    assert "landmark.ae/about" in prompt


def test_build_user_prompt_truncates_website_text() -> None:
    long_text = "A" * 10_000
    prompt = build_user_prompt(
        company_name="X",
        sector="Retailers",
        search_results=[],
        website_text=long_text,
    )
    # Website text is capped at 4000 chars
    assert len(prompt) < 10_000 + 500  # some headroom for framing


def test_build_user_prompt_includes_metadata_schema() -> None:
    schema = {"store_count": "integer — number of stores"}
    prompt = build_user_prompt(
        company_name="X",
        sector="Retailers",
        search_results=[],
        website_text="",
        sector_metadata_schema=schema,
    )
    assert "store_count" in prompt


def test_system_prompt_contains_json_schema_instructions() -> None:
    assert "JSON" in SYSTEM_PROMPT
    assert "extraction_confidence" in SYSTEM_PROMPT
    assert "description_clean" in SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# ClaudeProvider.extract_profile (mocked Anthropic client)
# ---------------------------------------------------------------------------


def _make_mock_message(content: str) -> MagicMock:
    """Build a mock Anthropic Message response."""
    content_block = MagicMock()
    content_block.text = content
    usage = MagicMock()
    usage.input_tokens = 800
    usage.output_tokens = 250
    msg = MagicMock()
    msg.content = [content_block]
    msg.usage = usage
    return msg


@pytest.mark.asyncio
async def test_extract_profile_success() -> None:
    mock_response = _make_mock_message(json.dumps(VALID_EXTRACTION_JSON))

    with patch(
        "hak_talent_mapping.services.llm.claude_provider.AsyncAnthropic"
    ) as mock_anthropic_cls:
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_anthropic_cls.return_value = mock_client

        provider = ClaudeProvider(api_key="test-key")
        result = await provider.extract_profile(
            company_name="Landmark Group",
            sector="Retailers",
            search_results=SAMPLE_SEARCH_RESULTS,
            website_text=SAMPLE_WEBSITE_TEXT,
        )

    assert isinstance(result, ProfileExtractionResult)
    assert result.name == "Landmark Group"
    assert result.domain == "landmark.ae"
    assert result.headcount_exact == 55000


@pytest.mark.asyncio
async def test_extract_profile_strips_markdown_in_response() -> None:
    raw = f"```json\n{json.dumps(VALID_EXTRACTION_JSON)}\n```"
    mock_response = _make_mock_message(raw)

    with patch(
        "hak_talent_mapping.services.llm.claude_provider.AsyncAnthropic"
    ) as mock_anthropic_cls:
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_anthropic_cls.return_value = mock_client

        provider = ClaudeProvider(api_key="test-key")
        result = await provider.extract_profile(
            company_name="Landmark Group",
            sector="Retailers",
            search_results=[],
            website_text="",
        )

    assert result.name == "Landmark Group"


@pytest.mark.asyncio
async def test_extract_profile_raises_on_api_error() -> None:
    with patch(
        "hak_talent_mapping.services.llm.claude_provider.AsyncAnthropic"
    ) as mock_anthropic_cls:
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(side_effect=Exception("Rate limit exceeded"))
        mock_anthropic_cls.return_value = mock_client

        provider = ClaudeProvider(api_key="test-key")

        # tenacity retries 3x then re-raises
        with pytest.raises(LLMExtractionError, match="Claude API call failed"):
            await provider.extract_profile(
                company_name="Test Co",
                sector="Retailers",
                search_results=[],
                website_text="",
            )


@pytest.mark.asyncio
async def test_extract_profile_raises_on_invalid_json_response() -> None:
    mock_response = _make_mock_message("Here is the company info: blah blah not json")

    with patch(
        "hak_talent_mapping.services.llm.claude_provider.AsyncAnthropic"
    ) as mock_anthropic_cls:
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_anthropic_cls.return_value = mock_client

        provider = ClaudeProvider(api_key="test-key")

        with pytest.raises(LLMExtractionError):
            await provider.extract_profile(
                company_name="Test Co",
                sector="Retailers",
                search_results=[],
                website_text="",
            )


@pytest.mark.asyncio
async def test_extract_profile_uses_configured_model() -> None:
    mock_response = _make_mock_message(json.dumps(VALID_EXTRACTION_JSON))

    with patch(
        "hak_talent_mapping.services.llm.claude_provider.AsyncAnthropic"
    ) as mock_anthropic_cls:
        mock_client = MagicMock()
        mock_client.messages.create = AsyncMock(return_value=mock_response)
        mock_anthropic_cls.return_value = mock_client

        provider = ClaudeProvider(api_key="test-key", model="claude-haiku-4-5-20251001")
        await provider.extract_profile(
            company_name="Test",
            sector="Retailers",
            search_results=[],
            website_text="",
        )

    call_kwargs = mock_client.messages.create.call_args.kwargs
    assert call_kwargs["model"] == "claude-haiku-4-5-20251001"
