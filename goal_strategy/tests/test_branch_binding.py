"""Name-bound conditional branches (CROW-C117 fix, 2026-08-24): branch
identity comes from statement slot NAMES, not positions — an else-only
if_then_else must run its else on a false condition, never execute the
else body as the if-branch. Empty condition slots evaluate false (VEX)."""
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


DRIVE = ('<block type="pg_drivetrain_drive_for" id="{i}">'
         '<field name="DIRECTION">fwd</field><field name="UNITS">mm</field>'
         '<value name="AMOUNT"><shadow type="math_number" id="{i}s">'
         '<field name="NUM">{amt}</field></shadow></value></block>')
RED = ('<block type="pg_sensing_optical_color" id="c">'
       '<field name="OPTICAL">downeye</field><field name="COLORS">red</field></block>')
NONE_COLOR = ('<block type="pg_sensing_optical_color" id="c">'
              '<field name="OPTICAL">downeye</field><field name="COLORS">none</field></block>')


def _prog(if_block):
    return (f"<xml {NS}>"
            '<block type="pg_events_when_started" id="h"><next>'
            f"{if_block}</next></block></xml>")


def _sim(xml, ctx):
    return simulate_path(parse_workspace(xml, "branch-test"), ctx)


def test_else_only_if_runs_else_on_false_condition(ctx):
    # condition red (false at spawn), NO if-branch, else = drive: the else
    # must run — under positional binding the else body sat at children[0]
    # and was skipped as the "if-branch" (the CROW-C117 defect).
    xml = _prog('<block type="pg_control_if_then_else" id="if1">'
                f'<value name="CONDITION">{RED}</value>'
                f'<statement name="SUBSTACK2">{DRIVE.format(i="e", amt=200)}</statement>'
                "</block>")
    sim = _sim(xml, ctx)
    assert [p for p in sim.path if p.block_id == "e"], "else branch must execute"


def test_else_only_if_runs_nothing_on_true_condition(ctx):
    xml = _prog('<block type="pg_control_if_then_else" id="if1">'
                f'<value name="CONDITION">{NONE_COLOR}</value>'   # true at spawn
                f'<statement name="SUBSTACK2">{DRIVE.format(i="e", amt=200)}</statement>'
                "</block>")
    sim = _sim(xml, ctx)
    assert not [p for p in sim.path if p.block_id == "e"]


def test_both_branches_bind_normally(ctx):
    xml = _prog('<block type="pg_control_if_then_else" id="if1">'
                f'<value name="CONDITION">{NONE_COLOR}</value>'
                f'<statement name="SUBSTACK">{DRIVE.format(i="t", amt=100)}</statement>'
                f'<statement name="SUBSTACK2">{DRIVE.format(i="e", amt=200)}</statement>'
                "</block>")
    sim = _sim(xml, ctx)
    assert [p for p in sim.path if p.block_id == "t"]
    assert not [p for p in sim.path if p.block_id == "e"]


def test_elseif_chain_binds_by_name(ctx):
    xml = _prog('<block type="pg_control_if_elseif_else" id="if1">'
                f'<value name="CONDITION1">{RED}</value>'          # false
                f'<statement name="SUBSTACK1">{DRIVE.format(i="b1", amt=100)}</statement>'
                f'<value name="CONDITION2">{NONE_COLOR}</value>'   # true
                f'<statement name="SUBSTACK2">{DRIVE.format(i="b2", amt=200)}</statement>'
                f'<statement name="SUBSTACK_ELSE">{DRIVE.format(i="be", amt=300)}</statement>'
                "</block>")
    sim = _sim(xml, ctx)
    assert [p for p in sim.path if p.block_id == "b2"]
    assert not [p for p in sim.path if p.block_id in ("b1", "be")]


def test_empty_condition_falls_to_else(ctx):
    # VEX: an empty boolean slot is false -> the else runs
    xml = _prog('<block type="pg_control_if_then_else" id="if1">'
                f'<statement name="SUBSTACK">{DRIVE.format(i="t", amt=100)}</statement>'
                f'<statement name="SUBSTACK2">{DRIVE.format(i="e", amt=200)}</statement>'
                "</block>")
    sim = _sim(xml, ctx)
    assert [p for p in sim.path if p.block_id == "e"]
    assert not [p for p in sim.path if p.block_id == "t"]
