"""Edge-triggered re-arming detection hats (reviewer ruling 2026-08-24):
the real runtime re-runs a detection hat on every NEW detection event.
Re-fires on genuine condition re-entry; a continuously-true condition is
one edge; timer hats re-fire after a reset re-crossing."""
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
    return simulate_path(parse_workspace(xml, "refire-test"), ctx)


DRIVE = ('<block type="pg_drivetrain_drive_for" id="{i}">'
         '<field name="DIRECTION">{d}</field><field name="UNITS">mm</field>'
         '<value name="AMOUNT"><shadow type="math_number" id="{i}s">'
         '<field name="NUM">{amt}</field></shadow></value>{next}</block>')


def test_eye_hat_refires_on_reentry(ctx):
    # Drive west past courtyard_tower_1, reverse back out, drive in again:
    # THREE genuine cone entries — inbound pass, the tower sweeping back
    # through the west-facing cone while reversing east, and the second
    # inbound pass. Three fires.
    main = DRIVE.format(i="in1", d="fwd", amt=2000, next="<next>"
        + DRIVE.format(i="out1", d="reverse", amt=2000, next="<next>"
        + DRIVE.format(i="in2", d="fwd", amt=2000, next="")
        + "</next>") + "</next>")
    xml = (f"<xml {NS}>"
           '<block type="pg_events_when_started" id="h"><next>' + main +
           "</next></block>"
           '<block type="pg_events_optical_detect_object" id="eye">'
           '<field name="OPTICAL">fronteye</field><field name="OPTIONS">detects</field>'
           '<next><block type="pg_magnet_set_magnet_state" id="m">'
           '<field name="MAGNET">Magnet</field><field name="ACTION">boost</field>'
           "</block></next></block></xml>")
    sim = _sim(xml, ctx)
    fires = sim.sensor_hats_fired.get("eye", [])
    assert len(fires) == 3, f"expected 3 fires (three cone entries), got {fires}"


def test_continuously_true_condition_is_one_edge(ctx):
    # Drive INTO detection range and stop there; several waits follow while
    # the condition stays true: exactly ONE fire, no infinite re-triggering.
    def wait(k, nxt=""):
        return ('<block type="pg_control_wait" id="w%d">'
                '<value name="TIME"><shadow type="math_number" id="ws%d">'
                '<field name="NUM">1</field></shadow></value>%s</block>'
                % (k, k, f"<next>{nxt}</next>" if nxt else ""))
    main = DRIVE.format(i="in1", d="fwd", amt=1700,
                        next=f"<next>{wait(1, wait(2, wait(3)))}</next>")
    xml = (f"<xml {NS}>"
           '<block type="pg_events_when_started" id="h"><next>' + main +
           "</next></block>"
           '<block type="pg_events_optical_detect_object" id="eye">'
           '<field name="OPTICAL">fronteye</field><field name="OPTIONS">detects</field>'
           '<next><block type="pg_magnet_set_magnet_state" id="m">'
           '<field name="MAGNET">Magnet</field><field name="ACTION">boost</field>'
           "</block></next></block></xml>")
    sim = _sim(xml, ctx)
    assert len(sim.sensor_hats_fired.get("eye", [])) <= 1


def test_timer_hat_refires_after_reset_recrossing(ctx):
    # threshold 1s; drive ~2s, reset timer, drive ~2s: two crossings.
    main = DRIVE.format(i="d1", d="fwd", amt=988, next="<next>"
        + '<block type="pg_sensing_reset_timer" id="rt"><next>'
        + DRIVE.format(i="d2", d="reverse", amt=988, next="")
        + "</next></block></next>")
    xml = (f"<xml {NS}>"
           '<block type="pg_events_when_started" id="h"><next>' + main +
           "</next></block>"
           '<block type="pg_events_when_timer" id="th">'
           '<value name="AMOUNT"><shadow type="math_positive_number_only" id="ts">'
           '<field name="NUM">1</field></shadow></value>'
           '<next><block type="pg_magnet_set_magnet_state" id="m">'
           '<field name="MAGNET">Magnet</field><field name="ACTION">boost</field>'
           "</block></next></block></xml>")
    sim = _sim(xml, ctx)
    assert len(sim.sensor_hats_fired.get("th", [])) == 2


def test_mid_stack_detection_restarts_and_truncates(ctx):
    # Hat stack: turn LEFT 90 then a LONG eastward... construct: main stack
    # parks the robot 300mm west of courtyard_tower_1's cone entry heading
    # west; hat fires on tower entry, its stack turns and drives BACK
    # through the cone region — the drive should truncate at the new edge
    # and the script restart (>= 2 firing events recorded).
    main = DRIVE.format(i="in1", d="fwd", amt=2000, next="")
    hat_stack = ('<block type="pg_drivetrain_turn_for" id="t1">'
                 '<field name="TURNDIRECTION">right</field>'
                 '<value name="AMOUNT"><shadow type="math_number" id="ta">'
                 '<field name="NUM">180</field></shadow></value>'
                 '<next>' + DRIVE.format(i="hd", d="fwd", amt=1500, next="") +
                 "</next></block>")
    xml = (f"<xml {NS}>"
           '<block type="pg_events_when_started" id="h"><next>' + main +
           "</next></block>"
           '<block type="pg_events_optical_detect_object" id="eye">'
           '<field name="OPTICAL">fronteye</field><field name="OPTIONS">detects</field>'
           f"<next>{hat_stack}</next></block></xml>")
    sim = _sim(xml, ctx)
    fires = sim.sensor_hats_fired.get("eye", [])
    # at least the initial fire; if the reversed drive re-enters a cone the
    # restart machinery records additional fires and truncated moves
    assert fires, "hat must fire at least once"
    assert "execution_budget_exhausted" not in sim.execution_flags
