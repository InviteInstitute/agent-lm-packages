"""Per-registry-function tests on hand-built simulator fixtures: abstention reasons,
continuous values, origin seeding, latch semantics, zone flags, fallback flags."""
import math

import pytest

from goal_strategy.detector.simulation.simulate_path import (
    ObjectRef,
    PathStep,
    PlaygroundContext,
    SimulationResult,
)

from goal_strategy.codefacts import CodeFacts, extract_code_facts
from goal_strategy.indicators import EvalContext, REGISTRY

BEACON = ObjectRef(object_id="beacon", x=100.0, y=0.0, tolerance=50.0)

CARD = {
    "playground_id": "toy",
    "objects": {"beacon": {"x": 100, "y": 0, "tolerance": 50,
                           "engagement": {"zones": {
                               "direct": {"y_min": 0, "y_max": 10},
                               "stuck": {"y_min": 20, "y_max": 30},
                               "assisted": {"y_min": 30},
                           }}}},
    "regions": {"pad": {}},
}

ZONE_BINDING = {"object": "beacon", "state": "magnet_active",
                "zones_ref": "object.engagement.zones", "zone_axis": "y",
                "zone_flags": {"stuck": "stuck_zone"},
                "unmatched_flag": "geometry_undescribed"}


def step(i, x, y, magnet_fires=False):
    return PathStep(step=i, x=x, y=y, heading=90.0, block_type="b", block_id=str(i),
                    regions_entered=frozenset(), objects_in_tolerance=frozenset(),
                    magnet_fires=magnet_fires)


def ctx(sim=None, code_facts=None, params=None, full_sim="same",
        boundary_exceeded=False):
    context = PlaygroundContext(spawn_x=0.0, spawn_y=0.0, spawn_heading=90.0,
                                field_radius=2000.0, objects={"beacon": BEACON},
                                regions={})
    return EvalContext(
        program_id="p", playground="toy", card=CARD, context=context,
        block_families={"magnet": frozenset({"m"}), "movement": frozenset({"d"})},
        code_facts=code_facts, full_sim=sim if full_sim == "same" else full_sim,
        scored_sim=sim, playground_params=params,
        boundary_exceeded=boundary_exceeded, boundary_exit_step=None)


def sim_with(path=(), origin=(0.0, 0.0), fires_at=None, min_dists=None,
             coverage=None, net_disp=0.0):
    return SimulationResult(
        path=list(path), origin_x=origin[0], origin_y=origin[1],
        magnet_fires_at_step=fires_at,
        min_distance_to_objects=min_dists or {},
        region_coverage_fractions=coverage or {},
        net_displacement_from_spawn=net_disp)


# ------------------------------------------------------- min_distance_to_object

def test_min_distance_abstains_without_simulation():
    res = REGISTRY["min_distance_to_object"](ctx(None), {"object": "beacon"})
    assert res.abstained and res.abstain_reason == "no_simulation"
    assert res.value is None


def test_min_distance_is_origin_seeded():
    # Origin sits 40mm from the beacon; the path leads directly away, so no
    # segment point gets closer than the origin itself.
    sim = sim_with(path=[step(0, 60, 900)], origin=(60.0, 0.0),
                   min_dists={"beacon": 900.0})
    res = REGISTRY["min_distance_to_object"](ctx(sim), {"object": "beacon"})
    assert res.value == pytest.approx(40.0)


def test_min_distance_is_continuous_along_segments():
    # 2026-08-19 C031 falsification: the robot occupies every point of a
    # drive, so a segment sweeping past the beacon counts its closest
    # approach, not just its endpoints (both 900+mm away here).
    sim = sim_with(path=[step(0, -800, 30), step(1, 1000, 30)],
                   min_dists={"beacon": 900.0}, origin=(-800.0, 30.0))
    res = REGISTRY["min_distance_to_object"](ctx(sim), {"object": "beacon"})
    assert res.value == pytest.approx(30.0)   # perpendicular pass at y=30


def test_min_distance_uses_simulator_minimum_when_smaller():
    sim = sim_with(origin=(1000.0, 0.0), min_dists={"beacon": 12.5})
    res = REGISTRY["min_distance_to_object"](ctx(sim), {"object": "beacon"})
    assert res.value == pytest.approx(12.5)


# ------------------------------------------------------------- region_coverage

def test_region_coverage_value_and_default():
    sim = sim_with(coverage={"pad": 0.42})
    assert REGISTRY["region_coverage"](ctx(sim), {"region": "pad"}).value == 0.42
    assert REGISTRY["region_coverage"](ctx(sim), {"region": "other"}).value == 0.0
    res = REGISTRY["region_coverage"](ctx(None), {"region": "pad"})
    assert res.abstained and res.abstain_reason == "no_simulation"


# -------------------------------------------------- state_active_within_radius

def test_state_never_active_is_meaningful_absence_not_abstention():
    sim = sim_with(path=[step(0, 100, 0)], fires_at=None)
    res = REGISTRY["state_active_within_radius"](ctx(sim), ZONE_BINDING)
    assert not res.abstained and res.value is None and res.raw is None


def test_state_active_min_distance_only_counts_steps_after_activation():
    # Step 0 touches the beacon but the magnet arms at step 1, far away.
    sim = sim_with(path=[step(0, 100, 0), step(1, 500, 0, magnet_fires=True),
                         step(2, 400, 0)], fires_at=1)
    res = REGISTRY["state_active_within_radius"](ctx(sim), ZONE_BINDING)
    assert res.value == pytest.approx(300.0)   # 400 - 100, not 0
    assert res.flags == []                     # never qualified => no zone flags


def test_zone_flag_matched_zone():
    sim = sim_with(path=[step(0, 0, 25, magnet_fires=True), step(1, 100, 25)],
                   fires_at=0)
    res = REGISTRY["state_active_within_radius"](ctx(sim), ZONE_BINDING)
    assert res.value == pytest.approx(25.0)
    assert res.flags == ["stuck_zone"]


def test_zone_flag_described_zone_unflagged():
    sim = sim_with(path=[step(0, 100, 5, magnet_fires=True)], fires_at=0)
    res = REGISTRY["state_active_within_radius"](ctx(sim), ZONE_BINDING)
    assert res.flags == []


def test_zone_flag_unmatched_coordinate():
    sim = sim_with(path=[step(0, 100, -8, magnet_fires=True)], fires_at=0)
    res = REGISTRY["state_active_within_radius"](ctx(sim), ZONE_BINDING)
    assert res.flags == ["geometry_undescribed"]


def test_zone_boundary_tie_first_match_wins():
    # y=30 is in both "stuck" (20-30) and "assisted" (30-); card order wins.
    sim = sim_with(path=[step(0, 100, 30, magnet_fires=True)], fires_at=0)
    res = REGISTRY["state_active_within_radius"](ctx(sim), ZONE_BINDING)
    assert res.flags == ["stuck_zone"]


def test_zone_precedence_later_described_step_clears_flag():
    # First qualifying step in the stuck zone, a later one in direct-attraction
    # range: engagement is plausible — no flag (revised spec, 2026-08-18).
    sim = sim_with(path=[step(0, 100, 25, magnet_fires=True), step(1, 100, 5)],
                   fires_at=0)
    res = REGISTRY["state_active_within_radius"](ctx(sim), ZONE_BINDING)
    assert res.flags == []


def test_zone_precedence_flagged_steps_keep_first_outcome():
    # No qualifying sample ever reaches an unflagged described zone: the first
    # sample's outcome stands (undescribed first, stuck later -> undescribed).
    # y runs 12 -> 25 so the continuous traversal never crosses the described
    # "direct" band (0-10) — under continuous sampling a crossing would clear.
    sim = sim_with(path=[step(0, 100, 12, magnet_fires=True), step(1, 100, 25)],
                   fires_at=0)
    res = REGISTRY["state_active_within_radius"](ctx(sim), ZONE_BINDING)
    assert res.flags == ["geometry_undescribed"]


def test_zone_check_is_opt_in():
    binding = {"object": "beacon", "state": "magnet_active"}
    sim = sim_with(path=[step(0, 100, -8, magnet_fires=True)], fires_at=0)
    res = REGISTRY["state_active_within_radius"](ctx(sim), binding)
    assert res.flags == []


def test_unknown_simulator_state_abstains():
    sim = sim_with(path=[step(0, 100, 0)], fires_at=0)
    res = REGISTRY["state_active_within_radius"](
        ctx(sim), {"object": "beacon", "state": "warp_drive"})
    assert res.abstained and res.abstain_reason == "unknown_simulator_state"


def test_truncated_slice_nulls_latch_reads_not_armed():
    # Emulates §6a: arming after the boundary exit leaves the sliced result
    # with magnet_fires_at_step=None -> meaningful absence.
    sim = sim_with(path=[step(0, 100, 0)], fires_at=None)
    res = REGISTRY["state_active_within_radius"](ctx(sim), ZONE_BINDING)
    assert res.raw is None and not res.abstained


# --------------------------------------------------------- code-channel facts

def test_code_state_authored_ladder_of_raws():
    fn = REGISTRY["code_state_authored"]
    binding = {"block_family": "magnet"}
    assert fn(ctx(code_facts=None), binding).abstain_reason == "no_code"
    absent = CodeFacts({"magnet": 0}, {"magnet": frozenset()})
    assert fn(ctx(code_facts=absent), binding).raw is None
    present = CodeFacts({"magnet": 1}, {"magnet": frozenset({"drop"})})
    assert fn(ctx(code_facts=present), binding).raw == frozenset({"drop"})
    boost = CodeFacts({"magnet": 2}, {"magnet": frozenset({"boost", "magnet"})})
    res = fn(ctx(code_facts=boost), binding)
    assert res.raw == frozenset({"boost", "magnet"})
    assert res.value == "boost|magnet"
    assert res.channel == "code"


def test_code_movement_authored_counts():
    fn = REGISTRY["code_movement_authored"]
    facts = CodeFacts({"movement": 3}, {"movement": frozenset()})
    res = fn(ctx(code_facts=facts), {"block_family": "movement"})
    assert res.value == 3 and res.channel == "code"
    assert fn(ctx(code_facts=None), {"block_family": "movement"}).abstained


def test_extract_code_facts_active_blocks_only():
    xml = """<xml xmlns="https://developers.google.com/blockly/xml">
      <block type="pg_events_when_started" id="e1"><next>
        <block type="m" id="m1"><field name="ACTION">boost</field></block>
      </next></block>
      <block type="m" id="m2"><field name="ACTION">drop</field></block>
    </xml>"""
    from goal_strategy.detector.parsing.parse_blocks import parse_workspace
    program = parse_workspace(xml, "p")
    facts = extract_code_facts(program, {"magnet": frozenset({"m"})})
    # The detached (orphan) drop-block does not count — corpus-verified scope.
    assert facts.family_counts["magnet"] == 1
    assert facts.family_field_values["magnet"] == frozenset({"boost"})


# ------------------------------------------------------ displacement_from_spawn

def test_displacement_outcome_channel():
    params = {"gps_x_position": 300.0, "gps_y_position": 400.0}
    res = REGISTRY["displacement_from_spawn"](
        ctx(params=params), {"source": "outcome", "x_field": "gps_x_position",
                             "y_field": "gps_y_position"})
    assert res.value == pytest.approx(500.0)
    assert res.channel == "outcome" and res.flags == []


def test_displacement_falls_back_to_simulation_with_flags():
    sim = sim_with(net_disp=123.0)
    res = REGISTRY["displacement_from_spawn"](
        ctx(sim), {"source": "outcome", "x_field": "gps_x_position",
                   "y_field": "gps_y_position"})
    assert res.value == 123.0 and res.channel == "simulation"
    assert res.flags == ["simulated_fallback", "simulated_attainment"]


def test_displacement_abstains_with_neither_channel():
    res = REGISTRY["displacement_from_spawn"](
        ctx(None), {"source": "outcome", "x_field": "x", "y_field": "y"})
    assert res.abstained and res.abstain_reason == "no_simulation"


def test_displacement_simulation_source():
    sim = sim_with(net_disp=77.0)
    res = REGISTRY["displacement_from_spawn"](ctx(sim), {"source": "simulation"})
    assert res.value == 77.0 and res.channel == "simulation" and res.flags == []


# --------------------------------------------------------------- outcome_field

def test_outcome_field_values_and_abstentions():
    fn = REGISTRY["outcome_field"]
    assert fn(ctx(params={"weight": 810}), {"field": "weight"}).value == 810.0
    assert fn(ctx(params=None), {"field": "weight"}).abstain_reason == "outcome_field_absent"
    assert fn(ctx(params={}), {"field": "weight"}).abstain_reason == "outcome_field_absent"
    assert fn(ctx(params={"weight": None}), {"field": "weight"}).abstain_reason \
        == "outcome_field_absent"
    assert fn(ctx(params={"weight": "n/a"}), {"field": "weight"}).abstain_reason \
        == "outcome_field_invalid"


# ----------------------------------------------------------- boundary_exceeded

def test_boundary_exceeded_mirrors_profile_flag():
    sim = sim_with()
    assert REGISTRY["boundary_exceeded"](ctx(sim, boundary_exceeded=True), {}).value is True
    assert REGISTRY["boundary_exceeded"](ctx(None), {}).abstain_reason == "no_simulation"


# ------------------------------------------------- remain_on_island (2026-08-25)

ISLAND_CARD = {
    **CARD,
    "field_boundary": {"polygon_mm": [[-1000, -1000], [1000, -1000],
                                      [1000, 1000], [-1000, 1000]]},
    "robot": {"length_mm": 0.0, "width_mm": 0.0},   # zero tolerance: centre rule
}


def _island_ctx(**kw):
    import dataclasses
    return dataclasses.replace(ctx(**{k: v for k, v in kw.items()
                                      if k != "card"}), card=ISLAND_CARD)


def test_outcome_on_island_observed_positions():
    fn = REGISTRY["outcome_on_island"]
    binding = {"x_field": "gx", "y_field": "gy"}
    assert fn(_island_ctx(params={"gx": 0, "gy": 0}), binding).value == "on_island"
    assert fn(_island_ctx(params={"gx": 5000, "gy": 0}), binding).value == "off_island"
    # no GPS -> abstain (the sim side fills these)
    res = fn(_island_ctx(params=None), binding)
    assert res.abstained and res.abstain_reason == "gps_unavailable"
    assert fn(_island_ctx(params={"gx": "n/a", "gy": 0}), binding).abstain_reason \
        == "gps_unavailable"
    assert fn(_island_ctx(params={"gx": 0, "gy": 0}), binding).channel == "outcome"


def test_sim_on_island_follows_boundary_exceeded():
    fn = REGISTRY["sim_on_island"]
    sim = sim_with()
    assert fn(_island_ctx(sim=sim), {}).value == "on_island"
    res = fn(_island_ctx(sim=sim, boundary_exceeded=True), {})
    assert res.value == "off_island" and res.channel == "simulation"
    assert fn(_island_ctx(sim=None), {}).abstain_reason == "no_simulation"
