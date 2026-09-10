"""The generic indicator registry — 8 functions, parameterised entirely by binding.

No playground entity name, block type, zone name, flag string, or numeric threshold
appears here. Everything an indicator needs beyond the shared EvalContext comes from
its goal-card binding, resolved against the playground card.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from types import SimpleNamespace
from typing import Any, Callable, Optional

from goal_strategy.detector.simulation.simulate_path import (
    PathStep,
    PlaygroundContext,
    SimulationResult,
)

from .codefacts import CodeFacts

# Simulator states a binding may name. Adding an entry requires simulator work —
# the one documented boundary of the YAML-only extensibility rule (spec §5).
# Each accessor returns the step index from which the state is persistently
# active, or None if it never activates.
_STATE_ACTIVE_FROM_STEP: dict[str, Callable[[SimulationResult], Optional[int]]] = {
    "magnet_active": lambda sim: sim.magnet_fires_at_step,
}

_BINDING_SECTIONS = {"object": "objects", "region": "regions"}


def resolve_reference(ref: str, binding: dict, card: dict) -> Any:
    """Resolve a dotted card reference like ``object.tolerance``.

    The first token names a binding key (e.g. ``object``); the bound entity's node
    in the playground card is the root; remaining tokens index into it.
    """
    first, *rest = ref.split(".")
    if first not in _BINDING_SECTIONS:
        raise KeyError(f"reference root {first!r} is not a bindable entity kind")
    entity = binding[first]
    node: Any = card[_BINDING_SECTIONS[first]][entity]
    for token in rest:
        node = node[token]
    return node


@dataclass(frozen=True)
class EvalContext:
    program_id: str
    playground: str
    card: dict
    context: PlaygroundContext
    block_families: dict[str, frozenset[str]]
    code_facts: Optional[CodeFacts]        # None => XML unparseable
    full_sim: Optional[SimulationResult]
    scored_sim: Optional[SimulationResult]  # §6a-truncated; == full_sim when no boundary exit
    playground_params: Optional[dict]
    boundary_exceeded: bool
    boundary_exit_step: Optional[int]
    # Task-3 Part B: "execute" (B1) | "suppress" (B2) | "abstain" (B3)
    conditional_hat_treatment: str = "execute"
    # Why the sim channel is unavailable when full_sim/scored_sim is None —
    # "no_simulation" (default), or a specific rejection like
    # switch_syntax_error (reviewer ruling 2026-08-24: invalid Switch text
    # makes VEX reject the WHOLE program; no code executes at all).
    sim_unavailable_reason: str = "no_simulation"


@dataclass
class IndicatorResult:
    value: float | bool | str | None       # the contract's continuous value
    raw: Any = None                        # what RungSpec.evaluate bins (often == value)
    channel: str = "simulation"
    flags: list[str] = field(default_factory=list)
    abstained: bool = False
    abstain_reason: str | None = None


def _abstain(channel: str, reason: str) -> IndicatorResult:
    return IndicatorResult(None, None, channel, abstained=True, abstain_reason=reason)


def _distance(x0: float, y0: float, x1: float, y1: float) -> float:
    return math.hypot(x1 - x0, y1 - y0)


def _segment_closest(ax: float, ay: float, bx: float, by: float,
                     px: float, py: float) -> tuple[float, float, float]:
    """Closest approach of segment a->b to point p: (distance, cx, cy).

    The robot occupies every point of the segment, not just its endpoints —
    waypoint-only sampling misses close passes that happen mid-drive
    (C031 falsification, 2026-08-19)."""
    dx, dy = bx - ax, by - ay
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq == 0.0:
        return _distance(ax, ay, px, py), ax, ay
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg_len_sq))
    cx, cy = ax + t * dx, ay + t * dy
    return _distance(cx, cy, px, py), cx, cy


def _polyline_min_distance(points: list[tuple[float, float]],
                           px: float, py: float) -> float:
    """Continuous minimum distance from a polyline to a point."""
    if not points:
        return math.inf
    best = _distance(points[0][0], points[0][1], px, py)
    for (ax, ay), (bx, by) in zip(points, points[1:]):
        d, _, _ = _segment_closest(ax, ay, bx, by, px, py)
        best = min(best, d)
    return best


def min_distance_to_object(ctx: EvalContext, binding: dict) -> IndicatorResult:
    sim = ctx.scored_sim
    if sim is None:
        return _abstain("simulation", ctx.sim_unavailable_reason)
    obj = ctx.context.objects[binding["object"]]
    # Origin seeding (spec §3) falls out naturally: the polyline starts at
    # origin_x/origin_y, the state before the first block.
    pts = [(sim.origin_x, sim.origin_y)] + [(ps.x, ps.y) for ps in sim.path]
    d = _polyline_min_distance(pts, obj.x, obj.y)
    # The vendored waypoint minimum can only agree or be larger; kept as a
    # belt-and-braces floor in case it ever samples positions we don't see.
    d = min(d, sim.min_distance_to_objects.get(binding["object"], math.inf))
    return IndicatorResult(value=d, raw=d, channel="simulation")


def region_coverage(ctx: EvalContext, binding: dict) -> IndicatorResult:
    sim = ctx.scored_sim
    if sim is None:
        return _abstain("simulation", ctx.sim_unavailable_reason)
    frac = sim.region_coverage_fractions.get(binding["region"], 0.0)
    return IndicatorResult(value=frac, raw=frac, channel="simulation")


def state_active_within_radius(ctx: EvalContext, binding: dict) -> IndicatorResult:
    sim = ctx.scored_sim
    if sim is None:
        return _abstain("simulation", ctx.sim_unavailable_reason)
    accessor = _STATE_ACTIVE_FROM_STEP.get(binding["state"])
    if accessor is None:
        return _abstain("simulation", "unknown_simulator_state")
    active_from = accessor(sim)
    if active_from is None:
        # State never activated within scoring scope — meaningful absence
        # (rung comes from the card's absent_label), not an abstention.
        return IndicatorResult(value=None, raw=None, channel="simulation")

    obj = ctx.context.objects[binding["object"]]
    radius = float(obj.tolerance)
    active_pts = [ps for ps in sim.path if ps.step >= active_from]
    if not active_pts:
        return IndicatorResult(value=None, raw=None, channel="simulation")

    # Continuous sampling: the robot occupies every point of each active
    # segment, so both the minimum distance and the zone-qualifying positions
    # are evaluated along segments, not just at waypoints (C031, 2026-08-19).
    min_d = math.inf
    qualifying: list = []

    def _note(x: float, y: float) -> None:
        if _distance(x, y, obj.x, obj.y) <= radius:
            qualifying.append(SimpleNamespace(x=x, y=y))

    first = active_pts[0]
    min_d = min(min_d, _distance(first.x, first.y, obj.x, obj.y))
    _note(first.x, first.y)
    for a, b in zip(active_pts, active_pts[1:]):
        d, cx, cy = _segment_closest(a.x, a.y, b.x, b.y, obj.x, obj.y)
        min_d = min(min_d, d)
        if d <= radius:
            # Sample the qualifying stretch: entry into the radius circle,
            # closest approach, and exit (clamped to the segment) — real robot
            # positions, ordered along the path, so zone precedence sees the
            # whole traversed band rather than segment endpoints.
            for x, y in _radius_crossings(a, b, obj.x, obj.y, radius):
                _note(x, y)
            _note(cx, cy)
            _note(b.x, b.y)

    flags: list[str] = []
    if qualifying and "zones_ref" in binding:
        flag = _zone_flag(ctx.card, binding, qualifying)
        if flag:
            flags.append(flag)
    return IndicatorResult(value=min_d, raw=min_d, channel="simulation", flags=flags)


def _radius_crossings(a, b, px: float, py: float,
                      radius: float) -> list[tuple[float, float]]:
    """Points where segment a->b crosses the circle (px, py, radius),
    clamped to the segment, in path order."""
    dx, dy = b.x - a.x, b.y - a.y
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq == 0.0:
        return []
    fx, fy = a.x - px, a.y - py
    qa, qb = seg_len_sq, 2.0 * (fx * dx + fy * dy)
    qc = fx * fx + fy * fy - radius * radius
    disc = qb * qb - 4.0 * qa * qc
    if disc < 0.0:
        return []
    root = math.sqrt(disc)
    out = []
    for t in ((-qb - root) / (2.0 * qa), (-qb + root) / (2.0 * qa)):
        if 0.0 <= t <= 1.0:
            out.append((a.x + t * dx, a.y + t * dy))
    return out


def _zone_match(card: dict, binding: dict, step: PathStep) -> str | None:
    """The card-declared zone a step's zone_axis coordinate falls in, or None.

    Zones are matched in card order with missing bounds open (±inf), bounds
    inclusive, first match wins.
    """
    zones = resolve_reference(binding["zones_ref"], binding, card)
    axis = binding.get("zone_axis", "y")
    coord = getattr(step, axis)
    for zone_name, zone in zones.items():
        lo = zone.get(f"{axis}_min", -math.inf)
        hi = zone.get(f"{axis}_max", math.inf)
        if lo <= coord <= hi:
            return zone_name
    return None


def _zone_step_flag(card: dict, binding: dict, step: PathStep) -> str | None:
    """This single step's zone outcome: the matched zone's flag, the
    unmatched_flag, or None for a described zone that maps to no flag."""
    matched = _zone_match(card, binding, step)
    if matched is not None and matched not in binding.get("zone_flags", {}):
        return None
    return binding.get("zone_flags", {}).get(matched) if matched \
        else binding.get("unmatched_flag")


def _zone_flag(card: dict, binding: dict, steps: list[PathStep]) -> str | None:
    """Across qualifying steps, precedence: if ANY step lands in a described
    zone that maps to no flag, engagement is plausible — no flag, regardless of
    where the trajectory started. Otherwise the first qualifying step's outcome
    stands: its zone's flag, or the binding's unmatched_flag when it matched no
    zone."""
    zone_flags = binding.get("zone_flags", {})
    first_flag: str | None = None
    for i, ps in enumerate(steps):
        matched = _zone_match(card, binding, ps)
        if matched is not None and matched not in zone_flags:
            return None
        if i == 0:
            first_flag = zone_flags.get(matched) if matched \
                else binding.get("unmatched_flag")
    return first_flag


def code_state_authored(ctx: EvalContext, binding: dict) -> IndicatorResult:
    if ctx.code_facts is None:
        return _abstain("code", "no_code")
    fam = binding["block_family"]
    if ctx.code_facts.family_counts.get(fam, 0) == 0:
        return IndicatorResult(value=None, raw=None, channel="code")
    values = ctx.code_facts.family_field_values.get(fam, frozenset())
    return IndicatorResult(value="|".join(sorted(values)), raw=values, channel="code")


def code_movement_authored(ctx: EvalContext, binding: dict) -> IndicatorResult:
    if ctx.code_facts is None:
        return _abstain("code", "no_code")
    count = ctx.code_facts.family_counts.get(binding["block_family"], 0)
    return IndicatorResult(value=count, raw=count, channel="code")


def displacement_from_spawn(ctx: EvalContext, binding: dict) -> IndicatorResult:
    source = binding.get("source", "outcome")
    if source == "outcome":
        params = ctx.playground_params or {}
        xf, yf = binding.get("x_field"), binding.get("y_field")
        if params.get(xf) is not None and params.get(yf) is not None:
            try:
                px, py = float(params[xf]), float(params[yf])
            except (TypeError, ValueError, OverflowError):
                return _abstain("outcome", "outcome_field_invalid")
            if not all(math.isfinite(v) for v in (px, py)):
                return _abstain("outcome", "outcome_field_invalid")
            d = _distance(ctx.context.spawn_x, ctx.context.spawn_y, px, py)
            return IndicatorResult(value=d, raw=d, channel="outcome")
        # Real-run position unavailable — fall back to simulated net displacement.
        if ctx.scored_sim is not None:
            d = ctx.scored_sim.net_displacement_from_spawn
            return IndicatorResult(value=d, raw=d, channel="simulation",
                                   flags=["simulated_fallback", "simulated_attainment"])
        return _abstain("simulation", ctx.sim_unavailable_reason)
    if ctx.scored_sim is None:
        return _abstain("simulation", ctx.sim_unavailable_reason)
    d = ctx.scored_sim.net_displacement_from_spawn
    return IndicatorResult(value=d, raw=d, channel="simulation")


def outcome_field(ctx: EvalContext, binding: dict) -> IndicatorResult:
    params = ctx.playground_params
    name = binding["field"]
    if not params or params.get(name) is None:
        return _abstain("outcome", "outcome_field_absent")
    try:
        value = float(params[name])
    except (TypeError, ValueError, OverflowError):
        return _abstain("outcome", "outcome_field_invalid")
    if not math.isfinite(value):
        return _abstain("outcome", "outcome_field_invalid")
    return IndicatorResult(value=value, raw=value, channel="outcome")


def boundary_exceeded(ctx: EvalContext, binding: dict) -> IndicatorResult:
    if ctx.full_sim is None:
        return _abstain("simulation", ctx.sim_unavailable_reason)
    return IndicatorResult(value=ctx.boundary_exceeded, raw=ctx.boundary_exceeded,
                           channel="simulation")


def outcome_on_island(ctx: EvalContext, binding: dict) -> IndicatorResult:
    """remain_on_island, observed side: the run's final GPS tested against the
    island boundary polygon (any-part-on-island tolerance, both from the
    playground card). Abstains when the run has no GPS — the sim-side
    indicator fills those cases at lower certainty."""
    from .profile import _fall_off_tolerance, _on_island   # lazy: avoids cycle
    params = ctx.playground_params or {}
    gx, gy = params.get(binding.get("x_field")), params.get(binding.get("y_field"))
    if gx is None or gy is None:
        return _abstain("outcome", "gps_unavailable")
    try:
        gx, gy = float(gx), float(gy)
    except (TypeError, ValueError, OverflowError):
        return _abstain("outcome", "gps_unavailable")
    if not all(math.isfinite(v) for v in (gx, gy)):
        return _abstain("outcome", "gps_invalid")
    polygon = (ctx.card.get("field_boundary") or {}).get("polygon_mm")
    if not polygon:
        return _abstain("outcome", "island_boundary_undeclared")
    on = _on_island(gx, gy, polygon, _fall_off_tolerance(ctx.card))
    value = "on_island" if on else "off_island"
    return IndicatorResult(value=value, raw=value, channel="outcome")


def sim_on_island(ctx: EvalContext, binding: dict) -> IndicatorResult:
    """remain_on_island, simulation side (§6a rule): a simulated boundary exit
    means the run ended off the island — everything after the exit is
    fiction. Simulation-channel evidence: stands in for missing observation
    at lower certainty."""
    if ctx.full_sim is None:
        return _abstain("simulation", ctx.sim_unavailable_reason)
    value = "off_island" if ctx.boundary_exceeded else "on_island"
    return IndicatorResult(value=value, raw=value, channel="simulation")


def _point_rect_dist(px: float, py: float, rect: tuple) -> float:
    x0, x1, y0, y1 = rect
    dx = max(x0 - px, 0.0, px - x1)
    dy = max(y0 - py, 0.0, py - y1)
    return math.hypot(dx, dy)


def _seg_seg_dist(ax, ay, bx, by, cx, cy, dx, dy) -> float:
    def orient(px, py, qx, qy, rx, ry):
        return (qx - px) * (ry - py) - (qy - py) * (rx - px)
    o1 = orient(ax, ay, bx, by, cx, cy)
    o2 = orient(ax, ay, bx, by, dx, dy)
    o3 = orient(cx, cy, dx, dy, ax, ay)
    o4 = orient(cx, cy, dx, dy, bx, by)
    if ((o1 > 0) != (o2 > 0)) and ((o3 > 0) != (o4 > 0)):
        return 0.0   # proper intersection
    return min(_segment_closest(ax, ay, bx, by, cx, cy)[0],
               _segment_closest(ax, ay, bx, by, dx, dy)[0],
               _segment_closest(cx, cy, dx, dy, ax, ay)[0],
               _segment_closest(cx, cy, dx, dy, bx, by)[0])


def _seg_rect_dist(ax, ay, bx, by, rect: tuple) -> float:
    x0, x1, y0, y1 = rect
    for px, py in ((ax, ay), (bx, by)):
        if x0 <= px <= x1 and y0 <= py <= y1:
            return 0.0
    corners = ((x0, y0), (x1, y0), (x1, y1), (x0, y1))
    return min(_seg_seg_dist(ax, ay, bx, by, corners[i][0], corners[i][1],
                             corners[(i + 1) % 4][0], corners[(i + 1) % 4][1])
               for i in range(4))


def _attachment_structures(card: dict, object_name: str):
    """Parse the card's attachment block: [(kind, geometry, gap_mm)] or None."""
    spec = ((card.get("objects") or {}).get(object_name) or {}).get("attachment")
    if not isinstance(spec, dict):
        return None
    out = []
    for entry in (spec.get("structures") or {}).values():
        gap = float(entry["attach_gap_mm"])
        if "rect_mm" in entry:
            r = entry["rect_mm"]
            cx, cy = float(r["center"][0]), float(r["center"][1])
            hw, hh = float(r["width"]) / 2.0, float(r["height"]) / 2.0
            out.append(("rect", (cx - hw, cx + hw, cy - hh, cy + hh), gap))
        elif "point_mm" in entry:
            out.append(("point", (float(entry["point_mm"][0]),
                                  float(entry["point_mm"][1])), gap))
    return out or None


def _magnet_pose_margin(x, y, heading_deg, structures, mount) -> float:
    """Clearance margin (min over structures of distance - gap) for one pose."""
    h = math.radians(heading_deg)
    mx, my = x + mount * math.cos(h), y + mount * math.sin(h)
    return min((_point_rect_dist(mx, my, geo) if kind == "rect"
                else _distance(mx, my, geo[0], geo[1])) - gap
               for kind, geo, gap in structures)


def _magnet_pair_margin(a, b, structures, mount) -> float:
    """Clearance margin over the magnet's travel from pose a to pose b:
    the shifted segment for a drive, the swept arc for an in-place turn
    (net sweep normalized to (-180, 180] — multi-revolution turns collapse;
    acceptable, such programs revisit their poses driving)."""
    if (a.x, a.y) != (b.x, b.y):
        h = math.radians(b.heading)
        ux, uy = math.cos(h), math.sin(h)
        return min((_seg_rect_dist(a.x + mount * ux, a.y + mount * uy,
                                   b.x + mount * ux, b.y + mount * uy, geo)
                    if kind == "rect" else
                    _segment_closest(a.x + mount * ux, a.y + mount * uy,
                                     b.x + mount * ux, b.y + mount * uy,
                                     geo[0], geo[1])[0]) - gap
                   for kind, geo, gap in structures)
    if a.heading == b.heading:
        return _magnet_pose_margin(b.x, b.y, b.heading, structures, mount)
    delta = (b.heading - a.heading + 180.0) % 360.0 - 180.0
    n = max(2, int(abs(delta) // 3) + 1)
    return min(_magnet_pose_margin(b.x, b.y, a.heading + delta * i / n,
                                   structures, mount)
               for i in range(n + 1))


def state_active_attachment_clearance(ctx: EvalContext, binding: dict) -> IndicatorResult:
    """Near-contact attachment estimate (OI-21 probe series, 2026-08-21).

    Value: minimum clearance (mm) of the MAGNET POINT beyond the card's
    structure attach gaps, over the state-active portion of the path;
    <= 0 estimates attachment. The magnet point leads the robot centre by
    the robot card's magnet mount offset — attachment is front-gated (rear
    robot contact does not attach: probe M3), so drives evaluate the shifted
    segment and in-place turns evaluate the swept magnet arc (probe M3b:
    the swing IS what attaches). Turn sweeps are normalized to (-180, 180]:
    a net-sweep approximation that under-covers multi-revolution turns
    (acceptable — such programs revisit the same poses driving).
    """
    sim = ctx.scored_sim
    if sim is None:
        return _abstain("simulation", ctx.sim_unavailable_reason)
    accessor = _STATE_ACTIVE_FROM_STEP.get(binding["state"])
    if accessor is None:
        return _abstain("simulation", "unknown_simulator_state")
    active_from = accessor(sim)
    if active_from is None:
        return IndicatorResult(value=None, raw=None, channel="simulation")
    structures = _attachment_structures(ctx.card, binding["object"])
    if structures is None:
        return _abstain("simulation", "no_attachment_model")
    mount = float((ctx.context.sensor_specs.get("magnet") or {})
                  .get("mount_forward_mm") or 0.0)
    pts = [ps for ps in sim.path if ps.step >= active_from]
    if not pts:
        return IndicatorResult(value=None, raw=None, channel="simulation")

    first = pts[0]
    margin = _magnet_pose_margin(first.x, first.y, first.heading,
                                 structures, mount)
    for a, b in zip(pts, pts[1:]):
        margin = min(margin, _magnet_pair_margin(a, b, structures, mount))

    flags: list[str] = []
    band = float((((ctx.card.get("objects") or {}).get(binding["object"]) or {})
                  .get("attachment") or {}).get("marginal_band_mm") or 0.0)
    if band and abs(margin) <= band:
        flags.append("attachment_boundary_marginal")
    return IndicatorResult(value=margin, raw=margin,
                           channel="simulation", flags=flags)


REGISTRY: dict[str, Callable[[EvalContext, dict], IndicatorResult]] = {
    "min_distance_to_object": min_distance_to_object,
    "region_coverage": region_coverage,
    "state_active_within_radius": state_active_within_radius,
    "state_active_attachment_clearance": state_active_attachment_clearance,
    "code_state_authored": code_state_authored,
    "code_movement_authored": code_movement_authored,
    "outcome_on_island": outcome_on_island,
    "sim_on_island": sim_on_island,
    "displacement_from_spawn": displacement_from_spawn,
    "outcome_field": outcome_field,
    "boundary_exceeded": boundary_exceeded,
}
