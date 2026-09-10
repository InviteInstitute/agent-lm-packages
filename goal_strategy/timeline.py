"""timeline() — the moments at which each goal's evidence changes.

Every event is a rung transition on an indicator already declared in the goal
card (task 2 §A2): no per-goal event conditions, no new configuration, and the
timeline stays correct automatically when rungs are edited. This is NOT
segmentation — no spans, no intervals, no exclusivity; an ordered event list
and nothing more.

Efficiency (§A3): monotone indicators use monotone scans — running minima and
the state latch in one O(n) pass, region coverage by binary-searching the first
prefix crossing each rung edge (~log2(n) slices per edge). Unknown
simulation-channel indicators fall back to a per-step scan and must declare
monotonicity to opt in to the fast paths.

Conventions:
- The origin pseudo-step is step -1 with block_id/block_type None — the state
  before the first block runs (profile §3 origin seeding). Code-channel events
  land there (authored code precedes execution; a zero-step program still has
  them). §A3's "step 0" for code events is read as "start of timeline".
- Outcome-channel events land on the final scored step (the outcome is a fact
  about the real run, reported once).
- from_rung is the previous rung in the chain; the implicit start is the
  no-evidence rung (worst label / categorical absent / absent_label).
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Optional

from goal_strategy.detector.parsing.parse_blocks import parse_workspace
from goal_strategy.detector.simulation.simulate_path import (
    SimulationResult,
    simulate_path,
    slice_sim_result,
)

from .codefacts import extract_code_facts
from .config import IndicatorSpec, LoadedConfig, RungSpec, load_configs
from .indicators import (
    _STATE_ACTIVE_FROM_STEP,
    _attachment_structures,
    _distance,
    _magnet_pair_margin,
    _magnet_pose_margin,
    _zone_step_flag,
    EvalContext,
    REGISTRY,
)
from .profile import _find_boundary_exit

ORIGIN_STEP = -1


@dataclass
class GoalEvent:
    step: int                  # path step index; ORIGIN_STEP for the origin pseudo-step
    block_id: str | None       # None only for the origin pseudo-step
    block_type: str | None
    goal: str
    indicator: str
    kind: str                  # "intent" | "attainment" | "failure"
    from_rung: str | None
    to_rung: str
    value: float | bool | str
    flags: list[str] = field(default_factory=list)


@dataclass
class TimelineResult:
    events: list[GoalEvent]            # scored scope (§6a) + the failure event
    post_exit_events: list[GoalEvent]  # simulation fiction after the boundary exit
    boundary_exit_step: int | None


def timeline(workspace_xml: str, program_id: str,
             playground_params: dict | None = None,
             playground: str = "castle_crashers") -> list[GoalEvent]:
    return timeline_result(workspace_xml, program_id, playground_params,
                           playground).events


def timeline_result(workspace_xml: str, program_id: str,
                    playground_params: dict | None = None,
                    playground: str = "castle_crashers",
                    configs_dir: str | None = None,
                    conditional_hats: str | None = None,
                    scheduler: str | None = None,
                    stack_precedence: str | None = None,
                    _execution=None) -> TimelineResult:
    from .execution import prepare_execution
    execution = _execution or prepare_execution(
        workspace_xml, program_id, playground_params, playground,
        configs_dir=configs_dir, conditional_hats=conditional_hats,
        scheduler=scheduler, stack_precedence=stack_precedence)
    cfg, ectx = execution.config, execution.context
    full = ectx.full_sim
    if full is None:
        # Preserve valid constant outcome evidence without inventing a path.
        empty = SimulationResult()
        events = []
        for goal in cfg.goals:
            for kind, specs in (("intent", goal.intent), ("attainment", goal.attainment)):
                for spec in specs:
                    if spec.rungs is not None:
                        events.extend(_scan_constant(goal.id, kind, spec, cfg, empty, ectx, -1))
        return TimelineResult(events, [], None)
    exit_idx = execution.exit_index
    scoring_exit = None if execution.boundary_exit_overridden else exit_idx
    scored_last = scoring_exit if scoring_exit is not None else len(full.path) - 1

    events: list[GoalEvent] = []
    order: dict[tuple, int] = {}
    for gi, goal in enumerate(cfg.goals):
        for kind, specs in (("intent", goal.intent), ("attainment", goal.attainment)):
            for si, spec in enumerate(specs):
                order[(goal.id, spec.name)] = gi * 100 + (0 if kind == "intent" else 50) + si
                if spec.rungs is None:
                    continue
                scanner = _SCANNERS.get(spec.indicator, _scan_constant)
                events.extend(scanner(goal.id, kind, spec, cfg, full, ectx,
                                      scored_last))

    main, post = [], []
    for ev in events:
        (post if scoring_exit is not None and ev.step > scoring_exit else main).append(ev)

    if exit_idx is not None:
        ps = full.path[exit_idx]
        flags = ["boundary_exit_fabricated"] if exit_idx in full.fabricated_steps else []
        main.append(GoalEvent(step=exit_idx, block_id=ps.block_id,
                              block_type=ps.block_type, goal="__boundary__",
                              indicator="boundary_exceeded", kind="failure",
                              from_rung=None, to_rung="exceeded", value=True,
                              flags=flags))

    def sort_key(ev: GoalEvent):
        return (ev.step, order.get((ev.goal, ev.indicator), 10_000))

    from .profile import _profile
    prof = _profile(workspace_xml, program_id, playground_params, playground, _execution=execution)
    evidence = {(g.goal, i.name): i for g in prof.goals for i in g.intent + g.attainment}
    for event in main + post:
        indicator = evidence.get((event.goal, event.indicator))
        if indicator:
            event.flags = sorted(set(event.flags + indicator.flags))
            if execution.boundary_exit_overridden and event.step > exit_idx and indicator.channel == "simulation":
                event.flags = sorted(set(event.flags + ["evidence_post_sim_exit"]))
    main.sort(key=sort_key)
    post.sort(key=sort_key)
    return TimelineResult(main, post, exit_idx)


# ------------------------------------------------------------------ scanners
# Each scanner returns the FULL-path events for one indicator; timeline_result
# splits them into scored/post-exit at the boundary. Prefix-monotonicity makes
# the full-path crossing steps identical to truncated-path ones at steps <= exit.

def _no_evidence_rung(rungs: RungSpec) -> str | None:
    if rungs.kind == "categorical":
        return rungs.labels[0]
    if rungs.absent_label is not None:
        return rungs.absent_label
    return rungs.labels[0] if rungs.direction == "higher_is_better" else rungs.labels[-1]


def _event(step, sim, goal, kind, spec, from_rung, to_rung, value, flags=None):
    if step == ORIGIN_STEP:
        block_id = block_type = None
    else:
        ps = sim.path[step]
        block_id, block_type = ps.block_id, ps.block_type
    return GoalEvent(step=step, block_id=block_id, block_type=block_type,
                     goal=goal, indicator=spec.name, kind=kind,
                     from_rung=from_rung, to_rung=to_rung, value=value,
                     flags=list(flags or []))


def _scan_min_distance(goal, kind, spec, cfg, full, ectx, scored_last):
    """Running minimum, origin-seeded — only improves. O(n)."""
    obj = cfg.context.objects[spec.binding["object"]]
    events = []
    cur = _no_evidence_rung(spec.rungs)
    running = _distance(full.origin_x, full.origin_y, obj.x, obj.y)
    rung = spec.rungs.evaluate(running)
    if rung != cur:
        events.append(_event(ORIGIN_STEP, full, goal, kind, spec, cur, rung, running))
        cur = rung
    from .indicators import _segment_closest
    previous = (full.origin_x, full.origin_y)
    for i, ps in enumerate(full.path):
        d, _, _ = _segment_closest(*previous, ps.x, ps.y, obj.x, obj.y)
        previous = (ps.x, ps.y)
        if d < running:
            running = d
            rung = spec.rungs.evaluate(running)
            if rung != cur:
                events.append(_event(i, full, goal, kind, spec, cur, rung, running))
                cur = rung
    return events


def _scan_region_coverage(goal, kind, spec, cfg, full, ectx, scored_last):
    """Cells only accumulate — binary-search the first prefix crossing each edge."""
    region = spec.binding["region"]
    final_cov = full.region_coverage_fractions.get(region, 0.0)
    cache: dict[int, float] = {len(full.path): final_cov}

    def cov_at(k: int) -> float:   # coverage of path prefix [0, k)
        if k not in cache:
            sliced = slice_sim_result(full, 0, k, context=cfg.context)
            cache[k] = sliced.region_coverage_fractions.get(region, 0.0)
        return cache[k]

    events = []
    cur = _no_evidence_rung(spec.rungs)
    for edge_i, edge in enumerate(spec.rungs.edges):
        if final_cov < edge:      # higher_is_better: crossing means value >= edge
            break
        lo, hi = 1, len(full.path)
        while lo < hi:
            mid = (lo + hi) // 2
            if cov_at(mid) >= edge:
                hi = mid
            else:
                lo = mid + 1
        step = lo - 1
        rung = spec.rungs.labels[edge_i + 1]
        events.append(_event(step, full, goal, kind, spec, cur, rung, cov_at(lo)))
        cur = rung
    return events


def _scan_state_active(goal, kind, spec, cfg, full, ectx, scored_last):
    """Latches once true; then a running minimum over armed steps. O(n)."""
    accessor = _STATE_ACTIVE_FROM_STEP.get(spec.binding["state"])
    if accessor is None:
        return []
    active_from = accessor(full)
    if active_from is None:
        return []
    obj = cfg.context.objects[spec.binding["object"]]
    radius = float(obj.tolerance)
    events = []
    cur = _no_evidence_rung(spec.rungs)
    running = math.inf
    from .indicators import _segment_closest
    from types import SimpleNamespace
    previous = None
    for i, ps in enumerate(full.path):
        if ps.step < active_from:
            continue
        d, cx, cy = (_distance(ps.x, ps.y, obj.x, obj.y), ps.x, ps.y) if previous is None else _segment_closest(previous.x, previous.y, ps.x, ps.y, obj.x, obj.y)
        previous = ps
        if d < running:
            running = d
            rung = spec.rungs.evaluate(running)
            if rung != cur:
                flags = []
                if d <= radius and "zones_ref" in spec.binding:
                    zone_flag = _zone_step_flag(cfg.card, spec.binding, SimpleNamespace(x=cx, y=cy))
                    if zone_flag:
                        flags.append(zone_flag)
                events.append(_event(i, full, goal, kind, spec, cur, rung,
                                     running, flags))
                cur = rung
    return events


def _scan_attachment_clearance(goal, kind, spec, cfg, full, ectx, scored_last):
    """Near-contact attachment (OI-21): running minimum of the magnet-point
    clearance margin over armed steps — the attach event lands on the step
    whose travel first brings the magnet within the structure gap, which is
    the timing the reviewer observed live (C032 attaches on its second
    drive, not at its later closest-approach)."""
    accessor = _STATE_ACTIVE_FROM_STEP.get(spec.binding["state"])
    if accessor is None:
        return []
    active_from = accessor(full)
    if active_from is None:
        return []
    structures = _attachment_structures(cfg.card, spec.binding["object"])
    if not structures:
        return []
    mount = float((cfg.context.sensor_specs.get("magnet") or {})
                  .get("mount_forward_mm") or 0.0)
    events = []
    cur = _no_evidence_rung(spec.rungs)
    running = math.inf
    prev = None
    for i, ps in enumerate(full.path):
        if ps.step < active_from:
            continue
        m = (_magnet_pose_margin(ps.x, ps.y, ps.heading, structures, mount)
             if prev is None else
             _magnet_pair_margin(prev, ps, structures, mount))
        prev = ps
        if m < running:
            running = m
            rung = spec.rungs.evaluate(running)
            if rung != cur:
                events.append(_event(i, full, goal, kind, spec, cur, rung,
                                     running))
                cur = rung
    return events


def _scan_constant(goal, kind, spec, cfg, full, ectx, scored_last):
    """Code- and outcome-channel indicators: one event when evidence exists.

    Code events land on the origin pseudo-step (authored code precedes
    execution); outcome events on the final scored step. The value comes from
    the registry function itself — nothing is reimplemented here.
    """
    result = REGISTRY[spec.indicator](ectx, spec.binding)
    if result.abstained:
        return []
    rung = spec.rungs.evaluate(result.raw)
    start = _no_evidence_rung(spec.rungs)
    if rung is None or rung == start:
        return []
    if result.channel == "code":
        step = ORIGIN_STEP
    else:
        step = scored_last if scored_last >= 0 else ORIGIN_STEP
    return [_event(step, full, goal, kind, spec, start, rung, result.value,
                   flags=result.flags)]


_SCANNERS = {
    "min_distance_to_object": _scan_min_distance,
    "region_coverage": _scan_region_coverage,
    "state_active_within_radius": _scan_state_active,
    "state_active_attachment_clearance": _scan_attachment_clearance,
    # everything else (code/outcome channels) -> _scan_constant
}
