"""Run scoring counts typed-in values and only the code that runs."""
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
