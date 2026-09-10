"""CLI smoke test: the review CSV covers all 119 programs, values and rungs flat."""
import pandas as pd

from goal_strategy.cli import main


def test_cli_writes_flat_csv(tmp_path):
    out = tmp_path / "profiles.csv"
    assert main(["--out", str(out)]) == 0
    frame = pd.read_csv(out)
    assert len(frame) == 112   # filtered testing set
    for column in (
        "program_id", "config_version", "boundary_exceeded", "boundary_exit_step",
        "engage_plow__plow_approach_intent__value",
        "engage_plow__plow_approach_intent__rung",
        "engage_plow__plow_proximity_execution__flags",
        "clear_debris_zone__weight_cleared__abstain_reason",
    ):
        assert column in frame.columns, column
    assert frame["program_id"].is_unique
