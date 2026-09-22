"""The code/full-program rubric-evidence layer (B-2 layer 1, 2026-08-31).

Pins the reviewer-probed semantics: nested forevers are NOT coordination
(zero relations); a dead conditional (no arm alternation) contributes
nothing; census ceilings make every dimension decidable without tests
for dead reckoners; the red-cycler shape reads as integrated.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from goal_strategy.detector.parsing.parse_blocks import parse_workspace
from goal_strategy.detector.simulation.simulate_path import (
    PlaygroundContext, simulate_path,
)
from goal_strategy.rubric_evidence import code_evidence

_ROOT = Path(__file__).resolve().parent.parent
NS = 'xmlns="https://developers.google.com/blockly/xml"'


def _ctx():
    card = yaml.safe_load(open(_ROOT / "configs" / "playgrounds" / "castle_crashers.yaml"))
    robot = yaml.safe_load(open(_ROOT / "configs" / "robot" / "vr_robot.yaml"))
    return PlaygroundContext.from_playground_card(card, robot)


def _num(v):
    return f'<shadow type="math_number"><field name="NUM">{v}</field></shadow>'


def _ev(xml):
    prog = parse_workspace(xml, "rubric-test")
    sim = simulate_path(prog, _ctx(), scheduler="cooperative",
                        loop_iteration_time_s=1 / 60, time_budget_s=15.0)
    return code_evidence(prog, sim)


DRIVE = ('<block type="pg_drivetrain_drive_for" id="d1">'
         '<field name="DIRECTION">fwd</field><field name="UNITS">mm</field>'
         f'<value name="AMOUNT">{_num(300)}</value></block>')
RED = ('<block type="pg_sensing_optical_color" id="oc"><field name="OPTICAL">downeye</field>'
       '<field name="COLORS">red</field></block>')
DIST = '<block type="pg_sensing_distance_found" id="sf"><field name="DISTANCE">distance</field></block>'


def _prog(body):
    return (f"<xml {NS}><block type=\"pg_events_when_started\" id=\"h\">"
            f"<next>{body}</next></block></xml>")


def test_dead_reckoner_capped_everywhere_no_tests_needed():
    ev = _ev(_prog(DRIVE))
    assert not ev.sensing_in_executable
    assert ev.ceilings["environmental_feedback"] == 0
    assert ev.ceilings["task_state_regulation"] == 0
    assert ev.ceilings["recovery"] == 0
    assert ev.ceilings["spatial_motion"] == 1
    assert ev.ceilings["control_structure"] == 0
    assert ev.ceilings["representation"] == 0
    assert ev.construct_coordination_relations == 0


def test_nested_forevers_are_zero_relations():
    """The reviewer's probe: same-construct nesting is repetition, never
    coordination."""
    inner = ('<block type="pg_control_forever" id="f2">'
             f'<statement name="SUBSTACK">{DRIVE}</statement></block>')
    xml = _prog('<block type="pg_control_forever" id="f1">'
                f'<statement name="SUBSTACK">{inner}</statement></block>')
    ev = _ev(xml)
    assert ev.has_loops and not ev.sensing_in_executable
    assert ev.construct_coordination_relations == 0
    assert ev.max_arm_alternations == 0


def test_exercised_conditional_counts_without_alternation():
    """Separability ruling (2026-09-05): coordination is ARCHITECTURE.
    A sensing conditional EVALUATED inside an exercised loop is a
    relation even when its arm never alternates — while EF
    (max_arm_alternations) correctly stays 0. The same shape now reads
    differently on the two dimensions, which is the decontamination."""
    body = ('<block type="pg_control_if_then" id="if1">'
            f'<value name="CONDITION">{RED}</value>'
            '<statement name="SUBSTACK">'
            '<block type="pg_drivetrain_turn_for" id="t1">'
            '<field name="TURNDIRECTION">right</field>'
            f'<value name="AMOUNT">{_num(30)}</value></block>'
            "</statement></block>")
    xml = _prog('<block type="pg_control_forever" id="f1">'
                f'<statement name="SUBSTACK">{body}</statement></block>')
    ev = _ev(xml)
    assert ev.sensing_in_recurrent          # census ceiling open
    assert ev.max_arm_alternations == 0     # EF: no alternation evidence
    assert ev.construct_coordination_relations == 1   # CS: architecture
    assert ev.exercised_conditional_count == 1


def test_red_cycler_reads_integrated():
    """Continuous drive + sensing wait + reverse inside a forever: a
    sensing wait releasing in an exercised loop is a relation, and the
    motion is state-gated."""
    body = ('<block type="pg_drivetrain_drive" id="dv">'
            '<field name="DIRECTION">fwd</field><next>'
            '<block type="pg_control_wait_until" id="w1">'
            f'<value name="CONDITION">{RED}</value><next>'
            '<block type="pg_drivetrain_drive_for" id="rv">'
            '<field name="DIRECTION">rev</field><field name="UNITS">mm</field>'
            f'<value name="AMOUNT">{_num(600)}</value>'
            "</block></next></block></next></block>")
    xml = _prog('<block type="pg_control_forever" id="f1">'
                f'<statement name="SUBSTACK">{body}</statement></block>')
    ev = _ev(xml)
    # spawn is ~700mm from the east ring: the cycler reaches red, releases
    assert ev.wait_release_counts.get("w1", 0) >= 1
    assert any(r.startswith("sensing_wait_in_loop") for r in ev.coordination_detail)
    assert ev.state_terminated_motion_fraction is not None
    assert ev.state_terminated_motion_fraction > 0.0


def test_sensing_never_recurrent_caps_level_two():
    body = ('<block type="pg_control_if_then" id="if1">'
            f'<value name="CONDITION">{DIST}</value>'
            f'<statement name="SUBSTACK">{DRIVE}</statement></block>')
    ev = _ev(_prog(body))
    assert ev.sensing_in_executable and not ev.sensing_in_recurrent
    assert ev.ceilings["environmental_feedback"] == 1
    assert ev.ceilings["task_state_regulation"] == 1
    assert ev.ceilings["recovery"] == 1


# ---- construct-separability detectors (reviewer-ruled 2026-09-05) ----

def test_conditional_redirect_reads_state_terminated():
    """THE degenerate-extract fix: `forever { if red: rev 400 else drive
    fwd 150 }` — the dominant corpus idiom — must read a NON-ZERO
    state-terminated motion fraction once red actually alternates.
    (Production world: the drive reaches the ring within 15s.)"""
    body = ('<block type="pg_control_if_then_else" id="if1">'
            f'<value name="CONDITION">{RED}</value>'
            '<statement name="SUBSTACK">'
            '<block type="pg_drivetrain_drive_for" id="ra">'
            '<field name="DIRECTION">rev</field><field name="UNITS">mm</field>'
            f'<value name="AMOUNT">{_num(400)}</value></block></statement>'
            '<statement name="SUBSTACK2">'
            '<block type="pg_drivetrain_drive_for" id="rb">'
            '<field name="DIRECTION">fwd</field><field name="UNITS">mm</field>'
            f'<value name="AMOUNT">{_num(150)}</value></block></statement>'
            "</block>")
    xml = _prog('<block type="pg_control_forever" id="f1">'
                f'<statement name="SUBSTACK">{body}</statement></block>')
    ev = _ev(xml)
    if ev.max_arm_alternations >= 1:     # the redirect actually happened
        assert ev.state_terminated_motion_fraction is not None
        assert ev.state_terminated_motion_fraction > 0
    # and the SMC state-gated detector sees the gated drives either way
    assert ev.state_gated_drivetrain_count == 2


def test_pure_dead_reckon_fraction_zero_and_ungated():
    xml = _prog(DRIVE)
    ev = _ev(xml)
    assert (ev.state_terminated_motion_fraction or 0) == 0
    assert ev.state_gated_drivetrain_count == 0
    assert ev.computed_motion_param_count == 0


def test_architecture_set_counts():
    """Fixed repeat + sensing conditional inside: exercised-loop
    classification, nesting depth, conditional count."""
    body = ('<block type="pg_control_if_then" id="if1">'
            f'<value name="CONDITION">{DIST}</value>'
            '<statement name="SUBSTACK">'
            '<block type="pg_drivetrain_turn_for" id="t1">'
            '<field name="TURNDIRECTION">right</field>'
            f'<value name="AMOUNT">{_num(30)}</value></block></statement>'
            "</block>")
    xml = _prog('<block type="pg_control_repeat" id="r1">'
                f'<value name="TIMES">{_num(5)}</value>'
                f'<statement name="SUBSTACK">{body}</statement></block>')
    ev = _ev(xml)
    assert ev.exercised_loops_fixed == 1
    assert ev.exercised_loops_state == 0
    assert ev.exercised_conditional_count == 1
    assert ev.max_nesting_depth >= 2          # conditional inside loop


def test_computed_motion_param_detected():
    """A drive_for whose AMOUNT is an operator expression (not a literal
    shadow) counts as a computed motion parameter."""
    amount = ('<block type="pg_operator_math" id="op1">'
              '<field name="MATH">+</field>'
              f'<value name="NUM1">{_num(100)}</value>'
              f'<value name="NUM2">{_num(50)}</value></block>')
    xml = _prog('<block type="pg_drivetrain_drive_for" id="d1">'
                '<field name="DIRECTION">fwd</field><field name="UNITS">mm</field>'
                f'<value name="AMOUNT">{amount}</value></block>')
    ev = _ev(xml)
    assert ev.computed_motion_param_count == 1


def test_duplicated_sequence_detected():
    """The same 3-block chain written twice = a duplicated sequence
    (concrete representation); variables/procedures metrics default."""
    seq = ('<block type="pg_drivetrain_drive_for" id="dA{i}">'
           '<field name="DIRECTION">fwd</field><field name="UNITS">mm</field>'
           f'<value name="AMOUNT">{_num(300)}</value><next>'
           '<block type="pg_drivetrain_turn_for" id="tA{i}">'
           '<field name="TURNDIRECTION">right</field>'
           f'<value name="AMOUNT">{_num(90)}</value><next>'
           '<block type="pg_drivetrain_drive_for" id="dB{i}">'
           '<field name="DIRECTION">fwd</field><field name="UNITS">mm</field>'
           f'<value name="AMOUNT">{_num(200)}</value>')
    chain = (seq.format(i=1) + '<next>' + seq.format(i=2)
             + '</block></next></block></next></block>'
             + '</next></block></next></block></next></block>')
    xml = _prog(chain)
    ev = _ev(xml)
    assert ev.duplicated_sequence_count >= 1
    assert ev.procedure_metrics["calls"] == 0
    assert ev.variable_metrics["sets"] == 0


# ---- SMC lower-scale restructure (reviewer-ruled 2026-09-09) ----

def _turn(v, bid="t1"):
    return (f'<block type="pg_drivetrain_turn_for" id="{bid}">'
            '<field name="TURNDIRECTION">right</field>'
            f'<value name="AMOUNT">{_num(v)}</value></block>')


def _drive(v, bid="d1"):
    return (f'<block type="pg_drivetrain_drive_for" id="{bid}">'
            '<field name="DIRECTION">fwd</field><field name="UNITS">mm</field>'
            f'<value name="AMOUNT">{_num(v)}</value></block>')


def _chain(*blocks):
    out = ""
    for b in reversed(blocks):
        out = b[:-len("</block>")] + f"<next>{out}</next></block>" if out else b
    return out


_PALETTE = {"canonical_drive_values": [200, 800, 1200, 2000, 1000, 3000],
            "canonical_turn_values": [90, 120, 180, 60, 270, 45],
            "round_drive_multiple_mm": 100, "cardinal_turn_multiple_deg": 45,
            "cluster_merge_pct": 5, "fine_grain_multiple": 5}
_RULE = {"min_literals": 1, "distinct_drive_clusters_min": 3,
         "fine_values_min": 1, "canonical_prop_max": 0.5,
         "canonical_prop_min_literals": 4}


def _specificity(xml):
    from goal_strategy.rubric_evidence import (
        fixed_motion_diagnostics, fixed_motion_specificity,
        fixed_motion_vocabulary)
    prog = parse_workspace(xml, "smc-test")
    diag = fixed_motion_diagnostics(fixed_motion_vocabulary(prog), _PALETTE)
    return fixed_motion_specificity(diag, _RULE), diag


def test_specificity_coarse_palette_reads_zero():
    """200/90/200 is the shared default palette: coarse, verified —
    specificity 0, never U (the run IS evaluable)."""
    spec, diag = _specificity(_prog(_chain(
        _drive(200, "d1"), _turn(90, "t1"), _drive(200, "d2"))))
    assert spec == 0
    assert diag["canonical_prop"] == 1.0 and diag["fine_value_count"] == 0


def test_specificity_differentiated_clusters_read_one():
    """Three meaningfully-distinct non-palette drive magnitudes: the
    fitted-vocabulary residue (route B)."""
    spec, diag = _specificity(_prog(_chain(
        _drive(350, "d1"), _drive(760, "d2"), _drive(1410, "d3"))))
    assert spec == 1 and diag["distinct_drive_clusters"] == 3


def test_specificity_fine_grained_value_reads_one():
    """62 degrees is not a multiple of 5 — a value only tuning
    produces (the CROW-C114 pattern)."""
    spec, diag = _specificity(_prog(_chain(_drive(200, "d1"),
                                           _turn(62, "t1"))))
    assert spec == 1 and diag["fine_value_count"] == 1


def test_specificity_cluster_merge_five_pct():
    """1497 and 1500 are ONE value (within 5%), so two near-identical
    literals do not fake differentiation."""
    spec, diag = _specificity(_prog(_chain(
        _drive(1497, "d1"), _drive(1500, "d2"), _drive(1520, "d3"))))
    assert diag["distinct_drive_clusters"] == 1
    assert spec in (0, 1)   # decided by other signals, not clusters


def test_specificity_no_literals_is_none():
    spec, diag = _specificity(_prog(RED))
    assert spec is None and diag["literal_total"] == 0


def test_canonical_ambiguous_match_annotated():
    """800 matching a 752 target is flagged ambiguous (palette value);
    755 matching the same target is not."""
    from goal_strategy.rubric_evidence import canonical_ambiguous_matches
    amb = canonical_ambiguous_matches(
        parse_workspace(_prog(_drive(800)), "amb"), [752.0], 10.0, _PALETTE)
    assert amb == 1
    clean = canonical_ambiguous_matches(
        parse_workspace(_prog(_drive(755)), "amb2"), [752.0], 10.0, _PALETTE)
    assert clean == 0


def test_smc_lower_columns_shape():
    from goal_strategy.rubric_evidence import smc_lower_columns
    vals = smc_lower_columns(parse_workspace(_prog(_drive(200)), "cols"),
                             [752.0], 10.0, _PALETTE, _RULE)
    assert len(vals) == 6 and vals[0] == 0   # coarse, evaluable


# ---- OI-33 liveness ruling (2026-09-10) ----

def test_post_forever_literals_are_dead():
    """A drive_for literal after a forever loop can never run: it is
    excluded from the vocabulary/audit (the liveness ruling)."""
    from goal_strategy.rubric_evidence import (
        calibration_audit, fixed_motion_vocabulary)
    xml = _prog('<block type="pg_control_forever" id="f1">'
                '<statement name="SUBSTACK">'
                + _turn(90, "t0") +
                '</statement><next>' + _drive(1497, "dd") + '</next></block>')
    prog = parse_workspace(xml, "dead")
    v = fixed_motion_vocabulary(prog)
    assert v["drives"] == [] and v["turns"] == [90.0]
    assert calibration_audit(prog, [1497.0], 10.0) == (0, 0)


def test_sensing_only_after_forever_gets_ceilings():
    """Sensing that can never execute must not lift the census
    ceilings — the 4-run probe class from the liveness review."""
    xml = _prog('<block type="pg_control_forever" id="f1">'
                '<statement name="SUBSTACK">'
                + _drive(200, "d0") +
                f'</statement><next><block type="pg_control_if_then" id="c1">'
                f'<value name="CONDITION">{RED}</value>'
                '<statement name="SUBSTACK">' + _drive(100, "d9") +
                '</statement></block></next></block>')
    ev = _ev(xml)
    assert not ev.sensing_in_executable
    assert ev.ceilings["environmental_feedback"] == 0


def test_state_gated_executed_vs_architecture():
    """`forever{if red: drive}` with red never firing: architecture
    counts 1, executed counts 0 (the OI-33 scoring variant); motion in
    the always-taken ELSE arm counts as executed."""
    never = _prog('<block type="pg_control_forever" id="f1">'
                  '<statement name="SUBSTACK">'
                  '<block type="pg_control_if_then" id="c1">'
                  f'<value name="CONDITION">{RED}</value>'
                  '<statement name="SUBSTACK">' + _drive(200, "gm") +
                  '</statement></block></statement></block>')
    ev = _ev(never)
    assert ev.state_gated_drivetrain_count == 1
    assert ev.state_gated_drivetrain_executed == 0
    assert any("downeye" in s for s in ev.gated_sensor_fields)
    taken = _prog('<block type="pg_control_forever" id="f1">'
                  '<statement name="SUBSTACK">'
                  '<block type="pg_control_if_then_else" id="c1">'
                  f'<value name="CONDITION">{RED}</value>'
                  '<statement name="SUBSTACK">' + _turn(90, "gm1") +
                  '</statement><statement name="SUBSTACK2">'
                  + _drive(200, "gm2") +
                  '</statement></block></statement></block>')
    ev2 = _ev(taken)
    assert ev2.state_gated_drivetrain_executed >= 1
