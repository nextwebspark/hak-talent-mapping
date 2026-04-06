from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import yaml

from hak_talent_mapping.core.exceptions import ScoringConfigError
from hak_talent_mapping.core.models import SectorScoringConfig

# Cache loaded configs in memory (keyed by config_id)
_cache: dict[str, SectorScoringConfig] = {}


def load_sector_config(sector: str, config_dir: str = "scoring_configs") -> SectorScoringConfig:
    """Load and validate a sector scoring config from YAML.

    Args:
        sector: Sector name (e.g. "Retailers"). Converted to filename by
                lowercasing and replacing spaces with underscores.
        config_dir: Directory containing YAML configs.

    Returns:
        Validated SectorScoringConfig instance.

    Raises:
        ScoringConfigError: If the file is missing or the YAML is invalid.
    """
    filename = sector.lower().replace(" ", "_").replace("&", "and") + ".yaml"
    path = Path(config_dir) / filename

    if not path.exists():
        raise ScoringConfigError(
            f"No scoring config found for sector '{sector}' at {path}"
        )

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ScoringConfigError(
            f"Invalid YAML in scoring config {path}: {exc}"
        ) from exc

    try:
        config = SectorScoringConfig.model_validate(raw)
    except Exception as exc:
        raise ScoringConfigError(
            f"Scoring config validation failed for {sector}: {exc}"
        ) from exc

    _cache[config.config_id] = config
    return config


def compute_config_hash(config: SectorScoringConfig) -> str:
    """Return a short hash of the config content for reproducibility tracking."""
    content = json.dumps(config.model_dump(), sort_keys=True, default=str)
    return hashlib.sha256(content.encode()).hexdigest()[:12]


def get_sector_metadata_schema(config: SectorScoringConfig) -> dict[str, Any] | None:
    """Extract the sector_metadata_schema from the YAML config if present."""
    # The schema is stored in the raw YAML under sector_metadata_schema
    # but not in the Pydantic model — we re-read it as extra data via model_extra
    return config.model_extra.get("sector_metadata_schema") if config.model_extra else None
