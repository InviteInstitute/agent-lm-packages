"""Test-case playground harness (sensing build Phase 5, 2026-08-19).

Runs a student's program against authored scenario cards — empty island plus
declared test pieces, with the simulator's testcase-only kinematic push model
and raised loop caps — and reports goal-aligned responsivity that the main
simulation cannot evidence (reviewer §6 of the design discussion: the tests
exist to observe sensor-driven behavior toward MOVABLE, IMPERMANENT objects;
red-line sensing is already sim-evidenced and is not re-tested here).

Everything scenario-specific lives in configs/testcases/<playground>/*.yaml:
piece placements, spawn overrides, check rules and thresholds, and each
check's goal facet. Nothing here names a playground entity.

Multi-goal cards (2026-08-27): a scenario contributes evidence to more than
one goal — a card's stays_on_island check is remain_on_island evidence
while its clearing checks feed clear_debris_zone (every T-family card). The card's `goal`
field accepts a string or a list (first entry = primary, the default
attribution); a check may carry its own `goal:` to route its evidence in
the roll-up. Card-declared, like everything else.

Check rules:
- behavioral_divergence: the same code is run WITH and WITHOUT the pieces;
  "detects" passes only if the trajectory actually responds (path diverges
  beyond divergence_mm or step counts differ). A blind sweeper that clears a
  piece without reacting fails detects while passing pushes_off — exactly
  the distinction the harness exists to draw.
- min_distance: continuous (segment-level) minimum distance from the path to
  any piece's initial position, against within_mm.
- pieces_cleared: at least `count` pieces pushed off the island.
- on_island: the ROBOT never exits the boundary (the fall-off failure
  condition is handled).

Loop/conditional inference (reviewer ruling: every check is upper-bounded;
each check carries its own rule): when a check fails but the run was
loop-capped and shows the check's progress signal, the result is
CONDITIIONAL, annotated with the card's progress_annotation (e.g.
could_reach_if_run) rather than a hard fail.
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Optional

from goal_strategy.detector.parsing.parse_blocks import parse_workspace
from goal_strategy.detector.simulation.simulate_path import (
    PlaygroundContext, _point_in_convex_polygon, _point_segment_dist,
    simulate_path,
)

from .config import _DEFAULT_CONFIGS_DIR, _load_yaml
from .paths import data_path, require_data
from .indicators import _segment_closest

# Block types whose information the main sim cannot fully evidence — code
# consulting these qualifies for the battery. Down-eye color (red line) is
# deliberately absent: the sim already models it faithfully (reviewer §6).
_SENSOR_QUALIFIERS_EXACT = frozenset({
    "pg_sensing_bumper", "pg_sensing_bumper_pressed", "pg_sensing_bumper_near",
    "pg_events_when_bumper",
    "pg_sensing_optical_near_object", "pg_sensing_eye", "pg_sensing_optical",
    "pg_events_optical_detect_object",
})
_SENSOR_QUALIFIER_PREFIXES = ("pg_sensing_distance",)


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str                    # "pass" | "conditional" | "fail" | "measured"
    facet: str
    annotation: Optional[str] = None
    detail: Optional[str] = None
    # Which goal this check's evidence feeds in the roll-up: the check's own
    # card-declared `goal:` if present, else the scenario's primary goal.
    goal: Optional[str] = None
    # Measurement rules (directive 2026-08-27) report the raw observation
    # here (status "measured"); boolean rules leave it None. `capped` marks
    # a measurement taken on a loop-capped run (lower certainty — the
    # rollup card decides the credit).
    value: Optional[float] = None
    capped: bool = False
    # Abstention (boundary-family Phase 1, reviewer-ruled 2026-08-28/31):
    # the check produced NO evidence — the run never reached the phase the
    # check measures. Mirrors indicators.py: consumers guard on the FLAG,
    # never the value; an abstained check is SKIPPED everywhere (goal
    # mapping, requires-gates, rollup weight), never scored fail or zero.
    # Appended after existing fields — tests construct CheckResult
    # positionally.
    abstained: bool = False
    abstain_reason: Optional[str] = None


@dataclass(frozen=True)
class ScenarioResult:
    scenario_id: str
    goal: str
    checks: tuple[CheckResult, ...]
    # Which sensing construct this variant materialized pieces for (Option A,
    # reviewer-approved 2026-08-19): "block_type@block_id" for per-construct
    # variants, "static" for absolute-piece scenarios.
    construct: str = "static"
    # Card-declared family (battery build 2026-08-27): configuration
    # families (e.g. t1_debris_field) group scenarios for the rollup;
    # defaults to the scenario_id when the card declares none.
    family: str = ""


@dataclass(frozen=True)
class ScenarioArtifact:
    """Full run artifact per (scenario, construct) — the B-1 forward-design
    constraint (SENSOR_TESTBATTERY §6.2): preserve the whole run, not just
    check booleans, so later readers re-read without re-running. Only
    collected when run_battery(collect_sims=True)."""
    scenario_id: str
    construct: str
    family: str
    context: object          # with-pieces PlaygroundContext
    baseline: object         # SimulationResult without pieces
    sim: object              # SimulationResult with pieces


@dataclass(frozen=True)
class BatteryReport:
    program_id: str
    eligible: bool
    qualifying_blocks: tuple[str, ...]
    scenarios: tuple[ScenarioResult, ...]
    # goal id -> facet -> "pass" | "conditional" | "fail" — the roll-up that
    # feeds unobservable goal evidence (reviewer: fills in what the outcome
    # channel and main sim cannot show). Measurement checks ("measured")
    # stay out of this ranking; the rollup layer reads their values.
    goal_mapping: dict = field(default_factory=dict)
    # Full run artifacts, only when collect_sims=True (viz / B-1(c)).
    artifacts: tuple = ()


def load_scenarios(playground: str, configs_dir: str | None = None) -> list[dict]:
    base = Path(configs_dir or _DEFAULT_CONFIGS_DIR) / "testcases" / playground
    if not base.is_dir():
        return []
    out = []
    for path in sorted(base.glob("*.yaml")):
        card = _load_yaml(path)
        if isinstance(card, dict) and card.get("scenario_id"):
            out.append(card)
    return out


def _iter_blocks(node):
    while node is not None:
        yield node
        for child in node.children:
            yield from _iter_blocks(child)
        for value in node.values:
            yield from _iter_blocks(value)
        node = node.next


def _constructs(program) -> list[dict]:
    """Qualifying sensing constructs as instances: reporters (materialization
    timed by the baseline's first-evaluation trace) and hats (armed from step
    0, so they materialize at 0)."""
    out, seen = [], set()
    for root in program.live_stacks:
        is_hat_root = root.block_type in ("pg_events_optical_detect_object",
                                          "pg_events_when_bumper")
        if is_hat_root and root.block_id not in seen:
            seen.add(root.block_id)
            out.append({"id": root.block_id, "block_type": root.block_type,
                        "kind": "hat"})
        for block in _iter_blocks(root):
            bt = block.block_type
            if block.block_id in seen:
                continue
            qualifies = bt in _SENSOR_QUALIFIERS_EXACT and not bt.startswith("pg_events") \
                or any(bt.startswith(pfx) for pfx in _SENSOR_QUALIFIER_PREFIXES)
            if not qualifies and bt in ("pg_sensing_optical_color",
                                        "pg_sensing_optical_detected_color_is"):
                qualifies = "down" not in (block.get_field("OPTICAL") or "").lower()
            if qualifies:
                seen.add(block.block_id)
                out.append({"id": block.block_id, "block_type": bt,
                            "kind": "reporter"})
    return out


def qualifying_blocks(program) -> list[str]:
    found = []
    for root in program.live_stacks:
        for block in _iter_blocks(root):
            bt = block.block_type
            if bt in found:
                continue
            if bt in _SENSOR_QUALIFIERS_EXACT or \
                    any(bt.startswith(p) for p in _SENSOR_QUALIFIER_PREFIXES):
                found.append(bt)
    for root in program.live_stacks:
        for block in _iter_blocks(root):
            if block.block_type in ("pg_sensing_optical_color",
                                    "pg_sensing_optical_detected_color_is"):
                eye = (block.get_field("OPTICAL") or "").lower()
                if "down" not in eye and block.block_type not in found:
                    found.append(block.block_type)
    return found


def _scenario_card(base_card: dict, scenario: dict, with_pieces: bool,
                   activate_at_step: int = 0,
                   world_events: list | None = None) -> dict:
    """Overlay a scenario onto the base playground card: empty island (all
    original objects removed), declared test pieces, optional spawn override,
    and the testcase physics switch.

    Boundary-family overlays (Phase 2, 2026-08-31): `arena_polygon_mm`
    replaces the island polygon with the card's enlarged open arena AND
    removes the red ring (there is no boundary to see until an event places
    one — the pre-activation world is deliberately featureless so no
    program exits early and the sticky exits_boundary flag stays clean);
    `world_events` (already resolved by the caller — `at: activation`
    rewritten to a concrete at_step) pass through to the simulator."""
    card = copy.deepcopy(base_card)
    if scenario.get("arena_polygon_mm"):
        fb = dict(card.get("field_boundary") or {})
        fb["polygon_mm"] = copy.deepcopy(scenario["arena_polygon_mm"])
        card["field_boundary"] = fb
        card["color_zones"] = [z for z in (card.get("color_zones") or [])
                               if str(z.get("color", "")).lower() != "red"]
    if world_events:
        card["world_events"] = copy.deepcopy(world_events)
    pieces = scenario.get("pieces") or {}
    if with_pieces and pieces:
        first = next(iter(pieces.values()))
        merged = copy.deepcopy(pieces)
        if activate_at_step:
            for piece in merged.values():
                piece["active_from_step"] = activate_at_step
        card["objects"] = {"test_pieces": {
            "object_type": "target", "movable": True,
            "x": first.get("x", 0), "y": first.get("y", 0), "tolerance": 1,
            "pieces": merged,
        }}
    else:
        card["objects"] = {}
    if scenario.get("spawn"):
        # MERGE, not replace (T5 blocker, 2026-08-28): a card that declares
        # only `heading:` must inherit the canonical x/y — replacing the
        # dict wholesale dropped the position and spawned the robot at the
        # card default (0,0). No production scenario had used `spawn:`
        # before T5, so this path was unexercised.
        spawn = dict((card.get("spawn_points") or {}).get("default_start") or {})
        spawn.update(scenario["spawn"])
        card.setdefault("spawn_points", {})["default_start"] = spawn
    card["testcase_physics"] = dict(scenario.get("testcase_physics") or {})
    return card


def _path_divergence(sim_a, sim_b, polygon=None,
                     grace_mm: float = 0.0) -> float:
    """Max pointwise divergence — PRE-FAILURE scoped when a polygon is
    given (OI-37 ruling 2026-09-11): behavior after either run leaves
    the island beyond grace cannot evidence detection, and a
    step-count difference counts as divergence only when BOTH runs
    ended naturally pre-failure (a stop-responder), never when the
    difference is failure timing itself (a chunk-driver falling off at
    different moments in the two worlds is not detection)."""
    la, lb = len(sim_a.path), len(sim_b.path)
    if polygon is None:
        if la != lb:
            return float("inf")
        worst = 0.0
        for pa, pb in zip(sim_a.path, sim_b.path):
            worst = max(worst, math.hypot(pa.x - pb.x, pa.y - pb.y))
        return worst
    from .battery_evidence import _dense_samples, _scenario_exit_step
    from goal_strategy.detector.simulation.simulate_path import (
        _point_in_convex_polygon,
    )
    pedges = list(zip(polygon, polygon[1:] + polygon[:1]))

    def _prefail(s):
        """Pre-failure polyline: rows up to the exit step, PLUS the
        clipped position where the exiting segment left the island —
        so a response that BEGINS on-island counts even when its
        block's endpoint lands outside."""
        path = list(s.path or [])
        ex = _scenario_exit_step(path, polygon, grace_mm,
                                 (s.origin_x, s.origin_y))
        if ex is None:
            return [(p.x, p.y) for p in path]
        pts = [(p.x, p.y) for p in path if int(p.step) <= ex]
        last_inside = None
        for sx, sy, sstep in _dense_samples(path,
                                            (s.origin_x, s.origin_y)):
            if int(sstep) > ex:
                break
            if _point_in_convex_polygon(sx, sy, polygon):
                last_inside = (sx, sy)
            else:
                d = min(_point_segment_dist(sx, sy, a[0], a[1],
                                            b[0], b[1])
                        for a, b in pedges)
                if d > grace_mm:
                    break
        if last_inside is not None:
            pts.append(last_inside)
        return pts or [(s.origin_x, s.origin_y)]

    A, B = _prefail(sim_a), _prefail(sim_b)
    n = min(len(A), len(B))
    worst = 0.0
    for (ax, ay), (bx, by) in zip(A[:n], B[:n]):
        worst = max(worst, math.hypot(ax - bx, ay - by))
    # tail: extra PRE-FAILURE motion in either run beyond the other's
    # final pre-failure position is itself behavioral divergence (the
    # stop-responder and respond-then-move cases)
    for extra, other in ((A[n:], B), (B[n:], A)):
        if extra and other:
            ox, oy = other[-1]
            for (px, py) in extra:
                worst = max(worst, math.hypot(px - ox, py - oy))
    return worst


def _continuous_min_distance(sim, px: float, py: float) -> float:
    pts = [(sim.origin_x, sim.origin_y)] + [(p.x, p.y) for p in sim.path]
    best = float("inf")
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        d, _, _ = _segment_closest(ax, ay, bx, by, px, py)
        best = min(best, d)
    if pts:
        best = min(best, math.hypot(pts[0][0] - px, pts[0][1] - py))
    return best


def _distance_trend_improving(sim, px: float, py: float) -> bool:
    """Progress signal for capped runs: the closest approach in the final
    third of the path beats the first third's."""
    n = len(sim.path)
    if n < 6:
        return False
    third = n // 3
    first = min(math.hypot(p.x - px, p.y - py) for p in sim.path[:third])
    last = min(math.hypot(p.x - px, p.y - py) for p in sim.path[-third:])
    return last < first


def _abstain(name: str, facet: str, reason: str) -> CheckResult:
    """No-evidence result (boundary family): the run never reached the phase
    this check measures. Reason tokens (snake_case): `test_not_activated`
    (no sensing block ever evaluated, the event never fired),
    `encounter_not_reached` (event fired but the robot never came within the
    card-declared distance of the placed edge), `repeat_not_activated` (the
    retreat condition never met, only the repeat event abstains)."""
    return CheckResult(name, "abstained", facet, abstained=True,
                       abstain_reason=reason)


def _evaluate_check(check: dict, positions: list, sim, baseline,
                    ctx=None) -> CheckResult:
    name = str(check.get("name"))
    rule = str(check.get("rule"))
    facet = str(check.get("facet", name))
    annotation = check.get("progress_annotation")

    # Measurement rules (directive 2026-08-27): the check reports the RAW
    # observation as `value` with status "measured" — no thresholds in
    # cards; rungs/weights/thresholds live only in the rollup card.
    if rule == "proportion_cleared":
        presented = max(1, len(sim.piece_positions))
        cleared = len(sim.pieces_cleared)
        frac = cleared / presented
        return CheckResult(name, "measured", facet, value=frac,
                           capped=bool(sim.loop_was_capped),
                           annotation=annotation if sim.loop_was_capped else None,
                           detail=f"{cleared}/{presented} cleared")

    if rule == "proportion_engaged":
        presented = max(1, len(sim.piece_positions))
        engaged = sum(1 for pid in sim.object_contacts
                      if pid in sim.piece_positions)
        frac = engaged / presented
        return CheckResult(name, "measured", facet, value=frac,
                           capped=bool(sim.loop_was_capped),
                           annotation=annotation if sim.loop_was_capped else None,
                           detail=f"{engaged}/{presented} pieces contacted")

    if rule == "proportion_on_island":
        pts = [(sim.origin_x, sim.origin_y)] + [(p.x, p.y) for p in sim.path]
        if ctx is not None and ctx.field_hex_vertices:
            inside = sum(1 for x, y in pts if _point_in_convex_polygon(
                x, y, ctx.field_hex_vertices))
        elif ctx is not None:
            inside = sum(1 for x, y in pts
                         if math.hypot(x, y) <= ctx.field_radius)
        else:
            inside = len(pts)
        frac = inside / max(1, len(pts))
        return CheckResult(name, "measured", facet, value=frac,
                           capped=bool(sim.loop_was_capped),
                           detail=f"{inside}/{len(pts)} steps on island")

    if rule == "behavioral_divergence":
        _r = dict(check.get("episode_rules") or {})
        div = _path_divergence(sim, baseline,
                               polygon=ctx.field_hex_vertices,
                               grace_mm=float(_r.get("exit_grace_mm")
                                              or 0.0))
        ok = div > float(check.get("divergence_mm", 100))
        return CheckResult(name, "pass" if ok else "fail", facet,
                           detail=f"max path divergence {'inf' if math.isinf(div) else round(div)}mm")

    if rule == "min_distance":
        within = float(check.get("within_mm", 180))
        best = min((_continuous_min_distance(sim, px, py)
                    for px, py in positions), default=float("inf"))
        if best <= within:
            return CheckResult(name, "pass", facet, detail=f"min distance {round(best)}mm")
        if sim.loop_was_capped and any(
                _distance_trend_improving(sim, px, py) for px, py in positions):
            return CheckResult(name, "conditional", facet, annotation=annotation,
                               detail=f"capped at {round(best)}mm, closing")
        return CheckResult(name, "fail", facet, detail=f"min distance {round(best)}mm")

    if rule == "pieces_cleared":
        need = int(check.get("count", 1))
        got = len(sim.pieces_cleared)
        if got >= need:
            return CheckResult(name, "pass", facet, detail=f"{got} cleared")
        if sim.loop_was_capped and (got > 0 or sim.object_contacts):
            return CheckResult(name, "conditional", facet, annotation=annotation,
                               detail=f"capped with {got} cleared, contact made")
        return CheckResult(name, "fail", facet, detail=f"{got} cleared")

    if rule == "on_island":
        ok = not sim.exits_field_boundary
        return CheckResult(name, "pass" if ok else "fail", facet,
                           detail="robot stayed on island" if ok else "robot exited")

    if rule == "edge_encounters_survived":
        # Reviewer ruling 2026-09-01: stays_on_island is a MEASUREMENT —
        # the proportion of edge ENCOUNTERS the robot survived, with a
        # depth grace of the production card's physical half-diagonal
        # (episode_rules.exit_grace_mm; a transient centre poke <= grace
        # with recovery is not a fall). Zero encounters = NO evidence:
        # abstain encounter_not_reached (same token, same meaning as the
        # boundary family's), never a trivial pass for standing still.
        from .battery_evidence import _edges, edge_encounter_episodes
        rules = dict((check.get("episode_rules") or {}))
        # An ENCOUNTER = the down-eye entered the ring (the boundary became
        # sensor-relevant), so the band reaches band_mm + the eye's forward
        # offset — a program that stops precisely short (centre back, eye on
        # the ring) registers a SURVIVED encounter, not none (reviewer
        # 2026-09-01).
        band = float(rules.get("band_mm") or 0.0) + float(rules.get("eye_reach_mm") or 0.0)
        retreat = float(rules.get("retreat_mm") or 0.0)
        grace = float(rules.get("exit_grace_mm") or 0.0)
        edges = _edges(sim, ctx)
        polygon = list(getattr(ctx, "field_hex_vertices", None) or [])
        origin = (getattr(sim, "origin_x", None), getattr(sim, "origin_y", None))
        origin = origin if origin[0] is not None else None
        eps = edge_encounter_episodes(sim.path or [], edges, polygon,
                                      band, retreat, grace, origin=origin)
        if not eps:
            return _abstain(name, facet, "encounter_not_reached")
        survived = sum(1 for *_e, ok in eps if ok)
        return CheckResult(name, "measured", facet,
                           value=survived / len(eps),
                           capped=bool(sim.loop_was_capped),
                           detail=f"{survived}/{len(eps)} encounters survived"
                                  f" (grace {grace:g}mm)")

    return CheckResult(name, "fail", facet, detail=f"unknown rule {rule!r}")


_STATUS_RANK = {"pass": 0, "conditional": 1, "fail": 2}


def _run_boundary_scenario(program, base_card: dict, robot_card: dict,
                           scenario: dict, scheduler: str, clock: dict,
                           constructs: list, baseline, collect_sims: bool):
    """One boundary-family scenario (Phase 2, plan §6.2a): resolve the
    ruled activation trigger (first sensing evaluation, uniformly; hats are
    armed from step 0), schedule the card's world events at it, run ONCE in
    the arena world, and emit abstentions where the run produced no
    evidence — `test_not_activated` (no sensing ever evaluated),
    `encounter_not_reached` (the placed edge was never approached within
    the card-declared distance), `repeat_not_activated` (a check requiring
    an unfired repeat event; the first encounter's evidence still counts).
    Returns (ScenarioResult, ScenarioArtifact | None)."""
    sid = str(scenario["scenario_id"])
    family = str(scenario.get("family") or sid)
    declared = scenario.get("goal", "")
    goals = [str(g) for g in declared] if isinstance(declared, list) \
        else [str(declared)]
    primary_goal = goals[0] if goals else ""
    checks_spec = scenario.get("checks") or []

    def _all_abstained(reason):
        crs = tuple(replace(_abstain(str(c.get("name")),
                                     str(c.get("facet", c.get("name"))),
                                     reason),
                            goal=str(c.get("goal") or primary_goal))
                    for c in checks_spec)
        return ScenarioResult(scenario_id=sid, goal=primary_goal,
                              checks=crs, construct="world_events",
                              family=family), None

    act = None
    if any(c["kind"] == "hat" for c in constructs):
        act = 0
    elif baseline.sensor_first_eval:
        act = min(step for step, _bt in baseline.sensor_first_eval.values())
    if act is None:
        return _all_abstained("test_not_activated")

    events = copy.deepcopy(scenario["world_events"])
    for ev in events:
        if ev.get("at") == "activation":
            ev.pop("at", None)
            ev["at_step"] = int(act)
    ctx = PlaygroundContext.from_playground_card(
        _scenario_card(base_card, scenario, with_pieces=False,
                       world_events=events), robot_card)
    sim = simulate_path(program, ctx, scheduler=scheduler, **clock)

    fired = {e[1] for e in sim.world_event_log}
    first_edge = next((((e[2]), (e[3])) for e in sim.world_event_log
                       if e[2] is not None), None)
    enc_mm = scenario.get("encounter_within_mm")
    if first_edge is not None and enc_mm is not None:
        fire_step = sim.world_event_log[0][0]
        (ax, ay), (bx, by) = first_edge
        # SEGMENT-AWARE approach (2026-09-01, same lesson as the episode
        # walk): path points are block ENDPOINTS — a robot that STARTS at
        # the placed edge (T6 assured detection) and whose first block is
        # the retreat would read its own start pose as never-approached.
        # Seed with the origin pose and take each segment's closest point.
        pre = [(p.x, p.y) for p in sim.path if p.step < fire_step]
        seed = pre[-1] if pre else (sim.origin_x, sim.origin_y)
        pts = [seed] + [(p.x, p.y) for p in sim.path if p.step >= fire_step]
        # DENSIFY each segment (<=25mm): path points are block endpoints, so
        # a single long drive that sails THROUGH the edge would otherwise be
        # missed — only its endpoints (near/far) get checked (the big-jump
        # bug, 2026-09-01). Same lesson as the episode walk.
        approach = float("inf")
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            seg = math.hypot(x1 - x0, y1 - y0)
            n = max(1, int(seg // 25))
            for i in range(n + 1):
                t = i / n
                approach = min(approach, _point_segment_dist(
                    x0 + (x1 - x0) * t, y0 + (y1 - y0) * t, ax, ay, bx, by))
        if approach > float(enc_mm):
            return _all_abstained("encounter_not_reached")

    positions = list(sim.piece_positions.values())
    evaluated: dict[str, CheckResult] = {}
    ordered = []
    for c in checks_spec:
        c = {**c, "episode_rules": scenario.get("episode_rules") or {}}
        req_ev = c.get("requires_event")
        if req_ev and str(req_ev) not in fired:
            cr = _abstain(str(c.get("name")),
                          str(c.get("facet", c.get("name"))),
                          "repeat_not_activated")
        else:
            cr = _evaluate_check(c, positions, sim, baseline, ctx)
            req = c.get("requires")
            if req and not cr.abstained and cr.status != "fail":
                prereq = evaluated.get(str(req))
                if prereq is None or prereq.status != "pass":
                    cr = CheckResult(cr.name, "fail", cr.facet,
                                     detail=f"{cr.detail}; but no {req} "
                                            "response — accidental, not "
                                            "evidence")
        cr = replace(cr, goal=str(c.get("goal") or primary_goal))
        evaluated[cr.name] = cr
        ordered.append(cr)
    result = ScenarioResult(scenario_id=sid, goal=primary_goal,
                            checks=tuple(ordered),
                            construct="world_events", family=family)
    artifact = ScenarioArtifact(scenario_id=sid, construct="world_events",
                                family=family, context=ctx,
                                baseline=baseline, sim=sim) \
        if collect_sims else None
    return result, artifact


def downeye_only_sensing(program) -> bool:
    """The rubric-router's structural gate (2026-09-05): the program's
    ONLY executable sensing is the down-eye color read — no battery
    qualifier anywhere. (Front-eye color qualifies; down-eye does not —
    the same field-aware rule as `_constructs`.)"""
    if qualifying_blocks(program):
        return False
    for root in program.live_stacks:
        for block in _iter_blocks(root):
            if block.block_type in ("pg_sensing_optical_color",
                                    "pg_sensing_optical_detected_color_is"):
                if "down" in (block.get_field("OPTICAL") or "").lower():
                    return True
    return False


def run_battery(workspace_xml: str, program_id: str,
                playground: str = "castle_crashers",
                configs_dir: str | None = None,
                scheduler: str | None = None,
                collect_sims: bool = False,
                budget_key: str = "time_budget_s",
                families: "set[str] | None" = None,
                rubric_channel: bool = False) -> BatteryReport:
    """budget_key (OI-28, 2026-08-28) selects WHICH card-declared wall-clock
    budget this pass uses — 'time_budget_s' (the primary) or
    'invariance_budget_s' (the second point of the reviewer's two-budget
    invariance requirement: a capability level that changes with the budget
    is not a property of the program, so it must read U)."""
    base = Path(configs_dir or _DEFAULT_CONFIGS_DIR)
    base_card = _load_yaml(base / "playgrounds" / f"{playground}.yaml")
    robot_path = base / "robot" / f"{base_card.get('robot_ref', 'vr_robot')}.yaml"
    robot_card = _load_yaml(robot_path) if robot_path.exists() else {}
    # Card-default scheduler (2026-08-27, mirrors profile.py): the battery
    # previously hard-defaulted to sequential, diverging from the shipped
    # cooperative execution model.
    if scheduler is None:
        scheduler = str((base_card.get("simulation") or {})
                        .get("scheduler") or "sequential")

    program = parse_workspace(workspace_xml or "", program_id)
    if program is None:
        # Invalid/empty XML: no program to place in any world. Explicitly
        # ineligible rather than crashing in qualifying_blocks (host-safety).
        return BatteryReport(program_id=program_id, eligible=False,
                             qualifying_blocks=(), scenarios=())
    qualifiers = qualifying_blocks(program)
    if not qualifiers and not rubric_channel:
        return BatteryReport(program_id=program_id, eligible=False,
                             qualifying_blocks=(), scenarios=())
    if rubric_channel and not qualifiers:
        # Rubric-router gate (reviewer-ruled 2026-09-03, built 2026-09-05):
        # a down-eye-only program enters the battery for RUBRIC evidence
        # only — the caller restricts `families` (the boundary family) and
        # marks every downstream row channel=rubric_only. Down-eye color
        # is the qualifying construct here; activation resolution works
        # unchanged (it is a sensing evaluation like any other).
        qualifiers = ("pg_sensing_optical_color@downeye",)

    results = []
    artifacts = []
    facet_status: dict[str, dict[str, str]] = {}
    constructs = _constructs(program)
    for scenario in load_scenarios(playground, configs_dir):
        if families is not None and scenario.get("family") not in families:
            continue
        # OI-28: the wall-clock loop is card-declared per scenario and MUST
        # apply to the baseline too — comparing a marched run against a
        # frozen one would make behavioral_divergence meaningless.
        tp = scenario.get("testcase_physics") or {}
        hz = tp.get("loop_clock_hz")
        clock = {"loop_iteration_time_s": 1.0 / float(hz),
                 "time_budget_s": float(tp.get(budget_key)
                                        or tp.get("time_budget_s") or 60.0)} \
            if hz else {}
        ctx0 = PlaygroundContext.from_playground_card(
            _scenario_card(base_card, scenario, with_pieces=False), robot_card)
        baseline = simulate_path(program, ctx0, scheduler=scheduler, **clock)
        if scenario.get("world_events"):
            # Boundary family (Phase 2): one event-scheduled run, abstention
            # over failure when the run never reached the tested phase.
            res, art = _run_boundary_scenario(
                program, base_card, robot_card, scenario, scheduler, clock,
                constructs, baseline, collect_sims)
            results.append(res)
            if art is not None:
                artifacts.append(art)
            for cr in res.checks:
                if cr.abstained or cr.status not in _STATUS_RANK:
                    continue
                facets = facet_status.setdefault(cr.goal, {})
                prev = facets.get(cr.facet)
                if prev is None or _STATUS_RANK[cr.status] < _STATUS_RANK[prev]:
                    facets[cr.facet] = cr.status
            continue
        pieces = scenario.get("pieces") or {}
        # Option A (reviewer-approved 2026-08-19): scenarios with RELATIVE
        # piece placements run one variant per sensing construct — pieces
        # materialize at the step the baseline first consulted that construct
        # (hats: step 0, armed from start), placed relative to the robot's
        # pose then. Absolute-piece scenarios run once,
        # static from t0.
        relative = any(isinstance(p, dict) and p.get("relative")
                       for p in pieces.values())
        if relative:
            variants = []
            for c in constructs:
                step = 0 if c["kind"] == "hat" else \
                    baseline.sensor_first_eval.get(c["id"], (0, ""))[0]
                variants.append((f"{c['block_type']}@{c['id'][:8]}", step))
        else:
            variants = [("static", 0)]
        for construct_label, activate_step in variants:
            ctx = PlaygroundContext.from_playground_card(
                _scenario_card(base_card, scenario, with_pieces=True,
                               activate_at_step=activate_step), robot_card)
            sim = simulate_path(program, ctx, scheduler=scheduler, **clock)
        # `requires:` (reviewer ruling 2026-08-19): a check whose card names a
        # prerequisite check contributes evidence only when that prerequisite
        # passed — reaching or clearing a piece WITHOUT a detection response
        # is accidental, not evidence ("accidentally knocking the piece off
        # should not be evidence in itself; it should be paired with the
        # detection").
            positions = list(sim.piece_positions.values()) or [
                (p["x"], p["y"]) for p in pieces.values()
                if isinstance(p, dict) and "x" in p and "y" in p]
            # Multi-goal cards (2026-08-27): `goal` may be a string or a
            # list; the first entry is the primary (default attribution),
            # and a check's own `goal:` routes its evidence elsewhere.
            declared = scenario.get("goal", "")
            goals = [str(g) for g in declared] if isinstance(declared, list) \
                else [str(declared)]
            primary_goal = goals[0] if goals else ""
            family = str(scenario.get("family") or scenario["scenario_id"])
            evaluated: dict[str, CheckResult] = {}
            ordered = []
            for c in scenario.get("checks") or []:
                c = {**c, "episode_rules": scenario.get("episode_rules") or {}}
                cr = _evaluate_check(c, positions, sim, baseline, ctx)
                req = c.get("requires")
                # An abstained check never enters the requires-gate rewrite —
                # without this guard an abstention silently becomes `fail`.
                if req and not cr.abstained and cr.status != "fail":
                    prereq = evaluated.get(str(req))
                    if prereq is None or prereq.status != "pass":
                        cr = CheckResult(cr.name, "fail", cr.facet,
                                         detail=f"{cr.detail}; but no {req} response "
                                                "— accidental, not evidence")
                cr = replace(cr, goal=str(c.get("goal") or primary_goal))
                evaluated[cr.name] = cr
                ordered.append(cr)
            checks = tuple(ordered)
            results.append(ScenarioResult(
                scenario_id=str(scenario["scenario_id"]),
                goal=primary_goal, checks=checks,
                construct=construct_label, family=family))
            if collect_sims:
                artifacts.append(ScenarioArtifact(
                    scenario_id=str(scenario["scenario_id"]),
                    construct=construct_label, family=family,
                    context=ctx, baseline=baseline, sim=sim))
            for cr in checks:
                if cr.abstained:
                    continue      # no evidence — never enters the mapping
                if cr.status not in _STATUS_RANK:
                    continue      # measurements roll up via the rollup card
                facets = facet_status.setdefault(cr.goal, {})
                prev = facets.get(cr.facet)
                # best status across scenarios AND constructs wins:
                # capability shown anywhere is shown
                if prev is None or _STATUS_RANK[cr.status] < _STATUS_RANK[prev]:
                    facets[cr.facet] = cr.status

    return BatteryReport(program_id=program_id, eligible=True,
                         qualifying_blocks=tuple(qualifiers),
                         scenarios=tuple(results), goal_mapping=facet_status,
                         artifacts=tuple(artifacts))


def _main() -> None:   # pragma: no cover — thin CLI
    import argparse
    import csv
    import json

    ap = argparse.ArgumentParser(description="Run the sensor test-case battery "
                                             "over the corpus (eligible programs only)")
    ap.add_argument("--parquet", default=str(data_path("final_code_states.parquet")))
    ap.add_argument("--out", default="testcases_report.csv")
    ap.add_argument("--playground", default="castle_crashers")
    args = ap.parse_args()

    import pandas as pd
    from .config import load_configs

    cfg = load_configs(args.playground)
    required = (cfg.card.get("corpus_filter") or {}).get("required_outcome_field")
    df = pd.read_parquet(require_data(args.parquet))
    rows = []
    for rec in df.to_dict("records"):
        params = rec.get("playground_params")
        params = json.loads(params) if isinstance(params, str) and params else {}
        if required is not None and required not in params:
            continue
        pid = f"{rec['student_study_id']}_{rec['derived_session_id']}"
        xml = rec.get("workspace_xml")
        if not isinstance(xml, str) or not xml.strip():
            continue
        report = run_battery(xml, pid, playground=args.playground)
        if not report.eligible:
            continue
        for s in report.scenarios:
            for c in s.checks:
                rows.append({
                    "program_id": pid, "scenario": s.scenario_id,
                    "construct": s.construct, "goal": c.goal or s.goal,
                    "check": c.name, "facet": c.facet, "status": c.status,
                    "value": "" if c.value is None else c.value,
                    "capped": str(c.capped),
                    "abstain_reason": c.abstain_reason or "",
                    "annotation": c.annotation or "", "detail": c.detail or "",
                })
        for goal, facets in report.goal_mapping.items():
            for facet, status in facets.items():
                rows.append({"program_id": pid, "scenario": "__rollup__",
                             "construct": "", "goal": goal, "check": "",
                             "facet": facet, "status": status,
                             "value": "", "capped": "",
                             "abstain_reason": "",
                             "annotation": "", "detail": ""})
    with open(args.out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["program_id", "scenario", "construct", "goal",
                                               "check", "facet", "status",
                                               "value", "capped",
                                               "abstain_reason",
                                               "annotation", "detail"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows to {args.out}")


if __name__ == "__main__":   # pragma: no cover
    _main()
