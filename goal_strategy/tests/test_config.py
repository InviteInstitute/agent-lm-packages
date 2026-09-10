"""Config layer: rung engine semantics, reference resolution, validation, versioning."""
import textwrap

import pytest

from goal_strategy.config import (
    ConfigError,
    RungSpec,
    _parse_indicator,
    _parse_rungs,
    load_configs,
)
from goal_strategy.indicators import resolve_reference

CARD = {
    "playground_id": "toy",
    "objects": {"beacon": {"x": 100, "y": 0, "tolerance": 50,
                           "engagement": {"zones": {"front": {"y_min": 0}}}}},
    "regions": {"pad": {"x_min": -1, "x_max": 1, "y_min": -1, "y_max": 1}},
}


# ---------------------------------------------------------------- rung engine

def test_lower_is_better_edges_inclusive_to_better_bin():
    spec = RungSpec(kind="numeric", direction="lower_is_better",
                    edges=(190.0, 380.0, 570.0),
                    labels=("reached", "near", "approached", "never_close"))
    assert spec.evaluate(0) == "reached"
    assert spec.evaluate(190.0) == "reached"      # the pin-load-bearing case
    assert spec.evaluate(190.0001) == "near"
    assert spec.evaluate(380.0) == "near"
    assert spec.evaluate(570.0) == "approached"
    assert spec.evaluate(570.1) == "never_close"


def test_higher_is_better_edges_inclusive_to_better_bin():
    spec = RungSpec(kind="numeric", direction="higher_is_better",
                    edges=(0.05, 0.10, 0.20),
                    labels=("negligible", "some", "meaningful", "systematic"))
    assert spec.evaluate(0.049) == "negligible"
    assert spec.evaluate(0.05) == "some"
    assert spec.evaluate(0.10) == "meaningful"
    assert spec.evaluate(0.20) == "systematic"


def test_weight_cleared_ladder():
    # goal-anchored bands (reviewer rulings 2026-08-25): 700 -> initial,
    # 2500 -> med ("start high at 2501"), 4000 -> advanced
    spec = RungSpec(kind="numeric", direction="higher_is_better",
                    edges=(0.001, 701.0, 2501.0, 4000.0),
                    labels=("none", "initial_goal", "med_goal",
                            "high_goal", "advanced_goal"))
    assert spec.evaluate(0.0) == "none"
    assert spec.evaluate(0.5) == "initial_goal"
    assert spec.evaluate(700.0) == "initial_goal"
    assert spec.evaluate(701.0) == "med_goal"
    assert spec.evaluate(2500.0) == "med_goal"
    assert spec.evaluate(2501.0) == "high_goal"
    assert spec.evaluate(4000.0) == "advanced_goal"


def test_absent_label_on_numeric_rung():
    spec = RungSpec(kind="numeric", direction="lower_is_better", edges=(190.0,),
                    labels=("armed_within_radius", "armed_never_close"),
                    absent_label="not_armed")
    assert spec.evaluate(None) == "not_armed"
    assert spec.evaluate(190.0) == "armed_within_radius"
    assert spec.evaluate(191.0) == "armed_never_close"


def test_categorical_rung_mapping():
    spec = RungSpec(kind="categorical",
                    labels=("absent", "present_not_boost", "boost"))
    assert spec.evaluate(None) == "absent"
    assert spec.evaluate(frozenset()) == "present_not_boost"       # present, unmatched
    assert spec.evaluate(frozenset({"drop"})) == "present_not_boost"
    assert spec.evaluate(frozenset({"boost", "magnet"})) == "boost"  # noise values inert
    assert spec.evaluate("boost") == "boost"


# ------------------------------------------------------- parsing / validation

def test_numeric_rungs_require_direction():
    with pytest.raises(ConfigError, match="direction"):
        _parse_rungs({"edges": [1], "labels": ["a", "b"]}, {}, CARD, "t")


def test_categorical_rungs_reject_direction():
    with pytest.raises(ConfigError, match="categorical"):
        _parse_rungs({"labels": ["a", "b"], "direction": "lower_is_better"}, {}, CARD, "t")


def test_label_edge_arity_enforced():
    with pytest.raises(ConfigError, match="labels"):
        _parse_rungs({"edges": [1, 2], "labels": ["a", "b"],
                      "direction": "lower_is_better"}, {}, CARD, "t")


def test_edges_must_ascend():
    with pytest.raises(ConfigError, match="ascending"):
        _parse_rungs({"edges": [2, 1], "labels": ["a", "b", "c"],
                      "direction": "lower_is_better"}, {}, CARD, "t")


def test_edges_as_multiples_resolve_reference():
    spec = _parse_rungs({"reference": "object.tolerance",
                         "edges_as_multiples": [1.0, 2.0], "direction": "lower_is_better",
                         "labels": ["a", "b", "c"]}, {"object": "beacon"}, CARD, "t")
    assert spec.edges == (50.0, 100.0)
    assert spec.reference == "object.tolerance"


def test_resolve_reference_walks_nested_nodes():
    assert resolve_reference("object.engagement.zones", {"object": "beacon"}, CARD) \
        == {"front": {"y_min": 0}}


def test_unknown_indicator_rejected():
    with pytest.raises(ConfigError, match="unknown indicator"):
        _parse_indicator({"name": "x", "indicator": "nope", "binding": {}}, CARD, {}, "t")


def test_unbound_entity_rejected():
    with pytest.raises(ConfigError, match="not in playground card"):
        _parse_indicator({"name": "x", "indicator": "min_distance_to_object",
                          "binding": {"object": "ghost"}}, CARD, {}, "t")


def test_unknown_block_family_rejected():
    with pytest.raises(ConfigError, match="not in playground card"):
        _parse_indicator({"name": "x", "indicator": "code_movement_authored",
                          "binding": {"block_family": "ghost"}}, CARD, {}, "t")


def test_flag_rule_shape_enforced():
    with pytest.raises(ConfigError, match="flag_rule"):
        _parse_indicator({"name": "x", "indicator": "outcome_field",
                          "binding": {"field": "f"},
                          "flag_rules": [{"flag": "f"}]}, CARD, {}, "t")


# ------------------------------------------------------------- load_configs

def _write_cards(base, edges="[0.001, 810]"):
    (base / "playgrounds").mkdir(parents=True, exist_ok=True)
    (base / "goals").mkdir(parents=True, exist_ok=True)
    (base / "playgrounds" / "toy.yaml").write_text(textwrap.dedent("""
        playground_id: toy
        field_geometry: {playable_radius_mm: 1000}
        spawn_points: {default_start: {x: 0, y: 0, heading: 0}}
        objects: {beacon: {x: 100, y: 0, tolerance: 50}}
        regions: {pad: {x_min: -100, x_max: 100, y_min: -100, y_max: 100}}
        block_families: {movement: [pg_drivetrain_drive_for]}
    """))
    (base / "goals" / "toy.yaml").write_text(textwrap.dedent(f"""
        playground: toy
        version: 1
        goals:
          - id: g1
            intent:
              - name: score
                indicator: outcome_field
                binding: {{field: points}}
                rungs:
                  direction: higher_is_better
                  edges: {edges}
                  labels: [none, some, substantial]
            attainment: []
    """))


def test_load_configs_and_version_changes_with_card(tmp_path):
    _write_cards(tmp_path)
    load_configs.cache_clear()
    cfg1 = load_configs("toy", str(tmp_path))
    assert cfg1.goals[0].attainment == ()
    assert cfg1.goals[0].intent[0].rungs.edges == (0.001, 810.0)

    _write_cards(tmp_path, edges="[0.001, 900]")
    load_configs.cache_clear()
    cfg2 = load_configs("toy", str(tmp_path))
    assert cfg2.config_version != cfg1.config_version
    load_configs.cache_clear()


def test_goals_card_playground_mismatch_rejected(tmp_path):
    _write_cards(tmp_path)
    (tmp_path / "goals" / "toy.yaml").write_text("playground: other\ngoals: []\n")
    load_configs.cache_clear()
    with pytest.raises(ConfigError, match="goals card"):
        load_configs("toy", str(tmp_path))
    load_configs.cache_clear()
