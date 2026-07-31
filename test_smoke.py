"""Test suite for LogParserDeltaEngine and LearnerModels.

Run with: python test_smoke.py
Needs `apted` (LearnerModels).
"""
import json
from datetime import datetime, timedelta, timezone

from LogParserDeltaEngine import (
    generate_compact_prompt, generate_compact_prompt_from_content,
    generate_readable_text, generate_readable_lines,
    smart_delta_engine,
)
from LearnerModels import (
    compute_run_edit_distances, detect_run_triggers, detect_run_triggers_by_playground,
    detect_inactive_trigger, segment_session, INACTIVE_RUN_INDEX,
)

SIMPLE_XML = (
    '<xml>'
    '  <block type="events_whenStarted" id="hat" x="0" y="0">'
    '    <statement name="STACK"><block type="pg_drive" id="child"/></statement>'
    '  </block>'
    '  <block type="pg_turn" id="loose" x="200" y="200"/>'
    '</xml>'
)

RICH_XML = (
    '<xml>'
    '<block type="pg_events_when_started" id="hat">'
    '<next><block type="pg_drivetrain_drive_for" id="drive">'
    '<field name="DIRECTION">fwd</field><field name="UNITS">mm</field>'
    '<value name="AMOUNT"><shadow type="math_number"><field name="NUM">200</field></shadow></value>'
    '</block>'
    '<next><block type="pg_drivetrain_turn_for" id="turn">'
    '<field name="DIRECTION">right</field><field name="UNITS">deg</field>'
    '<value name="AMOUNT"><shadow type="math_number"><field name="NUM">90</field></shadow></value>'
    '</block></next>'
    '</next></block></xml>'
)


# ---------------------------------------------------------------------------
# LogParserDeltaEngine: compact renderer
# ---------------------------------------------------------------------------
def test_compact_prompt_basic():
    prompt = generate_compact_prompt(SIMPLE_XML)
    assert prompt is not None
    assert "whenStarted" in prompt and "drive" in prompt
    assert "[Active]" in prompt and "[Orphaned]" in prompt


def test_compact_prompt_orphan_split():
    prompt = generate_compact_prompt(SIMPLE_XML)
    lines = prompt.split("\n")
    active_section = lines.index("[Active]")
    orphan_section = lines.index("[Orphaned]")
    active_block = lines[active_section + 1]
    orphan_block = lines[orphan_section + 1]
    assert "whenStarted" in active_block
    assert "turn" in orphan_block


def test_compact_prompt_value_literals():
    prompt = generate_compact_prompt(RICH_XML)
    assert "AMOUNT=200" in prompt
    assert "AMOUNT=90" in prompt
    assert "DIRECTION=fwd" in prompt
    assert "DIRECTION=right" in prompt


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
    assert "whenStarted" in prompt


def test_compact_prompt_from_content_json_string():
    content = {"project": json.dumps({"workspace": SIMPLE_XML})}
    prompt = generate_compact_prompt_from_content(content)
    assert prompt is not None
    assert "whenStarted" in prompt


def test_compact_prompt_from_content_empty():
    assert generate_compact_prompt_from_content({}) is None
    assert generate_compact_prompt_from_content({"project": {}}) is None
    assert generate_compact_prompt_from_content(None) is None


# ---------------------------------------------------------------------------
# LogParserDeltaEngine: readable renderer
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


# ---------------------------------------------------------------------------
# LogParserDeltaEngine: delta path
# ---------------------------------------------------------------------------
def test_delta_create_with_initial_fields():
    engine = smart_delta_engine()

    def send(evt):
        engine.process_log({"content": json.dumps(evt)})

    send({"eventType": "blockEventData", "blockEventData": json.dumps({
        "eventType": "create", "blockID": "b1", "blockType": "pg_drivetrain_drive_for",
        "fields": [{"name": "DIRECTION", "value": "fwd"}, {"name": "UNITS", "value": "mm"}]})})

    assert engine.blocks["b1"]["fields"]["DIRECTION"] == "fwd"
    assert engine.blocks["b1"]["fields"]["UNITS"] == "mm"


def test_delta_shadow_change_propagates():
    engine = smart_delta_engine()

    def send(evt):
        engine.process_log({"content": json.dumps(evt)})

    send({"eventType": "blockEventData", "blockEventData": json.dumps({
        "eventType": "create", "blockID": "hat", "blockType": "pg_events_when_started"})})
    send({"eventType": "blockEventData", "blockEventData": json.dumps({
        "eventType": "create", "blockID": "b1", "blockType": "pg_drivetrain_drive_for",
        "fields": [{"name": "DIRECTION", "value": "fwd"}]})})
    send({"eventType": "blockEventData", "blockEventData": json.dumps({
        "eventType": "create", "blockID": "s1", "blockType": "math_number_shadow",
        "fields": [{"name": "NUM", "value": "200"}]})})
    send({"eventType": "blockEventData", "blockEventData": json.dumps({
        "eventType": "move", "blockID": "b1", "newInfo": {"parent": "hat", "type": "next"}})})
    send({"eventType": "blockEventData", "blockEventData": json.dumps({
        "eventType": "move", "blockID": "s1", "newInfo": {"parent": "b1", "type": "value", "inputName": "AMOUNT"}})})

    assert engine.blocks["b1"]["fields"]["AMOUNT"] == "200"

    send({"eventType": "blockEventData", "blockEventData": json.dumps({
        "eventType": "change", "blockID": "s1", "name": "NUM", "newValue": "300"})})

    assert engine.blocks["s1"]["fields"]["NUM"] == "300"
    assert engine.blocks["b1"]["fields"]["AMOUNT"] == "300"


def test_delta_delete_cascade():
    engine = smart_delta_engine()

    def send(evt):
        engine.process_log({"content": json.dumps(evt)})

    send({"eventType": "blockEventData", "blockEventData": json.dumps({
        "eventType": "create", "blockID": "hat", "blockType": "pg_events_when_started"})})
    send({"eventType": "blockEventData", "blockEventData": json.dumps({
        "eventType": "create", "blockID": "b1", "blockType": "pg_drive"})})
    send({"eventType": "blockEventData", "blockEventData": json.dumps({
        "eventType": "create", "blockID": "b2", "blockType": "pg_turn"})})
    send({"eventType": "blockEventData", "blockEventData": json.dumps({
        "eventType": "move", "blockID": "b1", "newInfo": {"parent": "hat", "type": "next"}})})
    send({"eventType": "blockEventData", "blockEventData": json.dumps({
        "eventType": "move", "blockID": "b2", "newInfo": {"parent": "b1", "type": "next"}})})

    assert "b1" in engine.blocks and "b2" in engine.blocks

    send({"eventType": "blockEventData", "blockEventData": json.dumps({
        "eventType": "delete", "blockID": "b1"})})

    assert "b1" not in engine.blocks
    assert "b2" not in engine.blocks


def test_delta_orphan_recompute_on_move():
    engine = smart_delta_engine()

    def send(evt):
        engine.process_log({"content": json.dumps(evt)})

    send({"eventType": "blockEventData", "blockEventData": json.dumps({
        "eventType": "create", "blockID": "hat", "blockType": "pg_events_when_started"})})
    send({"eventType": "blockEventData", "blockEventData": json.dumps({
        "eventType": "create", "blockID": "b1", "blockType": "pg_drive"})})

    assert engine.orphan_status["b1"] is True

    send({"eventType": "blockEventData", "blockEventData": json.dumps({
        "eventType": "move", "blockID": "b1", "newInfo": {"parent": "hat", "type": "next"}})})

    assert engine.orphan_status["b1"] is False
    assert engine.get_runnable_block_count() == 2


def test_delta_block_counts_exclude_shadows():
    engine = smart_delta_engine()

    def send(evt):
        engine.process_log({"content": json.dumps(evt)})

    send({"eventType": "blockEventData", "blockEventData": json.dumps({
        "eventType": "create", "blockID": "hat", "blockType": "pg_events_when_started"})})
    send({"eventType": "blockEventData", "blockEventData": json.dumps({
        "eventType": "create", "blockID": "s1", "blockType": "math_number_shadow",
        "fields": [{"name": "NUM", "value": "5"}]})})

    assert engine.get_total_blocks() == 1
    assert "s1" not in [b for b in engine.blocks if not engine.blocks[b].get("is_shadow")]


# ---------------------------------------------------------------------------
# LearnerModels: edit distances
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
# LearnerModels: triggers
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
# LearnerModels: inactive trigger
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
# LearnerModels: session segmentation
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
