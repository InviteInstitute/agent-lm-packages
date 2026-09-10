"""Rung sweep (OI-9 data layer) — column shape, 307 agreement with the
fidelity sweep, CSV↔profile spot-checks, and the inert provenance card key."""
from __future__ import annotations

from goal_strategy.paths import data_path

import csv
from pathlib import Path

import pytest

from goal_strategy.config import load_configs
from goal_strategy.profile import _profile
from goal_strategy.rung_sweep import identity_columns, indicator_columns

_ROOT = Path(__file__).resolve().parent.parent
RUNGS = data_path() / "ccp_run_dataset" / "stage2_rungs.csv"
FIDELITY = data_path() / "ccp_run_dataset" / "stage2_fidelity.csv"


def test_column_shape_matches_card():
    # eight indicators × five columns each, after the versioned identity columns
    # (movement_authored removed, remain_on_island's two indicators added —
    # 2026-08-25 rung-review rulings)
    cols = indicator_columns()
    assert len(cols) == 8 * 5
    assert cols[0] == "playground_engagement__robot_moved__value"
    assert "remain_on_island__on_island_observed__rung" in cols
    assert "remain_on_island__on_island_sim__rung" in cols
    assert "clear_debris_zone__weight_cleared__rung" in cols
    assert len(identity_columns()) == 12
    assert {"pipeline_version", "playground", "config_version"} <= set(identity_columns())


@pytest.fixture(scope="module")
def rows():
    if not RUNGS.exists():
        pytest.skip("stage2_rungs.csv not generated")
    with open(RUNGS) as fh:
        return list(csv.DictReader(fh))


def test_sweep_covers_all_runs_and_307(rows):
    assert len(rows) == 7984
    v307 = {r["run_id"] for r in rows if r["validation_307"] == "True"}
    assert len(v307) == 307
    if FIDELITY.exists():
        with open(FIDELITY) as fh:
            fid307 = {r["run_id"] for r in csv.DictReader(fh)
                      if r["validation_307"] == "True"}
        assert v307 == fid307   # same last-telemetry-run-per-session rule


def test_rows_match_live_profile_spot_check(rows):
    from goal_strategy.ccp_runs import load_ccp_runs
    by_id = {r.run_id: r for r in load_ccp_runs()}
    picked = [r for r in rows if r["has_params"] == "True"][::1500][:3]
    for row in picked:
        run = by_id[row["run_id"]]
        prof = _profile(run.workspace_xml or "", run.run_id,
                        run.playground_params or {})
        for goal in prof.goals:
            for ind in goal.intent + goal.attainment:
                base = f"{goal.goal}__{ind.name}"
                assert row[f"{base}__rung"] == (ind.rung or "")
                want = "" if ind.value is None else str(ind.value)
                assert row[f"{base}__value"] == want
                assert row[f"{base}__channel"] == ind.channel


def test_provenance_card_key_parsed_and_inert():
    specs = {ind.name: ind for g in load_configs("castle_crashers").goals
             for ind in g.intent + g.attainment}
    prov = {n: (s.rungs.provenance if s.rungs else None)
            for n, s in specs.items()}
    assert prov["plow_approach_intent"].startswith("design")
    assert prov["plow_proximity_execution"].startswith("design")
    assert prov["debris_zone_coverage"].startswith("abstract")
    assert prov["weight_cleared"].startswith("design")   # goal-anchored 2026-08-25
    assert prov["robot_moved"].startswith("abstract")
    assert "movement_authored" not in prov   # removed 2026-08-25
    assert prov["on_island_observed"].startswith("exact")
    assert prov["on_island_sim"].startswith("exact")
    # inert: rung assignment is untouched by the annotation
    ladder = specs["plow_approach_intent"].rungs
    assert ladder.evaluate(200) == "near" and ladder.evaluate(190) == "reached"
