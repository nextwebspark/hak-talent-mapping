from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from hak_talent_mapping.core.exceptions import LLMExtractionError
from hak_talent_mapping.core.models import ProfileExtractionResult
from hak_talent_mapping.services.llm.base import LLMProvider, parse_llm_json
from hak_talent_mapping.services.llm.perplexity_prompts import (
    LEADERSHIP_SYSTEM,
    SECTOR_META_SYSTEM,
    build_leadership_user,
    build_perplexity_system_prompt,
    build_perplexity_user_prompt,
    build_sector_meta_user,
)

logger = structlog.get_logger()

_PERPLEXITY_API_URL = "https://api.perplexity.ai/chat/completions"
_DEFAULT_MODEL = "sonar-pro"
_MAX_TOKENS_MAIN = 4096
_MAX_TOKENS_LEADERSHIP = 1024
_MAX_TOKENS_SECTOR_META = 2048
_REQUEST_TIMEOUT = 60.0


class PerplexityProvider(LLMProvider):
    """LLM provider backed by Perplexity AI's sonar-pro model.

    Makes 3 parallel calls per company — sonar-pro self-limits output tokens
    so a single combined call drops fields. Focused calls retrieve each group
    reliably then merge into ProfileExtractionResult.

      Call 1 — Main profile  : description, domain, city, headcount, founded, sub_sector, funding, alumni
      Call 2 — Leadership    : all C-suite + VP-level executives
      Call 3 — Sector meta   : store_count, revenue, brands, malls, press, awards, etc.
    """

    def __init__(
        self,
        api_key: str,
        model: str = _DEFAULT_MODEL,
        country: str = "",
    ) -> None:
        self._api_key = api_key
        self._model = model
        self._country = country
        self.last_system_prompt: str = ""
        self.last_user_prompt: str = ""
        self.last_raw_response: str = ""
        self.last_sector_meta_raw: str = ""
        self.last_leadership_raw: list[dict[str, Any]] = []

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
        llm_guidance: str | None = None,
    ) -> ProfileExtractionResult:
        """Run 3 parallel Perplexity calls then merge results.

        search_results and website_text are ignored — Perplexity does its own retrieval.
        """
        system_prompt = build_perplexity_system_prompt(
            sector_metadata_schema=sector_metadata_schema,
            llm_guidance=llm_guidance,
        )
        user_prompt = build_perplexity_user_prompt(
            company_name=company_name,
            sector=sector,
            country=self._country,
        )
        self.last_system_prompt = system_prompt
        self.last_user_prompt = user_prompt

        async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT) as client:
            profile_raw, leadership, sector_meta = await asyncio.gather(
                self._call(client, company_name, system_prompt, user_prompt, _MAX_TOKENS_MAIN),
                self._fetch_leadership(client, company_name),
                self._fetch_sector_metadata(client, company_name, sector_metadata_schema),
            )

        self.last_raw_response = profile_raw
        self.last_leadership_raw = leadership
        parsed = parse_llm_json(profile_raw.strip(), company_name)

        updates: dict[str, Any] = {}

        if not parsed.leadership_names and leadership:
            updates["leadership_names"] = leadership
            logger.debug("leadership_merged", company=company_name, count=len(leadership))

        if sector_meta:
            merged_sm = {**parsed.sector_metadata}
            for k, v in sector_meta.items():
                if merged_sm.get(k) is None:
                    merged_sm[k] = v
            if merged_sm != parsed.sector_metadata:
                updates["sector_metadata"] = merged_sm
                logger.debug("sector_meta_merged", company=company_name, fields=list(sector_meta.keys()))

        if updates:
            parsed = parsed.model_copy(update=updates)

        return parsed

    async def _call(
        self,
        client: httpx.AsyncClient,
        company_name: str,
        system_prompt: str,
        user_prompt: str,
        max_tokens: int,
    ) -> str:
        try:
            response = await client.post(
                _PERPLEXITY_API_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "max_tokens": max_tokens,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                },
            )
            response.raise_for_status()
            data = response.json()
        except httpx.HTTPStatusError as exc:
            raise LLMExtractionError(
                f"Perplexity API HTTP error for {company_name}: "
                f"{exc.response.status_code} {exc.response.text[:200]}"
            ) from exc
        except Exception as exc:
            raise LLMExtractionError(
                f"Perplexity API call failed for {company_name}: {exc}"
            ) from exc

        usage = data.get("usage", {})
        logger.debug(
            "perplexity_response",
            company=company_name,
            model=self._model,
            tokens_in=usage.get("prompt_tokens", 0),
            tokens_out=usage.get("completion_tokens", 0),
        )
        return data["choices"][0]["message"]["content"] or ""

    async def _fetch_leadership(
        self,
        client: httpx.AsyncClient,
        company_name: str,
    ) -> list[dict[str, Any]]:
        user_msg = build_leadership_user(company_name, self._country)
        try:
            response = await client.post(
                _PERPLEXITY_API_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "max_tokens": _MAX_TOKENS_LEADERSHIP,
                    "messages": [
                        {"role": "system", "content": LEADERSHIP_SYSTEM},
                        {"role": "user", "content": user_msg},
                    ],
                },
            )
            response.raise_for_status()
            data = response.json()
            raw = data["choices"][0]["message"]["content"] or ""
            usage = data.get("usage", {})
            logger.debug(
                "perplexity_leadership_response",
                company=company_name,
                tokens_in=usage.get("prompt_tokens", 0),
                tokens_out=usage.get("completion_tokens", 0),
            )
        except Exception as exc:
            logger.warning("leadership_fetch_failed", company=company_name, error=str(exc))
            return []

        return _parse_leadership(raw.strip())

    async def _fetch_sector_metadata(
        self,
        client: httpx.AsyncClient,
        company_name: str,
        sector_metadata_schema: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if not sector_metadata_schema:
            return {}

        user_msg = build_sector_meta_user(company_name, self._country, sector_metadata_schema)
        try:
            response = await client.post(
                _PERPLEXITY_API_URL,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self._model,
                    "max_tokens": _MAX_TOKENS_SECTOR_META,
                    "messages": [
                        {"role": "system", "content": SECTOR_META_SYSTEM},
                        {"role": "user", "content": user_msg},
                    ],
                },
            )
            response.raise_for_status()
            data = response.json()
            raw = data["choices"][0]["message"]["content"] or ""
            usage = data.get("usage", {})
            logger.debug(
                "perplexity_sector_meta_response",
                company=company_name,
                tokens_in=usage.get("prompt_tokens", 0),
                tokens_out=usage.get("completion_tokens", 0),
            )
        except Exception as exc:
            logger.warning("sector_meta_fetch_failed", company=company_name, error=str(exc))
            return {}

        logger.debug("sector_meta_raw_response", company=company_name, raw=raw[:500])
        self.last_sector_meta_raw = raw
        return _parse_dict(raw.strip())


def _parse_dict(raw: str) -> dict[str, Any]:
    text = raw
    if text.startswith("```"):
        text = text.split("```", 2)[1]
        if text.startswith("json"):
            text = text[4:]
        text = text.rsplit("```", 1)[0].strip()
    try:
        result = json.loads(text)
        if isinstance(result, dict):
            return result
    except Exception:
        pass
    return {}


def _parse_leadership(raw: str) -> list[dict[str, Any]]:
    data = _parse_dict(raw)
    leaders = data.get("leadership_names", [])
    if isinstance(leaders, list):
        return [
            {"name": str(l.get("name", "")), "title": l.get("title")}
            for l in leaders
            if isinstance(l, dict) and l.get("name")
        ]
    return []


