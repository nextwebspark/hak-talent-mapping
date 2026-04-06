from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hak_talent_mapping.services.vector.embeddings import (
    OpenAIEmbeddingProvider,
    build_embed_text,
    build_pinecone_metadata,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _profile(
    name: str = "Landmark Group",
    sector: str = "Retailers",
    sub_sector: str = "Fashion Retail",
    city: str = "Dubai",
    region: str = "Dubai",
    description: str = "A leading retail group in the Middle East.",
    headcount_range: str = "5001+",
    founded_year: int = 1973,
    domain: str = "landmark.ae",
    country_code: str = "AE",
    store_count: int | None = 200,
    brands: list[str] | None = None,
) -> dict:
    sector_meta: dict = {}
    if store_count is not None:
        sector_meta["store_count"] = store_count
    if brands is not None:
        sector_meta["brands_owned"] = brands
    return {
        "id": "detail-uuid-123",
        "company_id": "cid-001",
        "name": name,
        "sector": sector,
        "sub_sector": sub_sector,
        "city": city,
        "region": region,
        "description_clean": description,
        "headcount_range": headcount_range,
        "founded_year": founded_year,
        "domain": domain,
        "country_code": country_code,
        "sector_metadata": sector_meta,
        "data_quality_score": 0.85,
        "enrichment_version": 1,
    }


def _score(
    base_score: float = 78.5,
    config_id: str = "retailers_v1",
    overall_band: str = "medium",
) -> dict:
    return {
        "company_detail_id": "detail-uuid-123",
        "scoring_config_id": config_id,
        "base_score": base_score,
        "overall_confidence_band": overall_band,
        "overall_tolerance_pct": 20.0,
        "dimension_scores": {
            "organisational_scale": {"score": 8.5, "confidence_band": "tight"},
            "leadership_depth": {"score": 7.0, "confidence_band": "medium"},
            "sector_fit_confidence": {"score": 9.5, "confidence_band": "tight"},
        },
    }


# ---------------------------------------------------------------------------
# build_embed_text
# ---------------------------------------------------------------------------


def test_embed_text_contains_company_name() -> None:
    text = build_embed_text(_profile())
    assert "Landmark Group" in text


def test_embed_text_contains_sector() -> None:
    text = build_embed_text(_profile())
    assert "Retailers" in text


def test_embed_text_contains_description() -> None:
    text = build_embed_text(_profile())
    assert "leading retail group" in text


def test_embed_text_contains_location() -> None:
    text = build_embed_text(_profile())
    assert "Dubai" in text


def test_embed_text_contains_store_count() -> None:
    text = build_embed_text(_profile(store_count=200))
    assert "200" in text


def test_embed_text_contains_brands() -> None:
    text = build_embed_text(_profile(brands=["Babyshop", "Splash", "Home Centre"]))
    assert "Babyshop" in text


def test_embed_text_contains_score_when_provided() -> None:
    text = build_embed_text(_profile(), score_row=_score(base_score=78.5))
    assert "78.5" in text


def test_embed_text_no_score_when_not_provided() -> None:
    text = build_embed_text(_profile(), score_row=None)
    assert "HAK score" not in text


def test_embed_text_pipe_separated() -> None:
    text = build_embed_text(_profile())
    assert " | " in text


def test_embed_text_skips_empty_fields() -> None:
    profile = _profile(sub_sector="", city="", region="")
    text = build_embed_text(profile)
    # Should not have double pipes from empty fields
    assert " |  | " not in text


def test_embed_text_brands_capped_at_five() -> None:
    many_brands = [f"Brand{i}" for i in range(10)]
    text = build_embed_text(_profile(brands=many_brands))
    # Only first 5 should appear
    for i in range(5):
        assert f"Brand{i}" in text
    # Brand9 should not be present (index > 4)
    assert "Brand9" not in text


# ---------------------------------------------------------------------------
# build_pinecone_metadata
# ---------------------------------------------------------------------------


def test_metadata_contains_identity_fields() -> None:
    meta = build_pinecone_metadata(_profile())
    assert meta["company_id"] == "cid-001"
    assert meta["name"] == "Landmark Group"
    assert meta["domain"] == "landmark.ae"


def test_metadata_contains_location_fields() -> None:
    meta = build_pinecone_metadata(_profile())
    assert meta["sector"] == "Retailers"
    assert meta["country_code"] == "AE"
    assert meta["city"] == "Dubai"


def test_metadata_contains_scores_when_provided() -> None:
    meta = build_pinecone_metadata(_profile(), score_row=_score())
    assert meta["base_score"] == 78.5
    assert meta["overall_confidence_band"] == "medium"


def test_metadata_flattens_dimension_scores() -> None:
    meta = build_pinecone_metadata(_profile(), score_row=_score())
    assert "organisational_scale_score" in meta
    assert meta["organisational_scale_score"] == 8.5
    assert "leadership_depth_score" in meta
    assert "sector_fit_confidence_score" in meta


def test_metadata_dimension_bands_flattened() -> None:
    meta = build_pinecone_metadata(_profile(), score_row=_score())
    assert meta["organisational_scale_band"] == "tight"
    assert meta["leadership_depth_band"] == "medium"


def test_metadata_no_scores_key_absent_when_no_score() -> None:
    meta = build_pinecone_metadata(_profile(), score_row=None)
    assert "base_score" not in meta
    assert "organisational_scale_score" not in meta


def test_metadata_null_fields_become_empty_strings() -> None:
    profile = _profile(sub_sector="", city="", domain="")
    meta = build_pinecone_metadata(profile)
    # None/empty values should not be None in metadata (Pinecone doesn't support null)
    assert meta["sub_sector"] == ""
    assert meta["city"] == ""


def test_metadata_founded_year_zero_for_missing() -> None:
    profile = _profile()
    profile["founded_year"] = None
    meta = build_pinecone_metadata(profile)
    assert meta["founded_year"] == 0


# ---------------------------------------------------------------------------
# OpenAIEmbeddingProvider (mocked)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_embed_texts_returns_vectors() -> None:
    fake_vectors = [[0.1, 0.2, 0.3]] * 2

    with patch(
        "hak_talent_mapping.services.vector.embeddings.AsyncOpenAI"
    ) as mock_cls:
        mock_client = MagicMock()
        item1 = MagicMock()
        item1.embedding = fake_vectors[0]
        item2 = MagicMock()
        item2.embedding = fake_vectors[1]
        response = MagicMock()
        response.data = [item1, item2]
        mock_client.embeddings.create = AsyncMock(return_value=response)
        mock_cls.return_value = mock_client

        provider = OpenAIEmbeddingProvider(api_key="test-key")
        result = await provider.embed_texts(["text one", "text two"])

    assert len(result) == 2
    assert result[0] == [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_embed_texts_empty_input_returns_empty() -> None:
    provider = OpenAIEmbeddingProvider(api_key="test-key")
    result = await provider.embed_texts([])
    assert result == []


@pytest.mark.asyncio
async def test_embed_one_returns_single_vector() -> None:
    fake_vector = [0.5] * 10

    with patch(
        "hak_talent_mapping.services.vector.embeddings.AsyncOpenAI"
    ) as mock_cls:
        mock_client = MagicMock()
        item = MagicMock()
        item.embedding = fake_vector
        response = MagicMock()
        response.data = [item]
        mock_client.embeddings.create = AsyncMock(return_value=response)
        mock_cls.return_value = mock_client

        provider = OpenAIEmbeddingProvider(api_key="test-key")
        result = await provider.embed_one("single text")

    assert result == fake_vector


@pytest.mark.asyncio
async def test_embed_texts_raises_vector_store_error_on_failure() -> None:
    from hak_talent_mapping.core.exceptions import VectorStoreError

    with patch(
        "hak_talent_mapping.services.vector.embeddings.AsyncOpenAI"
    ) as mock_cls:
        mock_client = MagicMock()
        mock_client.embeddings.create = AsyncMock(side_effect=Exception("API error"))
        mock_cls.return_value = mock_client

        provider = OpenAIEmbeddingProvider(api_key="test-key")

        with pytest.raises(VectorStoreError, match="OpenAI embedding call failed"):
            await provider.embed_texts(["some text"])
