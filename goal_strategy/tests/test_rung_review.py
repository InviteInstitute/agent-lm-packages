"""Rung-review page — pure-helper tests (aggregations, ladder ordering,
catalog provenance). The Streamlit shell is exercised by hand per the plan's
verification list."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

_ROOT = Path(__file__).resolve().parent.parent

from goal_strategy.viz import rung_review as rr


def _df(with_abstained=False):
    # two sessions: S1 climbs low→mid→high; S2 opens high, ends mid
    rows = [
        ("r1", "S1", 1, False, 48.0, "low"),
        ("r2", "S1", 2, False, 60.0, "mid"),
        ("r3", "S1", 3, True, 120.0, "high"),
        ("r4", "S2", 1, False, 150.0, "high"),
        ("r5", "S2", 2, True, 95.0, "mid"),
    ]
    if with_abstained:
        rows.append(("r6", "S2", 3, False, None, None))
    return pd.DataFrame(rows, columns=[
        "run_id", "session", "run_seq", "validation_307",
        "g__i__value", "g__i__rung"])


LABELS, DIRECTION = ["low", "mid", "high"], "higher_is_better"


def test_ladder_order_and_ranks():
    assert rr.ladder_order(LABELS, DIRECTION) == ["low", "mid", "high"]
    # lower_is_better reverses; absent_label sits below the worst rung
    assert rr.ladder_order(["reached", "never"], "lower_is_better",
                           "not_armed") == ["not_armed", "never", "reached"]
    ranks = rr.rung_ranks(["reached", "never"], "lower_is_better", "not_armed")
    assert ranks == {"never": 0, "reached": 1, "not_armed": -1}


def test_occupancy_counts_and_abstained_row():
    occ = rr.occupancy(_df(with_abstained=True), "g__i", LABELS, DIRECTION)
    got = dict(zip(occ["rung"], occ["runs"]))
    assert got == {"low": 1, "mid": 2, "high": 2, "(abstained)": 1}


def test_near_edge_window():
    table, tols = rr.near_edge(_df(), "g__i", [50, 100], pct=0.10)
    assert tols == {50: 5.0, 100: 10.0}
    assert list(table["run_id"]) == ["r1", "r5"]   # 48 near 50, 95 near 100


def test_near_edge_zero_edge_falls_back_to_spread():
    df = _df()
    _, tols = rr.near_edge(df, "g__i", [0.0], pct=0.10)
    assert tols[0.0] > 0   # data-driven window, not a zero-width band


def test_progress_occupancy_shares():
    po = rr.progress_occupancy(_df(), "g__i", LABELS, DIRECTION, n_bins=2)
    first, last = po.iloc[0], po.iloc[1]
    assert first["n"] == 2 and last["n"] == 3
    assert first["low"] == 0.5 and first["high"] == 0.5
    assert abs(last["mid"] - 2 / 3) < 1e-9 and abs(last["high"] - 1 / 3) < 1e-9


def test_first_reach_curves():
    curves, max_k, n_sessions = rr.first_reach(_df(), "g__i", LABELS, DIRECTION)
    assert n_sessions == 2 and max_k == 3
    assert set(curves) == {"mid", "high"}   # the floor rung is skipped
    assert curves["mid"] == [0.5, 1.0, 1.0]    # S2 opens ≥mid; S1 reaches at k=2
    assert curves["high"] == [0.5, 0.5, 1.0]   # S2 at k=1; S1 at k=3


def test_best_vs_final_regression():
    bf = rr.best_vs_final(_df(), "g__i", LABELS, DIRECTION)
    # S1 ends at its best (high); S2's best (high) beats its final (mid)
    assert bf == {"sessions": 2, "regressed": 1, "regressed_share": 0.5}


def test_high_certainty_mask():
    df = pd.DataFrame({
        "run_id": ["a", "b", "c", "d", "e"],
        "has_params": [True, True, True, False, False],
        "g__i__flags": ["", "sensor_reading_stale", "", "", "fabricated_motion"],
        "g__i__abstain_reason": ["", "", "", "", ""],
    })
    verdicts = {"a": "agree", "b": "agree", "c": "sensor_uncertainty"}
    m = rr.high_certainty_mask(df, "g__i", verdicts)
    # a: clean + agree → in; b: stale flag → out; c: clean but disagreeing
    # verdict → out; d: non-telemetry, clean → in (no verdict exists);
    # e: non-telemetry but flagged → out
    assert list(df.loc[m, "run_id"]) == ["a", "d"]
    # without a verdict map, flags alone decide
    m2 = rr.high_certainty_mask(df, "g__i")
    assert list(df.loc[m2, "run_id"]) == ["a", "c", "d"]
    # abstention excludes even when unflagged
    df.loc[0, "g__i__abstain_reason"] = "outcome_field_absent"
    assert list(df.loc[rr.high_certainty_mask(df, "g__i", verdicts),
                       "run_id"]) == ["d"]


def test_coverage_weight_monotone_case():
    df = pd.DataFrame({
        "clear_debris_zone__debris_zone_coverage__value": [0.0, 0.1, 0.2, 0.3],
        "clear_debris_zone__weight_cleared__value": [0.0, 200.0, 900.0, 2000.0],
        "run_id": ["a", "b", "c", "d"], "cohort": ["X"] * 4,
    })
    sc, rho, _ = rr.coverage_weight(df)
    assert len(sc) == 4 and abs(rho - 1.0) < 1e-9


def test_indicator_catalog_provenance():
    from goal_strategy.viz import data as vd
    cat = {c["name"]: c for c in vd.indicator_catalog()}
    assert cat["plow_approach_intent"]["design_informed"]        # reference-derived
    assert cat["plow_proximity_execution"]["design_informed"]    # provenance: design
    assert not cat["debris_zone_coverage"]["design_informed"]    # abstract T-3 ladder
    # goal-anchored since the 2026-08-25 ruling (communicated 700kg target)
    assert cat["weight_cleared"]["design_informed"]
    assert cat["weight_cleared"]["provenance"].startswith("design")
    assert cat["plow_approach_intent"]["edges"] == [190.0, 380.0, 570.0]
    assert cat["plow_proximity_execution"]["absent_label"] == "not_armed"
    assert cat["weight_cleared"]["edges"] == [0.001, 701.0, 2501.0, 4000.0]
    # remain_on_island (2026-08-25): categorical pair, observed + sim
    assert cat["on_island_observed"]["rung_kind"] == "categorical"
    assert cat["on_island_sim"]["labels"] == ["unknown", "off_island", "on_island"]
