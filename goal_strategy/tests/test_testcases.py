"""Phase-5 harness tests: scenario overlays, check rules, push model,
eligibility, and the goal-mapping roll-up.

The three synthetic programs pin the harness's core distinction (reviewer
design): a RESPONSIVE pusher (bumper-gated) passes detects; a BLIND sweeper
clears the piece but fails detects — clearing without sensing is visible as
exactly that; an INERT program fails everything.
"""
from __future__ import annotations

import pytest

from goal_strategy.testcases import run_battery

RESPONSIVE_PUSHER = """<xml xmlns="https://developers.google.com/blockly/xml">
<block type="pg_events_when_started" id="h1"><next>
<block type="pg_drivetrain_drive" id="d1"><field name="DIRECTION">fwd</field><next>
<block type="pg_control_wait_until" id="w1">
  <value name="CONDITION"><block type="pg_sensing_bumper" id="b1">
    <field name="BUMPER">leftbumper</field></block></value><next>
<block type="pg_drivetrain_drive_for" id="d2"><field name="DIRECTION">fwd</field>
  <field name="UNITS">mm</field>
  <value name="AMOUNT"><shadow type="math_number" id="s2"><field name="NUM">2500</field></shadow></value>
</block></next></block></next></block></next></block></xml>"""

# The if-bumper check runs FIRST (so under Option A the piece materializes
# ahead of the robot at spawn), then a blind 3000mm sweep plows through it.
# The check itself never alters the trajectory: clearing is accidental.
BLIND_SWEEPER_REAL = """<xml xmlns="https://developers.google.com/blockly/xml">
<block type="pg_events_when_started" id="h1"><next>
<block type="pg_control_if_then" id="i1">
  <value name="CONDITION"><block type="pg_sensing_bumper" id="b1">
    <field name="BUMPER">leftbumper</field></block></value>
  <statement name="DO"><block type="pg_drivetrain_stop" id="st1"/></statement><next>
<block type="pg_drivetrain_drive_for" id="d1"><field name="DIRECTION">fwd</field>
  <field name="UNITS">mm</field>
  <value name="AMOUNT"><shadow type="math_number" id="s1"><field name="NUM">3000</field></shadow></value>
</block></next></block></next></block></xml>"""

INERT_SENSOR_PROGRAM = """<xml xmlns="https://developers.google.com/blockly/xml">
<block type="pg_events_when_started" id="h1"><next>
<block type="pg_control_if_then" id="i1">
  <value name="CONDITION"><block type="pg_sensing_bumper" id="b1">
    <field name="BUMPER">leftbumper</field></block></value>
  <statement name="DO"><block type="pg_drivetrain_drive_for" id="d1">
    <field name="DIRECTION">fwd</field><field name="UNITS">mm</field>
    <value name="AMOUNT"><shadow type="math_number" id="s1">
    <field name="NUM">500</field></shadow></value></block></statement>
</block></next></block></xml>"""

DOWN_EYE_ONLY = """<xml xmlns="https://developers.google.com/blockly/xml">
<block type="pg_events_when_started" id="h1"><next>
<block type="pg_control_wait_until" id="w1">
  <value name="CONDITION"><block type="pg_sensing_optical_color" id="e1">
    <field name="OPTICAL">downeye</field><field name="COLORS">red</field></block></value>
</block></next></block></xml>"""


def _scenario(report, sid):
    return next(s for s in report.scenarios if s.scenario_id == sid)


def _check(scenario, name):
    return next(c for c in scenario.checks if c.name == name)


@pytest.fixture(scope="module")
def responsive():
    return run_battery(RESPONSIVE_PUSHER, "responsive-pusher")


def test_responsive_pusher_detects_navigates_and_clears(responsive):
    ahead = _scenario(responsive, "piece_ahead")
    assert _check(ahead, "detects").status == "pass"
    assert _check(ahead, "navigates_to").status == "pass"
    assert _check(ahead, "pushes_off").status == "pass"


def test_blind_sweeper_gets_no_accidental_credit():
    report = run_battery(BLIND_SWEEPER_REAL, "blind-sweeper")
    ahead = _scenario(report, "piece_ahead")
    # Reviewer ruling 2026-08-19: accidental clearing is not evidence — the
    # pushes_off check is gated on the detection response it lacks. The
    # accident stays visible in the detail text, never in the status.
    assert _check(ahead, "detects").status == "fail"
    push = _check(ahead, "pushes_off")
    assert push.status == "fail"
    assert "accidental" in (push.detail or "")
    nav = _check(ahead, "navigates_to")
    assert nav.status == "fail"
    assert "accidental" in (nav.detail or "")


def test_inert_sensor_program_fails_everything():
    report = run_battery(INERT_SENSOR_PROGRAM, "inert")
    ahead = _scenario(report, "piece_ahead")
    assert {c.status for c in ahead.checks} == {"fail"}


def test_down_eye_only_program_is_ineligible():
    # Red-line sensing is already sim-evidenced — the battery adds nothing
    # (reviewer ruling): not eligible.
    report = run_battery(DOWN_EYE_ONLY, "down-eye-only")
    assert report.eligible is False
    assert report.scenarios == ()


def test_two_piece_reset_distinguishes_single_clear(responsive):
    two = _scenario(responsive, "two_pieces_reset")
    # The straight-line pusher clears the first piece but never reacquires
    # the off-axis second piece.
    assert _check(two, "pushes_off").status == "pass"
    assert _check(two, "resets_to_next").status != "pass"


def test_goal_mapping_rolls_up_facets(responsive):
    mapping = responsive.goal_mapping.get("clear_debris_zone", {})
    assert mapping.get("object_detection") == "pass"
    assert mapping.get("object_pursuit") == "pass"
    assert mapping.get("push_execution") == "pass"
    assert "repeat_acquisition" in mapping
    assert "edge_failure_handling" in mapping


def test_battery_uses_push_model_only_in_scenarios(responsive):
    # Sanity: the main profile pipeline still never clears pieces — the push
    # switch lives only in scenario cards.
    from goal_strategy.config import load_configs
    cfg = load_configs("castle_crashers")
    assert cfg.context.testcase_physics == {}


# --------------------------------- Option A: sequential-goal isolation

# Phase 1 of the code pursues a different goal (drive north 800, turn to
# face west); only THEN does the bumper-gated clearing code engage. Under
# Option A the piece materializes when the bumper is first consulted —
# ahead of the robot's pose AT THAT MOMENT, not ahead of spawn.
SEQUENTIAL_CLEARER = """<xml xmlns="https://developers.google.com/blockly/xml">
<block type="pg_events_when_started" id="h1"><next>
<block type="pg_drivetrain_turn_for" id="t0"><field name="TURNDIRECTION">right</field>
  <value name="AMOUNT"><shadow type="math_number" id="s0"><field name="NUM">90</field></shadow></value><next>
<block type="pg_drivetrain_drive_for" id="d0"><field name="DIRECTION">fwd</field>
  <field name="UNITS">mm</field>
  <value name="AMOUNT"><shadow type="math_number" id="s1"><field name="NUM">800</field></shadow></value><next>
<block type="pg_drivetrain_turn_for" id="t1"><field name="TURNDIRECTION">left</field>
  <value name="AMOUNT"><shadow type="math_number" id="s2"><field name="NUM">90</field></shadow></value><next>
<block type="pg_drivetrain_drive" id="d1"><field name="DIRECTION">fwd</field><next>
<block type="pg_control_wait_until" id="w1">
  <value name="CONDITION"><block type="pg_sensing_bumper" id="b1">
    <field name="BUMPER">leftbumper</field></block></value><next>
<block type="pg_drivetrain_drive_for" id="d2"><field name="DIRECTION">fwd</field>
  <field name="UNITS">mm</field>
  <value name="AMOUNT"><shadow type="math_number" id="s3"><field name="NUM">2500</field></shadow></value>
</block></next></block></next></block></next></block></next></block></next></block></next></block></xml>"""


def test_sequential_goal_piece_materializes_at_phase_two():
    report = run_battery(SEQUENTIAL_CLEARER, "sequential-clearer")
    ahead = _scenario(report, "piece_ahead")
    # Phase 1 ran uncontaminated; the clearing phase still earns full credit.
    assert _check(ahead, "detects").status == "pass"
    assert _check(ahead, "navigates_to").status == "pass"
    assert _check(ahead, "pushes_off").status == "pass"
    assert ahead.construct.startswith("pg_sensing_bumper")
