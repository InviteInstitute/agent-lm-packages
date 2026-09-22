"""Banded rollup v2 unit tests (§4.8 fully-ruled spec, 2026-09-04).

Synthetic reports against a synthetic card: the flat mean over VALID
tests, the ruled rung cuts, U-with-subtag (D3b), the sparse and
budget-sensitivity certainty demotions (D4a), and the label contract.
The retired v1 (weighted-mean capability levels) has no tests — D2(a).
"""
from __future__ import annotations

from goal_strategy.battery_rollup import (
    GoalBand, banded_invariant, banded_rollup, load_rollup_card,
)
from goal_strategy.testcases import (
    BatteryReport, CheckResult, ScenarioResult,
)

GOAL = "clear_debris_zone"


def _scenario(sid, checks, family="fam"):
    return ScenarioResult(scenario_id=sid, goal=GOAL, checks=tuple(checks),
                          construct="static", family=family)


def _measured(value):
    return CheckResult("m", "measured", "m", goal=GOAL, value=value)


def _abstained(reason):
    return CheckResult("m", "measured", "m", goal=GOAL,
                       abstained=True, abstain_reason=reason)


def _report(*scenarios):
    return BatteryReport(program_id="p", eligible=True,
                         qualifying_blocks=("x",), scenarios=tuple(scenarios))


def _card(sparse_min=0):
    return {"goals": {GOAL: {
        "check": "m",
        "rungs": [{"min": 0.35, "band": "high"},
                  {"min": 0.10, "band": "mid"},
                  {"min": 0.02, "band": "low"},
                  {"min": 0.0, "band": "none"}],
        "sparse_min_valid": sparse_min,
    }}}


def test_flat_mean_over_valid_tests_only():
    rep = _report(_scenario("a", [_measured(0.4)]),
                  _scenario("b", [_measured(0.2)]),
                  _scenario("c", [_abstained("encounter_not_reached")]))
    gb = banded_rollup(rep, _card())[GOAL]
    assert abs(gb.score - 0.3) < 1e-9          # mean of 0.4, 0.2 — abstain skipped
    assert gb.n_valid == 2 and gb.n_abstained == 1
    assert gb.band == "mid" and not gb.indeterminate


def test_rung_cuts_are_inclusive_at_min():
    for score, band in ((0.35, "high"), (0.10, "mid"),
                        (0.02, "low"), (0.0, "none")):
        rep = _report(_scenario("a", [_measured(score)]))
        assert banded_rollup(rep, _card())[GOAL].band == band


def test_all_abstained_is_U_with_dominant_subtag():
    rep = _report(_scenario("a", [_abstained("test_not_activated")]),
                  _scenario("b", [_abstained("test_not_activated")]),
                  _scenario("c", [_abstained("encounter_not_reached")]))
    gb = banded_rollup(rep, _card())[GOAL]
    assert gb.indeterminate and gb.band is None and gb.score is None
    assert gb.abstain_subtag == "test_not_activated"
    assert gb.label == "U/test_not_activated"


def test_mixed_abstention_subtag():
    rep = _report(_scenario("a", [_abstained("x")]),
                  _scenario("b", [_abstained("y")]),
                  _scenario("c", [_abstained("z")]))
    assert banded_rollup(rep, _card())[GOAL].abstain_subtag == "mixed"


def test_sparse_evidence_demotes_certainty_not_score():
    rep = _report(_scenario("a", [_measured(0.5)]))
    gb = banded_rollup(rep, _card(sparse_min=3))[GOAL]
    assert gb.band == "high"                    # score untouched
    assert gb.certainty == "reduced"
    assert "sparse_evidence" in gb.certainty_reasons


def test_budget_sensitivity_keeps_primary_band_and_demotes():
    primary = _report(_scenario("a", [_measured(0.4)]))     # high
    alt = _report(_scenario("a", [_measured(0.05)]))        # low
    gb = banded_invariant([primary, alt], _card())[GOAL]
    assert gb.band == "high"                    # D4(a): primary kept
    assert gb.certainty == "reduced"
    assert "budget_sensitive" in gb.certainty_reasons


def test_budget_agreement_stays_full():
    primary = _report(_scenario("a", [_measured(0.4)]))
    alt = _report(_scenario("a", [_measured(0.5)]))         # same band
    gb = banded_invariant([primary, alt], _card())[GOAL]
    assert gb.certainty == "full" and not gb.certainty_reasons


def test_real_card_loads_with_ruled_cuts():
    card = load_rollup_card("castle_crashers")
    cdz = card["goals"]["clear_debris_zone"]
    roi = card["goals"]["remain_on_island"]
    assert cdz["check"] == "proportion_cleared"
    assert [r["min"] for r in cdz["rungs"]] == [0.35, 0.10, 0.02, 0.0]
    assert roi["check"] == "stays_on_island"
    assert [r["min"] for r in roi["rungs"]] == [0.5, 0.1, 0.0]
    assert roi.get("calibrated_model")
