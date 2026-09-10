"""External research data paths. Core profiling needs no data directory."""
import os
from pathlib import Path


def data_path(*parts, data_root=None):
    """Explicit root, environment, then the documented checkout convenience."""
    root = Path(data_root or os.environ.get("GOAL_STRATEGY_DATA_DIR") or Path.cwd() / "data" / "goal_strategy")
    return root.joinpath(*parts)


def require_data(path):
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Missing goal data: {path}. Set GOAL_STRATEGY_DATA_DIR or supply an explicit file path.")
    return path
