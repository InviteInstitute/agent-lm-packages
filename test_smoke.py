"""Test suite for log_parser_delta_engine and learner_models.

Run with: python test_smoke.py
Requires `apted` (installed automatically with `pip install .`).
"""
import json
from datetime import datetime, timedelta, timezone

from log_parser_delta_engine import (
    generate_compact_prompt, generate_compact_prompt_from_content,
    generate_compact_prompt_from_project,
    generate_readable_text, generate_readable_lines,
    smart_delta_engine,
)
from log_parser_delta_engine.humanize import ORPHAN_HEADER
from learner_models import (
    compute_run_edit_distances, detect_run_triggers,
    detect_inactive_trigger, segment_session, detect_switches, INACTIVE_RUN_INDEX,
)

NS = 'xmlns="https://developers.google.com/blockly/xml"'
MUT_NS = 'xmlns="http://www.w3.org/1999/xhtml"'


def ws(*blocks, ns=True):
    """A workspace XML string. Real VEX workspaces are namespaced, so that's the
    default; ns=False covers hand-written un-namespaced XML."""
    return f"<xml {NS if ns else ''}>" + "".join(blocks) + "</xml>"


def num(slot, n):
    return (f'<value name="{slot}"><shadow type="math_number">'
            f'<field name="NUM">{n}</field></shadow></value>')


def drive(bid, mm, nxt="", extra=""):
    return (f'<block type="pg_drivetrain_drive_for" id="{bid}" {extra}>'
            '<field name="DIRECTION">fwd</field><field name="UNITS">mm</field>'
            + num("AMOUNT", mm) + (f"<next>{nxt}</next>" if nxt else "") + "</block>")


def turn(bid, deg, nxt="", extra=""):
    return (f'<block type="pg_drivetrain_turn_for" id="{bid}" {extra}>'
            '<field name="TURNDIRECTION">right</field>'
            + num("ANGLE", deg) + (f"<next>{nxt}</next>" if nxt else "") + "</block>")


def started(body="", bid="hat", extra=""):
    return (f'<block type="pg_events_when_started" id="{bid}" {extra}>'
            + (f"<next>{body}</next>" if body else "") + "</block>")


def definition(name, body, bid="def"):
    return (f'<block type="procedures_definition" id="{bid}">'
            '<statement name="custom_block"><shadow type="procedures_prototype">'
            f'<mutation {MUT_NS} proccode="{name}" argumentids="[]"/></shadow></statement>'
            f"<next>{body}</next></block>")


def call(name, bid="call", nxt=""):
    return (f'<block type="procedures_call" id="{bid}">'
            f'<mutation {MUT_NS} proccode="{name}" argumentids="[]"/>'
            + (f"<next>{nxt}</next>" if nxt else "") + "</block>")


def sections(prompt):
    """Split a compact prompt into its (active, orphaned) body lines."""
    lines = prompt.split("\n")
    i = lines.index("[Orphaned]")
    return lines[1:i], lines[i + 1:]


SIMPLE_XML = ws(started(drive("child", 100)), turn("loose", 90))
RICH_XML = ws(started(drive("drive", 200, turn("turn", 90))))


# ---------------------------------------------------------------------------
# log_parser_delta_engine: compact renderer
# ---------------------------------------------------------------------------
def test_compact_prompt_basic():
    prompt = generate_compact_prompt(SIMPLE_XML)
    assert prompt is not None
    assert "events_when_started" in prompt and "drive_for" in prompt
    assert "[Active]" in prompt and "[Orphaned]" in prompt


def test_compact_prompt_orphan_split():
    active, orphaned = sections(generate_compact_prompt(SIMPLE_XML))
    assert "events_when_started" in active[0]
    assert any("drivetrain_drive_for" in ln for ln in active)
    assert orphaned == [" drivetrain_turn_for (TURNDIRECTION=right,ANGLE=90)"]


def test_compact_prompt_value_literals_on_namespaced_xml():
    # Real VEX XML is namespaced; the shadow literal lookup used to miss it and drop
    # every number from the prompt.
    for xml in (RICH_XML, ws(started(drive("drive", 200, turn("turn", 90))), ns=False)):
        prompt = generate_compact_prompt(xml)
        assert "AMOUNT=200" in prompt and "ANGLE=90" in prompt
        assert "DIRECTION=fwd" in prompt and "TURNDIRECTION=right" in prompt


def test_compact_prompt_sequence_stays_at_one_depth():
    # A next chain is a sequence, not nesting: it must not staircase. Each stack
    # opens at depth 1 and its sequence sits at depth 2, so stacks never run together.
    xml = ws(started(drive("drive", 200, turn("turn", 90))), started(drive("x", 5), bid="h2"))
    active, _ = sections(generate_compact_prompt(xml))
    assert active == [
        " events_when_started",
        "  drivetrain_drive_for (DIRECTION=fwd,UNITS=mm,AMOUNT=200)",
        "  drivetrain_turn_for (TURNDIRECTION=right,ANGLE=90)",
        " events_when_started",
        "  drivetrain_drive_for (DIRECTION=fwd,UNITS=mm,AMOUNT=5)",
    ]


def test_compact_prompt_bodies_indent_and_else_is_labeled():
    xml = ws(started(
        '<block type="pg_control_if_then_else" id="if">'
        '<value name="CONDITION"><block type="pg_sensing_bumper" id="b">'
        '<field name="BUMPER">leftbumper</field></block></value>'
        f'<statement name="SUBSTACK">{drive("d", 10)}</statement>'
        f'<statement name="SUBSTACK2">{turn("t", 45)}</statement></block>'))
    active, _ = sections(generate_compact_prompt(xml))
    assert active == [
        " events_when_started",
        "  control_if_then_else",
        "   sensing_bumper (BUMPER=leftbumper)",
        "   drivetrain_drive_for (DIRECTION=fwd,UNITS=mm,AMOUNT=10)",
        "  else:",
        "   drivetrain_turn_for (TURNDIRECTION=right,ANGLE=45)",
    ]


def test_compact_prompt_connected_reporter_covers_shadow():
    # Blockly writes the covered shadow BEFORE the connected block; the block is the
    # real input and its stale default must not leak into the fields.
    xml = ws(started(
        '<block type="pg_control_wait_until" id="w"><value name="CONDITION">'
        '<block type="pg_operator_comparison" id="cmp"><field name="COMPARISON">==</field>'
        '<value name="NUM1"><shadow type="math_number"><field name="NUM">0</field></shadow>'
        '<block type="pg_sensing_position_angle" id="ang"/></value>'
        + num("NUM2", 180) + "</block></value></block>"))
    prompt = generate_compact_prompt(xml)
    assert "operator_comparison (COMPARISON===,NUM2=180)" in prompt
    assert "sensing_position_angle" in prompt
    assert "NUM1=0" not in prompt


def test_compact_prompt_loose_broadcast_is_orphaned():
    # "events_" in the type is not what makes a hat: broadcast is a stack block.
    xml = ws(started(drive("a", 100)),
             '<block type="pg_events_broadcast" id="b"><field name="BROADCAST_OPTION">m</field>'
             f'<next>{drive("z", 900)}</next></block>')
    active, orphaned = sections(generate_compact_prompt(xml))
    assert not any("broadcast" in ln for ln in active)
    assert orphaned[0] == " events_broadcast (BROADCAST_OPTION=m)"
    assert any("AMOUNT=900" in ln for ln in orphaned)


def test_compact_prompt_procedures_are_live_only_when_called():
    called = ws(started(call("go")), definition("go", drive("d", 400)))
    active, orphaned = sections(generate_compact_prompt(called))
    assert "  procedures_call (PROC=go)" in active
    assert " procedures_definition (PROC=go)" in active
    assert orphaned == [" (empty)"]

    uncalled = ws(started(drive("a", 100)), definition("go", drive("d", 400)))
    active, orphaned = sections(generate_compact_prompt(uncalled))
    assert not any("procedures" in ln for ln in active)
    assert orphaned[0] == " procedures_definition (PROC=go)"


def test_compact_prompt_procedure_called_from_orphan_stays_orphaned():
    xml = ws(started(drive("a", 100)), turn("t", 10, call("go")),
             definition("go", drive("d", 400)))
    _, orphaned = sections(generate_compact_prompt(xml))
    assert " procedures_definition (PROC=go)" in orphaned


def test_compact_prompt_marks_disabled_and_counts_only_runnable():
    xml = ws(started(drive("a", 100, turn("off", 90, drive("b", 50), extra='disabled="true"'))))
    engine = smart_delta_engine()
    engine.process_log({"content": {"project": {"workspace": xml}}})
    prompt = engine.generate_compact_prompt()
    assert "  drivetrain_turn_for (TURNDIRECTION=right,ANGLE=90) [disabled]" in prompt
    assert "AMOUNT=50" in prompt                  # the block after it still runs
    assert engine.get_total_blocks() == 4
    assert engine.get_runnable_block_count() == 3


def test_compact_prompt_disabled_hat_is_orphaned():
    xml = ws(started(drive("a", 100), extra='disabled="true"'))
    active, orphaned = sections(generate_compact_prompt(xml))
    assert active == [" (empty)"]
    assert orphaned[0] == " events_when_started [disabled]"


def test_compact_prompt_empty_inputs():
    assert generate_compact_prompt(None) is None
    assert generate_compact_prompt("") is None
    assert generate_compact_prompt("<xml></xml>") is None


def test_compact_prompt_malformed_xml():
    assert generate_compact_prompt("<xml><broken") is None


def test_compact_prompt_from_content():
    content = {"project": {"workspace": SIMPLE_XML}}
    prompt = generate_compact_prompt_from_content(content)
    assert prompt is not None
    assert "events_when_started" in prompt


def test_compact_prompt_from_content_json_string():
    content = {"project": json.dumps({"workspace": SIMPLE_XML})}
    prompt = generate_compact_prompt_from_content(content)
    assert prompt is not None
    assert "events_when_started" in prompt
    assert generate_compact_prompt_from_project(json.dumps({"workspace": SIMPLE_XML})) == prompt


def test_compact_prompt_from_content_empty():
    assert generate_compact_prompt_from_content({}) is None
    assert generate_compact_prompt_from_content({"project": {}}) is None
    assert generate_compact_prompt_from_content(None) is None


# ---------------------------------------------------------------------------
# log_parser_delta_engine: readable renderer
# ---------------------------------------------------------------------------
def test_readable_text_basic():
    text = generate_readable_text(RICH_XML)
    assert "when started" in text
    assert "200" in text
    assert "forward" in text


def test_readable_lines_basic():
    lines = generate_readable_lines(RICH_XML)
    assert isinstance(lines, list)
    assert any("200" in ln for ln in lines)


def test_readable_empty_inputs():
    assert generate_readable_text(None) == ""
    assert generate_readable_text("") == ""
    assert generate_readable_text("<xml><broken") == ""
    assert generate_readable_lines(None) == []
    assert generate_readable_lines("") == []


def test_readable_separates_orphans_from_live_code():
    xml = ws(started(drive("a", 100)), turn("loose", 90),
             '<block type="pg_events_broadcast" id="b"><field name="BROADCAST_OPTION">m</field></block>')
    assert generate_readable_lines(xml) == [
        "when started",
        "drive for forward, mm, amount 100",
        "",
        ORPHAN_HEADER,
        "  turn for right, angle 90",
        "",
        "  broadcast event m",
    ]


def test_readable_separates_concurrent_stacks():
    xml = ws(started(drive("a", 100), bid="h1"), started(turn("t", 90), bid="h2"))
    assert generate_readable_lines(xml) == [
        "when started", "drive for forward, mm, amount 100", "",
        "when started", "turn for right, angle 90",
    ]


def test_readable_only_orphans():
    assert generate_readable_lines(ws(turn("t", 90))) == [ORPHAN_HEADER, "  turn for right, angle 90"]


def test_readable_connected_reporter_covers_shadow():
    xml = ws(started(
        '<block type="pg_control_wait_until" id="w"><value name="CONDITION">'
        '<block type="pg_operator_comparison"><field name="COMPARISON">==</field>'
        '<value name="NUM1"><shadow type="math_number"><field name="NUM">0</field></shadow>'
        '<block type="pg_sensing_position_angle"/></value>'
        + num("NUM2", 180) + "</block></value></block>"))
    line = generate_readable_lines(xml)[1]
    assert line.startswith("wait until (") and "180)" in line
    assert "(0 " not in line


def test_readable_names_procedures():
    xml = ws(started(call("go")), definition("go", drive("d", 400)))
    assert generate_readable_lines(xml) == [
        "when started", "call go", "", "define go", "drive for forward, mm, amount 400",
    ]


def test_readable_procedure_arguments_fill_placeholders():
    xml = ws(started(
        '<block type="procedures_call" id="c">'
        f'<mutation {MUT_NS} proccode="drive %s steps" argumentids=\'["a1"]\'/>'
        + num("a1", 3) + "</block>"),
        '<block type="procedures_definition" id="d"><statement name="custom_block">'
        '<shadow type="procedures_prototype">'
        f'<mutation {MUT_NS} proccode="drive %s steps" argumentids=\'["a1"]\' '
        'argumentnames=\'["count"]\'/></shadow></statement></block>')
    lines = generate_readable_lines(xml)
    assert "call drive 3 steps" in lines
    assert "define drive (count) steps" in lines


def test_readable_loose_operator_renders_as_expression():
    xml = ws(started(),
             '<block type="pg_operator_and_or"><field name="CHECK">and</field>'
             '<value name="OPERAND1"><block type="pg_sensing_bumper">'
             '<field name="BUMPER">leftbumper</field></block></value>'
             '<value name="OPERAND2"><block type="pg_sensing_optical_near_object">'
             '<field name="OPTICAL">fronteye</field></block></value></block>')
    assert generate_readable_lines(xml)[-1] == \
        "  (Bumper pressed leftbumper and eye near object fronteye)"


def test_readable_unknown_types_get_a_derived_name():
    xml = ws(started('<block type="pg_drivetrain_go_to_object">'
                     '<field name="OBJECT">minerals</field></block>'))
    assert generate_readable_lines(xml)[1] == "drivetrain go to object minerals"


def test_readable_marks_disabled_blocks():
    xml = ws(started(drive("a", 100, turn("off", 90, extra='disabled="true"'))))
    assert generate_readable_lines(xml)[-1] == "turn for right, angle 90 (disabled)"


# ---------------------------------------------------------------------------
# log_parser_delta_engine: event stream
# ---------------------------------------------------------------------------
def _vex_event(event_type, workspace, block_event=None):
    """The shape of a real VEX log event: the full project rides on every block
    event, as a JSON string, next to a thin blockEventData delta."""
    content = {"eventType": event_type,
               "project": json.dumps({"mode": "Blocks", "workspace": workspace})}
    if block_event is not None:
        content["blockEventData"] = json.dumps(block_event)
    return {"content": json.dumps(content)}


def test_process_log_rebuilds_from_the_event_snapshot():
    engine = smart_delta_engine()
    # A session starts from a workspace the stream never saw being built.
    engine.process_log(_vex_event("blockCreated", ws(started(), turn("t", 90)),
                                  {"eventType": "create", "blockID": "t",
                                   "blockType": "pg_drivetrain_turn_for"}))
    assert engine.orphan_status["t"] is True
    # Real moves name the new parent but not the slot; the snapshot has the answer.
    engine.process_log(_vex_event("blockMoved", ws(started(turn("t", 90))),
                                  {"eventType": "move", "blockID": "t",
                                   "newInfo": {"parent": "hat"}}))
    assert engine.orphan_status["t"] is False
    assert engine.get_runnable_block_count() == 2
    # Real changes carry fieldName, and shadows never get a create event.
    engine.process_log(_vex_event("blockChanged", ws(started(turn("t", 45))),
                                  {"eventType": "change", "blockID": "shadow",
                                   "blockType": "math_number", "fieldName": "NUM",
                                   "oldValue": 90, "newValue": 45}))
    assert engine.blocks["t"]["fields"]["ANGLE"] == "45"
    engine.process_log(_vex_event("blockDeleted", ws(started()),
                                  {"eventType": "delete", "blockID": "t"}))
    assert "t" not in engine.blocks and engine.get_total_blocks() == 1


def test_process_log_accepts_dict_content_and_ignores_events_without_a_project():
    engine = smart_delta_engine()
    engine.process_log({"content": {"eventType": "runProject",
                                    "project": {"workspace": RICH_XML}}})
    assert engine.get_runnable_block_count() == 3
    engine.process_log({"content": json.dumps({"eventType": "playgroundReset"})})
    engine.process_log({"content": "not json"})
    engine.process_log({})
    assert engine.get_runnable_block_count() == 3
    engine.process_log({"content": {"eventType": "newProject", "project": {"workspace": ""}}})
    assert engine.blocks == {} and engine.generate_compact_prompt() == \
        "[Active]\n (empty)\n[Orphaned]\n (empty)"


# ---------------------------------------------------------------------------
# learner_models: edit distances
# ---------------------------------------------------------------------------
def _make_run(ts, workspace, playground="RoverRescue"):
    return {
        "event_type": "runProject",
        "ts": ts,
        "content": {"eventType": "runProject", "playground": playground,
                    "project": {"workspace": workspace}},
    }


def test_edit_distance_identical_runs():
    xml = '<xml><block type="pg_drive" id="b1"/></xml>'
    events = [_make_run(1000.0, xml), _make_run(2000.0, xml)]
    runs = compute_run_edit_distances(events)["runs"]
    assert runs[0]["edit_distance"] is None
    assert runs[1]["edit_distance"] == 0


def test_edit_distance_different_runs():
    xml_a = '<xml><block type="pg_drive" id="b1"/></xml>'
    xml_b = '<xml><block type="pg_drive" id="b1"/><block type="pg_turn" id="b2"/></xml>'
    events = [_make_run(1000.0, xml_a), _make_run(2000.0, xml_b)]
    runs = compute_run_edit_distances(events)["runs"]
    assert runs[0]["edit_distance"] is None
    assert runs[1]["edit_distance"] is not None
    assert runs[1]["edit_distance"] > 0


def test_playground_switch_resets_distance():
    xml = '<xml><block type="pg_drive" id="b1"/></xml>'
    events = [
        _make_run(1000.0, xml, "RoverRescue"),
        _make_run(2000.0, xml, "CastleCrasherPlus"),
    ]
    runs = compute_run_edit_distances(events)["runs"]
    assert runs[0]["edit_distance"] is None
    assert runs[1]["edit_distance"] is None


# ---------------------------------------------------------------------------
# learner_models: triggers
# ---------------------------------------------------------------------------
def test_wheel_spin_fires():
    fired = {t for (t, _i, _d) in detect_run_triggers([None, 0, 0, 0, 0, 0, 0])}
    assert "wheel_spin" in fired


def test_wheel_spin_dedupes():
    fired = [(t, i) for (t, i, _d) in detect_run_triggers([None, 0, 0, 0, 0, 0, 0, 0, 0])]
    wheel_fires = [(t, i) for (t, i) in fired if t == "wheel_spin"]
    assert len(wheel_fires) == 1


def test_resilience_fires():
    fired = {t for (t, _i, _d) in detect_run_triggers([None, 0, 0, 0, 0, 3])}
    assert "resilience" in fired


def test_explorer_fires():
    fired = {t for (t, _i, _d) in detect_run_triggers([None, 20])}
    assert "explorer" in fired


def test_iterative_fires():
    fired = {t for (t, _i, _d) in detect_run_triggers([None, 1, 1, 1, 1, 1, 1])}
    assert "iterative" in fired


def test_triggers_empty_sequence():
    assert detect_run_triggers([]) == []
    assert detect_run_triggers([None]) == []


# ---------------------------------------------------------------------------
# learner_models: inactive trigger
# ---------------------------------------------------------------------------
def test_inactive_first_fire():
    now = datetime.now(timezone.utc)
    idle = now - timedelta(minutes=10)
    fire = detect_inactive_trigger(idle, now=now, last_inactive_fire=None)
    assert fire is not None
    assert fire[0] == "inactive"
    assert fire[1] == INACTIVE_RUN_INDEX


def test_inactive_no_realert_too_soon():
    now = datetime.now(timezone.utc)
    idle = now - timedelta(minutes=10)
    assert detect_inactive_trigger(idle, now=now, last_inactive_fire=(-1, now)) is None


def test_inactive_realert_after_delay():
    now = datetime.now(timezone.utc)
    idle = now - timedelta(minutes=30)
    old_fire_time = now - timedelta(minutes=15)
    fire = detect_inactive_trigger(idle, now=now, last_inactive_fire=(-1, old_fire_time))
    assert fire is not None
    assert fire[1] == -2


def test_inactive_not_idle():
    now = datetime.now(timezone.utc)
    assert detect_inactive_trigger(now, now=now) is None


def test_inactive_none_ts():
    now = datetime.now(timezone.utc)
    assert detect_inactive_trigger(None, now=now) is None


# ---------------------------------------------------------------------------
# learner_models: session segmentation
# ---------------------------------------------------------------------------
def test_segment_session_basic():
    events = [
        {"event_type": "blockMoved", "ts": 1000.0},
        {"event_type": "blockMoved", "ts": 1005.0},
        {"event_type": "runProject", "ts": 1010.0},
        {"event_type": "projectEnd", "ts": 1015.0},
    ]
    episodes, pauses = segment_session(events)
    assert len(episodes) >= 2
    assert any(e["episode_type"] == "CODE" for e in episodes)
    assert any(e["episode_type"] == "RUN" for e in episodes)


def test_segment_session_inactive_pause():
    events = [
        {"event_type": "blockMoved", "ts": 1000.0},
        {"event_type": "blockMoved", "ts": 1700.0},
    ]
    episodes, pauses = segment_session(events)
    assert any(p["episode_type"] == "INACTIVE_PAUSE" for p in pauses)


def test_segment_session_empty():
    episodes, pauses = segment_session([])
    assert episodes == []
    assert pauses == []


def test_segment_session_no_ts():
    events = [
        {"event_type": "blockMoved", "ts": None},
        {"event_type": "runProject", "ts": None},
    ]
    episodes, pauses = segment_session(events)
    assert len(episodes) >= 1
    assert pauses == []


# ---------------------------------------------------------------------------
# log_parser_delta_engine: compact prompt from a raw project value
# ---------------------------------------------------------------------------
def test_compact_prompt_from_project_dict():
    prompt = generate_compact_prompt_from_project({"workspace": RICH_XML})
    assert prompt is not None
    assert "drive_for" in prompt
    assert "AMOUNT=200" in prompt


def test_compact_prompt_from_project_json_string():
    prompt = generate_compact_prompt_from_project(json.dumps({"workspace": RICH_XML}))
    assert prompt is not None
    assert "drive_for" in prompt


def test_compact_prompt_from_project_empty():
    assert generate_compact_prompt_from_project(None) is None
    assert generate_compact_prompt_from_project({}) is None
    assert generate_compact_prompt_from_project({"workspace": ""}) is None


# ---------------------------------------------------------------------------
# learner_models: identity switches
# ---------------------------------------------------------------------------
def test_switches_casing_and_class():
    switches = detect_switches("cobra3", "FPFVDH", "Cobra3", "AFURRR")
    assert switches == [("casing", "cobra3", "Cobra3"), ("class", "FPFVDH", "AFURRR")]


def test_switches_casing_only():
    assert detect_switches("cobra3", "FPFVDH", "Cobra3", "FPFVDH") == [
        ("casing", "cobra3", "Cobra3")
    ]


def test_switches_none_when_unchanged_or_missing():
    assert detect_switches("cobra3", "FPFVDH", "cobra3", "FPFVDH") == []
    assert detect_switches(None, None, "cobra3", "FPFVDH") == []  # first event, no prior
    assert detect_switches("", "", "cobra3", "FPFVDH") == []      # empty prior is not a switch


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------
ALL_TESTS = [
    v for k, v in sorted(globals().items())
    if k.startswith("test_") and callable(v)
]


if __name__ == "__main__":
    passed = 0
    failed = 0
    for test in ALL_TESTS:
        try:
            test()
            print(f"  PASS  {test.__name__}")
            passed += 1
        except Exception as e:
            print(f"  FAIL  {test.__name__}: {e}")
            failed += 1
    print(f"\n{passed} passed, {failed} failed, {len(ALL_TESTS)} total")
    if failed:
        exit(1)
