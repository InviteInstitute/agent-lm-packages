"""Robustness across all three packages: what a live host actually feeds them.

  * a raw-format VEX session (content and project as JSON strings, as the log
    queue delivers them) replayed through every package with exact expectations
  * seeded random programs built from the block registry, through every entry point
  * batch and streaming APIs agreeing on damaged sessions, with run indices aligned
    across packages (the host joins goal evidence to distances by index)
  * hostile XML: never an exception, never a hang
"""
import csv
import json
import math
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from goal_strategy import GoalProfileStream, goal_profile, goal_profiles_from_events
from learner_models import (
    RunDistanceStream, SessionSegmenter, compute_run_edit_distances,
    detect_run_triggers_by_playground, segment_session, xml_to_block_ast,
)
from learner_models.distance import edit_distance_for, xml_digest
from log_parser_delta_engine import (
    generate_compact_prompt, generate_compact_prompt_from_content,
    generate_readable_lines, generate_readable_text, smart_delta_engine,
)

NS = 'xmlns="https://developers.google.com/blockly/xml"'
ALL_CHANNELS = dict(include_timeline=True, include_battery=True, include_rubric=True,
                    include_rollup=True)
STATUSES = {"profiled", "invalid_input", "unsupported_playground"}


# ---------------------------------------------------------------------------
# A raw-format VEX session
# ---------------------------------------------------------------------------
def _raw(event_type, xml, second, playground="CastleCrasherPlus", **extra):
    """One event the way the log queue delivers it: content is the raw message,
    a JSON string, and its project is a JSON string carrying the workspace."""
    project = {"mode": "Blocks", "hardwareTarget": "brain", "playground": playground,
               "robotModel": "vrGO", "slot": 0}
    if xml is not None:
        project["workspace"] = xml
    stamp = datetime(2026, 2, 21, 18, tzinfo=timezone.utc) + timedelta(seconds=second)
    message = dict(eventType=event_type, classCode="CLASS1", studentID="S1",
                   sessionID="sess-1", timestamp=stamp.isoformat().replace("+00:00", "Z"),
                   programType="Blocks", project=json.dumps(project),
                   hasOrphans=False, playground=playground, switchBlockCount=0, **extra)
    return {"event_type": event_type, "content": json.dumps(message), "ts": stamp.timestamp()}


DRIVE = ('<block type="pg_drivetrain_drive_for" id="d"><field name="DIRECTION">fwd</field>'
         '<field name="UNITS">mm</field><value name="AMOUNT"><shadow type="math_number" id="ds">'
         '<field name="NUM">600</field></shadow></value>{next}</block>')
TURN = ('<block type="pg_drivetrain_turn_for" id="t"><field name="TURNDIRECTION">right</field>'
        '<value name="AMOUNT"><shadow type="math_number" id="ts"><field name="NUM">90</field>'
        '</shadow></value></block>')


def _ws(body):
    return (f'<xml {NS}><block type="pg_events_when_started" id="h" x="70" y="110">'
            f'<next>{body}</next></block></xml>')


W1 = _ws(DRIVE.format(next=""))
W2 = _ws(DRIVE.format(next=f"<next>{TURN}</next>"))
OUTCOME = json.dumps({"playground": "CastleCrasherPlus", "parameters": {"weight_cleared": 700}})


def _session():
    events = [
        _raw("pageLoad", None, 0),
        _raw("blockCreated", W1, 5),
        _raw("runProject", W1, 10),                       # run 0
        _raw("projectEnd", W1, 14),
        _raw("playgroundData", W1, 15, playgroundData=OUTCOME),
        _raw("blockCreated", W2, 40),
        _raw("runProject", W2, 50),                       # run 1: +1 block
        _raw("projectEnd", W2, 53),
        _raw("runProject", W2, 400),                      # run 2, after a 347s idle gap
    ]
    for i in range(5):                                    # runs 3..7: the same code again
        events += [_raw("runProject", W2, 410 + 10 * i), _raw("projectEnd", W2, 413 + 10 * i)]
    return events


def test_raw_session_replays_through_every_package():
    events = _session()

    runs = compute_run_edit_distances(events)["runs"]
    assert [r["edit_distance"] for r in runs] == [None, 1, 0, 0, 0, 0, 0, 0]
    assert {r["playground"] for r in runs} == {"CastleCrasherPlus"}
    assert [(t, i) for t, i, _ in detect_run_triggers_by_playground(runs)] == [("wheel_spin", 7)]

    episodes, pauses = segment_session(events)
    assert [e["episode_type"] for e in episodes][:4] == ["CODE", "RUN", "CODE", "RUN"]
    assert [p["episode_type"] for p in pauses if p["episode_type"] == "INACTIVE_PAUSE"] == \
        ["INACTIVE_PAUSE"]

    engine = smart_delta_engine()
    for e in events:
        engine.process_log(e)
    compact = engine.generate_compact_prompt()
    assert compact.split("\n[Orphaned]")[0].count("drivetrain_") == 2
    assert compact == generate_compact_prompt_from_content(json.loads(events[-1]["content"]))
    assert engine.get_runnable_block_count() == 3

    out = goal_profiles_from_events(events, session_id="S1/sess-1",
                                    outcomes_by_run_index={0: {"playground_data": OUTCOME}})
    assert [r["index"] for r in out["runs"]] == list(range(8))
    assert all(r["status"] == "profiled" for r in out["runs"])
    assert {d["reason"] for d in out["diagnostics"]} == {"unassociated_outcome"}
    json.dumps(out, allow_nan=False)

    # the outcome arrives after run 0 was profiled live: same result as up front
    stream = GoalProfileStream("S1/sess-1")
    for e in events:
        stream.push(e)
    assert stream.associate_outcome(0, {"playground_data": OUTCOME}) == out["runs"][0]
    assert stream.runs == out["runs"]


# ---------------------------------------------------------------------------
# Seeded random programs from the block registry
# ---------------------------------------------------------------------------
_REGISTRY = list(csv.DictReader(
    (Path(__file__).parent / "goal_strategy/detector/data/blocks.csv").open()))
_STATEMENTS = [r["block_name"] for r in _REGISTRY if r["classification"] in
               ("movement", "other", "variable", "drawing", "console", "magnet", "timer",
                "loop", "conditional", "switch")]
_REPORTERS = [r["block_name"] for r in _REGISTRY if r["classification"] in ("operator", "sensor")]
_HATS = ["pg_events_when_started"] * 3 + ["pg_events_when_broadcasted", "pg_events_when_bumper",
                                          "pg_events_when_timer", "pg_events_optical_detect_object"]
_NUMBERS = ["0", "1", "-1", "90", "600", "1e308", "1e400", "-1e400", "NaN", "Infinity", "",
            "abc", "0.0001", "360", "100000"]
_FIELDS = {"DIRECTION": ["fwd", "rev"], "UNITS": ["mm", "inches"],
           "TURNDIRECTION": ["left", "right"], "MATH": ["+", "-", "*", "/"],
           "COMPARISON": ["&lt;", "&gt;", "="], "CHECK": ["and", "or"],
           "OPERATOR": ["abs", "sqrt", "ln", "10^", "e^", "floor"], "VARIABLE": ["v"],
           "BROADCAST_OPTION": ["m1"], "STATE": ["boost", "drop"], "TYPE": ["number", "text"]}
_SLOTS = ["AMOUNT", "TIMES", "TIME", "CONDITION", "VALUE", "NUM1", "NUM2", "OPERAND1",
          "VELOCITY", "HEADING", "TO", "FROM"]


class _Program:
    """A random workspace: every block type in the registry, wild literals,
    disabled blocks, repeated ids, My Blocks that call each other."""

    def __init__(self, seed):
        self.rng = random.Random(seed)
        self.ids = 0

    def id(self):
        self.ids += 1
        return "dup" if self.rng.random() < 0.03 else f"b{self.ids}"

    def fields(self):
        return "".join(f'<field name="{k}">{self.rng.choice(v)}</field>'
                       for k, v in _FIELDS.items() if self.rng.random() < 0.2)

    def value(self, depth):
        if depth > 3 or self.rng.random() < 0.4:
            return (f'<shadow type="math_number" id="{self.id()}"><field name="NUM">'
                    f'{self.rng.choice(_NUMBERS)}</field></shadow>')
        slots = "".join(f'<value name="{s}">{self.value(depth + 1)}</value>'
                        for s in self.rng.sample(_SLOTS, self.rng.randint(0, 3)))
        return (f'<block type="{self.rng.choice(_REPORTERS)}" id="{self.id()}">'
                f'{self.fields()}{slots}</block>')

    def sequence(self, depth, procs, n):
        out = ""
        for _ in range(n):
            if procs and self.rng.random() < 0.1:
                head = (f'<block type="procedures_call" id="{self.id()}">'
                        f'<mutation proccode="{self.rng.choice(procs)}"/>')
            else:
                disabled = ' disabled="true"' if self.rng.random() < 0.05 else ""
                head = (f'<block type="{self.rng.choice(_STATEMENTS)}" id="{self.id()}"{disabled}>'
                        + self.fields()
                        + "".join(f'<value name="{s}">{self.value(0)}</value>'
                                  for s in self.rng.sample(_SLOTS, self.rng.randint(0, 2))))
                if depth < 4 and self.rng.random() < 0.3:
                    for s in self.rng.sample(["SUBSTACK", "SUBSTACK2"], self.rng.randint(1, 2)):
                        head += (f'<statement name="{s}">'
                                 f'{self.sequence(depth + 1, procs, self.rng.randint(0, 3))}'
                                 '</statement>')
            out = head + (f"<next>{out}</next>" if out else "") + "</block>"
        return out

    def xml(self):
        procs = [f"p{i}" for i in range(self.rng.randint(0, 2))]
        stacks = [f'<block type="procedures_definition" id="{self.id()}"><statement name="custom_block">'
                  f'<shadow type="procedures_prototype"><mutation proccode="{p}"/></shadow>'
                  f'</statement><next>{self.sequence(1, procs, self.rng.randint(1, 4))}</next></block>'
                  for p in procs]
        for _ in range(self.rng.randint(1, 3)):
            stacks.append(f'<block type="{self.rng.choice(_HATS)}" id="{self.id()}">'
                          f'{self.fields()}<next>{self.sequence(1, procs, self.rng.randint(1, 6))}'
                          '</next></block>')
        if self.rng.random() < 0.3:
            stacks.append(self.sequence(1, procs, 2))
        return f"<xml {NS}>" + "".join(stacks) + "</xml>"


def _check_goal_result(result):
    assert result["status"] in STATUSES, (result["status"], result["reason"])
    broken = [d for d in result["diagnostics"] if d == "engine_error" or d.endswith("_failed")]
    assert not broken, broken
    json.dumps(result, allow_nan=False)


@pytest.mark.parametrize("seed", range(40))
def test_random_programs_through_every_entry_point(seed):
    xml = _Program(seed).xml()
    compact = generate_compact_prompt(xml)
    assert compact is None or compact.startswith(("[Active]", "[Unrenderable]"))
    assert isinstance(generate_readable_text(xml), str)
    engine = smart_delta_engine()
    engine._bootstrap_from_xml(xml)
    assert engine.get_runnable_block_count() <= engine.get_total_blocks()
    ast = xml_to_block_ast(xml)
    assert {e["target"] for e in ast["edges"]} <= set(ast["nodes"])
    distance = edit_distance_for("<xml/>", xml, xml_to_block_ast("<xml/>"), ast)
    assert distance is None or distance >= 0
    _check_goal_result(goal_profile(xml, f"random/{seed}"))


@pytest.mark.parametrize("seed", range(3))
def test_random_programs_with_every_channel(seed):
    _check_goal_result(goal_profile(_Program(1000 + seed).xml(), f"random/{seed}", **ALL_CHANNELS))


# ---------------------------------------------------------------------------
# Batch == stream on damaged sessions, indices aligned across packages
# ---------------------------------------------------------------------------
def _damaged_session(seed):
    rng = random.Random(seed)
    programs = [_Program(seed * 10 + i).xml() for i in range(3)] + [W1, W2, "", "<bad"]
    events, ts = [], 1_700_000_000.0
    for _ in range(rng.randint(5, 25)):
        ts += rng.choice([0, 1, 6, 30, 299, 301, 4000, -5])
        kind = rng.choice(["runProject"] * 4 + ["projectEnd", "blockMoved", "blockCreated",
                                                "playgroundData", "menuOpen", "loadProject"])
        event = {"event_type": kind, "ts": ts, "content": {
            "playground": rng.choice(["CastleCrasherPlus", "CasteCrasherPlus", "RoverRescue",
                                      None, None]),
            "project": json.dumps({"workspace": rng.choice(programs)})}}
        damage = rng.random()
        if damage < 0.05:
            event["content"] = json.dumps(event["content"])[: rng.randint(0, 40)]
        elif damage < 0.10:
            event["content"]["project"] = {"workspace": rng.choice([5, None, [], "\ud800"])}
        elif damage < 0.15:
            event["ts"] = rng.choice([None, math.nan, math.inf])
        elif damage < 0.18:
            event["content"] = rng.choice([None, "", "[]", 7])
        events.append(event)
    return events


@pytest.mark.parametrize("seed", range(12))
def test_streams_match_batch_on_damaged_sessions(seed):
    events = _damaged_session(seed)
    n_runs = sum(e["event_type"] == "runProject" for e in events)

    runs = compute_run_edit_distances(events)["runs"]
    stream = RunDistanceStream()
    for e in events:
        stream.push(e)
    assert stream.runs == runs and len(runs) == n_runs

    segmenter = SessionSegmenter()
    for e in events:
        segmenter.push(e["event_type"], e["ts"])
    assert segmenter.result() == segment_session(events)

    goal = GoalProfileStream("damaged")
    for k, e in enumerate(events):
        goal.push(e)
        if k == len(events) // 2:   # prefix identity: what a live host saw mid-session
            assert goal.runs == goal_profiles_from_events(events[:k + 1], session_id="damaged")["runs"]
    batch = goal_profiles_from_events(events, session_id="damaged")
    assert goal.runs == batch["runs"]
    assert [r["index"] for r in batch["runs"]] == list(range(n_runs))
    for r in batch["runs"]:
        _check_goal_result(r)

    engine = smart_delta_engine()
    for e in events:
        engine.process_log(e)


# ---------------------------------------------------------------------------
# Hostile XML
# ---------------------------------------------------------------------------
def _nest(open_, close, n, inner=""):
    return open_ * n + inner + close * n


_HAT = '<block type="pg_events_when_started" id="h">'
_LAUGHS = ('<!DOCTYPE l [<!ENTITY a "aaaaaaaaaa">'
           + "".join(f'<!ENTITY {chr(98 + i)} "{("&" + chr(97 + i) + ";") * 10}">' for i in range(8))
           + ']><xml>&i;</xml>')
# Nested deeper than any recursion limit the distance code may have raised the
# process to (MAX_DIFF_BLOCKS keeps that under 6000).
_DEEP = 10_000
HOSTILE = {
    "billion_laughs": _LAUGHS,
    "external_entity": '<!DOCTYPE x [<!ENTITY e SYSTEM "file:///etc/passwd">]><xml>&e;</xml>',
    "deep_statements": f"<xml {NS}>{_HAT}<statement name=\"SUBSTACK\">"
        + _nest('<block type="pg_control_forever"><statement name="SUBSTACK">',
                "</statement></block>", _DEEP) + "</statement></block></xml>",
    "deep_reporters": f'<xml {NS}>{_HAT}<next><block type="pg_drivetrain_drive_for"><value name="AMOUNT">'
        + _nest('<block type="pg_operator_round"><value name="NUM">', "</value></block>", _DEEP)
        + "</value></block></next></block></xml>",
    "wrong_root": f"<html {NS}>{_HAT}</block></html>",
    "comments_cdata_pi": f'<xml {NS}><!-- c --><?pi x?>{_HAT}<field name="X"><![CDATA[<b>]]></field></block></xml>',
    "untyped_blocks": f'<xml {NS}><block id="a"><next><block/></next></block></xml>',
    "empty_ids": f'<xml {NS}><block type="pg_events_when_started" id=""><next>'
                 '<block type="pg_control_forever" id=""/></next></block></xml>',
    "duplicate_nested_ids": f'<xml {NS}><block type="pg_events_when_started" id="X"><next>'
                            '<block type="pg_control_repeat" id="X"><statement name="SUBSTACK">'
                            '<block type="pg_control_forever" id="X"/></statement></block></next></block></xml>',
    "recursive_my_block": f'<xml {NS}>{_HAT}<next><block type="procedures_call"><mutation proccode="p"/>'
                          '</block></next></block><block type="procedures_definition"><statement name="custom_block">'
                          '<shadow type="procedures_prototype"><mutation proccode="p"/></shadow></statement>'
                          '<next><block type="procedures_call"><mutation proccode="p"/></block></next></block></xml>',
    "broken_mutation_json": f'<xml {NS}>{_HAT}<next><block type="procedures_call">'
                            '<mutation proccode="go %s %n" argumentids="[1,"/></block></next></block></xml>',
    "lone_surrogate": '<xml><block type="a\ud800"/></xml>',
    "nul": "<xml>\x00</xml>",
    "bom": "﻿<xml/>",
    "whitespace": "  \n ",
    "not_xml": "hello",
    "json": '{"workspace": "<xml/>"}',
    "too_large": f"<xml {NS}>" + '<block type="a"/>' * 120_000 + "</xml>",
}


@pytest.mark.parametrize("name", sorted(HOSTILE))
def test_hostile_xml_never_raises(name):
    xml = HOSTILE[name]
    lines = generate_readable_lines(xml)
    compact = generate_compact_prompt(xml)
    engine = smart_delta_engine()
    engine.process_log({"content": {"project": {"workspace": xml}}})
    engine.get_runnable_block_count()
    runs = compute_run_edit_distances(
        [{"event_type": "runProject", "content": {"project": {"workspace": x}}} for x in (xml, xml, W1)])
    assert len(runs["runs"]) == 3
    result = goal_profile(xml, name)
    _check_goal_result(result)

    if name in ("billion_laughs", "external_entity", "too_large", "wrong_root", "not_xml"):
        assert result["status"] == "invalid_input" and "invalid_xml" in result["diagnostics"]
    if name.startswith("deep_"):
        assert lines == [] and compact.startswith("[Unrenderable]")
        assert "invalid_xml" in result["diagnostics"]


def test_readable_renderer_is_linear_in_reporter_nesting():
    # each catch-all reporter rendered its slots twice, so depth d cost 2^d
    xml = _ws('<block type="pg_drivetrain_drive_for"><value name="AMOUNT">'
              + _nest('<block type="pg_operator_round"><value name="NUM">', "</value></block>", 40)
              + "</value></block>")
    start = time.perf_counter()
    text = generate_readable_text(xml)
    assert time.perf_counter() - start < 1.0
    assert text.count("round") == 40


def test_unnamespaced_xml_reads_the_same_everywhere():
    plain = W2.replace(f" {NS}", "")
    assert generate_compact_prompt(plain) == generate_compact_prompt(W2)
    assert generate_readable_text(plain) == generate_readable_text(W2)
    assert edit_distance_for(plain, W2, xml_to_block_ast(plain), xml_to_block_ast(W2),
                             xml_digest(plain), xml_digest(W2)) == 0
    a, b = goal_profile(plain, "p"), goal_profile(W2, "p")
    assert a["profile"] == b["profile"] and a["status"] == "profiled"
