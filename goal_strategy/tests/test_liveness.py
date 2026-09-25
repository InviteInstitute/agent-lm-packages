"""Liveness: which top-level stacks can run, end to end through scoring.

A stack is live when it starts at an enabled hat, or it is a My Block definition that
live code calls. Disabled blocks never run but the block after them does. These pin the
audit fixes (2026-09-25):
  * a "pg_events_" prefix made a detached broadcast stack count (and run) as a hat;
  * called My Block bodies were invisible to the code channel, the battery, the rubric
    census and the unmodeled-block gate, while the simulator ran them;
  * disabled blocks were executed.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET

import pytest

from goal_strategy.detector.parsing.block_program import HAT_BLOCK_TYPES
from goal_strategy.detector.parsing.parse_blocks import parse_workspace
from goal_strategy.execution import prepare_execution
from goal_strategy.profile import profile
from goal_strategy.serialize import profile_to_dict
from goal_strategy.testcases import qualifying_blocks
from goal_strategy.tests.test_oi23_builds import _call, _definition
from goal_strategy.tests.test_rubric_evidence import _ev
from log_parser_delta_engine import liveness

NS = 'xmlns="https://developers.google.com/blockly/xml"'


def _ws(*blocks):
    return f"<xml {NS}>" + "".join(blocks) + "</xml>"


def _drive(i, mm, nxt="", extra=""):
    return (f'<block type="pg_drivetrain_drive_for" id="{i}" {extra}>'
            '<field name="DIRECTION">fwd</field><field name="UNITS">mm</field>'
            f'<value name="DISTANCE"><shadow type="math_number" id="{i}s">'
            f'<field name="NUM">{mm}</field></shadow></value>'
            + (f"<next>{nxt}</next>" if nxt else "") + "</block>")


def _started(body="", extra=""):
    return (f'<block type="pg_events_when_started" id="h" {extra}>'
            + (f"<next>{body}</next>" if body else "") + "</block>")


_MAGNET = ('<block type="pg_magnet_set_magnet_state" id="m">'
           '<field name="MAGNET">magnet</field><field name="STATE">boost</field></block>')
_EYE_WAIT = ('<block type="pg_control_wait_until" id="w"><value name="CONDITION">'
             '<block type="pg_sensing_optical_near_object" id="e">'
             f'<field name="OPTICAL">fronteye</field></block></value><next>{_MAGNET}</next></block>')


def _without(d, *keys):
    return {k: v for k, v in d.items() if k not in keys}


def _final_x(xml):
    return prepare_execution(xml, "liveness").context.full_sim.final_x


def _code_indicators(xml):
    return {(g.goal, i.name): (i.value, i.rung)
            for g in profile(xml, "liveness").goals
            for i in g.intent + g.attainment if i.channel == "code"}


# ---------------------------------------------------------------- hats

def test_hat_set_is_shared_with_the_log_parser():
    assert HAT_BLOCK_TYPES == liveness.HAT_BLOCK_TYPES


@pytest.mark.parametrize("loose_type", ["pg_events_broadcast", "pg_events_broadcast_and_wait"])
def test_loose_broadcast_stack_is_an_orphan_and_changes_no_score(loose_type):
    base = _ws(_started(_drive("a", 100)))
    loose = _ws(_started(_drive("a", 100)),
                f'<block type="{loose_type}" id="b" x="400" y="0">'
                f'<field name="BROADCAST_OPTION">m</field><next>{_drive("z", 900)}</next></block>')
    program = parse_workspace(loose, "liveness")
    assert [s.block_type for s in program.event_handler_stacks] == ["pg_events_when_started"]
    assert [s.block_type for s in program.orphan_stacks] == [loose_type]

    before, after = profile_to_dict(profile(base, "t")), profile_to_dict(profile(loose, "t"))
    assert after["orphan_block_count"] == 3          # broadcast, drive, its shadow
    assert _without(after, "orphan_block_count") == _without(before, "orphan_block_count")


# ---------------------------------------------------------- My Blocks

def test_called_my_block_is_live_code_everywhere():
    inline = _ws(_started(_drive("d", 400, _EYE_WAIT)))
    wrapped = _ws(_started(_call("go")), _definition("go", _drive("d", 400, _EYE_WAIT)))
    program = parse_workspace(wrapped, "liveness")
    assert [s.block_type for s in program.procedure_stacks] == ["procedures_definition"]
    assert program.orphan_stacks == [] and program.orphan_block_count == 0

    assert _code_indicators(wrapped) == _code_indicators(inline)
    assert _code_indicators(wrapped)[("engage_plow", "magnet_activation_intent")][1] == "boost"
    assert qualifying_blocks(program) == qualifying_blocks(parse_workspace(inline, "i")) \
        == ["pg_sensing_optical_near_object"]
    assert _final_x(wrapped) == _final_x(inline)


def test_uncalled_my_block_is_an_orphan():
    xml = _ws(_started(_drive("a", 100)), _definition("go", _drive("d", 400, _EYE_WAIT)))
    program = parse_workspace(xml, "liveness")
    assert program.procedure_stacks == []
    assert [s.block_type for s in program.orphan_stacks] == ["procedures_definition"]
    assert qualifying_blocks(program) == []
    assert _code_indicators(xml)[("engage_plow", "magnet_activation_intent")][1] == "absent"


def test_my_block_called_only_from_an_orphan_or_another_live_block():
    from_orphan = _ws(_started(_drive("a", 100)), _drive("o", 5, _call("go")),
                      _definition("go", _MAGNET))
    assert parse_workspace(from_orphan, "t").procedure_stacks == []

    chained = _ws(_started(_call("outer", "c1")),
                  _definition("outer", _call("inner", "c2"), "d1"),
                  _definition("inner", _MAGNET, "d2"))
    assert [s.block_id for s in parse_workspace(chained, "t").procedure_stacks] == ["d1", "d2"]


def test_duplicate_my_block_definition_is_an_orphan():
    xml = _ws(_started(_call("go")), _definition("go", _MAGNET, "d1"),
              _definition("go", _drive("x", 5), "d2"))
    program = parse_workspace(xml, "t")
    assert [s.block_id for s in program.procedure_stacks] == ["d1"]
    assert [s.block_id for s in program.orphan_stacks] == ["d2"]


def test_unmodeled_block_inside_a_called_my_block_is_flagged():
    body = '<block type="pg_brand_new_2099" id="u"></block>'
    called = _ws(_started(_call("go")), _definition("go", body))
    uncalled = _ws(_started(_drive("a", 10)), _definition("go", body))
    flags = lambda xml: prepare_execution(xml, "t").context.full_sim.execution_flags
    assert "unmodeled_blocks" in flags(called)
    assert "unmodeled_blocks" not in flags(uncalled)


def test_rubric_sees_sensing_in_a_my_block_called_inside_a_loop():
    check = ('<block type="pg_control_if_then" id="if"><value name="CONDITION">'
             '<block type="pg_sensing_optical_near_object" id="e">'
             '<field name="OPTICAL">fronteye</field></block></value>'
             f'<statement name="SUBSTACK">{_MAGNET}</statement></block>')

    def looped(body):
        return ('<block type="pg_control_repeat" id="r"><value name="TIMES">'
                '<shadow type="math_number"><field name="NUM">3</field></shadow></value>'
                f'<statement name="SUBSTACK">{body}</statement></block>')

    inline = _ev(_ws(_started(looped(check))))
    wrapped = _ev(_ws(_started(looped(_call("check"))), _definition("check", check)))
    assert inline.sensing_in_recurrent and wrapped.sensing_in_recurrent
    assert wrapped.sensing_in_executable and wrapped.has_procedures
    assert wrapped.max_nesting_depth == inline.max_nesting_depth == 2


def test_recursive_my_block_does_not_hang_ancestry():
    xml = _ws(_started(_call("loop", "c1")),
              _definition("loop", _drive("d", 10, _call("loop", "c2"))))
    assert _ev(xml).procedure_metrics["calls"] == 2


# ------------------------------------------------------------ disabled

def test_disabled_block_in_live_code_does_not_run_but_its_next_does():
    live = _ws(_started(_drive("a", 100)))
    with_disabled = _ws(_started(_drive("off", 500, _drive("a", 100), extra='disabled="true"')))
    assert _final_x(with_disabled) == _final_x(live)
    program = parse_workspace(with_disabled, "t")
    assert [b.block_id for b in program.iter_all_blocks()] == ["h", "a", "as"]
    assert program.disabled_block_count == 2


def test_newer_disabled_reasons_attribute_is_honored():
    xml = _ws(_started(_drive("off", 500, extra='disabled-reasons="MANUALLY_DISABLED"')))
    assert parse_workspace(xml, "t").active_block_count == 1


def test_disabled_body_block_and_reporter():
    body = _ws(_started(
        '<block type="pg_control_repeat" id="r"><value name="TIMES">'
        '<shadow type="math_number" id="n"><field name="NUM">2</field></shadow></value>'
        f'<statement name="SUBSTACK">{_drive("off", 500, extra="disabled=\"true\"")}'
        '</statement></block>'))
    assert {b.block_id for b in parse_workspace(body, "t").iter_all_blocks()} == {"h", "r", "n"}

    # A disabled reporter leaves its slot to the shadow default.
    slot = _ws(_started(
        '<block type="pg_drivetrain_drive_for" id="d"><field name="DIRECTION">fwd</field>'
        '<field name="UNITS">mm</field><value name="DISTANCE">'
        '<shadow type="math_number" id="s"><field name="NUM">250</field></shadow>'
        '<block type="pg_sensing_distance_distance" id="r" disabled="true">'
        '<field name="DISTANCE">frontdistance</field></block></value></block>'))
    drive = parse_workspace(slot, "t").event_handler_stacks[0].next
    assert drive.value_slots["DISTANCE"].block_id == "s"


def test_disabled_hat_and_detached_disabled_blocks_are_orphans_as_authored():
    xml = _ws(_started(_drive("a", 100), extra='disabled="true"'),
              _drive("loose", 5, extra='disabled="true"'))
    program = parse_workspace(xml, "t")
    assert program.event_handler_stacks == []
    assert [s.block_id for s in program.orphan_stacks] == ["h", "loose"]
    assert program.orphan_block_count == 5 and program.disabled_block_count == 0


# -------------------------------------------- agreement across packages

_AGREEMENT_CASES = [
    _ws(_started(_drive("a", 1)), _drive("b", 2)),
    _ws('<block type="pg_events_broadcast" id="b"><field name="BROADCAST_OPTION">m</field></block>'),
    _ws(_started(_call("go")), _definition("go", _MAGNET)),
    _ws(_started(_drive("a", 1)), _definition("go", _MAGNET)),
    _ws(_started(_drive("a", 1), extra='disabled="true"')),
    _ws(_started(_call("go")), _definition("go", _MAGNET, "d1"), _definition("go", _MAGNET, "d2")),
    _ws(_started(_drive("off", 1, _call("go"), extra='disabled="true"')),
        _definition("go", _MAGNET)),
    _ws(_started(
        '<block type="pg_control_repeat" id="r" disabled="true"><statement name="SUBSTACK">'
        f'{_call("go")}</statement></block>'), _definition("go", _MAGNET)),
]


@pytest.mark.parametrize("xml", _AGREEMENT_CASES)
def test_parser_and_renderers_agree_on_liveness(xml):
    program = parse_workspace(xml, "t")
    root = liveness.strip_namespaces(ET.fromstring(xml))
    active, orphaned = liveness.split_stacks(root)
    assert {s.block_id for s in program.live_stacks} == {el.get("id") for el in active}
    assert [s.block_id for s in program.orphan_stacks] == [el.get("id") for el in orphaned]
