"""OI-23 builds (reviewer-ruled 2026-08-24): procedure inline expansion and
the when_timer clock."""
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
NS = 'xmlns="https://developers.google.com/blockly/xml"'


@pytest.fixture(scope="module")
def ctx() -> PlaygroundContext:
    card = yaml.safe_load(open(_ROOT / "configs" / "playgrounds" / "castle_crashers.yaml"))
    robot = yaml.safe_load(open(_ROOT / "configs" / "robot" / "vr_robot.yaml"))
    return PlaygroundContext.from_playground_card(card, robot)


def _sim(xml, ctx):
    return simulate_path(parse_workspace(xml, "oi23-test"), ctx)


DRIVE = ('<block type="pg_drivetrain_drive_for" id="{i}">'
         '<field name="DIRECTION">fwd</field><field name="UNITS">mm</field>'
         '<value name="AMOUNT"><shadow type="math_number" id="{i}s">'
         '<field name="NUM">{amt}</field></shadow></value>{next}</block>')

MUT = ('<mutation xmlns="http://www.w3.org/1999/xhtml" proccode="{name}" '
       'proceduredefid="{i}p" argumentids="[]"></mutation>')


def _definition(name, body, i="def1"):
    return (f'<block type="procedures_definition" id="{i}" x="900" y="0">'
            f'<statement name="custom_block"><shadow type="procedures_prototype" '
            f'id="{i}p">{MUT.format(name=name, i=i)}</shadow></statement>'
            f"<next>{body}</next></block>")


def _call(name, i="call1", nxt=""):
    return (f'<block type="procedures_call" id="{i}">'
            f"{MUT.format(name=name, i=i)}"
            + (f"<next>{nxt}</next>" if nxt else "") + "</block>")


def _prog(*top):
    return f"<xml {NS}>" + "".join(top) + "</xml>"


def _started(body):
    return ('<block type="pg_events_when_started" id="h"><next>'
            f"{body}</next></block>")


def test_call_executes_definition_body(ctx):
    xml = _prog(_started(_call("Go", nxt=DRIVE.format(i="after", amt=100, next=""))),
                _definition("Go", DRIVE.format(i="body", amt=400, next="")))
    sim = _sim(xml, ctx)
    assert len([p for p in sim.path if p.block_id == "body"]) == 1
    # caller continues after the call, and body ran FIRST
    steps = [p.block_id for p in sim.path]
    assert steps.index("body") < steps.index("after")


def test_call_twice_runs_body_twice(ctx):
    xml = _prog(_started(_call("Go", i="c1",
                               nxt=_call("Go", i="c2"))),
                _definition("Go", DRIVE.format(i="body", amt=200, next="")))
    sim = _sim(xml, ctx)
    assert len([p for p in sim.path if p.block_id == "body"]) == 2


def test_recursion_suppressed_with_flag(ctx):
    xml = _prog(_started(_call("Loop")),
                _definition("Loop", DRIVE.format(
                    i="body", amt=100,
                    next=f"<next>{_call('Loop', i='rec')}</next>")))
    sim = _sim(xml, ctx)
    assert len([p for p in sim.path if p.block_id == "body"]) == 1
    assert "procedure_recursion_suppressed" in sim.execution_flags


def test_undefined_call_is_flagged_noop(ctx):
    xml = _prog(_started(_call("Ghost",
                               nxt=DRIVE.format(i="after", amt=100, next=""))))
    sim = _sim(xml, ctx)
    assert "procedure_undefined" in sim.execution_flags
    assert [p for p in sim.path if p.block_id == "after"]


def test_movement_consumes_clock_time(ctx):
    # default 50% drive velocity = 494 mm/s: 988mm ~= 2.0s
    sim = _sim(_prog(_started(DRIVE.format(i="d", amt=988, next=""))), ctx)
    assert sim.sim_time_s == pytest.approx(2.0, rel=0.05)


def _when_timer(threshold, body):
    return (f'<block type="pg_events_when_timer" id="th">'
            f'<value name="AMOUNT"><shadow type="math_positive_number_only" '
            f'id="ts"><field name="NUM">{threshold}</field></shadow></value>'
            f"<next>{body}</next></block>")


def test_timer_hat_fires_when_clock_crosses(ctx):
    # main stack drives ~2s; timer hat at 1s fires mid-program, not eagerly
    xml = _prog(_started(DRIVE.format(i="d1", amt=494, next="") ),
                _when_timer(0.7, DRIVE.format(i="hat", amt=100, next="")))
    sim = _sim(xml, ctx)
    hat_steps = [p for p in sim.path if p.block_id == "hat"]
    assert hat_steps, "timer hat should fire once the clock crosses 0.7s"
    assert "timer_hat_unfired" not in sim.execution_flags
    # NOT eager: the main-stack drive committed before the hat ran
    steps = [p.block_id for p in sim.path]
    assert steps.index("d1") < steps.index("hat")


def test_timer_hat_unfired_when_program_too_short(ctx):
    xml = _prog(_started(DRIVE.format(i="d1", amt=100, next="")),
                _when_timer(60, DRIVE.format(i="hat", amt=100, next="")))
    sim = _sim(xml, ctx)
    assert not [p for p in sim.path if p.block_id == "hat"]
    assert "timer_hat_unfired" in sim.execution_flags
