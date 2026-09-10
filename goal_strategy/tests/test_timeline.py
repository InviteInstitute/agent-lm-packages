"""Task-2 §A5: timeline events are rung transitions — reachability, ordering,
origin pseudo-step, monotonicity, binary-search agreement, corpus regressions."""
import math
import statistics
import textwrap
import time

import pytest

from goal_strategy.detector.parsing.parse_blocks import parse_workspace
from goal_strategy.detector.simulation.simulate_path import simulate_path, slice_sim_result

from goal_strategy.config import load_configs
from goal_strategy.timeline import ORIGIN_STEP, timeline, timeline_result

from goal_strategy.tests.test_hat_execution import drive_for, hat, turn_for, workspace

PLAYGROUND = textwrap.dedent("""
    playground_id: toy_line
    field_geometry: {playable_radius_mm: 60000}
    spawn_points: {default_start: {x: 0, y: 0, heading: 0}}   # VEX 0 = math 180 = west
    robot: {width_mm: 50.8}
    field_boundary:
      polygon_mm: [[-50000, -50000], [50000, -50000], [50000, 50000], [-50000, 50000]]
    objects:
      beacon: {x: -2286, y: 0, tolerance: 100, object_type: target}
    regions:
      pad: {x_min: -2300, x_max: -100, y_min: -200, y_max: 200}
    block_families:
      magnet: [pg_magnet_set_magnet_state]
      movement: [pg_drivetrain_drive_for, pg_drivetrain_turn_for]
""")

GOALS = textwrap.dedent("""
    playground: toy_line
    version: 1
    goals:
      - id: reach
        intent:
          - name: approach
            indicator: min_distance_to_object
            binding: {object: beacon}
            rungs:
              direction: lower_is_better
              reference: object.tolerance
              edges_as_multiples: [1.0, 2.0]
              labels: [reached, near, far]
        attainment:
          - name: engaged
            indicator: state_active_within_radius
            binding: {object: beacon, state: magnet_active}
            rungs:
              direction: lower_is_better
              reference: object.tolerance
              edges_as_multiples: [1.0]
              labels: [armed_close, armed_far]
              absent_label: not_armed
      - id: sweep
        intent:
          - name: coverage
            indicator: region_coverage
            binding: {region: pad}
            rungs:
              direction: higher_is_better
              edges: [0.05, 0.5]
              labels: [low, mid, high]
        attainment:
          - name: points
            indicator: outcome_field
            binding: {field: points}
            rungs:
              direction: higher_is_better
              edges: [1]
              labels: [none, scored]
      - id: authored
        intent:
          - name: moved
            indicator: code_movement_authored
            binding: {block_family: movement}
            rungs:
              direction: higher_is_better
              edges: [1]
              labels: [none, authored]
        attainment: []
""")

MAGNET = ('<block type="pg_magnet_set_magnet_state" id="m1">'
          '<field name="MAGNET">Magnet</field><field name="ACTION">boost</field></block>')


@pytest.fixture()
def toy(tmp_path):
    (tmp_path / "playgrounds").mkdir()
    (tmp_path / "goals").mkdir()
    (tmp_path / "playgrounds" / "toy_line.yaml").write_text(PLAYGROUND)
    (tmp_path / "goals" / "toy_line.yaml").write_text(GOALS)
    load_configs.cache_clear()
    yield str(tmp_path)
    load_configs.cache_clear()


def tl(xml, toy_dir, params=None):
    return timeline_result(xml, "t", params, playground="toy_line",
                           configs_dir=toy_dir)


def by(events, indicator):
    return [e for e in events if e.indicator == indicator]


def test_min_distance_rung_transitions_reachable(toy):
    # spawn 2286mm west of nothing — beacon sits 2286mm away (far);
    # drive 2159mm -> 127mm remaining (near); drive 127mm -> 0mm (reached).
    xml = workspace(hat("pg_events_when_started",
                        drive_for(2159, nxt=f"<next>{drive_for(127)}</next>")))
    events = by(tl(xml, toy).events, "approach")
    assert [(e.from_rung, e.to_rung) for e in events] == \
        [("far", "near"), ("near", "reached")]
    assert [e.step for e in events] == [0, 1]
    assert all(e.block_id for e in events)


def test_state_latch_and_running_min(toy):
    # magnet fires at spawn (2286mm away: not_armed -> armed_far),
    # then the drive arrives within radius (armed_far -> armed_close).
    xml = workspace(hat("pg_events_when_started",
                        MAGNET.replace("</block>",
                                       f"<next>{drive_for(2286)}</next></block>")))
    events = by(tl(xml, toy).events, "engaged")
    assert [(e.from_rung, e.to_rung) for e in events] == \
        [("not_armed", "armed_far"), ("armed_far", "armed_close")]
    assert events[0].kind == "attainment"


def test_coverage_crossings_and_code_and_outcome_events(toy):
    # a 2286mm westward drive sweeps straight through the pad region
    xml = workspace(hat("pg_events_when_started", drive_for(2286)))
    result = tl(xml, toy, params={"points": 5})
    coverage = by(result.events, "coverage")
    assert coverage and coverage[0].from_rung == "low"
    assert [e.to_rung for e in coverage] == \
        ["mid", "high"][:len(coverage)]     # ascending, single-drive crossings
    # code event on the origin pseudo-step, block-less
    moved = by(result.events, "moved")
    assert len(moved) == 1 and moved[0].step == ORIGIN_STEP
    assert moved[0].block_id is None and moved[0].block_type is None
    # outcome event on the final scored step
    points = by(result.events, "points")
    assert len(points) == 1
    assert points[0].step == len(simulate_path(
        parse_workspace(xml, "t"),
        load_configs("toy_line", toy).context).path) - 1
    assert points[0].to_rung == "scored"


def test_events_ordered_by_step_then_card_order(toy):
    xml = workspace(hat("pg_events_when_started",
                        MAGNET.replace("</block>",
                                       f"<next>{drive_for(2286)}</next></block>")))
    result = tl(xml, toy, params={"points": 5})
    steps = [e.step for e in result.events]
    assert steps == sorted(steps)
    # ties broken by goal-card order: at the arrival step, reach-goal events
    # precede sweep-goal events
    arrival = [e for e in result.events if e.step == 1]
    goals_in_order = [e.goal for e in arrival]
    assert goals_in_order == sorted(goals_in_order,
                                    key=["reach", "sweep", "authored"].index)


def test_block_id_none_only_on_origin_pseudo_step(corpus):
    for prog in corpus[:30]:
        result = timeline_result(prog.workspace_xml or "", prog.program_id,
                                 prog.playground_params)
        for ev in result.events + result.post_exit_events:
            if ev.step == ORIGIN_STEP:
                assert ev.block_id is None and ev.block_type is None
            else:
                assert ev.block_id, (prog.program_id, ev)


def test_monotonicity_of_fast_scan_assumptions(corpus):
    """§A3: the fast paths assume prefix-monotone indicators — assert it."""
    cfg = load_configs("castle_crashers")
    plow = cfg.context.objects["plow"]
    checked = 0
    for prog in corpus:
        if checked >= 10:
            break
        program = parse_workspace(prog.workspace_xml or "", prog.program_id)
        if program is None:
            continue
        full = simulate_path(program, cfg.context)
        if len(full.path) < 5:
            continue
        checked += 1
        # running min distance never increases
        running = math.inf
        for ps in full.path:
            d = math.hypot(ps.x - plow.x, ps.y - plow.y)
            running = min(running, d)
            assert running <= d
        # prefix coverage never decreases
        prev = 0.0
        for k in range(1, len(full.path) + 1, max(1, len(full.path) // 10)):
            cov = slice_sim_result(full, 0, k, context=cfg.context) \
                .region_coverage_fractions.get("debris_zone", 0.0)
            assert cov >= prev - 1e-12
            prev = cov
    assert checked == 10


def test_binary_search_coverage_agrees_with_brute_force(corpus):
    cfg = load_configs("castle_crashers")
    spec = next(s for g in cfg.goals for s in g.intent
                if s.indicator == "region_coverage")
    checked = 0
    for prog in corpus:
        if checked >= 10:
            break
        program = parse_workspace(prog.workspace_xml or "", prog.program_id)
        if program is None:
            continue
        full = simulate_path(program, cfg.context)
        if full.region_coverage_fractions.get("debris_zone", 0.0) < spec.rungs.edges[0]:
            continue
        checked += 1
        # brute force: first prefix k whose coverage crosses each edge
        covs = [slice_sim_result(full, 0, k, context=cfg.context)
                .region_coverage_fractions.get("debris_zone", 0.0)
                for k in range(1, len(full.path) + 1)]
        expected = {}
        for i, edge in enumerate(spec.rungs.edges):
            for k, cov in enumerate(covs, start=1):
                if cov >= edge:
                    expected[spec.rungs.labels[i + 1]] = k - 1
                    break
        result = timeline_result(prog.workspace_xml, prog.program_id,
                                 prog.playground_params)
        measured = {e.to_rung: e.step
                    for e in result.events + result.post_exit_events
                    if e.indicator == "debris_zone_coverage"}
        assert measured == expected, prog.program_id
    assert checked == 10


def test_regression_c094_arm_then_approach_with_boundary_failure(corpus):
    prog = next(p for p in corpus if p.program_id.startswith("WREN-C094"))
    result = timeline_result(prog.workspace_xml, prog.program_id,
                             prog.playground_params)
    failures = [e for e in result.events if e.kind == "failure"]
    assert len(failures) == 1
    assert failures[0].goal == "__boundary__" and failures[0].to_rung == "exceeded"
    attach = next(e for e in result.events
                  if e.indicator == "plow_proximity_execution"
                  and e.to_rung == "attach_estimated")
    reached = next(e for e in result.events
                   if e.indicator == "plow_approach_intent" and e.to_rung == "reached")
    # Near-contact attachment model (OI-21, 2026-08-21): C094 drives up
    # BESIDE the blade with the magnet off (no attach — armed-window gated),
    # then arms at step 3 parked with the magnet 45mm from the blade — which
    # attaches immediately, like the parked P-series statics. The old
    # anchor-radius model read this program as "arm then approach" because
    # the robot CENTRE was 235mm from the ANCHOR at arming; the measured
    # model reads it as "arm AT the plow, then drive away".
    assert attach.step == 3 and attach.value <= 0
    assert reached.step > attach.step   # the anchor-approach minimum comes later


def test_regression_c050_approach_then_arm(corpus):
    prog = next(p for p in corpus if p.program_id.startswith("WREN-C050"))
    result = timeline_result(prog.workspace_xml, prog.program_id,
                             prog.playground_params)
    armed = next(e for e in result.events
                 if e.indicator == "plow_proximity_execution")
    reached = next(e for e in result.events
                   if e.indicator == "plow_approach_intent" and e.to_rung == "reached")
    assert reached.step < armed.step        # approach-then-arm


def test_no_spans_and_lists_never_merged(corpus):
    """§A4: post-exit events are separate; §A1: events only, no span concepts."""
    exited = 0
    for prog in corpus:
        result = timeline_result(prog.workspace_xml or "", prog.program_id,
                                 prog.playground_params)
        if result.boundary_exit_step is None:
            assert result.post_exit_events == []
        else:
            exited += 1
            assert all(e.step <= result.boundary_exit_step for e in result.events)
            assert all(e.step > result.boundary_exit_step
                       for e in result.post_exit_events)
    assert exited == 70    # 2026-08-26 castle structure: C018+C046 exit on tower detections (was 68)


def test_malformed_and_empty_programs(toy):
    assert timeline("<not xml", "broken") == []
    result = tl(workspace(hat("pg_events_when_started", MAGNET)), toy)
    # magnet-only program: no movement, engaged fires at the magnet step
    assert all(e.step in (ORIGIN_STEP, 0) for e in result.events)


def test_timeline_performance(corpus):
    times = []
    for prog in corpus:
        start = time.perf_counter()
        timeline_result(prog.workspace_xml or "", prog.program_id,
                        prog.playground_params)
        times.append(time.perf_counter() - start)
    median_ms = statistics.median(times) * 1000
    print(f"\ntimeline median over {len(times)} programs: {median_ms:.1f}ms")
    assert median_ms < 100
