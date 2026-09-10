"""Version checks before joining generated research tables."""
from .config import load_configs
from .serialize import PIPELINE_VERSION


def validate_artifact(rows, playground="castle_crashers"):
    version = load_configs(playground).config_version
    for row in rows:
        if (row.get("pipeline_version") != PIPELINE_VERSION or
            row.get("config_version") != version or row.get("playground") != playground):
            raise ValueError("This analysis table uses missing or different pipeline/configuration versions. Regenerate it with the current goal tools before joining results.")
