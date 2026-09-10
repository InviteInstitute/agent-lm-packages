"""OI-24 reviewer rulings (2026-08-24) as executable semantics:

1. Faithful forever nesting — an inner forever that runs to its cap stops
   every enclosing loop (a real forever never exits, so outer iterations 2+
   never happen). Collapses depth-47 nesting to linear cost.
2. Non-finite parameters, VEX-probed: percents max out (execution
   continues); DISCRETE values hang the block (stack stalls, parallel
   stacks continue) -> nonfinite_parameter_stall; `repeat Infinity` LOOPS
   like forever.
3. Invalid Switch text: VEX rejects the whole program — no simulation, sim
   channel abstains with switch_syntax_error, code channel unaffected.
4. Foreign-playground blocks (brightness in CCP): faithful no-op,
   foreign_playground_block flag, not unmodeled.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from goal_strategy.detector.parsing.parse_blocks import parse_workspace
from goal_strategy.detector.simulation.simulate_path import (
    PlaygroundContext,
    simulate_path,
)

_ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture(scope="module")
def ctx() -> PlaygroundContext:
    card = yaml.safe_load(open(_ROOT / "configs" / "playgrounds" / "castle_crashers.yaml"))
    robot = yaml.safe_load(open(_ROOT / "configs" / "robot" / "vr_robot.yaml"))
    return PlaygroundContext.from_playground_card(card, robot)


def _sim(xml, ctx):
    return simulate_path(parse_workspace(xml, "oi24-test"), ctx)


def _wrap(body: str) -> str:
    return ('<xml xmlns="https://developers.google.com/blockly/xml">'
            '<block type="pg_events_when_started" id="h"><next>'
            f"{body}</next></block></xml>")


DRIVE = ('<block type="pg_drivetrain_drive_for" id="{i}">'
         '<field name="DIRECTION">fwd</field><field name="UNITS">mm</field>'
         '<value name="AMOUNT"><shadow type="math_number" id="{i}s">'
         '<field name="NUM">{amt}</field></shadow></value>{next}</block>')


def _forever(inner: str, i: str) -> str:
    return (f'<block type="pg_control_forever" id="{i}">'
            f'<statement name="SUBSTACK">{inner}</statement></block>')


def test_nested_forever_is_faithful_prefix_then_inner(ctx):
    # forever{ driveA(10); forever{ driveB(20) } }: A runs ONCE, B caps at 20
    inner = DRIVE.format(i="b", amt=20, next="")
    body = DRIVE.format(i="a", amt=10,
                        next=f"<next>{_forever(inner, 'f2')}</next>")
    sim = _sim(_wrap(_forever(body, "f1")), ctx)
    a_steps = [p for p in sim.path if p.block_id == "a"]
    b_steps = [p for p in sim.path if p.block_id == "b"]
    assert len(a_steps) == 1        # outer iteration 2 never happens
    assert len(b_steps) == 20       # inner forever runs to its cap


def test_repeat_containing_forever_stops_after_one_iteration(ctx):
    # repeat 5 { forever{ drive } }  (the WREN-C060 shape): 20 drives, not 100
    inner = DRIVE.format(i="b", amt=20, next="")
    body = (f'<block type="pg_control_repeat" id="r">'
            f'<value name="TIMES"><shadow type="math_number" id="t">'
            f'<field name="NUM">5</field></shadow></value>'
            f'<statement name="SUBSTACK">{_forever(inner, "f")}</statement></block>')
    sim = _sim(_wrap(body), ctx)
    assert len([p for p in sim.path if p.block_id == "b"]) == 20


def test_deep_pure_nesting_is_linear_not_exponential(ctx):
    # 30 nested forevers around one drive: 20 drive steps, tiny block count
    xml = DRIVE.format(i="d", amt=10, next="")
    for k in range(30):
        xml = _forever(xml, f"f{k}")
    sim = _sim(_wrap(xml), ctx)
    assert len([p for p in sim.path if p.block_id == "d"]) == 20
    assert sim.blocks_executed < 1000
    assert "execution_budget_exhausted" not in sim.execution_flags


def test_drive_for_infinity_stalls_the_stack(ctx):
    body = DRIVE.format(i="d1", amt="Infinity",
                        next="<next>" + DRIVE.format(i="d2", amt=100, next="") + "</next>")
    sim = _sim(_wrap(body), ctx)
    assert "nonfinite_parameter_stall" in sim.execution_flags
    assert not [p for p in sim.path if p.block_id == "d1"]   # no motion
    assert not [p for p in sim.path if p.block_id == "d2"]   # never reached
    assert (sim.final_x, sim.final_y) == (sim.origin_x, sim.origin_y)


def test_repeat_infinity_loops_like_forever(ctx):
    body = (f'<block type="pg_control_repeat" id="r">'
            f'<value name="TIMES"><shadow type="math_number" id="t">'
            f'<field name="NUM">Infinity</field></shadow></value>'
            f'<statement name="SUBSTACK">{DRIVE.format(i="d", amt=50, next="")}'
            f'</statement></block>')
    sim = _sim(_wrap(body), ctx)
    assert len([p for p in sim.path if p.block_id == "d"]) == 20
    assert "nonfinite_parameter_stall" not in sim.execution_flags
    assert "nonfinite_numeric_clamped" in sim.execution_flags


def test_velocity_infinity_maxes_out_and_continues(ctx):
    body = ('<block type="pg_drivetrain_set_drive_velocity" id="v">'
            '<field name="UNITS">%</field>'
            '<value name="VELOCITY"><shadow type="math_number" id="vs">'
            '<field name="NUM">Infinity</field></shadow></value>'
            '<next>' + DRIVE.format(i="d", amt=100, next="") + "</next></block>")
    sim = _sim(_wrap(body), ctx)
    assert [p for p in sim.path if p.block_id == "d"]       # execution continued
    assert "nonfinite_parameter_stall" not in sim.execution_flags


def test_switch_block_rejects_whole_program():
    from goal_strategy.profile import _profile
    xml = ('<xml xmlns="https://developers.google.com/blockly/xml">'
           '<block type="pg_events_when_started" id="h"><next>'
           + DRIVE.format(i="d", amt=500, next="")
           + '</next></block>'
           '<block type="pg_mixed_multiline_command" id="sw"/></xml>')
    prof = _profile(xml, "switch-test", {"weight_cleared": 0})
    sim_inds = [i for g in prof.goals for i in g.intent + g.attainment
                if i.channel == "simulation"]
    assert sim_inds and all(i.abstained for i in sim_inds)
    assert {i.abstain_reason for i in sim_inds} == {"switch_syntax_error"}
    code_inds = [i for g in prof.goals for i in g.intent + g.attainment
                 if i.channel == "code" and not i.abstained]
    assert code_inds                                          # code channel intact


def test_brightness_is_foreign_not_unmodeled():
    from goal_strategy.ccp_runs import load_ccp_runs
    from goal_strategy.profile import _profile
    r = next(x for x in load_ccp_runs(tag_dev_overlap=False)
             if "optical_brightness" in (x.workspace_xml or ""))
    prof = _profile(r.workspace_xml, r.run_id, r.playground_params)
    flags = {f for g in prof.goals for i in g.intent + g.attainment
             for f in (i.flags or [])}
    assert "foreign_playground_block" in flags
    assert "unmodeled_blocks" not in flags
