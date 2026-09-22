"""Purpose-1 calibration substrate (SENSOR_TESTBATTERY §4.7): the
assembler joins per-run targets with per-program battery predictors —
loose sample, abstentions as NaN never zero, weight as validation."""
from __future__ import annotations

import math

import pytest

# goal_calibration builds a pandas DataFrame; pandas is an optional analysis
# extra ([goal-strategy-analysis]), so skip this module cleanly when absent.
pytest.importorskip("pandas")


@pytest.fixture(scope="module")
def table():
    from goal_strategy.goal_calibration import calibration_table
    return calibration_table()


def test_table_structure(table):
    from goal_strategy.goal_calibration import predictor_columns
    assert len(table) > 0
    for col in ("run_id", "student", "coverage_value", "coverage_rung",
                "weight_cleared", "roi_sim_rung", "roi_observed_off",
                "verdict"):
        assert col in table.columns
    preds = predictor_columns(table)
    assert preds
    assert table["run_id"].is_unique


def test_loose_sample_keeps_all_verdicts(table):
    """No certainty gating (Q1 ruling): flagged/disagreeing runs stay in
    with their verdicts as columns, never filtered."""
    verd = set(v for v in table["verdict"].unique() if v)
    # the eligible+telemetry population spans multiple verdict lanes
    assert len(verd) >= 2 or table["has_telemetry"].sum() == 0


def test_abstentions_are_nan_not_zero():
    """Plan §4: an abstained CHECK is UNOBSERVED (NaN, never 0). Since
    stays_on_island became an independent encounter measure (2026-09-01)
    abstention is PER-CHECK, not per-scenario: a T1 run may abstain
    stays_on_island (never hit an edge) while its clearing checks still
    measure. So the invariant is verified per (scenario, check) directly
    off the sweep CSV: wherever a row carries an abstain_reason, the
    corresponding table cell must be NaN."""
    import csv
    from pathlib import Path

    from goal_strategy.goal_calibration import calibration_table
    table = calibration_table().set_index("run_id")
    data = Path(__file__).resolve().parent.parent / "data" / "ccp_run_dataset"
    checked = 0
    with open(data / "stage3_battery.csv") as fh:
        for r in csv.DictReader(fh):
            if not r.get("abstain_reason") or r["run_id"] not in table.index:
                continue
            col = f"{r['scenario']}__{r['check']}"
            if col in table.columns:
                import math
                v = table.loc[r["run_id"], col]
                assert (isinstance(v, float) and math.isnan(v)), \
                    (r["run_id"], col, v, r["abstain_reason"])
                checked += 1
    assert checked > 0, "no abstained (scenario, check) rows found"
