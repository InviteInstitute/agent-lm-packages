"""Run scoring counts typed-in values and only the code that runs."""
import xml.etree.ElementTree as ET

import pytest

from learner_models.distance import clear_cache
from learner_models.run_sequence import RunDistanceStream, compute_run_edit_distances

NS = 'xmlns="https://developers.google.com/blockly/xml"'


def drive(value=100, kind="shadow", bid="d", inside=""):
    """A drive block whose DISTANCE slot holds `value` as a shadow or a real block."""
    return (f'<block type="pg_drive" id="{bid}"><value name="DISTANCE">'
            f'<{kind} type="math_number" id="n{bid}"><field name="NUM">{value}</field></{kind}>'
            f'{inside}</value></block>')


def hat(body="", kind="pg_events_when_started", bid="s", extra=""):
    nxt = f"<next>{body}</next>" if body else ""
    return f'<block type="{kind}" id="{bid}" {extra}>{nxt}</block>'


def ws(*tops):
    return f'<xml {NS}>{"".join(tops)}</xml>'


def events(*xmls):
    return [{"event_type": "runProject", "ts": i,
             "content": {"playground": "CastleCrasherPlus", "project": {"workspace": x}}}
            for i, x in enumerate(xmls)]


def score(a, b):
    clear_cache()
    return compute_run_edit_distances(events(a, b))["runs"][1]["edit_distance"]


def my_block(body, called=True):
    proto = ('<statement name="custom_block"><shadow type="procedures_prototype" id="pp">'
             '<mutation proccode="go"/></shadow></statement>')
    call = '<block type="procedures_call" id="c"><mutation proccode="go"/></block>'
    return ws(hat(call if called else ""),
              f'<block type="procedures_definition" id="p">{proto}<next>{body}</next></block>')


def test_numeric_parameter():
    assert score(ws(hat(drive(100))), ws(hat(drive(150)))) == 1


def test_text_parameter():
    a = ws(hat(drive("hello"))).replace("math_number", "text").replace("NUM", "TEXT")
    assert score(a, a.replace("hello", "world")) == 1


def test_real_literal_block_edit_is_not_doubled():
    assert score(ws(hat(drive(1, "block"))), ws(hat(drive(2, "block")))) == 1


def test_shadow_hidden_behind_a_block_does_not_count():
    def covered(v):
        return ws(hat(drive(v, inside='<block type="pg_sensing_x" id="r"/>')))
    assert score(covered(1), covered(2)) == 0


def test_drive_insertion_cost_is_not_doubled():
    assert score(ws(hat()), ws(hat(drive()))) == 1


@pytest.mark.parametrize("pair", [
    ("", '<block type="turn" id="o"><field name="X">1</field></block>'),
    ('<block type="turn" id="o"><field name="X">1</field></block>', ""),
    ('<block type="turn" id="o"><field name="X">1</field></block>',
     '<block type="turn" id="o"><field name="X">2</field></block>'),
])
def test_orphan_add_delete_and_edit(pair):
    assert score(ws(hat(drive()), pair[0]), ws(hat(drive()), pair[1])) == 0


def test_detached_program_is_empty_until_attached():
    assert score(ws(drive(100)), ws(drive(150))) == 0
    assert score(ws(drive()), ws(hat(drive()))) > 0


def test_disabled_hat_does_not_run():
    def off(v):
        return ws(hat(drive(v), extra='disabled="true"'))
    assert score(off(1), off(2)) == 0


@pytest.mark.parametrize("kind", ["pg_events_when_broadcasted", "pg_events_when_bumper",
                                  "pg_events_when_timer"])
def test_other_hats_run(kind):
    def two(v):
        return ws(hat(drive()), hat(drive(v, bid="d2"), kind=kind, bid="h2"))
    assert score(two(20), two(30)) == 1


def test_multiple_start_stacks():
    def two(v):
        return ws(hat(drive()), hat(drive(v, bid="d2"), bid="s2"))
    assert score(two(20), two(30)) == 1


def test_called_my_block_runs_and_uncalled_does_not():
    assert score(my_block(drive(1)), my_block(drive(2))) == 1
    assert score(my_block(drive(1), called=False), my_block(drive(2), called=False)) == 0


def test_disabling_a_block_scores_like_deleting_it():
    tail = drive(2, bid="d2")
    on = ws(hat(drive(1).replace("</block>", f"<next>{tail}</next></block>", 1)))
    off = on.replace('id="d"', 'id="d" disabled="true"', 1)
    assert score(on, off) == score(on, ws(hat(tail))) == 1


def test_edits_inside_a_disabled_block_do_not_count():
    def loop(v):
        body = drive(v)
        return ws(hat(f'<block type="pg_control_repeat" id="r" disabled="true">'
                      f'<statement name="DO">{body}</statement></block>'))
    assert score(loop(1), loop(2)) == 0

    def covered(v):  # a disabled block in a slot falls back to the shadow under it
        return ws(hat(drive(5, inside=f'<block type="math_number" id="m" disabled="true">'
                                      f'<field name="NUM">{v}</field></block>')))
    assert score(covered(1), covered(2)) == 0


def test_which_my_block_is_called_counts():
    def two(first, second):
        calls = (f'<block type="procedures_call" id="c1"><mutation proccode="{first}"/><next>'
                 f'<block type="procedures_call" id="c2"><mutation proccode="{second}"/>'
                 '</block></next></block>')
        proto = '<statement name="custom_block"><shadow type="procedures_prototype" id="p{0}">' \
                '<mutation proccode="{0}"/></shadow></statement>'
        defs = "".join(f'<block type="procedures_definition" id="{p}">{proto.format(p)}'
                       f'<next>{drive(p, bid="d" + p)}</next></block>' for p in "ab")
        return ws(hat(calls), defs)
    assert score(two("a", "b"), two("b", "a")) == 2


def test_orphans_do_not_hit_size_guard():
    orphans = "".join(f'<block type="turn" id="o{i}"/>' for i in range(601))
    assert score(ws(hat(drive(100)), orphans), ws(hat(drive(150)), orphans)) == 1


@pytest.mark.parametrize("bad", ["", "<xml", "<xml><block type='a'>\ud800</block></xml>"])
def test_bad_xml_scores_as_empty(bad):
    assert score(bad, ws(hat())) == 1


def test_live_batch_parity_and_playground_reset():
    es = events(ws(hat(drive())), ws(hat(drive(150))), ws(hat(drive(200))))
    es[-1]["content"]["playground"] = "RoverRescue"
    clear_cache()
    stream = RunDistanceStream()
    for ev in es:
        stream.push(ev)
    assert stream.runs == compute_run_edit_distances(es)["runs"]
    assert [r["edit_distance"] for r in stream.runs] == [None, 1, None]


# ---------------------------------------------------------------------------
# Every kind of edit a student can make, on one realistic program, and what it
# should score. 0 means the robot does exactly what it did before.
# ---------------------------------------------------------------------------
def _drive(amount="100", direction="fwd", bid="d", extra=""):
    return (f'<block type="pg_drivetrain_drive_for" id="{bid}"{extra}>'
            f'<field name="DIRECTION">{direction}</field>'
            f'<value name="DISTANCE"><shadow type="math_number" id="n{bid}">'
            f'<field name="NUM">{amount}</field></shadow></value>')


_TURN = ('<block type="pg_drivetrain_turn_for" id="t"><field name="TURNDIRECTION">right</field>'
         '<value name="ANGLE"><shadow type="math_number" id="nt"><field name="NUM">90</field>'
         '</shadow></value></block>')
_PEN = ('<block type="pg_looks_set_pen_color" id="p"><value name="COLOR">'
        '<shadow type="pg_looks_color_menu" id="pm"><field name="COLOR">black</field></shadow>'
        '</value></block>')


def program(drive=None, after=_TURN, hat_type="pg_events_when_started", hat_extra=' x="10" y="10"',
            tops="", head='<variables><variable id="v1">count</variable></variables>', ns=True):
    drive = drive if drive is not None else _drive()
    body = f'{drive}<next>{after}</next></block>' if after else f"{drive}</block>"
    xmlns = f" {NS}" if ns else ""
    return (f'<xml{xmlns}>{head}<block type="{hat_type}" id="s"{hat_extra}><next>{body}</next>'
            f'</block>{tops}</xml>')


BASE = program()
CALL = '<block type="procedures_call" id="c"><mutation proccode="{}"/></block>'


def _definition(name, body):
    return (f'<block type="procedures_definition" id="def{name}"><statement name="custom_block">'
            f'<shadow type="procedures_prototype" id="pp{name}"><mutation proccode="{name}"/>'
            f'</shadow></statement><next>{body}</next></block>')


SAME = {
    "move a stack on the canvas": program(hat_extra=' x="300" y="45"'),
    "collapse a block": program(_drive(extra=' collapsed="true"')),
    "inline inputs": program(_drive(extra=' inline="true"')),
    "lock a block": program(_drive(extra=' deletable="false" movable="false" editable="false"')),
    "every block gets a new id": BASE.replace('id="', 'id="copy-'),
    "add a block comment": BASE.replace("</field>", '</field><comment pinned="false" h="80" '
                                        'w="160">why</comment>', 1),
    "add a workspace comment": program(tops='<comment x="1" y="1" h="80" w="160">hi</comment>'),
    "add a comment block": program(after=f'<block type="{"aim_other_comment"}" id="cm">'
                                         f'<field name="COMMENT">todo</field><next>{_TURN}</next>'
                                         '</block>'),
    "declare an unused variable": program(head='<variables><variable id="v2">x</variable></variables>'),
    "whitespace around a value": program(_drive(" 100 ")),
    "no xml namespace": program(ns=False),
    "empty next connection": program(after=_TURN.replace("</block>", "<next></next></block>")),
    "add an orphan block": program(tops=_PEN),
    "add an uncalled My Block": program(tops=_definition("go", _PEN)),
    "edit a value hidden behind a sensor": None,  # filled in below
}
_COVERED = ('<block type="pg_drivetrain_drive_for" id="d"><field name="DIRECTION">fwd</field>'
            '<value name="DISTANCE"><shadow type="math_number" id="nd"><field name="NUM">{}</field>'
            '</shadow><block type="pg_sensing_distance_distance" id="r"/></value>')
SAME["edit a value hidden behind a sensor"] = (program(_COVERED.format(1)), program(_COVERED.format(2)))


@pytest.mark.parametrize("name", sorted(SAME))
def test_edits_that_change_nothing_that_runs_score_0(name):
    case = SAME[name]
    before, after = case if isinstance(case, tuple) else (BASE, case)
    ET.fromstring(before), ET.fromstring(after)  # a broken fixture would score 0 too
    assert score(before, after) == 0


CHANGED = {
    "edit a number": (BASE, program(_drive("150")), 1),
    "pick another dropdown option": (BASE, program(_drive(direction="rev")), 1),
    "pick another menu shadow option": (program(after=_PEN), program(after=_PEN.replace("black", "red")), 1),
    "insert a block": (program(after=""), BASE, 1),
    "delete a block": (BASE, program(after=""), 1),
    "swap a block for another type": (BASE, program(after=_TURN.replace("turn_for", "turn")), 1),
    "disable a block": (BASE, program(after=_TURN.replace('id="t"', 'id="t" disabled="true"')), 1),
    "enable a block": (program(after=_TURN.replace('id="t"', 'id="t" disabled="true"')), BASE, 1),
    "change the hat": (BASE, program(hat_type="pg_events_when_bumper"), 1),
    "change a value inside a nested shadow": (
        program(after=_PEN.replace('black</field>', 'black</field><value name="ALPHA"><shadow '
                                   'type="math_number" id="a"><field name="NUM">5</field></shadow>'
                                   '</value>')),
        program(after=_PEN.replace('black</field>', 'black</field><value name="ALPHA"><shadow '
                                   'type="math_number" id="a"><field name="NUM">9</field></shadow>'
                                   '</value>')), 1),
    "edit Switch Python": (program(after='<block type="pg_mixed_multiline_command" id="m">'
                                         '<field name="CODE">drivetrain.drive(FORWARD)</field></block>'),
                           program(after='<block type="pg_mixed_multiline_command" id="m">'
                                         '<field name="CODE">drivetrain.drive(REVERSE)</field></block>'), 1),
    "edit inside a called My Block": (program(after=CALL.format("go"), tops=_definition("go", _drive("1", bid="g") + "</block>")),
                                      program(after=CALL.format("go"), tops=_definition("go", _drive("2", bid="g") + "</block>")), 1),
    # Pinned on purpose: the slot's number goes away (1) and a sensor comes in (1).
    "plug a sensor over a number": (BASE, program(_COVERED.format(100)), 2),
    # Pinned on purpose: the call changes (1) and the definition that runs changes (1).
    "call another My Block": (program(after=CALL.format("a"), tops=_definition("a", _PEN) + _definition("b", _PEN)),
                              program(after=CALL.format("b"), tops=_definition("a", _PEN) + _definition("b", _PEN)), 2),
    "delete the hat": (BASE, program(hat_type="pg_drivetrain_drive_for"), 3),
    "move a block into a loop": (
        program(after='<block type="pg_control_forever" id="f"><next>' + _TURN + '</next></block>'),
        program(after='<block type="pg_control_forever" id="f"><statement name="SUBSTACK">'
                      + _TURN + '</statement></block>'), 1),
    # Pinned on purpose: the loop comes in (1) and the block moves into it (1).
    "wrap a block in a loop": (BASE, program(after='<block type="pg_control_forever" id="f">'
                                                   '<statement name="SUBSTACK">' + _TURN
                                                   + '</statement></block>'), 2),
    "add a second stack": (BASE, program(tops='<block type="pg_events_when_bumper" id="b2">'
                                              '<next>' + _PEN + '</next></block>'), 2),
    "typed text that looks like another field": (
        program(after=_PEN.replace("black", "x")), program(after=_PEN.replace("black", "x|B=2")), 1),
    "disable the hat": (BASE, program(hat_extra=' disabled="true"'), 3),
}


@pytest.mark.parametrize("name", sorted(CHANGED))
def test_edits_that_change_what_runs(name):
    before, after, want = CHANGED[name]
    ET.fromstring(before), ET.fromstring(after)
    assert score(before, after) == want
    assert score(after, before) == want  # undoing an edit costs the same
