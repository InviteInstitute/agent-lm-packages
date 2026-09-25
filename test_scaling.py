"""Scaling guards for learner_models and log_parser_delta_engine: long programs
must not hit the recursion limit, the per-run distance stream must match the batch
call, and nothing held in memory grows without bound."""
import time

import learner_models.distance as distance
from learner_models import RunDistanceStream, compute_run_edit_distances, xml_to_block_ast
from learner_models.constants import MAX_DIFF_BLOCKS
from log_parser_delta_engine import smart_delta_engine

NS = 'xmlns="https://developers.google.com/blockly/xml"'


def _straight(n, amount=100, turn="right"):
    """when started, then n blocks in one sequence. Blockly nests each next block
    inside the previous one, so this is an n-deep XML tree."""
    inner = (f'<block type="pg_drivetrain_drive_for" id="d{n - 1}"><field name="DIRECTION">fwd</field>'
             f'<value name="AMOUNT"><shadow type="math_number" id="s"><field name="NUM">{amount}</field>'
             '</shadow></value></block>')
    for i in range(n - 2, -1, -1):
        inner = (f'<block type="pg_drivetrain_turn_for" id="d{i}"><field name="TURNDIRECTION">{turn}</field>'
                 f'<next>{inner}</next></block>')
    return f'<xml {NS}><block type="pg_events_when_started" id="h"><next>{inner}</next></block></xml>'


def _run(xml, ts, playground="castle_crashers"):
    return {"event_type": "runProject", "ts": ts,
            "content": {"playground": playground, "project": {"workspace": xml}}}


def test_ast_of_a_long_program_does_not_recurse():
    ast = xml_to_block_ast(_straight(5000))
    assert len(ast["nodes"]) == 5001
    assert len(ast["edges"]) == 5000


def test_distance_of_a_deep_program_raises_recursion_headroom():
    # 520 blocks is an APTED tree over 1000 levels deep (edge nodes included),
    # past Python's default recursion limit.
    a, b = _straight(520, turn="right"), _straight(520, turn="left")
    runs = compute_run_edit_distances([_run(a, 1), _run(b, 2)])["runs"]
    assert runs[1]["edit_distance"] == 519


def test_distance_past_the_size_cap_is_not_compared():
    distance.clear_cache()
    big = MAX_DIFF_BLOCKS + 1
    a, b = _straight(big, turn="right"), _straight(big, turn="left")
    start = time.perf_counter()
    runs = compute_run_edit_distances([_run(a, 1), _run(b, 2)])["runs"]
    assert runs[1]["edit_distance"] is None
    assert time.perf_counter() - start < 5


def test_identical_trees_skip_apted(monkeypatch):
    # Changing only a number changes the XML but not the AST (shadows are left
    # out), so the pair is 0 without running APTED at all.
    distance.clear_cache()
    monkeypatch.setattr(distance, "APTED", None)
    runs = compute_run_edit_distances([_run(_straight(50, 100), 1),
                                       _run(_straight(50, 300), 2)])["runs"]
    assert runs[1]["edit_distance"] == 0


def test_stream_matches_batch_and_parses_lazily(monkeypatch):
    events = [
        _run(_straight(3), 1),
        {"event_type": "blockMoved", "ts": 2, "content": {}},
        _run(_straight(3), 3),                      # rerun, no edit
        _run(_straight(5), 4),                      # real edit
        _run(_straight(5), 5, playground="CoralReefRescue"),  # switch: None
        _run(_straight(6), 6, playground=None),     # inherits the playground
    ]
    batch = compute_run_edit_distances(events)["runs"]

    parsed = []
    import learner_models.run_sequence as rs
    original = rs.xml_to_block_ast

    def counting(xml):
        parsed.append(xml)
        return original(xml)

    monkeypatch.setattr(rs, "xml_to_block_ast", counting)
    distance.clear_cache()
    stream = RunDistanceStream()
    out = [stream.push(ev) for ev in events]
    assert stream.runs == batch
    assert out[1] is None and out[0] == batch[0]
    assert [r["edit_distance"] for r in batch] == [None, 0, 2, None, 1]
    # Only the two real edits between comparable runs parsed anything: both sides
    # of 3 -> 5 and of 5 -> 6. The rerun and the playground switch parsed nothing.
    assert len(parsed) == 4


def test_distance_cache_is_bounded(monkeypatch):
    distance.clear_cache()
    monkeypatch.setattr(distance, "_CACHE_MAX", 3)
    xmls = [_straight(n) for n in range(2, 9)]
    for a, b in zip(xmls, xmls[1:]):
        distance.cached_edit_distance(a, b, xml_to_block_ast(a), xml_to_block_ast(b))
    assert len(distance._distance_cache) == 3
    distance.clear_cache()


def test_delta_engine_skips_unchanged_workspaces(monkeypatch):
    engine = smart_delta_engine()
    ev = {"content": {"project": {"workspace": _straight(4)}}}
    engine.process_log(ev)
    before = engine.generate_compact_prompt()
    calls = []
    monkeypatch.setattr(engine, "_bootstrap_from_xml", lambda xml: calls.append(xml))
    engine.process_log(ev)
    engine.process_log({"content": {"eventType": "menuSelect", "project": {"workspace": _straight(4)}}})
    assert calls == []
    assert engine.generate_compact_prompt() == before
    engine.process_log({"content": {"project": {"workspace": _straight(5)}}})
    assert len(calls) == 1


def _random_stream(rng, n):
    from learner_models.constants import (
        CODE_EVENTS, POST_RUN_PAUSE_TRANSPARENT_TYPES, RESET_EVENTS, SOFT_EVENT_TYPES,
    )
    types = (sorted(CODE_EVENTS) + ["runProject"] * 3 + ["projectEnd"] * 3 + sorted(RESET_EVENTS)
             + sorted(SOFT_EVENT_TYPES) + sorted(POST_RUN_PAUSE_TRANSPARENT_TYPES)
             + ["workspaceClick", "", None])
    ts, out = 1000.0, []
    for _ in range(n):
        ts += rng.choice([0, 1, 4, 5, 6, 30, 299, 300, 301, 5000, 86401, -3])
        out.append({"event_type": rng.choice(types), "ts": None if rng.random() < 0.05 else ts})
    return out


def test_segmenter_matches_segment_session_after_every_push():
    import random
    from learner_models import SessionSegmenter, segment_session
    rng = random.Random(7)
    for _ in range(300):
        events = _random_stream(rng, rng.randint(0, 60))
        seg = SessionSegmenter()
        for k, ev in enumerate(events):
            seg.push(ev["event_type"], ev["ts"])
            assert seg.result() == segment_session(events[:k + 1])


def test_segmenter_forget_before_keeps_the_recent_window():
    import random
    from learner_models import SessionSegmenter, segment_session
    events = _random_stream(random.Random(3), 400)
    seg = SessionSegmenter()
    for ev in events:
        seg.push(ev["event_type"], ev["ts"])
    full_eps, full_pauses = segment_session(events)
    still_open = seg._open is not None
    seg.forget_before(200)
    eps, pauses = seg.result()
    # Finished episodes before the index are gone; the open one always stays.
    expected = [e for e in full_eps[:-1] if e["start_idx"] >= 200]
    last = full_eps[-1]
    if still_open or last["start_idx"] >= 200:
        expected.append(last)
    assert eps == expected
    assert pauses == [p for p in full_pauses if p["after_idx"] >= 200]
