from __future__ import annotations

import json
from typing import Any

import structlog
from anthropic import AsyncAnthropic
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from hak_talent_mapping.core.exceptions import LLMExtractionError
from hak_talent_mapping.core.models import ProfileExtractionResult
from hak_talent_mapping.services.llm.base import LLMProvider
from hak_talent_mapping.services.llm.prompts import SYSTEM_PROMPT, build_user_prompt

logger = structlog.get_logger()

_MAX_TOKENS = 2048


class ClaudeProvider(LLMProvider):
    """LLM provider backed by Anthropic Claude (claude-haiku-4-5 by default)."""

    def __init__(self, api_key: str, model: str = "claude-haiku-4-5-20251001") -> None:
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model

    @retry(
        retry=retry_if_exception_type(LLMExtractionError),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
    )
    async def extract_profile(
        self,
        company_name: str,
        sector: str,
        search_results: list[dict[str, Any]],
        website_text: str,
        sector_metadata_schema: dict[str, Any] | None = None,
    ) -> ProfileExtractionResult:
        """Call Claude to extract a structured company profile."""
        user_prompt = build_user_prompt(
            company_name=company_name,
            sector=sector,
            search_results=search_results,
            website_text=website_text,
            sector_metadata_schema=sector_metadata_schema,
        )

        try:
            message = await self._client.messages.create(
                model=self._model,
                max_tokens=_MAX_TOKENS,
                system=SYSTEM_PROMPT,
                messages=[{"role": "user", "content": user_prompt}],
            )
        except Exception as exc:
            raise LLMExtractionError(
                f"Claude API call failed for {company_name}: {exc}"
            ) from exc

        raw_text = message.content[0].text.strip()
        logger.debug(
            "llm_response",
            company=company_name,
            tokens_in=message.usage.input_tokens,
            tokens_out=message.usage.output_tokens,
        )

        return _parse_extraction(raw_text, company_name)


def _parse_extraction(raw_text: str, company_name: str) -> ProfileExtractionResult:
    """Parse JSON from LLM response into ProfileExtractionResult."""
    # Strip accidental markdown code fences
    text = raw_text
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.rsplit("```", 1)[0].strip()

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise LLMExtractionError(
            f"LLM returned invalid JSON for {company_name}: {exc}\nRaw: {raw_text[:200]}"
        ) from exc

    try:
        return ProfileExtractionResult.model_validate(data)
    except Exception as exc:
        raise LLMExtractionError(
            f"ProfileExtractionResult validation failed for {company_name}: {exc}"
        ) from exc
