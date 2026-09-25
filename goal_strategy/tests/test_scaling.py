"""Scaling guards for goal_strategy: long programs parse without hitting the
recursion limit, My Block ancestry stays cheap however the blocks call each other,
the timeline's coverage scan matches re-slicing, and a live stream can bound its
memory."""
import time

import pytest

from goal_strategy import GoalProfileStream
from goal_strategy.detector.parsing.parse_blocks import parse_workspace
from goal_strategy.detector.simulation.simulate_path import slice_sim_result, simulate_path
from goal_strategy.rubric_evidence import (
    _Ancestry, _call_sites, _is_body, _is_loop, _walk, code_evidence,
)
from goal_strategy.tests.test_oi23_builds import MUT
from goal_strategy.tests.test_rubric_evidence import _ctx, _ev
from goal_strategy.timeline import _prefix_coverage

NS = 'xmlns="https://developers.google.com/blockly/xml"'


def _drive(i, mm=200):
    return (f'<block type="pg_drivetrain_drive_for" id="{i}"><field name="DIRECTION">fwd</field>'
            f'<field name="UNITS">mm</field><value name="AMOUNT"><shadow type="math_number">'
            f'<field name="NUM">{mm}</field></shadow></value>{{NEXT}}</block>')


def _chain(blocks):
    """Join block templates (each with one {NEXT}) into a single sequence."""
    out = "{NEXT}"
    for b in blocks:
        out = out.replace("{NEXT}", "<next>" + b + "</next>", 1)
    out = out.replace("{NEXT}", "")
    return out[len("<next>"):-len("</next>")]


def _call(name, i):
    return f'<block type="procedures_call" id="{i}">{MUT.format(name=name, i=i)}{{NEXT}}</block>'


def _repeat(i, body, times=2):
    return (f'<block type="pg_control_repeat" id="{i}"><value name="TIMES"><shadow type="math_number">'
            f'<field name="NUM">{times}</field></shadow></value>'
            f'<statement name="SUBSTACK">{body}</statement>{{NEXT}}</block>')


def _definition(name, i, body):
    return (f'<block type="procedures_definition" id="{i}" x="900" y="0"><statement name="custom_block">'
            f'<shadow type="procedures_prototype" id="{i}p">{MUT.format(name=name, i=i)}</shadow>'
            f'</statement><next>{body}</next></block>')


def _nested_my_blocks(levels, fanout):
    """when started -> p0. Each p_k repeats a body that calls p_{k+1} `fanout`
    times; the last one drives. A block in the last body has fanout**levels
    call chains above it."""
    tops = [f'<block type="pg_events_when_started" id="h"><next>{_chain([_call("p0", "c")])}</next></block>']
    for k in range(levels):
        if k == levels - 1:
            body = _chain([_drive("leaf")])
        else:
            body = _chain([_call(f"p{k + 1}", f"c{k}_{j}") for j in range(fanout)])
        tops.append(_definition(f"p{k}", f"def{k}", _chain([_repeat(f"r{k}", body)])))
    return f"<xml {NS}>" + "".join(tops) + "</xml>"


# ---------------------------------------------------------------- long programs

def test_a_long_straight_program_parses_and_profiles():
    body = _chain([_drive(f"d{i}", 10) for i in range(3000)])
    xml = f'<xml {NS}><block type="pg_events_when_started" id="h"><next>{body}</next></block></xml>'
    program = parse_workspace(xml, "long")
    assert program.total_block_count == 3001 + 3000   # blocks + their number shadows
    result = GoalProfileStream("long").push(
        {"event_type": "runProject", "content": {"playground": "castle_crashers",
                                                 "project": {"workspace": xml}}})
    assert result["status"] == "profiled"


# ---------------------------------------------------------------- My Block ancestry

def _reference_paths(node, sites, seen=frozenset()):
    """The path enumeration the ancestry replaced, kept as the oracle."""
    chain, top, p = [], node, node.parent
    while p is not None:
        chain.append(p)
        top = p
        p = p.parent
    extended = False
    for call in sites.get(id(top), ()):
        if id(call) in seen:
            continue
        for rest in _reference_paths(call, sites, seen | {id(call)}):
            extended = True
            yield chain + [call] + rest
    if not extended:
        yield chain


def _reference_first(node, sites, pred):
    for path in _reference_paths(node, sites):
        for p in path:
            if pred(p):
                return p
    return None


@pytest.mark.parametrize("levels,fanout", [(1, 1), (2, 2), (3, 3), (4, 2)])
def test_ancestry_matches_path_enumeration(levels, fanout):
    program = parse_workspace(_nested_my_blocks(levels, fanout), "anc")
    blocks = [b for root in program.live_stacks for b in _walk(root)]
    sites = _call_sites(program, blocks)
    ancestry = _Ancestry(sites)
    for b in blocks:
        for pred in (_is_loop, _is_body):
            assert ancestry.first(b, pred) is _reference_first(b, sites, pred)
            assert ancestry.depth(b, pred) == max(
                sum(1 for p in path if pred(p)) for path in _reference_paths(b, sites))


def test_recursive_my_blocks_terminate():
    tops = [f'<block type="pg_events_when_started" id="h"><next>{_chain([_call("a", "ca")])}</next></block>',
            _definition("a", "da", _chain([_repeat("ra", _chain([_call("b", "cb")]))])),
            _definition("b", "db", _chain([_call("a", "cba"), _drive("leaf")]))]
    program = parse_workspace(f"<xml {NS}>" + "".join(tops) + "</xml>", "rec")
    blocks = [b for root in program.live_stacks for b in _walk(root)]
    sites = _call_sites(program, blocks)
    ancestry = _Ancestry(sites)
    for b in blocks:
        assert ancestry.first(b, _is_loop) is _reference_first(b, sites, _is_loop)


def test_deeply_nested_my_blocks_stay_fast():
    # 3**13 (about 1.6M) call chains sit above the leaf; enumerating them took
    # about 40s, the memoized ancestry is a few lookups per block.
    xml = _nested_my_blocks(13, 3)
    start = time.perf_counter()
    ev = _ev(xml)
    assert time.perf_counter() - start < 10
    assert ev.max_nesting_depth == 13


# ---------------------------------------------------------------- timeline coverage

def test_prefix_coverage_matches_slicing():
    ctx = _ctx()
    moves = []
    for k in range(12):
        moves.append(_drive(f"m{k}", 150 + 40 * k))
        moves.append(f'<block type="pg_drivetrain_turn_for" id="t{k}"><field name="TURNDIRECTION">right</field>'
                     '<field name="UNITS">deg</field><value name="AMOUNT"><shadow type="math_number">'
                     '<field name="NUM">70</field></shadow></value>{NEXT}</block>')
    xml = (f'<xml {NS}><block type="pg_events_when_started" id="h"><next>{_chain(moves)}</next>'
           '</block></xml>')
    full = simulate_path(parse_workspace(xml, "cov"), ctx)
    assert len(full.path) > 10 and ctx.regions
    for region in ctx.regions:
        prefix = _prefix_coverage(full, ctx, region)
        for k in range(1, len(full.path)):
            sliced = slice_sim_result(full, 0, k, context=ctx)
            assert prefix[k] == sliced.region_coverage_fractions.get(region, 0.0), (region, k)


# ---------------------------------------------------------------- stream memory

def _run_event(i):
    xml = (f'<xml {NS}><block type="pg_events_when_started" id="h"><next>'
           f'{_chain([_drive("d", 100 + i)])}</next></block></xml>')
    return {"event_type": "runProject", "ts": i,
            "content": {"playground": "castle_crashers", "project": {"workspace": xml}}}


def test_stream_release_frees_a_run():
    stream = GoalProfileStream("mem")
    for i in range(3):
        stream.push(_run_event(i))
    stream.release(0)
    assert stream.runs[0] is None
    assert [r["index"] for r in stream.runs[1:]] == [1, 2]
    assert stream.associate_outcome(0, {"playground_data": {}}) is None
    assert stream.diagnostics[-1] == {"index": 0, "reason": "outcome_run_released"}
    assert stream.associate_outcome(2, {"playground_data": {}})["index"] == 2
    stream.push(_run_event(3))
    assert stream.runs[3]["index"] == 3


def test_release_needs_a_profiled_run():
    stream = GoalProfileStream("mem")
    with pytest.raises(ValueError):
        stream.release(0)


def test_code_evidence_on_a_long_path_is_linear():
    # A forever loop runs the path up to the simulator's execution budget, and
    # 300 sensing waits sit in an arm that never runs. Each wait used to rescan
    # the whole executed path; now it is one lookup.
    waits = _chain([f'<block type="pg_control_wait_until" id="w{k}"><value name="CONDITION">'
                    f'<block type="pg_sensing_distance_found" id="s{k}"><field name="DISTANCE">'
                    'distance</field></block></value>{NEXT}</block>' for k in range(300)])
    guard = ('<block type="pg_control_if_then" id="g"><value name="CONDITION">'
             '<block type="pg_sensing_distance_found" id="gs"><field name="DISTANCE">distance</field>'
             f'</block></value><statement name="SUBSTACK">{waits}</statement>{{NEXT}}</block>')
    loop_body = _chain([guard] + [_drive(f"d{k}", 1) for k in range(60)])
    xml = (f'<xml {NS}><block type="pg_events_when_started" id="h"><next>'
           f'<block type="pg_control_forever" id="f"><statement name="SUBSTACK">{loop_body}</statement>'
           '</block></next></block></xml>')
    program = parse_workspace(xml, "long-path")
    sim = simulate_path(program, _ctx(), scheduler="cooperative",
                        loop_iteration_time_s=1 / 60, time_budget_s=600.0)
    assert "execution_budget_exhausted" in sim.execution_flags
    start = time.perf_counter()
    code_evidence(program, sim)
    # about 0.02s now, about 0.8s with the per-wait rescans
    assert time.perf_counter() - start < 0.4


def test_state_gated_walk_ends_on_recursive_my_blocks():
    # a loops calling b, and b loops calling a, then drives. The drive's
    # loop/conditional ancestors through the call sites go around that cycle
    # (a's loop, b's loop, a's loop, ...). The walk used to loop forever; it must
    # stop once it comes back to an ancestor it already checked.
    tops = [f'<block type="pg_events_when_started" id="h"><next>{_chain([_call("a", "ca")])}</next></block>',
            _definition("a", "da", _chain([_repeat("ra", _chain([_call("b", "cb")]))])),
            _definition("b", "db", _chain([_repeat("rb", _chain([_call("a", "cba")])), _drive("leaf")]))]
    start = time.perf_counter()
    _ev(f"<xml {NS}>" + "".join(tops) + "</xml>")
    assert time.perf_counter() - start < 5
