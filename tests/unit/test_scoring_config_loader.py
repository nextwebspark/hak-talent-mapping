from __future__ import annotations

import textwrap
from pathlib import Path

import pytest

from hak_talent_mapping.core.exceptions import ScoringConfigError
from hak_talent_mapping.core.models import SectorScoringConfig
from hak_talent_mapping.services.enrichment.scoring.config_loader import (
    compute_config_hash,
    load_sector_config,
)


# ---------------------------------------------------------------------------
# Fixtures — write temp YAML files to a tmp_path dir
# ---------------------------------------------------------------------------


VALID_YAML = textwrap.dedent(
    """\
    sector: Retailers
    config_id: retailers_v1
    version: "1.0"
    search_queries:
      - "{name} retail overview"
    dimensions:
      - key: organisational_scale
        label: Organisational Scale
        default_weight: 0.35
        cold_start_weight: 0.35
        signals: []
      - key: leadership_depth
        label: Leadership Depth
        default_weight: 0.35
        signals: []
      - key: sector_fit_confidence
        label: Sector Fit Confidence
        default_weight: 0.30
        signals: []
    sub_sector_gate:
      enabled: false
      sub_sectors: []
      classification_signals: []
    sector_metadata_schema:
      store_count: "integer | null"
      ded_license_confirmed: "boolean | null"
    """
)


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """Return a temp directory with a valid retailers.yaml."""
    (tmp_path / "retailers.yaml").write_text(VALID_YAML)
    return tmp_path


# ---------------------------------------------------------------------------
# load_sector_config
# ---------------------------------------------------------------------------


def test_load_sector_config_returns_model(config_dir: Path) -> None:
    config = load_sector_config("Retailers", config_dir=str(config_dir))
    assert isinstance(config, SectorScoringConfig)
    assert config.sector == "Retailers"
    assert config.config_id == "retailers_v1"


def test_load_sector_config_dimensions(config_dir: Path) -> None:
    config = load_sector_config("Retailers", config_dir=str(config_dir))
    assert len(config.dimensions) == 3
    keys = [d.key for d in config.dimensions]
    assert "organisational_scale" in keys
    assert "sector_fit_confidence" in keys


def test_load_sector_config_search_queries(config_dir: Path) -> None:
    config = load_sector_config("Retailers", config_dir=str(config_dir))
    assert len(config.search_queries) == 1
    assert "{name}" in config.search_queries[0]


def test_load_sector_config_sub_sector_gate(config_dir: Path) -> None:
    config = load_sector_config("Retailers", config_dir=str(config_dir))
    assert config.sub_sector_gate.enabled is False


def test_load_sector_config_extra_fields_preserved(config_dir: Path) -> None:
    """sector_metadata_schema (not in Pydantic model) is accessible via model_extra."""
    config = load_sector_config("Retailers", config_dir=str(config_dir))
    extra = config.model_extra or {}
    assert "sector_metadata_schema" in extra
    assert "store_count" in extra["sector_metadata_schema"]


def test_load_sector_config_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(ScoringConfigError, match="No scoring config found"):
        load_sector_config("UnknownSector", config_dir=str(tmp_path))


def test_load_sector_config_invalid_yaml_raises(tmp_path: Path) -> None:
    (tmp_path / "brokenformat.yaml").write_text("sector: [\nunterminated")
    with pytest.raises(ScoringConfigError):
        load_sector_config("brokenformat", config_dir=str(tmp_path))


def test_load_sector_config_sector_name_lowercased_to_filename(tmp_path: Path) -> None:
    """'Retailers' maps to 'retailers.yaml'."""
    (tmp_path / "retailers.yaml").write_text(VALID_YAML)
    config = load_sector_config("Retailers", config_dir=str(tmp_path))
    assert config.sector == "Retailers"


def test_load_sector_config_spaces_in_sector_name(tmp_path: Path) -> None:
    """'Academic & Educational Services' maps to 'academic_and_educational_services.yaml'."""
    yaml_content = VALID_YAML.replace("sector: Retailers", "sector: Academic & Educational Services").replace(
        "config_id: retailers_v1", "config_id: academic_v1"
    )
    (tmp_path / "academic_and_educational_services.yaml").write_text(yaml_content)
    config = load_sector_config(
        "Academic & Educational Services", config_dir=str(tmp_path)
    )
    assert config.config_id == "academic_v1"


# ---------------------------------------------------------------------------
# compute_config_hash
# ---------------------------------------------------------------------------


def test_config_hash_is_12_chars(config_dir: Path) -> None:
    config = load_sector_config("Retailers", config_dir=str(config_dir))
    h = compute_config_hash(config)
    assert len(h) == 12


def test_config_hash_is_deterministic(config_dir: Path) -> None:
    config = load_sector_config("Retailers", config_dir=str(config_dir))
    assert compute_config_hash(config) == compute_config_hash(config)


def test_config_hash_changes_with_content(tmp_path: Path) -> None:
    yaml_v1 = VALID_YAML
    yaml_v2 = VALID_YAML.replace('version: "1.0"', 'version: "2.0"')

    (tmp_path / "retailers.yaml").write_text(yaml_v1)
    config_v1 = load_sector_config("Retailers", config_dir=str(tmp_path))

    (tmp_path / "retailers.yaml").write_text(yaml_v2)
    # Clear cache by loading under a different config_id
    yaml_v2_modified = yaml_v2.replace("config_id: retailers_v1", "config_id: retailers_v2")
    (tmp_path / "retailers.yaml").write_text(yaml_v2_modified)
    config_v2 = load_sector_config("Retailers", config_dir=str(tmp_path))

    assert compute_config_hash(config_v1) != compute_config_hash(config_v2)


# ---------------------------------------------------------------------------
# Integration with real retailers.yaml (if it exists)
# ---------------------------------------------------------------------------


def test_real_retailers_config_loads() -> None:
    """Smoke-test that the actual retailers.yaml in scoring_configs/ is valid."""
    try:
        config = load_sector_config("Retailers", config_dir="scoring_configs")
    except ScoringConfigError:
        pytest.skip("scoring_configs/retailers.yaml not found — run from repo root")
    assert config.sector == "Retailers"
    assert len(config.dimensions) >= 3
