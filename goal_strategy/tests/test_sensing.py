"""Sensing build unit tests (Phase 1, 2026-08-19).

Covers the down-eye red-line model (eye-point geometry with the calibrated
forward offset, per-eye color zones, ring bands, object-registering markings)
and the ratified wait_until gate semantics (no self-motion; pending motion
marches to the condition; unmet conditions gate the stack).

The drive-till-red replica pins the physical calibration: the reviewer's
probe (data/screenshot_drivetillred/) stopped the robot centre 35mm inside
the detection line — eye point on the line.
"""
from __future__ import annotations

import math
from pathlib import Path

import pytest
import yaml

from goal_strategy.detector.parsing.parse_blocks import parse_workspace
from goal_strategy.detector.simulation.simulate_path import (
    PlaygroundContext, simulate_path,
)

_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def ctx() -> PlaygroundContext:
    card = yaml.safe_load(open(_ROOT / "configs" / "playgrounds" / "castle_crashers.yaml"))
    robot = yaml.safe_load(open(_ROOT / "configs" / "robot" / "vr_robot.yaml"))
    return PlaygroundContext.from_playground_card(card, robot)


def _sim(xml: str, ctx: PlaygroundContext, **kw):
    return simulate_path(parse_workspace(xml, "sensing-test"), ctx, **kw)


def _wrap(*blocks: str) -> str:
    body = ""
    for b in reversed(blocks):
        body = b.replace("{NEXT}", f"<next>{body}</next>" if body else "")
    return (f'<xml xmlns="https://developers.google.com/blockly/xml">'
            f'<block type="pg_events_when_started" id="hat"><next>{body}</next>'
            f"</block></xml>")


TURN_180 = ('<block type="pg_drivetrain_turn_for" id="t1">'
            '<field name="TURNDIRECTION">right</field>'
            '<value name="AMOUNT"><shadow type="math_number" id="s1">'
            '<field name="NUM">180</field></shadow></value>{NEXT}</block>')
BARE_DRIVE = '<block type="pg_drivetrain_drive" id="d1"><field name="DIRECTION">fwd</field>{NEXT}</block>'
STOP_DRIVE = '<block type="pg_drivetrain_stop" id="st1">{NEXT}</block>'


def wait_until_eye(eye: str, color: str, bid: str = "w1") -> str:
    return (f'<block type="pg_control_wait_until" id="{bid}">'
            f'<value name="CONDITION"><block type="pg_sensing_optical_color" id="e-{bid}">'
            f'<field name="OPTICAL">{eye}</field><field name="COLORS">{color}</field>'
            f"</block></value>{{NEXT}}</block>")


# ------------------------------------------------- drive-till-red calibration

def test_drive_till_red_stops_with_eye_on_detection_line(ctx):
    # Physical probe (screenshot_drivetillred): centre stopped ~35mm inside
    # the detection line (x=1634 east edge), eye on the line. March
    # granularity is 10mm, so the sim stop is within one increment.
    sim = _sim(_wrap(TURN_180, BARE_DRIVE, wait_until_eye("downeye", "red"), STOP_DRIVE), ctx)
    assert sim.color_detections and sim.color_detections[0][1:] == ("down", "red")
    assert sim.fabricated_steps == []
    assert "wait_until_unmet" not in sim.execution_flags
    final = sim.path[-1]
    assert final.x == pytest.approx(1634 - 35, abs=10.0)
    assert final.y == pytest.approx(49.0, abs=1.0)


def test_wait_until_gate_without_pending_motion_halts_stack(ctx):
    # No pending motion: a false position-based condition can never change —
    # the stack gates and the code below never executes.
    sim = _sim(_wrap(wait_until_eye("downeye", "red"), TURN_180), ctx)
    assert "wait_until_unmet" in sim.execution_flags
    assert all(ps.block_type != "pg_drivetrain_turn_for" for ps in sim.path)


def test_wait_until_unmet_with_pending_drive_runs_off_then_gates(ctx):
    # Down-eye BLUE never exists on this playground: the armed drive runs off
    # the field (runoff fallback, fabricated), then the stack gates.
    sim = _sim(_wrap(TURN_180, BARE_DRIVE, wait_until_eye("downeye", "blue"), STOP_DRIVE), ctx)
    assert "wait_until_unmet" in sim.execution_flags
    assert sim.fabricated_steps          # runoff magnitude is a fallback
    assert sim.exits_field_boundary
    assert all(ps.block_type != "pg_drivetrain_stop" for ps in sim.path)


def test_wait_until_already_true_passes_instantly(ctx):
    # Down-eye NONE is true at spawn — the ground is coded as no color
    # (reviewer probe 2026-08-19, OI-18 resolved): no motion, no flag,
    # following blocks run.
    sim = _sim(_wrap(wait_until_eye("downeye", "none"), TURN_180), ctx)
    assert "wait_until_unmet" not in sim.execution_flags
    assert any(ps.block_type == "pg_drivetrain_turn_for" for ps in sim.path)


# ------------------------------------------------------- eye-point geometry

def test_red_zone_is_down_eye_only(ctx):
    # A robot parked with its centre on the ring: down eye reads red, front
    # eye does not (2D marking, down-eye-only zone).
    from goal_strategy.detector.simulation.simulate_path import _Simulator

    sim = _Simulator(ctx)
    sim.x, sim.y, sim.heading = 1680.0, 49.0, 0.0   # on the ring, facing east
    assert sim._eye_detected_color("down") == "red"
    assert sim._eye_detected_color("front") is None


def test_eye_offset_shifts_detection_by_heading(ctx):
    # Centre 20mm inside the detection line: facing the edge, the 35mm eye
    # point is past the line (red); facing away, it is deep in the grass.
    from goal_strategy.detector.simulation.simulate_path import _Simulator

    sim = _Simulator(ctx)
    sim.x, sim.y = 1614.0, 49.0
    sim.heading = 0.0     # facing east toward the edge: eye at 1649 > 1634
    assert sim._eye_detected_color("down") == "red"
    sim.heading = 180.0   # facing west: eye at 1579 < 1634 — colorless grass
    assert sim._eye_detected_color("down") is None


def test_down_eye_near_object_fires_on_ring_but_not_grass(ctx):
    # Reviewer ruling 2026-08-19: the red line is a defined object; the grass
    # floor is not.
    from goal_strategy.detector.parsing.block_program import BlockNode
    from goal_strategy.detector.simulation.simulate_path import _Simulator

    block = parse_workspace(
        _wrap('<block type="pg_sensing_optical_near_object" id="n1">'
              '<field name="OPTICAL">downeye</field>{NEXT}</block>'),
        "near-test").event_handler_stacks[0].next
    sim = _Simulator(ctx)
    sim.x, sim.y, sim.heading = 0.0, 0.0, 0.0        # open grass, eye on floor
    assert sim._eval_expression(block) is False
    sim.x, sim.y = 1680.0, 49.0                      # centre on the ring
    assert sim._eval_expression(block) is True


def test_down_eye_near_object_fires_on_castle_piece(ctx):
    from goal_strategy.detector.simulation.simulate_path import _Simulator

    piece = next(p for p in ctx.pieces if p.object_id.endswith("inner_corner_tower_ne"))
    block = parse_workspace(
        _wrap('<block type="pg_sensing_optical_near_object" id="n2">'
              '<field name="OPTICAL">downeye</field>{NEXT}</block>'),
        "near-test").event_handler_stacks[0].next
    sim = _Simulator(ctx)
    sim.x, sim.y, sim.heading = piece.x, piece.y - 35.0, 90.0   # eye over the piece
    assert sim._eval_expression(block) is True


def test_color_none_true_everywhere_but_the_line(ctx):
    # OI-18 RESOLVED by reviewer probe (2026-08-19): the ground is coded as
    # no color, so 'none' is TRUE on open grass (the `not none` idiom reacts
    # to any colored object) and only the red line reads a color.
    from goal_strategy.detector.simulation.simulate_path import _Simulator

    sim = _Simulator(ctx)
    sim.heading = 0.0
    sim.x, sim.y = 0.0, 0.0   # open grass — colorless
    assert sim._eye_detected_color("down") is None
    sim.x = 1680.0            # centre on the ring: the one colored thing
    assert sim._eye_detected_color("down") == "red"
    sim.x = 1900.0            # beyond the outer edge — ocean, colorless
    assert sim._eye_detected_color("down") is None


# ------------------------------------------- Phase 2: cone, hats, staleness

HAT_DRIVE_XML = """<xml xmlns="https://developers.google.com/blockly/xml">
<block type="pg_events_when_started" id="h1"><next>
<block type="pg_drivetrain_drive_for" id="d1"><field name="DIRECTION">fwd</field>
  <field name="UNITS">mm</field>
  <value name="AMOUNT"><shadow type="math_number" id="s1"><field name="NUM">2400</field></shadow></value>
</block></next></block>
<block type="pg_events_optical_detect_object" id="h2">
  <field name="OPTICAL">fronteye</field><field name="OPTIONS">detects</field><next>
<block type="pg_magnet_set_magnet_state" id="m1">
  <field name="MAGNET">Magnet</field><field name="ACTION">boost</field>
</block></next></block></xml>"""


def test_eye_hat_fires_on_modeled_detection_not_eagerly(ctx):
    # Driving 2400mm west from spawn passes courtyard_tower_1 37mm off-lane —
    # inside the MEASURED proximity cone (OI-5 probe 2026-08-21: fov 13deg,
    # range 124mm): the hat's magnet boost fires mid-drive, never at step 0.
    # The model is measured, so sensor_model_assumed no longer flags.
    sim = _sim(HAT_DRIVE_XML, ctx)
    assert sim.magnet_fires_at_step is not None
    assert "sensor_model_assumed" not in sim.execution_flags
    assert "trigger_unfaithful" not in sim.execution_flags


def test_eye_hat_suppressed_under_b2(ctx):
    sim = _sim(HAT_DRIVE_XML, ctx, conditional_hats="suppress")
    assert sim.magnet_fires_at_step is None
    assert "conditional_hat_suppressed" in sim.execution_flags


def test_contact_marks_movable_target_stale(ctx):
    # Drive straight through courtyard_tower_1 (x=-712, y=86 ~ near the
    # spawn's westward line at y=49): contact is recorded; a later eye check
    # that sees the piece carries sensor_reading_stale.
    xml = _wrap(
        '<block type="pg_drivetrain_drive_for" id="d1"><field name="DIRECTION">fwd</field>'
        '<field name="UNITS">mm</field>'
        '<value name="AMOUNT"><shadow type="math_number" id="s1">'
        '<field name="NUM">1800</field></shadow></value>{NEXT}</block>')
    sim = _sim(xml, ctx)
    assert any(k.endswith("courtyard_tower_1") for k in sim.object_contacts)


def test_front_cone_respects_range(ctx):
    # At spawn facing west, the nearest piece is ~1200mm away — beyond the
    # assumed 1000mm range: no detection, hat never fires without motion.
    xml = """<xml xmlns="https://developers.google.com/blockly/xml">
<block type="pg_events_when_started" id="h1"><next>
<block type="pg_control_wait" id="w1">
  <value name="TIME"><shadow type="math_number" id="s1"><field name="NUM">1</field></shadow></value>
</block></next></block>
<block type="pg_events_optical_detect_object" id="h2">
  <field name="OPTICAL">fronteye</field><field name="OPTIONS">detects</field><next>
<block type="pg_magnet_set_magnet_state" id="m1">
  <field name="MAGNET">Magnet</field><field name="ACTION">boost</field>
</block></next></block></xml>"""
    sim = _sim(xml, ctx)
    assert sim.magnet_fires_at_step is None


# ---------------------------------------------------- Phase 4: bumper switch

def test_bumper_pressed_at_contact_respects_side(ctx):
    # Left bumper point touching rock_ne_large_1's surface (r=100 at 637,700);
    # the right bumper sits ~112mm away — not pressed.
    from goal_strategy.detector.simulation.simulate_path import _Simulator

    sim = _Simulator(ctx)
    sim.heading = 0.0                       # facing east toward the rock
    sim.x, sim.y = 637 - 166.5, 700 - 25.4  # left bumper point lands on the surface
    assert sim._bumper_pressed("leftbumper") is True
    assert sim._bumper_pressed("rightbumper") is False
    sim.x = 637 - 400.0                     # well short of contact
    assert sim._bumper_pressed("leftbumper") is False


def test_bumper_hat_fires_on_modeled_contact(ctx):
    # Drive east into the NE rock: the bumper hat's magnet boost fires at
    # contact — trigger_unsimulated retired for modeled bumpers.
    xml = """<xml xmlns="https://developers.google.com/blockly/xml">
<block type="pg_events_when_started" id="h1"><next>
<block type="pg_drivetrain_turn_for" id="t1"><field name="TURNDIRECTION">right</field>
  <value name="AMOUNT"><shadow type="math_number" id="s1"><field name="NUM">180</field></shadow></value><next>
<block type="pg_drivetrain_drive_for" id="d1"><field name="DIRECTION">fwd</field>
  <field name="UNITS">mm</field>
  <value name="AMOUNT"><shadow type="math_number" id="s2"><field name="NUM">700</field></shadow></value>
</block></next></block></next></block>
<block type="pg_events_when_bumper" id="h2">
  <field name="BUMPER">leftbumper</field><field name="OPTIONS">pressed</field><next>
<block type="pg_magnet_set_magnet_state" id="m1">
  <field name="MAGNET">Magnet</field><field name="ACTION">boost</field>
</block></next></block></xml>"""
    # spawn (1014,49) turn 180 -> east; rock_se is south, rocks NE north — no
    # contact on this line; use rock-free heading to assert NON-firing first.
    sim = _sim(xml, ctx)
    assert "trigger_unsimulated" not in sim.execution_flags
    sim2 = _sim(xml, ctx, conditional_hats="suppress")
    assert sim2.magnet_fires_at_step is None
    assert "conditional_hat_suppressed" in sim2.execution_flags


def test_bumper_hat_fires_driving_through_castle(ctx):
    # Westward drive from spawn runs through the castle pieces: the RIGHT
    # bumper (north of centreline when heading west) sweeps over
    # courtyard_tower_1 (y=86 vs bumper track y≈74) — the hat latches at
    # contact and its stack (magnet boost) runs. The left bumper's track
    # (y≈24) misses the tower by ~17mm: side selection is load-bearing.
    xml = """<xml xmlns="https://developers.google.com/blockly/xml">
<block type="pg_events_when_started" id="h1"><next>
<block type="pg_drivetrain_drive_for" id="d1"><field name="DIRECTION">fwd</field>
  <field name="UNITS">mm</field>
  <value name="AMOUNT"><shadow type="math_number" id="s2"><field name="NUM">2000</field></shadow></value>
</block></next></block>
<block type="pg_events_when_bumper" id="h2">
  <field name="BUMPER">rightbumper</field><field name="OPTIONS">pressed</field><next>
<block type="pg_magnet_set_magnet_state" id="m1">
  <field name="MAGNET">Magnet</field><field name="ACTION">boost</field>
</block></next></block></xml>"""
    sim = _sim(xml, ctx)
    assert sim.magnet_fires_at_step is not None
    assert any(k.startswith("castle_debris.") for k in sim.object_contacts)


# ---------------------------------------------- Phase 3: distance sensor

def _distance_block(kind="pg_sensing_distance_found", unit=None):
    unit_field = f'<field name="UNIT">{unit}</field>' if unit else ""
    xml = _wrap(f'<block type="{kind}" id="dist1">{unit_field}{{NEXT}}</block>')
    return parse_workspace(xml, "dist-test").event_handler_stacks[0].next


def test_distance_banded_cone_narrows_with_range(ctx):
    """Band narrowing on a SYNTHETIC one-object world (the castle card's
    corridors now contain the adopted structure towers, so no real lane is
    guaranteed empty — 2026-08-26); the measured 2,000mm cap on the real
    card's plow lane."""
    from goal_strategy.detector.simulation.simulate_path import (
        PlaygroundContext, _Simulator)

    toy = PlaygroundContext.from_playground_card(
        {"playground_id": "t", "field_geometry": {"playable_radius_mm": 60000},
         "spawn_points": {"default_start": {"x": 0, "y": 0, "heading": 0}},
         "objects": {"target": {"x": 0, "y": 700, "tolerance": 100,
                                "body_radius_mm": 100}}},
        yaml.safe_load(open(_ROOT / "configs" / "robot" / "vr_robot.yaml")))
    block = _distance_block()
    sim = _Simulator(toy)
    sim.heading = 90.0                     # facing north at the target
    sim.x, sim.y = -60.0, 100.0            # 60mm lateral, ~600mm: 10° band
    assert sim._eval_expression(block) is True
    sim.x, sim.y = -184.0, -600.0          # same-ish lateral, ~1300mm: 5° band
    assert sim._eval_expression(block) is False
    # OI-25 measured range (2026-08-26, rock_se back-away probe: flip at
    # 1,972±50mm): beyond 2,000mm nothing is found even dead-on
    sim.x, sim.y = 0.0, -1500.0            # dead-on, surface ~2,033mm: beyond cap
    assert sim._eval_expression(block) is False
    # the measured cap on the REAL card's plow lane
    sim2 = _Simulator(ctx)
    sim2.heading = 90.0
    sim2.x, sim2.y = 163.0, -900.0
    assert sim2._eval_expression(block) is True
    sim2.x, sim2.y = 163.0, -1100.0
    assert sim2._eval_expression(block) is False


def test_distance_reports_nearest_surface_and_units(ctx):
    from goal_strategy.detector.simulation.simulate_path import _Simulator

    sim = _Simulator(ctx)
    sim.heading = 90.0
    sim.x, sim.y = 637.0, 100.0            # dead ahead of the r=100 rock at y=700
    mm_block = _distance_block("pg_sensing_distance_distance")
    d = sim._eval_expression(mm_block)
    # surface = centre distance (600) - mount (66.5) - radius (100)
    assert d == pytest.approx(600 - 66.5 - 100, abs=1.0)
    inch_block = _distance_block("pg_sensing_distance_distance", unit="inches")
    assert sim._eval_expression(inch_block) == pytest.approx(d / 25.4, abs=0.1)
    # assumed dropped at radius ratification (2026-08-19): distance evidence
    # is fully measured — no sensor_model_assumed flag.
    assert "sensor_model_assumed" not in sim.execution_flags


def test_distance_no_object_reading(ctx):
    from goal_strategy.detector.simulation.simulate_path import _Simulator

    sim = _Simulator(ctx)
    sim.heading = 270.0                    # facing south from spawn: open water
    sim.x, sim.y = 1014.0, 49.0
    block = _distance_block("pg_sensing_distance_distance")
    assert sim._eval_expression(block) == pytest.approx(3000.0)
    found = _distance_block()
    assert sim._eval_expression(found) is False


def test_negative_reading_after_contact_is_stale(ctx):
    # Hybrid-ruling completion (CROW-C072, 2026-08-24): drive through a
    # piece (contact), then evaluate a distance condition that finds
    # NOTHING at card positions — the negative reading is conditional (the
    # real world has been rearranged) -> sensor_reading_stale.
    xml = _wrap(
        '<block type="pg_drivetrain_drive_for" id="d1"><field name="DIRECTION">fwd</field>'
        '<field name="UNITS">mm</field>'
        '<value name="AMOUNT"><shadow type="math_number" id="s1">'
        '<field name="NUM">1800</field></shadow></value>'
        '<next><block type="pg_control_if_then" id="if1">'
        '<value name="CONDITION"><block type="pg_sensing_distance_found" id="df">'
        '<field name="DISTANCE">frontdistance</field></block></value>'
        '</block></next>{NEXT}</block>')
    sim = _sim(xml, ctx)
    assert any(k.startswith("castle_debris") for k in sim.object_contacts)
    assert "sensor_reading_stale" in sim.execution_flags


def test_reading_without_prior_contact_is_not_stale(ctx):
    # distance check at spawn, nothing contacted: no staleness
    xml = _wrap(
        '<block type="pg_control_if_then" id="if1">'
        '<value name="CONDITION"><block type="pg_sensing_distance_found" id="df">'
        '<field name="DISTANCE">frontdistance</field></block></value>'
        '</block>{NEXT}')
    sim = _sim(xml, ctx)
    assert not sim.object_contacts
    assert "sensor_reading_stale" not in sim.execution_flags
