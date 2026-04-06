from __future__ import annotations

import json
from typing import Any

import structlog
from openai import AsyncOpenAI
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

_OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_DEFAULT_MODEL = "anthropic/claude-haiku-4-5"
_MAX_TOKENS = 2048


class OpenRouterProvider(LLMProvider):
    """LLM provider backed by OpenRouter using the OpenAI SDK.

    OpenRouter exposes an OpenAI-compatible API so any model available on
    OpenRouter (Claude, GPT-4o, Gemini, etc.) can be used by changing
    `model` in settings — no code changes required.

    Default model: anthropic/claude-haiku-4-5
    """

    def __init__(
        self,
        api_key: str,
        model: str = _DEFAULT_MODEL,
        base_url: str = _OPENROUTER_BASE_URL,
        site_url: str = "",
        site_name: str = "hak-talent-mapping",
    ) -> None:
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            default_headers={
                # OpenRouter recommends these headers for analytics / rate-limit routing
                "HTTP-Referer": site_url,
                "X-Title": site_name,
            },
        )
        self._model = model
        # Set after each call — read by the pipeline for audit logging
        self.last_system_prompt: str = ""
        self.last_user_prompt: str = ""
        self.last_raw_response: str = ""

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
        """Call the configured model via OpenRouter to extract a company profile."""
        user_prompt = build_user_prompt(
            company_name=company_name,
            sector=sector,
            search_results=search_results,
            website_text=website_text,
            sector_metadata_schema=sector_metadata_schema,
        )
        self.last_system_prompt = SYSTEM_PROMPT
        self.last_user_prompt = user_prompt

        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                max_tokens=_MAX_TOKENS,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
            )
        except Exception as exc:
            raise LLMExtractionError(
                f"OpenRouter API call failed for {company_name}: {exc}"
            ) from exc

        raw_text = response.choices[0].message.content or ""
        self.last_raw_response = raw_text
        usage = response.usage
        logger.debug(
            "llm_response",
            company=company_name,
            model=self._model,
            tokens_in=usage.prompt_tokens if usage else 0,
            tokens_out=usage.completion_tokens if usage else 0,
        )

        return _parse_extraction(raw_text.strip(), company_name)


def _parse_extraction(raw_text: str, company_name: str) -> ProfileExtractionResult:
    """Parse JSON from LLM response into ProfileExtractionResult."""
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
