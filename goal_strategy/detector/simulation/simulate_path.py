"""Simulate robot movement from a BlockProgram to produce a path trace.

VENDORING STATUS — no longer byte-identical to VEX_model_tracing (task 3,
2026-08-18). This file carries the hat-stack execution-fidelity changes
(AGENT_TASK_hat_execution_fidelity.md): Part A inline broadcast execution
(path-changing, attribution-reported), Part B conditional-hat treatment behind
the `conditional_hats` parameter (default preserves status quo), Parts C/D
additive flags (`execution_flags`, `fabricated_steps`); plus the continuous
drive/turn preemption semantics (reviewer decision 2026-08-18, path-changing,
attribution-reported): a bare continuous block arms pending motion that
persists until the next DRIVETRAIN command clears it — a later `wait` converts
it to velocity × time, instant blocks pass through, and unconsumed pending
means zero elapsed time and zero motion; the 200mm/90° fallback applies to
trailing bare blocks only. Sensing build Phase 1 (2026-08-19, path-changing,
attribution-reported): optical color checks read the corpus COLORS field,
evaluate at the per-eye eye point (offsets from the shared robot card via
from_playground_card's robot_card param / PlaygroundContext.sensor_specs),
and match card color_zones with per-eye applicability and ring bands (the
red boundary ring is a down-eye band zone); the down eye is floor-tuned for
near_object (3D bodies only, via ObjectRef.body_radius_mm and card pieces);
wait_until is the ratified OI-3 gate — no self-motion, pending motion marches
to the condition (real velocity-held move) and an unmet condition gates the
stack (_GateSignal, flag wait_until_unmet; legacy 50mm probes retired).
Every other file under vendor/ remains byte-identical to its source.

The simulator is playground-agnostic.  All field geometry, object positions,
and region bounds are supplied via PlaygroundContext, which is constructed from
a playground YAML card by PlaygroundContext.from_playground_card().

The simulator produces raw geometric observations:
  - path: full list of PathStep positions
  - min_distance_to_objects: per-object minimum approach distance
  - first_object_tolerance_steps: per-object first step within tolerance
  - region_coverage_fractions: per-region coverage estimate
  - magnet_fires_at_step: step when magnet boost first fired (VEX-specific observable)

Goal-specific derived metrics (axis progress toward a target, monotonicity,
magnet-before-plow ordering) are computed by the goal scorer using the raw path
and the PlaygroundContext — not here.  Use compute_axis_progress_metrics() for that.

Heading convention (internal, math convention):
  0°   = positive X (East)
  90°  = positive Y (North)
  180° = negative X (West)   ← robot's default facing direction at spawn (card heading 0)
  270° = negative Y (South)
  turn right = clockwise = heading decreases
  turn left  = counter-clockwise = heading increases

Playground cards store headings in VEX convention (0 = negative X / West).
Verified by GPS probing: FORWARD at heading 0 decreases x by the drive distance.
PlaygroundContext.from_playground_card() converts to math convention on load
using math_heading = (180 - card_heading) % 360.
"""

from __future__ import annotations

import copy as _copy
import functools
import math
import random
from dataclasses import dataclass, field
from typing import Optional, Any


# ------------------------------------------------------------------ #
# Heading conversion — ONE definition, used by every caller
# ------------------------------------------------------------------ #

def card_heading_to_math(card_heading: float) -> float:
    """Convert a VEX/card heading to the simulator's math convention.

        VEX/card convention:  0 deg = negative X (West) — verified by GPS probing
        Math convention:      0 deg = positive X (East), counter-clockwise positive

    Every place that turns a card heading into a simulator heading must call
    this.  It exists because two call sites previously rolled their own and
    disagreed by exactly 90 degrees: the spawn used (180 - h) while
    `turn_to_heading` used (90 - h), the standard compass formula.  This
    playground's heading 0 is NOT compass North — the playground card records
    "Heading 0 faces negative X (toward field center), not positive Y" and marks
    it verified — so the compass formula was wrong, and a `turn to heading`
    block rotated the robot 90 degrees away from where the student aimed it.
    """
    return (180.0 - card_heading) % 360.0


def _clamp_percent(value: float) -> float:
    """Clamp a VEX velocity percentage to the 0-100 range the hardware accepts.

    Student programs in the sample carry `inf` and 123456789 here.  VEX itself
    caps velocity at 100%, so clamping is what the real robot does — and it
    keeps `inf` out of simulator state, where it would turn into NaN on any
    zero-length wait.
    """
    if value != value:          # NaN
        return 50.0
    return max(0.0, min(100.0, value))


# ------------------------------------------------------------------ #
# Simulator control-flow signals
# ------------------------------------------------------------------ #

class _BreakSignal(Exception):
    """Raised by pg_control_break to exit the enclosing loop."""

class _StopSignal(Exception):
    """Raised by pg_control_stop_project to terminate the entire simulation."""

class _BudgetSignal(_StopSignal):
    """Raised when the global execution budget is exhausted (Stage-1
    validation campaign, 2026-08-21): students nest loops up to depth 47 in
    the wild, and multiplicative loop unrolling makes such programs
    unsimulatable without a bound. Halts like stop_project (no runoff) after
    flagging execution_budget_exhausted — the capped-run lane, not an error."""

class _HatRestartSignal(Exception):
    """Raised mid-hat-stack when the hat's own detection condition sees a
    NEW false->true edge (reviewer probe 2026-08-24: the real runtime
    RESTARTS the hat's behavior on a new detection while it is running —
    the current block is abandoned and the script re-runs from the top)."""

class _CondUnmet(Exception):
    """VR-Seq (Stage 2): thrown INTO a parked wait_until generator by the
    Sequencer when no live thread or motion can ever satisfy its condition —
    the branch then runs the legacy unmet path (fabricate + flag + gate)."""


class _Park:
    """VR-Seq (Stage 2): a park request yielded by a cooperative-mode block
    to the Sequencer. kind: 'motion' (blocking *_for; mode/sign/magnitude),
    'time' (wait; seconds), 'cond' (wait_until; the block re-evaluates at
    slice boundaries)."""
    __slots__ = ("kind", "mode", "sign", "magnitude", "block", "seconds")

    def __init__(self, kind, block, mode=None, sign=0.0, magnitude=0.0,
                 seconds=0.0):
        self.kind = kind
        self.block = block
        self.mode = mode
        self.sign = sign
        self.magnitude = magnitude
        self.seconds = seconds


class _GateSignal(Exception):
    """Raised by an unmet wait_until (ratified OI-3 semantics, 2026-08-19):
    the condition never turns true, so the code below the gate never executes.
    Halts the enclosing hat stack only — caught at the top-level dispatch and
    at the inline-broadcast site (a gated receiver stalls without stalling
    its broadcaster, approximating their real parallelism)."""


# ------------------------------------------------------------------ #
# Playground context (loaded from card)
# ------------------------------------------------------------------ #

@dataclass
class RegionBounds:
    """Region boundary for simulation tracking.

    Supports two modes:
    - AABB (default): uses x_min/x_max/y_min/y_max. Simple and fast.
    - Polygon: when polygon_vertices is set, contains() and total_grid_cells
      use the convex polygon instead. x_min/x_max/y_min/y_max serve as the
      bounding box (required for from_playground_card and slice_sim_result).
    """
    region_id: str
    x_min: float
    x_max: float
    y_min: float
    y_max: float
    # Card-driven (reviewer physics, 2026-08-24): entering this region
    # disturbs the movable world — physics scatters pieces unpredictably,
    # so subsequent sensor evaluations (and unfired-hat predictions) are
    # conditional even without a modeled contact.
    disturbs_world: bool = False
    # Ordered (x, y) mm vertices of a convex polygon boundary.
    # When present, supersedes AABB for contains() and total_grid_cells.
    polygon_vertices: list[tuple[float, float]] | None = None

    def contains(self, x: float, y: float) -> bool:
        if self.polygon_vertices:
            # Quick AABB pre-reject before the polygon test
            if not (self.x_min <= x <= self.x_max and self.y_min <= y <= self.y_max):
                return False
            return _point_in_convex_polygon(x, y, self.polygon_vertices)
        return self.x_min <= x <= self.x_max and self.y_min <= y <= self.y_max

    @property
    def total_grid_cells(self) -> int:
        """Number of 100mm grid cells whose centre falls inside this region."""
        if self.polygon_vertices:
            return _count_polygon_grid_cells(
                self.polygon_vertices, self.x_min, self.x_max, self.y_min, self.y_max
            )
        return (
            int((self.x_max - self.x_min) / _COVERAGE_GRID_CELL_MM)
            * int((self.y_max - self.y_min) / _COVERAGE_GRID_CELL_MM)
        )


@dataclass
class ObjectRef:
    """A named navigational landmark or target object on the field."""
    object_id: str
    x: float
    y: float
    tolerance: float          # proximity radius that counts as "reached" (used in scoring)
    segmentation_radius: float = 0.0  # wider radius for phase-boundary detection only; 0 = use tolerance
    # Taxonomy fields (loaded from YAML objects.{id}.object_type / .movable)
    object_type: str = "unspecified"   # tool | target | obstacle | unspecified
    movable: bool | None = None        # True = dynamic rigid body; False = fixed; None = unspecified
    navigation_target: bool = False    # True = primary object strategies should navigate toward
    # Sensing (Phase-1 sensing build, 2026-08-19): physical 3D extent for
    # eye/distance/bumper detection — distinct from the semantic tolerance —
    # and the front-eye-detectable color. None = not detectable / unknown.
    body_radius_mm: float | None = None
    color: str | None = None
    # Late materialization (testcase harness Option A, reviewer-approved
    # 2026-08-19): the piece does not exist for sensors/contact/push until
    # this step; a relative spec places it at activation time relative to
    # the robot's pose then (ahead along heading rotated by bearing, CCW+).
    # Inert in the main sim (defaults: active from step 0, absolute x/y).
    active_from_step: int = 0
    rel_ahead_mm: float | None = None
    rel_bearing_deg: float = 0.0


@dataclass
class ColorZone:
    """A named floor color zone on the field.

    Either a filled polygon (polygon_vertices) or a ring band (band_inner/
    band_outer: inside the outer polygon AND NOT inside the inner one).
    `eye` restricts the zone to one eye ("down" | "front"); None = any eye —
    the 2D red boundary ring is down-eye-only (reviewer 2026-08-19)."""
    color: str                                         # e.g. "red", "green"
    polygon_vertices: list[tuple[float, float]] | None = None  # ordered (x, y) mm vertices
    description: str = ""
    eye: str | None = None
    band_inner_vertices: list[tuple[float, float]] | None = None
    band_outer_vertices: list[tuple[float, float]] | None = None
    # Reviewer ruling 2026-08-19: some floor markings are defined OBJECTS in
    # the space (the red boundary line) — near_object fires over them; the
    # floor itself and the ocean are not objects (floor stays color-detectable).
    registers_as_object: bool = False


@dataclass
class PlaygroundContext:
    """All geometry needed to simulate a program on a specific playground.

    Constructed from a playground YAML card via from_playground_card().
    Uses math convention for headings (0 = East / positive X).
    """
    spawn_x: float
    spawn_y: float
    spawn_heading: float          # math convention: 90 = North / positive Y
    field_radius: float           # inscribed-circle radius fallback; superseded by field_hex_vertices
    objects: dict[str, ObjectRef]   # {object_id: ObjectRef}
    regions: dict[str, RegionBounds]  # {region_id: RegionBounds}
    robot_width_mm: float = 50.8  # physical robot width — used for footprint-aware coverage
    # Ordered (x, y) mm vertices of the playable boundary polygon (inner edge of red ring).
    # When present, boundary checking uses point-in-polygon instead of the circular fallback.
    field_hex_vertices: list[tuple[float, float]] | None = None
    # Color the eye sensor detects at the field boundary (polygon edge → outside)
    field_boundary_color: str = "red"
    # Additional named floor color zones (loaded from YAML color_zones section)
    color_zones: list[ColorZone] = field(default_factory=list)
    # Sensing build (2026-08-19): robot sensor hardware specs, from the shared
    # robot card's sensors: section (configs/robot/). Empty dict = no specs —
    # sensor geometry falls back to robot-centre evaluation.
    sensor_specs: dict = field(default_factory=dict)
    # Individual detectable pieces (e.g. castle blocks) parsed from
    # objects.{id}.pieces — sensor targets only; deliberately NOT merged into
    # `objects`, so proximity metrics and PathStep.objects_in_tolerance are
    # unchanged by their presence.
    pieces: list[ObjectRef] = field(default_factory=list)
    # Global execution budget override (0 = the module default; Stage-1
    # validation campaign 2026-08-21, card key simulation.execution_budget_blocks).
    execution_budget_blocks: int = 0
    # Test-case harness switch (sensing Phase 5, 2026-08-19). EMPTY in normal
    # operation — main-sim behaviour is byte-identical without it (the
    # identity fixture proves it). Scenario cards may set:
    #   push_model: kinematic  — contacted pieces slide ahead of the robot
    #                            and disappear off the island edge
    #   loop_unroll: N         — raises the forever/repeat caps so looping
    #                            clearers can finish the job under test
    testcase_physics: dict = field(default_factory=dict)

    @classmethod
    def from_playground_card(cls, card: dict[str, Any],
                             robot_card: dict[str, Any] | None = None,
                             ) -> "PlaygroundContext":
        """Build a PlaygroundContext from a loaded playground YAML card dict.

        Heading conversion:
          VEX/card convention:  0° = negative X (West) — verified by GPS probing
          Math convention:      0° = positive X (East)
          Conversion:           math_heading = (180 - card_heading) % 360
          So card heading 0 → math heading 180 (facing negative X = West).
          Right turn (clockwise, heading decreases) from 180° → 90° = positive Y (North).
          Verified: drive FORWARD 200mm at heading 0 → x decreases by 200.
        """
        # Spawn point
        spawn = card.get("spawn_points", {}).get("default_start", {})
        spawn_x = float(spawn.get("x", 0))
        spawn_y = float(spawn.get("y", 0))
        card_heading = float(spawn.get("heading", 0))
        spawn_heading = card_heading_to_math(card_heading)

        # Field radius
        geom = card.get("field_geometry", {})
        field_radius = float(
            geom.get("playable_radius_mm")
            or geom.get("radius_mm")
            or geom.get("diameter_mm", 0) / 2
        )

        # Named objects
        objects: dict[str, ObjectRef] = {}
        pieces: list[ObjectRef] = []
        for obj_id, obj_data in card.get("objects", {}).items():
            if not isinstance(obj_data, dict):
                continue
            x = obj_data.get("x")
            y = obj_data.get("y")
            if x is None or y is None:
                continue   # skip objects without explicit position
            objects[obj_id] = ObjectRef(
                object_id=obj_id,
                x=float(x),
                y=float(y),
                tolerance=float(obj_data.get("tolerance", 100)),
                segmentation_radius=float(obj_data.get("segmentation_radius", 0)),
                object_type=str(obj_data.get("object_type", "unspecified")),
                movable=obj_data.get("movable"),  # None if absent
                navigation_target=bool(obj_data.get("navigation_target", False)),
                body_radius_mm=(float(obj_data["body_radius_mm"])
                                if obj_data.get("body_radius_mm") is not None else None),
                color=(str(obj_data["color"]).lower()
                       if obj_data.get("color") else None),
            )
            # Individual detectable pieces (sensing build 2026-08-19) — sensor
            # targets only, never merged into `objects` (see PlaygroundContext).
            for piece_id, piece in (obj_data.get("pieces") or {}).items():
                if not isinstance(piece, dict):
                    continue
                px, py = piece.get("x"), piece.get("y")
                rel = piece.get("relative") or {}
                if (px is None or py is None) and not rel:
                    continue
                pieces.append(ObjectRef(
                    object_id=f"{obj_id}.{piece_id}",
                    x=float(px if px is not None else 0.0),
                    y=float(py if py is not None else 0.0),
                    tolerance=float(piece.get("body_radius_mm", 0) or 0),
                    object_type="piece",
                    movable=obj_data.get("movable"),
                    body_radius_mm=(float(piece["body_radius_mm"])
                                    if piece.get("body_radius_mm") is not None else None),
                    color=(str(piece["color"]).lower() if piece.get("color") else None),
                    active_from_step=int(piece.get("active_from_step", 0) or 0),
                    rel_ahead_mm=(float(rel["ahead_mm"])
                                  if rel.get("ahead_mm") is not None else None),
                    rel_bearing_deg=float(rel.get("bearing_deg", 0.0) or 0.0),
                ))

        # Named regions
        regions: dict[str, RegionBounds] = {}
        for region_id, region_data in card.get("regions", {}).items():
            if not isinstance(region_data, dict):
                continue
            x_min = region_data.get("x_min")
            x_max = region_data.get("x_max")
            y_min = region_data.get("y_min")
            y_max = region_data.get("y_max")
            if any(v is None for v in (x_min, x_max, y_min, y_max)):
                continue
            polygon_vertices = None
            raw_poly = region_data.get("polygon_mm")
            if isinstance(raw_poly, list) and len(raw_poly) >= 3:
                try:
                    polygon_vertices = [(float(v[0]), float(v[1])) for v in raw_poly]
                except (TypeError, IndexError):
                    polygon_vertices = None
            regions[region_id] = RegionBounds(
                region_id=region_id,
                x_min=float(x_min),
                x_max=float(x_max),
                y_min=float(y_min),
                y_max=float(y_max),
                disturbs_world=bool(region_data.get("disturbs_world")),
                polygon_vertices=polygon_vertices,
            )

        robot = card.get("robot", {})
        robot_width_mm = float(robot.get("width_mm", 50.8))

        # Field boundary polygon (inner edge of red ring — where down_eye fires).
        # Preferred: explicit field_boundary.polygon_mm section.
        # Fallback: legacy visualization_geometry.island.inner_hex_vertices_mm dict.
        _HEX_VERTEX_ORDER = ["top", "top_right", "bottom_right", "bottom", "bottom_left", "top_left"]
        field_hex_vertices = None
        field_boundary_color = "red"

        fb = card.get("field_boundary")
        if isinstance(fb, dict):
            field_boundary_color = str(fb.get("color", "red"))
            raw_poly = fb.get("polygon_mm")
            if isinstance(raw_poly, list) and len(raw_poly) >= 3:
                try:
                    field_hex_vertices = [(float(v[0]), float(v[1])) for v in raw_poly]
                    if len(field_hex_vertices) < 3:
                        field_hex_vertices = None
                except (TypeError, IndexError):
                    field_hex_vertices = None

        if field_hex_vertices is None:
            # Legacy fallback: dict-style inner hex vertices
            try:
                inner_verts = (
                    card.get("visualization_geometry", {})
                        .get("island", {})
                        .get("inner_hex_vertices_mm")
                )
                if isinstance(inner_verts, dict):
                    field_hex_vertices = [
                        (float(inner_verts[k][0]), float(inner_verts[k][1]))
                        for k in _HEX_VERTEX_ORDER if k in inner_verts
                    ]
                    if len(field_hex_vertices) < 3:
                        field_hex_vertices = None
            except (TypeError, KeyError, IndexError):
                field_hex_vertices = None

        # Color zones (floor colors) — filled polygon or ring band, optionally
        # restricted to one eye (sensing build 2026-08-19).
        def _verts(raw):
            if isinstance(raw, list) and len(raw) >= 3:
                try:
                    return [(float(v[0]), float(v[1])) for v in raw]
                except (TypeError, IndexError):
                    return None
            return None

        color_zones: list[ColorZone] = []
        for zone_data in card.get("color_zones", []):
            if not isinstance(zone_data, dict):
                continue
            color = str(zone_data.get("color", "")).lower()
            if not color:
                continue
            band = zone_data.get("between") or {}
            color_zones.append(ColorZone(
                color=color,
                polygon_vertices=_verts(zone_data.get("polygon_mm")),
                description=str(zone_data.get("description", "")),
                eye=(str(zone_data["eye"]).lower() if zone_data.get("eye") else None),
                band_inner_vertices=_verts(band.get("inner_polygon_mm")),
                band_outer_vertices=_verts(band.get("outer_polygon_mm")),
                registers_as_object=bool(zone_data.get("registers_as_object", False)),
            ))

        return cls(
            spawn_x=spawn_x,
            spawn_y=spawn_y,
            spawn_heading=spawn_heading,
            field_radius=field_radius,
            objects=objects,
            regions=regions,
            robot_width_mm=robot_width_mm,
            field_hex_vertices=field_hex_vertices,
            field_boundary_color=field_boundary_color,
            color_zones=color_zones,
            sensor_specs=dict((robot_card or {}).get("sensors") or {}),
            pieces=pieces,
            testcase_physics=dict(card.get("testcase_physics") or {}),
            execution_budget_blocks=int(
                (card.get("simulation") or {}).get("execution_budget_blocks") or 0),
        )


# ------------------------------------------------------------------ #
# Simulation constants (not playground-specific)
# ------------------------------------------------------------------ #

_COVERAGE_GRID_CELL_MM = 100.0   # resolution for region coverage estimation
_MAX_UNROLL_ITERATIONS = 20      # cap for repeat-N loop unrolling
_FOREVER_UNROLL = 20             # iterations for forever / repeat-until loops (matches _MAX_UNROLL_ITERATIONS)
# Global execution budget (blocks executed, all stacks; Stage-1 validation
# campaign 2026-08-21). Loop unrolling is MULTIPLICATIVE under nesting
# (20^depth); real students nest to depth 47, so unbounded unrolling hangs.
# Dev-corpus maximum is 602 block executions (measured) — 50k is ~83x
# headroom and bounds worst-case sim time to ~1s. Card-overridable via
# `simulation: {execution_budget_blocks: N}` in the playground card.
_EXECUTION_BUDGET_BLOCKS = 50_000
# Calibrated 2026-08-19 (OI-16, data/screenshot_velocitytest2): two-duration
# drive runs cancel ramp/stop-latency — cruise 494 mm/s at the 50% default,
# 9.88 mm/s per %; turns 201°/s (50%) / 420°/s (100%), 4.16 °/s per %; linear
# %-scaling confirmed at both settings. Previous values (100 mm/s, 75 °/s)
# were ~5x / ~2.7x too slow. Residual ~50-80ms stop latency observed but not
# modelled (second-order).
_DEFAULT_DRIVE_VELOCITY_MM_PER_S = 494.0  # 50% default; 9.88 mm/s per %
_DEFAULT_TURN_VELOCITY_DEG_PER_S  = 208.0  # 50% default; 4.16 °/s per %


# ------------------------------------------------------------------ #
# Output dataclasses
# ------------------------------------------------------------------ #

@dataclass
class PathStep:
    """One position snapshot in the simulated path trace."""
    step: int
    x: float
    y: float
    heading: float       # degrees, math convention
    block_type: str
    block_id: str

    # Which named regions contain this position
    regions_entered: frozenset  # frozenset[str]

    # Which named objects are within tolerance at this position
    objects_in_tolerance: frozenset  # frozenset[str]

    # Magnet flag
    magnet_fires: bool = False

    # VR-Seq (additive, 2026-08-26): index of the cooperative-scheduler
    # thread whose execution produced this step; None in sequential mode.
    # Steps stay in commitment order — one shared robot means consecutive
    # entries remain consecutive poses regardless of thread.
    thread_id: "int | None" = None


@dataclass
class SimulationResult:
    """Complete output of one program simulation.

    All object- and region-specific results are stored in dicts keyed by
    object_id / region_id from the PlaygroundContext.  Nothing here is
    specific to Castle Crashers.
    """

    # Full trace
    path: list[PathStep] = field(default_factory=list)

    # Final state
    final_x: float = 0.0
    final_y: float = 0.0
    final_heading: float = 90.0

    # Named object proximity
    min_distance_to_objects: dict = field(default_factory=dict)
    # {object_id: float}  — minimum distance reached during the run

    first_object_tolerance_steps: dict = field(default_factory=dict)
    # {object_id: Optional[int]}  — first step index within tolerance, or None

    first_object_segmentation_steps: dict = field(default_factory=dict)
    # {object_id: Optional[int]}  — first step within segmentation_radius (or tolerance if not set), or None
    # Used by segment_code.py for phase-boundary detection only; scoring uses first_object_tolerance_steps.

    # Named region coverage
    region_coverage_fractions: dict = field(default_factory=dict)
    # {region_id: float}  — fraction of region grid cells visited

    region_cells_visited: dict = field(default_factory=dict)
    # {region_id: int}

    regions_entered: set = field(default_factory=set)
    # set[str] of region_ids the robot entered at least once

    # Magnet (VEX-specific observable — kept as raw fact)
    magnet_fires_at_step: Optional[int] = None

    # Where this path STARTS.  The trace records a step only after a block runs,
    # so the robot's position before the first recorded step is not in `path`.
    # Path metrics must measure from here or they silently ignore the first move.
    # Whole run: the playground spawn.  Slice: the position at path_start - 1.
    origin_x: float = 0.0
    origin_y: float = 0.0
    origin_heading: float = 90.0

    # Path-level summary
    net_displacement_from_spawn: float = 0.0
    exits_field_boundary: bool = False
    min_distance_from_center: float = float("inf")

    # Pen drawing — recorded when robot moves with pen down.
    # Each entry is (x0, y0, x1, y1, color, width_name).
    pen_segments: list = field(default_factory=list)

    # Set True if any loop was capped during simulation (forever, repeat-until,
    # or repeat(N) with N > _MAX_UNROLL_ITERATIONS).  When True, coverage
    # estimates and final position may underrepresent the actual runtime behavior.
    loop_was_capped: bool = False

    # ---- Stage 0b fidelity propagation (additive, 2026-08-14) ---- #
    # Path-step indices at which a loop cap fired — lets slices answer
    # loop_was_capped PER SPAN instead of program-wide.
    loop_cap_steps: list = field(default_factory=list)
    # blocks.csv simulator_status for every block type in the program
    # (executed or not): {block_type: "handled" | "ignored" | ... | "unknown"}
    simulator_status_by_block_type: dict = field(default_factory=dict)
    # Reporter block types _eval_expression could not evaluate (returned 0).
    # RECORDED, never raised — raising is population-changing (§15.1).
    unknown_reporter_blocks: list = field(default_factory=list)

    # ---- Task 3 (hat execution fidelity), additive ---- #
    # Program-level execution-fidelity flags set during simulation:
    # broadcast_concurrency_approximated, broadcast_recursion_suppressed,
    # broadcast_multiple_receivers (Part A); trigger_unfaithful,
    # trigger_unsimulated, conditional_hat_suppressed (Part B);
    # concurrent_stacks_unverified (Part C); wait_until_unmet (sensing build
    # Phase 1 — an unmet wait_until gated its stack).
    execution_flags: list = field(default_factory=list)
    # Part D: path-step indices whose motion is a modelling fallback, not the
    # program's stated geometry — terminal runoff of a bare continuous drive,
    # nominal 90° of a bare continuous turn, runoff of an armed drive whose
    # wait_until condition never turned true. (The legacy 50mm wait_until
    # probes are retired — sensing build Phase 1, 2026-08-19: a satisfied
    # wait_until now commits one REAL velocity-held move, not fabricated.)
    # Mirrors loop_cap_steps; the block type at each step names the fallback.
    fabricated_steps: list = field(default_factory=list)

    # ---- Sensing build (Phase 1, 2026-08-19), additive ---- #
    # Eye color-detection events: (path-step index, eye, color) recorded when
    # an optical color check evaluates True. Consecutive duplicates collapsed.
    color_detections: list = field(default_factory=list)
    # ---- Sensing build (Phase 2, 2026-08-19), additive ---- #
    # First body-contact step per movable target (objects and pieces with a
    # declared body_radius_mm). The main sim never moves objects (hybrid
    # ruling): from this step on the target's position is STALE and sensor
    # readings against it carry the sensor_reading_stale flag.
    object_contacts: dict = field(default_factory=dict)
    # ---- Sensing build (Phase 5, 2026-08-19), additive ---- #
    # Testcase push model only: piece id -> step its centre crossed the
    # island edge (cleared). Always empty in the main sim.
    pieces_cleared: dict = field(default_factory=dict)
    # ---- Option A late materialization (2026-08-19), additive ---- #
    # piece id -> (x, y) at materialization (activation position — the
    # anchor for navigate-to measurements; push may move the piece later).
    piece_positions: dict = field(default_factory=dict)
    # block_id -> (first evaluation step, block_type) for sensing reporters —
    # the baseline run's trace that Option A materialization timing reads.
    sensor_first_eval: dict = field(default_factory=dict)
    # Total blocks executed across all stacks (Stage-1 validation campaign,
    # 2026-08-21) — the execution-budget instrument and a complexity metric.
    blocks_executed: int = 0
    # Simulated elapsed time (OI-23 timer build, 2026-08-24): waits + drives
    # + turn-for + wait_until marches at the calibrated velocities. Also the
    # clock behind when_timer hats and timer_value.
    sim_time_s: float = 0.0
    # hat block_id -> [steps at which it fired] (edge-triggered re-arming,
    # reviewer ruling 2026-08-24) — the instrument behind the
    # detection_physics fidelity lane.
    sensor_hats_fired: dict = field(default_factory=dict)
    # OI-7 lockout (2026-08-25): the when_started stack that owned the
    # drivetrain when a creation-order precedence was supplied and applied;
    # None when no precedence was supplied (legacy concurrent approximation).
    stack_lockout_winner: Optional[str] = None
    # VR-Seq (2026-08-26): which execution model produced this result —
    # "sequential" (legacy) or "cooperative" (scratch-vm-transliterated
    # scheduler). A RESULT FIELD, deliberately not a flag: flags feed the
    # high-certainty masks and the fidelity taxonomy, and a provenance
    # marker must not poison either.
    scheduler: str = "sequential"
    # VR-Seq spec delta (2026-08-26): superseded_motion is MEASURED
    # (truncate_and_resume), so these are provenance/diagnostic counts, NOT
    # conditional-evidence markers — result fields for the same reason as
    # `scheduler`; evidence touching such runs is full-tier.
    motions_superseded: int = 0
    drivetrain_contentions: int = 0
    # A3 rotation build (2026-08-26): final cumulative drive rotation
    # (VEX convention, CW-positive, 0 at spawn)
    drive_rotation_deg: float = 0.0
    # A2 structures-exercised trace (2026-08-26): which control structures
    # actually RAN — loop block_id -> iterations executed; branch block_id
    # -> arms taken in first-seen order. Feeds the rubric's Control
    # Structure dimension (battery plan §6.1 A2). Additive.
    loops_exercised: dict = field(default_factory=dict)
    branches_exercised: dict = field(default_factory=dict)
    # A3 close review (2026-08-26): final variable state — additive, lets
    # tests and evidence observe reporter values a program stored
    variables: dict = field(default_factory=dict)
    # A2 thread attribution (2026-08-26, reviewer-approved): ordered
    # structure events in the PARALLEL_EXECUTION §14 vocabulary —
    # (thread_id, event, block_id, detail). thread_id None = sequential.
    # Lets rubric evidence read WHICH thread exercised WHAT (concurrent
    # policy composition), and shares a format with scheduler traces.
    structure_trace: list = field(default_factory=list)


# Hat trust taxonomy (Part B, revised 2026-08-18). Trusted hats fire normally
# with no flag: when_started (structural), when_broadcasted (exact after Part A),
# when_timer (the simulated clock is modelled). The eye hat is evaluable but
# known-unfaithful (omnidirectional, against a 1136mm tolerance — pending a
# sensor audit): trigger_unfaithful. Any other hat (when_bumper) has no sensor
# simulation at all: trigger_unsimulated.
_HAT_STARTED = "pg_events_when_started"
_HAT_RECEIVER = "pg_events_when_broadcasted"
_HAT_TIMER = "pg_events_when_timer"
_TRUSTED_HATS = (_HAT_STARTED, _HAT_RECEIVER, _HAT_TIMER)
_HAT_EYE = "pg_events_optical_detect_object"
_HAT_BUMPER = "pg_events_when_bumper"


# ------------------------------------------------------------------ #
# Main entry point
# ------------------------------------------------------------------ #

# ------------------------------------------------------------------ #
# VR-Seq cooperative Sequencer (Stage 2, 2026-08-26 — BUILD_SPEC §2/§3)
# ------------------------------------------------------------------ #

_RUNNABLE, _PARKED_MOTION, _PARKED_TIME, _PARKED_COND, _T_GATED, _T_DONE = \
    range(6)

_SLICE_BACKSTOP = 100_000   # scheduling-slice safety cap (never expected)


class _SeqThread:
    __slots__ = ("root", "idx", "gen", "status", "wake_remaining", "park",
                 "forever_completed")

    def __init__(self, root, idx):
        self.root = root
        self.idx = idx
        self.gen = None
        self.status = _RUNNABLE
        # PARKED_TIME stores REMAINING seconds, decremented per slice —
        # never absolute wake times: (now + w) - now drifts in the last
        # float bit and G3 pins byte-identity against the legacy wait
        self.wake_remaining = None
        self.park = None
        self.forever_completed = False


class _Sequencer:
    """Transliteration of scratch-vm's stepThreads/stepThread for our
    event-driven setting (SCHEDULING_MODEL §10, BUILD_SPEC §2.2): one thread
    per when_started stack in document order; round-robin passes advance
    every RUNNABLE thread to its next yield point; when none are runnable
    the clock advances to the next event (motion completion, wait expiry,
    wait_until crossing) and one motion slice is committed. Exactly one
    blocking motion is active at a time (shared drivetrain, last write
    wins); continuous motion lives in the legacy pending fields, which
    already implement the last-write-wins cell for the non-blocking case."""

    def __init__(self, sim, roots, superseded_motion: str):
        self.sim = sim
        self.policy = superseded_motion
        self.threads = [_SeqThread(r, i) for i, r in enumerate(roots)]
        self.active = None            # (thread, park) — blocking *_for motion
        self.resume_queue = []        # resume_after policy
        self._phase_writers = set()   # thread idxs that wrote this phase

    # -- called from drivetrain branches (via sim._sequencer) --

    def notify_drivetrain_command(self) -> None:
        """Any drivetrain command supersedes an active blocking motion
        (last write wins — spec §2.4 rule 1/2)."""
        if self.active is not None:
            t, park = self.active
            self.active = None
            self.sim.motions_superseded += 1
            if self.policy == "truncate_and_park":
                t.status = _T_GATED          # dead, not an error
            elif self.policy == "resume_after":
                self.resume_queue.append((t, park))
            else:                            # truncate_and_resume (default)
                t.status = _RUNNABLE
        writer = self.sim._current_thread_idx
        self._phase_writers.add(writer)
        if len(self._phase_writers) > 1:
            # two DIFFERENT threads wrote the cell within one scheduling
            # event — diagnostic; the real system silently does the same
            self.sim.drivetrain_contentions += 1

    # -- thread context --

    def _enter(self, t):
        self.sim._forever_completed = t.forever_completed
        self.sim._current_root_id = t.root.block_id
        self.sim._current_thread_idx = t.idx

    def _exit(self, t):
        t.forever_completed = self.sim._forever_completed
        self.sim._current_root_id = None
        self.sim._current_thread_idx = None

    # -- main loop --

    def run(self) -> None:
        for t in self.threads:
            t.gen = self.sim.execute_stack(t.root)
        slices = 0
        while True:
            self._advance_runnables()
            live = [t for t in self.threads
                    if t.status in (_PARKED_MOTION, _PARKED_TIME, _PARKED_COND)]
            if not live:
                break
            slices += 1
            if slices > _SLICE_BACKSTOP:
                self.sim._flag("scheduler_slice_backstop")
                break
            if not self._advance_clock():
                break

    def _advance_runnables(self) -> None:
        self._phase_writers = set()
        progressed = True
        while progressed:
            progressed = False
            for t in self.threads:
                if t.status != _RUNNABLE:
                    continue
                progressed = True
                self._enter(t)
                try:
                    item = next(t.gen)
                except StopIteration:
                    t.status = _T_DONE
                except _GateSignal:
                    t.status = _T_GATED
                else:
                    if isinstance(item, _Park):
                        self._apply_park(t, item)
                    # a bare loop yield leaves the thread RUNNABLE — it gets
                    # its next pass on the following round-robin sweep
                finally:
                    self._exit(t)

    def _apply_park(self, t, park) -> None:
        if park.kind == "motion":
            # notify_drivetrain_command already superseded any prior owner
            self.active = (t, park)
            t.status = _PARKED_MOTION
            t.park = park
        elif park.kind == "time":
            t.status = _PARKED_TIME
            t.wake_remaining = park.seconds
            t.park = park
        else:
            t.status = _PARKED_COND
            t.park = park

    # -- events & slices --

    def _velocity(self, mode: str) -> float:
        return max(self.sim.drive_velocity_mm_per_s if mode == "drive"
                   else self.sim.turn_velocity_deg_per_s, 1e-9)

    def _motion_state(self):
        """(mode, sign, limit_dt|None). Blocking active motion first, else
        continuous pending; None when the drivetrain is idle."""
        sim = self.sim
        if self.active is not None:
            _, park = self.active
            return park.mode, park.sign, park.magnitude / self._velocity(park.mode)
        if sim.pending_drive_dir is not None:
            return "drive", sim.pending_drive_dir, None
        if sim.pending_turn_dir is not None:
            return "turn", sim.pending_turn_dir, None
        return None

    def _cond_true(self, t) -> bool:
        block = t.park.block
        return bool(block.values and self.sim._eval_expression(block.values[0]))

    def _cond_crossing_dt(self, t, bound_dt):
        """Seconds until t's condition becomes true under the current
        motion, using the existing march solvers; None if it never does
        within the bound / the caps."""
        m = self._motion_state()
        if m is None:
            return None
        mode, sign, limit_dt = m
        sim = self.sim
        horizon = bound_dt if bound_dt is not None else limit_dt
        if mode == "drive":
            cap_mm = 4.0 * max(sim.ctx.field_radius, 1.0)
            if horizon is not None:
                cap_mm = min(cap_mm, self._velocity("drive") * horizon)
            d = sim._march_drive_until(sign, cap_mm, lambda: self._cond_true(t))
            return None if d is None else d / self._velocity("drive")
        angle = sim._march_turn_until(sign, lambda: self._cond_true(t))
        if angle is None:
            return None
        dt = angle / self._velocity("turn")
        if horizon is not None and dt > horizon:
            return None
        return dt

    def _advance_clock(self) -> bool:
        """Advance to the next event; commit one motion slice. False when
        nothing can ever progress (after gating unmet conditions)."""
        sim = self.sim
        events = []                        # (dt, kind, thread|None)
        if self.active is not None:
            t, park = self.active
            events.append((park.magnitude / self._velocity(park.mode),
                           "complete", t))
        for t in self.threads:
            if t.status == _PARKED_TIME:
                events.append((max(0.0, t.wake_remaining), "wake", t))
        bound = min((dt for dt, _, _ in events), default=None)
        for t in self.threads:
            if t.status == _PARKED_COND:
                if self._cond_true(t):     # became true at this boundary
                    events.append((0.0, "cond", t))
                    continue
                dt = self._cond_crossing_dt(t, bound)
                if dt is not None:
                    events.append((dt, "cond", t))
        if not events:
            conds = [t for t in self.threads if t.status == _PARKED_COND]
            if not conds:
                return False
            # no motion, no timers, everything else DONE/GATED: no thread
            # can ever satisfy these conditions — legacy unmet semantics
            for t in conds:
                self._gate_cond(t)
            return True
        dt = min(dt for dt, _, _ in events)
        if sim.time_budget_s is not None:
            rem = sim.time_budget_s - sim.sim_time_s
            if rem <= 0:
                sim._flag("time_budget_exhausted")
                raise _BudgetSignal()
            dt = min(dt, rem)
        cond_hits = [t for d, kind, t in events
                     if kind == "cond" and d <= dt + 1e-12]
        self._commit_slice(dt, cond_hits[0] if cond_hits else None)
        eps = 1e-9
        # completion
        if self.active is not None:
            t, park = self.active
            if park.magnitude <= eps:
                self.active = None
                t.status = _RUNNABLE
                if self.policy == "resume_after" and self.resume_queue:
                    rt, rpark = self.resume_queue.pop(0)
                    self.active = (rt, rpark)
        # timer wakes
        for t in self.threads:
            if t.status == _PARKED_TIME:
                t.wake_remaining = max(0.0, t.wake_remaining - dt)
                if t.wake_remaining <= eps:
                    t.status = _RUNNABLE
        # condition wakes (re-evaluated against the post-slice world)
        for t in self.threads:
            if t.status == _PARKED_COND and self._cond_true(t):
                # OI-3 ratified semantics: pending motion marches TO the
                # condition and stops there (legacy clears the armed dir)
                m = self._motion_state()
                if m is not None and self.active is None:
                    if m[0] == "drive":
                        sim.pending_drive_dir = None
                    else:
                        sim.pending_turn_dir = None
                t.status = _RUNNABLE
        return True

    def _commit_slice(self, dt: float, cond_owner) -> None:
        """Move the robot for dt under the current motion. Attribution
        (G3-critical, mirrors legacy exactly): blocking motion -> its *_for
        block; continuous motion cut by a wait_until crossing -> that
        wait_until block (legacy adds time via _move); continuous motion cut
        by a wait expiry -> the earliest-waking wait block (legacy adds time
        manually, _move(add_time=False)); no motion -> clocks only."""
        sim = self.sim
        if dt <= 0:
            # zero-length BLOCKING motion still records its step (legacy
            # _move(0) does); every other zero slice is a pure no-op
            if not (self.active is not None
                    and self.active[1].magnitude <= 1e-9):
                return
        m = self._motion_state()
        if m is None:
            sim.sim_time_s += dt
            sim.timer_s += dt
            return
        mode, sign, _ = m
        blocking = self.active is not None
        if blocking:
            t, park = self.active
            sim._current_thread_idx = t.idx   # step attribution to the owner
            # completion slices apply the EXACT remaining magnitude — the
            # v*dt round-trip drifts in the last float bit, and G3 pins
            # byte-identity against the legacy single-shot computation
            mag = self._velocity(mode) * dt
            if mag >= park.magnitude - 1e-9:
                mag = park.magnitude
            if mode == "drive":
                sim._move(sign * mag, park.block)
            else:
                sim.sim_time_s += dt
                sim.timer_s += dt
                sim.heading = (sim.heading + sign * mag) % 360
                sim.drive_rotation_deg -= sign * mag
                sim._record_step(park.block)
                sim.step += 1
            park.magnitude = max(0.0, park.magnitude - mag)
            sim._current_thread_idx = None
            return
        # continuous pending motion
        if cond_owner is not None:
            attr = cond_owner.park.block
            if mode == "drive":
                sim._move(sign * self._velocity("drive") * dt, attr)
            else:
                sim.sim_time_s += dt
                sim.timer_s += dt
                sim.heading = (sim.heading
                               + sign * self._velocity("turn") * dt) % 360
                sim.drive_rotation_deg -= sign * self._velocity("turn") * dt
                sim._record_step(attr)
                sim.step += 1
            return
        waiters = [t for t in self.threads if t.status == _PARKED_TIME]
        attr_block = (min(waiters, key=lambda t: t.wake_remaining).park.block
                      if waiters else
                      (sim.pending_drive_block if mode == "drive"
                       else sim.pending_turn_block))
        sim.sim_time_s += dt
        sim.timer_s += dt
        if mode == "drive":
            sim._move(sign * self._velocity("drive") * dt, attr_block,
                      add_time=False)
        else:
            sim.heading = (sim.heading
                           + sign * self._velocity("turn") * dt) % 360
            sim.drive_rotation_deg -= sign * self._velocity("turn") * dt
            sim._record_step(attr_block)
            sim.step += 1

    def _gate_cond(self, t) -> None:
        """Throw _CondUnmet into the parked generator — its wait_until
        branch runs the legacy unmet path (fabricate + flag + gate)."""
        self._enter(t)
        try:
            t.gen.throw(_CondUnmet())
        except StopIteration:
            t.status = _T_DONE
        except _GateSignal:
            t.status = _T_GATED
        else:
            t.status = _T_GATED
        finally:
            self._exit(t)


def _iter_stack(root):
    """Every block in a stack's subtree: next-chain, statement slots, value
    slots (OI-7 loser pre-scan)."""
    node = root
    while node is not None:
        yield node
        for child in (node.statements or {}).values():
            yield from _iter_stack(child)
        slots = node.value_slots or {}
        for val in (slots.values() if isinstance(slots, dict) else []):
            if val is not None:
                yield from _iter_stack(val)
        node = node.next


def simulate_path(
    program,   # BlockProgram
    context: PlaygroundContext,
    conditional_hats: str = "execute",   # "execute" (status quo, B1) | "suppress" (B2/B3)
    stack_precedence: "str | None" = None,   # OI-7: winning when_started block id
    scheduler: str = "sequential",       # VR-Seq: "sequential" | "cooperative"
    superseded_motion: str = "truncate_and_resume",   # MEASURED in VEX VR
    loop_iteration_time_s: float = 0.0,  # 60Hz loop clock (measured 60.15Hz)
    thread_start_order: str = "document",   # "document" | "reverse_document"
    time_budget_s: "float | None" = None,   # wall-clock budget (observed run_duration)
    movable_predicates: "str | None" = None,   # bracketing: None|"floor"|"ceiling"
) -> SimulationResult:
    """Simulate robot movement for a BlockProgram on a given playground.

    Args:
        program: Parsed BlockProgram (from parse_blocks.parse_workspace).
        context: PlaygroundContext built from the playground YAML card.
        stack_precedence: OI-7 lockout (reviewer-probed rule 2026-08-21, built
            2026-08-25): the block id of the most recently CREATED
            when_started stack, recovered from longitudinal snapshots. When
            it names one of ≥2 when_started stacks, that stack owns the
            drivetrain OUTRIGHT: losing stacks' drivetrain commands
            (including velocity setters) are no-ops, skipped instantly —
            non-drivetrain effects still run. Whether a real loser's no-op
            drive consumes its duration is an open probe
            (`stack_lockout_timing_assumed` flags losers with post-drive
            effects). Absent or unmatched -> byte-identical legacy behavior
            (sequential approximation + concurrent_stacks_unverified).

    Returns:
        SimulationResult with full path trace and derived metrics.
    """
    sim = _Simulator(context)
    # Part A (task 3): broadcast receivers execute inline at their broadcast
    # site, keyed on BROADCAST_OPTION — never in the top-level document-order
    # loop (that would run them twice, or at the wrong time).
    # OI-23 procedures build (2026-08-24): definitions parse as orphan
    # stacks (their prototype shadow carries proccode); register bodies so
    # calls execute them inline. First definition of a name wins.
    for root in program.top_level_stacks:
        if root.block_type == "procedures_definition" and root.children:
            name = ((root.children[0].mutation or {}).get("proccode")
                    if root.children[0].mutation else None)
            if name and root.next is not None:
                sim.procedures.setdefault(name, root.next)
    top_level = []
    for root in program.event_handler_stacks:
        if root.block_type == _HAT_RECEIVER:
            key = root.get_field("BROADCAST_OPTION") or ""
            sim.receivers.setdefault(key, []).append(root)
        else:
            top_level.append(root)
    # Part C / OI-7: multiple when_started stacks run concurrently on the
    # real robot; the reviewer-probed rule is that the most recently CREATED
    # stack owns the drivetrain outright. With a recovered precedence we
    # apply the lockout; without one, the sequential approximation stands
    # and the flag stays (honest fallback — never silently re-picked).
    started_ids = [r.block_id for r in top_level
                   if r.block_type == _HAT_STARTED]
    if len(started_ids) > 1:
        if stack_precedence in started_ids:
            sim.stack_lockout_winner = stack_precedence
            sim.lockout_losers = frozenset(
                i for i in started_ids if i != stack_precedence)
            # Open probe (OI-7 detail): does a loser's no-op drive consume
            # its duration? Only matters when a losing stack pairs
            # drivetrain commands with other effects — flag those.
            for r in top_level:
                if r.block_id in sim.lockout_losers:
                    kinds = {n.block_type for n in _iter_stack(r)}
                    if any(k.startswith("pg_drivetrain_") for k in kinds) \
                            and any(k.startswith(("pg_magnet_",
                                                  "pg_events_broadcast",
                                                  "pg_control_stop_project"))
                                    for k in kinds):
                        sim._flag("stack_lockout_timing_assumed")
                        break
        elif scheduler != "cooperative":
            # the cooperative scheduler RESOLVES multi-stack execution
            # (spec §6): the flag is retired for those runs; the residual
            # P-B uncertainty travels on motion_superseded instead
            sim._flag("concurrent_stacks_unverified")
    has_front_eye_model = bool((context.sensor_specs.get("front_eye") or {})
                               .get("range_mm"))
    stopped = False
    # Part B (revised by sensing build Phase 2, 2026-08-19), two-pass: hats
    # are all REGISTERED before any stack executes — they are parallel
    # programs, so a modeled eye hat must be armed before an earlier stack's
    # motion can sweep a body through its cone. An eye hat with a modelled
    # eye DEFERS: its stack fires inline at the first modeled detection
    # (between blocks; mid-move detections latch), never eagerly. An eye hat
    # without a model keeps the legacy eager execution + trigger_unfaithful;
    # any other hat (bumper) is unsimulated. B2 suppresses either kind — and
    # with it any broadcast.
    has_bumper_model = isinstance(context.sensor_specs.get("bumpers"), dict)
    executable = []
    for root in top_level:
        if root.block_type == _HAT_TIMER:
            # OI-23 build (2026-08-24): when_timer DEFERS on the simulated
            # clock (which now advances with movement) instead of running
            # eagerly in document order. Stays in _TRUSTED_HATS: no trust
            # flag — the clock is modelled, calibrated state.
            sim.pending_sensor_hats.append(root)
            continue
        if root.block_type not in _TRUSTED_HATS:
            is_modeled_eye = (root.block_type == _HAT_EYE
                              and has_front_eye_model
                              and (root.get_field("OPTIONS") or "detects").lower()
                              == "detects")
            # Phase 4 (2026-08-19): bumper hats with mount geometry in the
            # robot card defer like eye hats — fire at first modeled contact.
            is_modeled_bumper = (root.block_type == _HAT_BUMPER
                                 and has_bumper_model
                                 and (root.get_field("OPTIONS") or "pressed").lower()
                                 == "pressed")
            if conditional_hats == "suppress":
                sim._flag("trigger_unfaithful" if root.block_type == _HAT_EYE
                          else "trigger_unsimulated")
                sim._flag("conditional_hat_suppressed")
                continue
            if is_modeled_eye or is_modeled_bumper:
                sim.pending_sensor_hats.append(root)
                continue
            sim._flag("trigger_unfaithful" if root.block_type == _HAT_EYE
                      else "trigger_unsimulated")
        executable.append(root)
    if scheduler not in ("sequential", "cooperative"):
        raise ValueError(f"unknown scheduler {scheduler!r}")
    if thread_start_order not in ("document", "reverse_document"):
        raise ValueError(f"unknown thread_start_order {thread_start_order!r}")
    sim.loop_iteration_time_s = loop_iteration_time_s
    sim.time_budget_s = time_budget_s
    if movable_predicates not in (None, "floor", "ceiling"):
        raise ValueError(f"unknown movable_predicates {movable_predicates!r}")
    sim.movable_predicates = movable_predicates
    if loop_iteration_time_s > 0 and time_budget_s is not None:
        # measured-clock mode (reviewer directive 2026-08-26): the wall-clock
        # budget REPLACES the arbitrary unroll caps — loops run until the
        # observed run duration (or the 50k block budget) stops them
        sim.forever_unroll = 10**9
        sim.max_unroll = 10**9
    try:
        if scheduler == "cooperative":
            # VR-Seq Stage 2: one thread per executable stack, round-robin
            # at the scratch-vm yield points. Start order SETTLED as
            # document order (measured — SCHEDULING_MODEL §11.2);
            # "reverse_document" is retained as a falsification alternative
            # only (tier-2 sensitivity sweep optional, not a gate).
            roots = (list(reversed(executable))
                     if thread_start_order == "reverse_document"
                     else executable)
            sim._sequencer = _Sequencer(sim, roots, superseded_motion)
            sim._sequencer.run()
        else:
            for root in executable:
                sim._forever_completed = False   # per-stack (parallel programs)
                sim._current_root_id = root.block_id   # OI-7 lockout scope
                try:
                    # sequential driver: drain the stack generator to
                    # completion (VR-Seq Stage 1 — yields are no-ops here)
                    for _ in sim.execute_stack(root):
                        pass
                except _GateSignal:
                    continue   # unmet wait_until gates this stack only
                finally:
                    sim._current_root_id = None
        # Detection state at program end may satisfy a still-pending hat
        # (e.g. the main stack's last move brought a body into the cone).
        sim.fire_ready_sensor_hats()
        if any(h.block_type == _HAT_TIMER
               and not sim.sensor_hats_fired.get(h.block_id)
               for h in sim.pending_sensor_hats):
            # The program's stacks finished before the threshold; whether the
            # real project stays open long enough to fire it is not modelled.
            sim._flag("timer_hat_unfired")
    except _StopSignal:
        stopped = True   # stop project halts the robot too — no runoff
    if not stopped:
        sim.finish_pending_motion()
    result = sim.build_result()
    # Stage 0b (additive): blocks.csv simulator_status for every block type the
    # program contains — executed or not — so the evidence layer can see which
    # semantics the reconstruction actually carries (C12).
    from ..parsing import block_registry as _br
    try:
        block_types = {b.block_type for b in program.iter_all_blocks_including_orphans()}
    except AttributeError:
        block_types = {ps.block_type for ps in result.path}
    result.simulator_status_by_block_type = {
        bt: _br.simulator_status(bt) for bt in sorted(block_types)}
    return result


# ------------------------------------------------------------------ #
# SimulationResult slicing (for per-segment scoring)
# ------------------------------------------------------------------ #

def slice_sim_result(
    full_result: SimulationResult,
    path_start: int,
    path_end: int,
    context: "PlaygroundContext | None" = None,
) -> SimulationResult:
    """Build a SimulationResult covering only a slice of the full simulation path.

    Used by rolling_goal_evidence.py (window scoring) and run_detector.py
    (segment scoring) to evaluate indicators against a contiguous sub-path.

    Args:
        full_result: The complete SimulationResult from the whole-program simulation.
        path_start:  Inclusive start index into full_result.path.
        path_end:    Exclusive end index into full_result.path.
        context:     PlaygroundContext — when provided, actual euclidean distances
                     to named objects are recomputed per step from their positions.
                     Without context, a proxy (objects_in_tolerance → 0.0) is used
                     with fallback to the full-result min distances, which can bleed
                     across window boundaries.

    Returns:
        A new SimulationResult recomputed from the path slice.  All dict-keyed
        fields (min_distance_to_objects, region_coverage_fractions, etc.) are
        recomputed from scratch over the slice.  magnet_fires_at_step is
        adjusted to be within the slice (None if it falls outside).
    """
    path_end = min(path_end, len(full_result.path))
    slice_path = full_result.path[path_start:path_end]

    # Where this slice starts.  path[0] is the END of the first movement, so the
    # position before it has to come from the preceding step (or the spawn for
    # the first segment) or the first move is never measured.
    if path_start > 0 and path_start <= len(full_result.path):
        prev_step = full_result.path[path_start - 1]
        origin_x, origin_y, origin_heading = prev_step.x, prev_step.y, prev_step.heading
    elif context is not None:
        origin_x, origin_y = context.spawn_x, context.spawn_y
        origin_heading = context.spawn_heading
    else:
        origin_x, origin_y = full_result.origin_x, full_result.origin_y
        origin_heading = full_result.origin_heading

    if not slice_path:
        # Empty slice: robot didn't move in this segment. Use full result's
        # final position (which equals spawn when nothing executed) so that
        # distance-from-spawn metrics compute correctly (0mm, not ~1015mm).
        return SimulationResult(
            final_x=full_result.final_x,
            final_y=full_result.final_y,
            final_heading=full_result.final_heading,
            min_distance_to_objects=dict(full_result.min_distance_to_objects),
            origin_x=origin_x,
            origin_y=origin_y,
            origin_heading=origin_heading,
        )

    last = slice_path[-1]
    final_x, final_y, final_heading = last.x, last.y, last.heading

    # Recompute per-object proximity
    min_dist: dict[str, float] = {}
    first_tol: dict[str, int | None] = {}
    for ps in slice_path:
        for obj_id in ps.objects_in_tolerance:
            if first_tol.get(obj_id) is None:
                first_tol[obj_id] = ps.step

    if context is not None:
        # Compute actual euclidean min distance to each object over this slice.
        # This prevents full-simulation min distances from bleeding across window
        # boundaries (e.g. an object reached at step 6 should not appear as
        # min_dist=0 in a window covering steps 0-4).
        for obj_id, obj in context.objects.items():
            d_min = float("inf")
            for ps in slice_path:
                d = math.sqrt((ps.x - obj.x) ** 2 + (ps.y - obj.y) ** 2)
                if d < d_min:
                    d_min = d
            min_dist[obj_id] = d_min
    else:
        # Legacy proxy: objects_in_tolerance → 0.0, fall back to full-result
        # distances for objects not entered. May bleed across window boundaries.
        for ps in slice_path:
            for obj_id in ps.objects_in_tolerance:
                if obj_id not in min_dist:
                    min_dist[obj_id] = 0.0
        for obj_id, dist in full_result.min_distance_to_objects.items():
            if obj_id not in min_dist:
                min_dist[obj_id] = dist

    # Recompute region coverage from slice using full lateral+longitudinal sampling,
    # identical to _Simulator._sample_region_coverage, so coverage fractions match
    # what the full simulation computes.
    region_cells: dict[str, set] = {}
    regions_entered: set[str] = set()

    if context is not None:
        prev_x, prev_y = origin_x, origin_y

        for ps in slice_path:
            for region_id, region in context.regions.items():
                cells = _coverage_cells_for_move(
                    prev_x, prev_y, ps.x, ps.y, ps.heading, context.robot_width_mm, region
                )
                if cells:
                    if region_id not in region_cells:
                        region_cells[region_id] = set()
                    region_cells[region_id].update(cells)
                    regions_entered.add(region_id)
            prev_x, prev_y = ps.x, ps.y
    else:
        # Legacy fallback: endpoint-only, single cell per step.
        for ps in slice_path:
            for region_id in ps.regions_entered:
                regions_entered.add(region_id)
                if region_id not in region_cells:
                    region_cells[region_id] = set()
                region_cells[region_id].add((
                    int(math.floor(ps.x / _COVERAGE_GRID_CELL_MM)),
                    int(math.floor(ps.y / _COVERAGE_GRID_CELL_MM)),
                ))

    # Build coverage fractions using the polygon/grid denominator from the region definition.
    coverage_fractions: dict[str, float] = {}
    cells_visited: dict[str, int] = {}
    for region_id, cells in region_cells.items():
        cells_visited[region_id] = len(cells)
        if context is not None and region_id in context.regions:
            total_grid = context.regions[region_id].total_grid_cells
        else:
            total_grid = full_result.region_cells_visited.get(region_id) or 0
        coverage_fractions[region_id] = min(1.0, len(cells) / total_grid) if total_grid > 0 else 0.0

    # Adjust magnet_fires_at_step to be within slice (absolute step index)
    magnet_step = full_result.magnet_fires_at_step
    if magnet_step is not None and path_start <= magnet_step < path_end:
        adjusted_magnet = magnet_step
    else:
        adjusted_magnet = None

    # Carry over first_object_segmentation_steps from full result (clipped to slice)
    first_seg: dict[str, int | None] = {}
    for obj_id, seg_step in full_result.first_object_segmentation_steps.items():
        if seg_step is not None and path_start <= seg_step < path_end:
            first_seg[obj_id] = seg_step
        else:
            first_seg[obj_id] = None

    # Net displacement and boundary check for the slice
    # Measured from the origin, not slice_path[0], so the first movement counts.
    net_displacement = math.sqrt(
        (final_x - origin_x) ** 2 + (final_y - origin_y) ** 2
    )

    return SimulationResult(
        path=slice_path,
        final_x=final_x,
        final_y=final_y,
        final_heading=final_heading,
        min_distance_to_objects=min_dist,
        first_object_tolerance_steps=first_tol,
        first_object_segmentation_steps=first_seg,
        region_coverage_fractions=coverage_fractions,
        region_cells_visited={k: len(v) for k, v in region_cells.items()},
        regions_entered=regions_entered,
        magnet_fires_at_step=adjusted_magnet,
        # Stage 0b: per-span loop_was_capped — a cap only taints the spans that
        # contain (or follow) it. When cap steps were recorded, a slice is
        # capped iff a cap fired at or before its end and inside-or-before it;
        # legacy results without cap steps fall back to the program-wide flag.
        loop_was_capped=(
            any(path_start <= cs < path_end for cs in full_result.loop_cap_steps)
            if full_result.loop_cap_steps else full_result.loop_was_capped),
        loop_cap_steps=[cs for cs in full_result.loop_cap_steps
                        if path_start <= cs < path_end],
        simulator_status_by_block_type=dict(full_result.simulator_status_by_block_type),
        unknown_reporter_blocks=list(full_result.unknown_reporter_blocks),
        net_displacement_from_spawn=net_displacement,
        exits_field_boundary=full_result.exits_field_boundary,
        origin_x=origin_x,
        origin_y=origin_y,
        origin_heading=origin_heading,
        color_detections=[cd for cd in full_result.color_detections
                          if path_start <= cd[0] < path_end],
        object_contacts={oid: s for oid, s in full_result.object_contacts.items()
                         if path_start <= s < path_end},
        pieces_cleared={pid: s for pid, s in full_result.pieces_cleared.items()
                        if path_start <= s < path_end},
        piece_positions=dict(full_result.piece_positions),
        sensor_first_eval={bid: v for bid, v in full_result.sensor_first_eval.items()
                           if path_start <= v[0] < path_end},
    )


# ------------------------------------------------------------------ #
# Path analysis utilities (operate on raw path, no playground coupling)
# ------------------------------------------------------------------ #

def compute_axis_progress_metrics(
    path: list[PathStep],
    target_x: float,
    target_y: float,
    origin: tuple[float, float] | None = None,
) -> dict:
    """Compute how consistently the path moves toward a target point.

    Considers only steps that involve movement (non-zero displacement).
    For each move step, records whether the robot closed the gap on either
    axis toward the target.

    Args:
        path:     List of PathStep from SimulationResult.path.
        target_x: X coordinate of the target point.
        target_y: Y coordinate of the target point.
        origin:   Position before path[0] — the spawn for a whole run, or the
                  position at path_start - 1 for a slice.  The trace records a
                  step only after a block has run, so path[0] is the END of the
                  first movement.  Without an origin that movement is never
                  measured, and a single-movement segment scores 0.0 because it
                  has no consecutive pair to compare.

    Returns:
        {
          'per_step': list[dict],         step-by-step progress records
          'monotonic_fraction': float,    fraction of move steps with progress
          'has_reversals': bool,          any step moved away from target
          'is_monotonic': bool,           monotonic_fraction >= 0.6
        }
    """
    per_step = []
    move_steps = []

    # (x, y, step_label) for each position, oldest first.
    points: list[tuple[float, float, int]] = []
    if origin is not None:
        points.append((origin[0], origin[1], -1))
    points.extend((ps.x, ps.y, ps.step) for ps in path)

    for i in range(1, len(points)):
        prev_x, prev_y, _ = points[i - 1]
        cur_x, cur_y, cur_step = points[i]
        if abs(cur_x - prev_x) < 0.01 and abs(cur_y - prev_y) < 0.01:
            continue  # no movement this step

        dx_toward = abs(prev_x - target_x) - abs(cur_x - target_x)
        dy_toward = abs(prev_y - target_y) - abs(cur_y - target_y)
        made_progress = dx_toward > 1.0 or dy_toward > 1.0

        record = {
            "step": cur_step,
            "x": cur_x,
            "y": cur_y,
            "dx_toward": dx_toward,
            "dy_toward": dy_toward,
            "made_progress": made_progress,
        }
        per_step.append(record)
        move_steps.append(made_progress)

    if not move_steps:
        return {
            "per_step": per_step,
            "monotonic_fraction": 0.0,
            "has_reversals": False,
            "is_monotonic": False,
        }

    monotonic_frac = sum(move_steps) / len(move_steps)
    return {
        "per_step": per_step,
        "monotonic_fraction": monotonic_frac,
        "has_reversals": any(not m for m in move_steps),
        "is_monotonic": monotonic_frac >= 0.6,
    }


def _movement_segments(
    path: list[PathStep],
    origin: tuple[float, float] | None = None,
) -> list[tuple[float, float, float, float]]:
    """Return (x0, y0, x1, y1) for each step that actually moved the robot.

    When `origin` is given it is treated as the position before path[0], so the
    robot's FIRST movement is measured.  Without it that move is invisible —
    the trace only records a position after a block has run, so path[0] is an
    endpoint, not a starting point.
    """
    points: list[tuple[float, float]] = []
    if origin is not None:
        points.append(origin)
    points.extend((p.x, p.y) for p in path)

    segments: list[tuple[float, float, float, float]] = []
    for i in range(1, len(points)):
        (x0, y0), (x1, y1) = points[i - 1], points[i]
        if _dist(x0, y0, x1, y1) > 0.01:
            segments.append((x0, y0, x1, y1))
    return segments


def compute_path_straightness(
    path: list[PathStep],
    target_x: float,
    target_y: float,
    origin: tuple[float, float] | None = None,
) -> dict:
    """Measure how geometrically efficient the executed path is.

    The straightness ratio is total traveled distance divided by net
    displacement.  A perfectly straight run is 1.0; an L-shaped path with
    equal legs is sqrt(2) ~ 1.41; detours and repeated correction push it
    higher.  Monotonicity alone cannot separate a straight path from an
    L-path (each leg of an L closes one axis, so both score 1.0 on
    compute_axis_progress_metrics) — this ratio is what distinguishes them.

    The ratio says nothing about *direction*, so callers should also require
    net_progress_to_target_mm > 0: a perfectly straight path away from the
    target is not direct navigation.

    Args:
        path:     List of PathStep from SimulationResult.path.
        target_x: X coordinate of the navigation target.
        target_y: Y coordinate of the navigation target.

    Returns:
        {
          'traveled_mm': float,                total distance moved
          'net_displacement_mm': float,        start to end, straight line
          'straightness_ratio': float,         traveled / net (inf if net ~ 0)
          'net_progress_to_target_mm': float,  positive = ended closer
        }
    """
    segments = _movement_segments(path, origin)
    if not segments:
        return {
            "traveled_mm": 0.0,
            "net_displacement_mm": 0.0,
            "straightness_ratio": float("inf"),
            "net_progress_to_target_mm": 0.0,
        }

    traveled = sum(_dist(x0, y0, x1, y1) for x0, y0, x1, y1 in segments)
    start_x, start_y = segments[0][0], segments[0][1]
    end_x, end_y = segments[-1][2], segments[-1][3]
    net = _dist(start_x, start_y, end_x, end_y)

    return {
        "traveled_mm": traveled,
        "net_displacement_mm": net,
        "straightness_ratio": (traveled / net) if net > 1e-6 else float("inf"),
        "net_progress_to_target_mm": (
            _dist(start_x, start_y, target_x, target_y)
            - _dist(end_x, end_y, target_x, target_y)
        ),
    }


def compute_path_leg_structure(
    path: list[PathStep],
    target_x: float,
    target_y: float,
    bearing_tolerance_deg: float = 15.0,
    min_leg_fraction: float = 0.15,
    origin: tuple[float, float] | None = None,
) -> dict:
    """Decompose the executed path into straight legs and the turns between them.

    Consecutive movement steps travelling in approximately the same direction
    are merged into one *leg*.  Legs shorter than min_leg_fraction of the total
    distance travelled are discarded as noise, and the transitions between the
    surviving legs describe the shape of the path:

        1 leg,  0 transitions              -> a direct run
        2 legs, 1 transition near 90 deg   -> an L-shaped / axis-aligned run
        3+ legs, 2+ transitions            -> repeated course correction

    Legs are grouped by *travel bearing* — the direction the robot actually
    moved — rather than by its heading field.  A student who steers with
    turn_to_heading blocks produces no relative turn angles at all, so
    code-derived turn features miss them entirely; travel bearing sees both
    styles identically.

    Callers should also require net_progress_to_target_mm > 0.  A serpentine
    sweep produces many legs and many transitions but never converges on the
    target, and that is what separates it from corrective navigation.

    Args:
        path:                   List of PathStep from SimulationResult.path.
        target_x:               X coordinate of the navigation target.
        target_y:               Y coordinate of the navigation target.
        bearing_tolerance_deg:  Direction change below this continues the
                                current leg instead of starting a new one.
        min_leg_fraction:       Legs shorter than this fraction of total travel
                                are dropped before transitions are computed.

    Returns:
        {
          'leg_count': int,                    substantial legs
          'leg_lengths_mm': list[float],
          'leg_bearings_deg': list[float],     0-360, math convention
          'transitions_deg': list[float],      0-180 between adjacent legs
          'primary_transition_deg': float|None,  between the two longest legs
          'major_transition_count': int,       transitions > bearing_tolerance
          'net_progress_to_target_mm': float,
        }
    """
    empty = {
        "leg_count": 0,
        "leg_lengths_mm": [],
        "leg_bearings_deg": [],
        "transitions_deg": [],
        "primary_transition_deg": None,
        "major_transition_count": 0,
        "net_progress_to_target_mm": 0.0,
    }

    segments = _movement_segments(path, origin)
    if not segments:
        return empty

    # --- merge consecutive steps sharing a travel bearing into legs --- #
    legs: list[list[float]] = []  # [bearing_deg, length_mm]
    for x0, y0, x1, y1 in segments:
        bearing = math.degrees(math.atan2(y1 - y0, x1 - x0)) % 360.0
        length = _dist(x0, y0, x1, y1)
        if legs and _angle_between(bearing, legs[-1][0]) <= bearing_tolerance_deg:
            # Length-weighted mean keeps a long leg from drifting on short steps.
            prev_bearing, prev_length = legs[-1]
            total = prev_length + length
            legs[-1][0] = _mean_bearing(prev_bearing, prev_length, bearing, length)
            legs[-1][1] = total
        else:
            legs.append([bearing, length])

    traveled = sum(length for _, length in legs)
    if traveled <= 0:
        return empty

    substantial = [(b, l) for b, l in legs if l >= min_leg_fraction * traveled]
    if not substantial:
        substantial = [max(legs, key=lambda leg: leg[1])]

    transitions = [
        _angle_between(substantial[i + 1][0], substantial[i][0])
        for i in range(len(substantial) - 1)
    ]

    primary = None
    if len(substantial) >= 2:
        longest = sorted(range(len(substantial)), key=lambda i: substantial[i][1])[-2:]
        i, j = min(longest), max(longest)
        primary = _angle_between(substantial[j][0], substantial[i][0])

    start_x, start_y = segments[0][0], segments[0][1]
    end_x, end_y = segments[-1][2], segments[-1][3]

    return {
        "leg_count": len(substantial),
        "leg_lengths_mm": [l for _, l in substantial],
        "leg_bearings_deg": [b for b, _ in substantial],
        "transitions_deg": transitions,
        "primary_transition_deg": primary,
        "major_transition_count": sum(
            1 for t in transitions if t > bearing_tolerance_deg
        ),
        "net_progress_to_target_mm": (
            _dist(start_x, start_y, target_x, target_y)
            - _dist(end_x, end_y, target_x, target_y)
        ),
    }


def compute_region_traversal_metrics(
    path: list[PathStep],
    region: "RegionBounds",
    robot_width_mm: float = 50.8,
    sample_interval_mm: float = _COVERAGE_GRID_CELL_MM / 2.0,
    bearing_tolerance_deg: float = 15.0,
    min_turn_deg: float = 30.0,
    min_leg_fraction_of_longest: float = 0.25,
    reversal_deg: float = 135.0,
    origin: tuple[float, float] | None = None,
) -> dict:
    """Describe how a path traverses a region: presence, recurrence, organization.

    One traversal of the movement segments produces every metric the area-traversal
    strategies need (`serpentine_sweep`, `cyclic_area_traversal`, `patchy_coverage`,
    `single_pass_traversal`), so the four detectors cannot disagree about what the
    robot did.

    This function deliberately does NOT compute a coverage fraction.  How much of
    the region was covered already has one owner — `region_coverage_fractions` on
    SimulationResult, footprint-aware via _coverage_cells_for_move — and callers
    must read it from there.  A second implementation here would drift: the
    simulator credits cells the robot occupies even while stationary (turning in
    place), whereas these metrics walk movement only, which is a real difference of
    about one cell on a small number of paths.

    `revisit_fraction` walks the CENTRE LINE, in order.  Footprint cells come back
    as an unordered set, which cannot express sequence, and revisitation is a claim
    about sequence.

    Revisitation counts CELL TRANSITIONS, not samples.  The centre line is sampled
    every half-cell, so consecutive samples land in the same cell by construction;
    counting samples would score roughly nine paths in ten as "revisiting" and
    measure the sampling rate rather than the robot's behaviour.

    Heading organization is measured over the WHOLE path, not the in-region clip.
    Clipping at the region boundary splits legs and manufactures turns the student
    never wrote.

    `alternating_turn_fraction` and `same_direction_turn_fraction` sum to exactly
    1.0 — they are one measurement seen from two sides, not two observations, and
    callers must treat them as mutually exclusive bands rather than independent
    evidence.  Both are 0.0 when fewer than two major turns occur, which is why
    `heading_organization_defined` exists: without checking it, "both fractions are
    low" is silently true of a straight line.

    Args:
        path:                   PathStep list from SimulationResult.path.
        region:                 RegionBounds for the traversal region.
        sample_interval_mm:     Centre-line sampling pitch (default half a cell).
        bearing_tolerance_deg:  Direction change below this continues the current
                                leg instead of starting a new one.
        min_turn_deg:           Leg-to-leg change at or above this is a major turn.
        min_leg_fraction_of_longest:
                                Legs shorter than this share of the longest leg are
                                dropped before turn structure is read, so a sweep's
                                short between-row connectors do not mask the rows.
        origin:                 Position before path[0].  REQUIRED for correctness —
                                without it the first movement is invisible, because
                                the trace only records a position after a block runs.

    Returns:
        {
          'traveled_mm', 'net_displacement_mm', 'path_closure_ratio',
          'in_region_distance_mm', 'path_fraction_in_region',
          'unique_cells_entered', 'cell_sequence_length', 'revisit_fraction',
          'leg_count', 'substantial_leg_count', 'opposed_heading_fraction',
          'major_turn_count', 'reversal_turn_count', 'turn_pair_count',
          'heading_organization_defined',
          'alternating_turn_fraction', 'same_direction_turn_fraction',
        }
    """
    empty = {
        "traveled_mm": 0.0,
        "net_displacement_mm": 0.0,
        "path_closure_ratio": 1.0,
        "in_region_distance_mm": 0.0,
        "path_fraction_in_region": 0.0,
        "unique_cells_entered": 0,
        "cell_sequence_length": 0,
        "revisit_fraction": 0.0,
        "leg_count": 0,
        "substantial_leg_count": 0,
        "opposed_heading_fraction": 0.0,
        "major_turn_count": 0,
        "reversal_turn_count": 0,
        "turn_pair_count": 0,
        "heading_organization_defined": False,
        "alternating_turn_fraction": 0.0,
        "same_direction_turn_fraction": 0.0,
    }

    segments = _movement_segments(path, origin)
    if not segments or region is None:
        return empty

    pitch = max(1.0, sample_interval_mm)

    traveled = 0.0
    in_region = 0.0
    cell_walk: list[tuple[int, int]] = []

    for x0, y0, x1, y1 in segments:
        length = _dist(x0, y0, x1, y1)
        traveled += length

        n = max(2, int(length / pitch) + 1)
        inside = 0
        for i in range(n + 1):
            t = i / n
            x = x0 + t * (x1 - x0)
            y = y0 + t * (y1 - y0)
            if region.contains(x, y):
                inside += 1
                cell = (
                    int(math.floor(x / _COVERAGE_GRID_CELL_MM)),
                    int(math.floor(y / _COVERAGE_GRID_CELL_MM)),
                )
                # Append only on a genuine cell change — see docstring.
                if not cell_walk or cell_walk[-1] != cell:
                    cell_walk.append(cell)
        in_region += length * (inside / (n + 1))

    if traveled <= 0:
        return empty

    seen: set = set()
    revisits = 0
    for cell in cell_walk:
        if cell in seen:
            revisits += 1
        else:
            seen.add(cell)

    start_x, start_y = segments[0][0], segments[0][1]
    end_x, end_y = segments[-1][2], segments[-1][3]
    net = _dist(start_x, start_y, end_x, end_y)

    # --- heading organization over the whole path --- #
    legs: list[list[float]] = []
    for x0, y0, x1, y1 in segments:
        bearing = math.degrees(math.atan2(y1 - y0, x1 - x0)) % 360.0
        length = _dist(x0, y0, x1, y1)
        if legs and _angle_between(bearing, legs[-1][0]) <= bearing_tolerance_deg:
            prev_bearing, prev_length = legs[-1]
            legs[-1][0] = _mean_bearing(prev_bearing, prev_length, bearing, length)
            legs[-1][1] = prev_length + length
        else:
            legs.append([bearing, length])

    # Keep only substantial legs before reading turn structure.  A lawnmower
    # sweep joins its rows with a short connector, and the two 90-degree turns
    # around that connector go the SAME way — so counting every leg scores a
    # textbook sweep at roughly 0.4 alternating and files it under irregular
    # movement.  Dropping the connectors leaves the rows, which alternate
    # perfectly.  The threshold is relative to the LONGEST leg, not to total
    # travel, because a fraction-of-total rule tightens as rows are added and
    # would start discarding the rows themselves on a long sweep.
    longest = max((length for _, length in legs), default=0.0)
    cutoff = min_leg_fraction_of_longest * longest
    substantial = [leg for leg in legs if leg[1] >= cutoff] or legs

    turns: list[float] = []
    for i in range(1, len(substantial)):
        delta = (substantial[i][0] - substantial[i - 1][0] + 180.0) % 360.0 - 180.0
        if abs(delta) >= min_turn_deg:
            turns.append(delta)

    # A turn of almost exactly 180 degrees has no meaningful sign: left-180 and
    # right-180 end in the same place, and the signed delta collapses to -180
    # either way.  Row reversals in a sweep are exactly that turn, so scoring
    # them by sign would read every lawnmower as perfectly same-direction —
    # i.e. as circling.  A reversal is therefore counted as a change of
    # direction on its own terms, which is what it is.
    # A reversal always changes the sense of travel relative to whatever came
    # before it, so it takes the opposite sign to the previous turn rather than
    # a sign of its own.  Comparing signs then works uniformly: a sweep's row
    # reversals alternate, a lap's quarter-turns do not.
    reversals = [abs(t) >= reversal_deg for t in turns]
    signs: list[int] = []
    for i, t in enumerate(turns):
        if reversals[i]:
            signs.append(-signs[i - 1] if i > 0 else 1)
        else:
            signs.append(1 if t > 0 else -1)

    # Share of substantial travel lying along a single AXIS (bearings taken
    # modulo 180, so a row and the row back count as the same axis).  Reversing
    # direction is not by itself a sweep — a random wander reverses constantly.
    # What makes a sweep is that its passes are PARALLEL, and that is what this
    # measures.
    axis_total = sum(length for _, length in substantial)
    opposed_fraction = 0.0
    if axis_total > 0:
        for candidate_bearing, _ in substantial:
            candidate_axis = candidate_bearing % 180.0
            aligned = sum(
                length for bearing, length in substantial
                if min(
                    abs(bearing % 180.0 - candidate_axis),
                    180.0 - abs(bearing % 180.0 - candidate_axis),
                ) <= bearing_tolerance_deg
            )
            opposed_fraction = max(opposed_fraction, aligned / axis_total)

    turn_pairs = max(0, len(turns) - 1)
    defined = turn_pairs >= 1
    if defined:
        alternating = sum(
            1 for i in range(turn_pairs) if signs[i] != signs[i + 1]
        ) / turn_pairs
        same_direction = 1.0 - alternating
    else:
        alternating = 0.0
        same_direction = 0.0

    return {
        "traveled_mm": traveled,
        "net_displacement_mm": net,
        "path_closure_ratio": net / traveled,
        "in_region_distance_mm": in_region,
        "path_fraction_in_region": in_region / traveled,
        "unique_cells_entered": len(seen),
        "cell_sequence_length": len(cell_walk),
        "revisit_fraction": revisits / len(cell_walk) if cell_walk else 0.0,
        "leg_count": len(legs),
        "substantial_leg_count": len(substantial),
        "opposed_heading_fraction": opposed_fraction,
        "major_turn_count": len(turns),
        "reversal_turn_count": sum(reversals),
        "turn_pair_count": turn_pairs,
        "heading_organization_defined": defined,
        "alternating_turn_fraction": alternating,
        "same_direction_turn_fraction": same_direction,
    }


def _angle_between(a_deg: float, b_deg: float) -> float:
    """Smallest absolute angle between two bearings, in [0, 180]."""
    diff = abs(a_deg - b_deg) % 360.0
    return min(diff, 360.0 - diff)


def _mean_bearing(a_deg: float, a_w: float, b_deg: float, b_w: float) -> float:
    """Weighted circular mean of two bearings, in [0, 360)."""
    total = a_w + b_w
    if total <= 0:
        return a_deg
    ar, br = math.radians(a_deg), math.radians(b_deg)
    x = (math.cos(ar) * a_w + math.cos(br) * b_w) / total
    y = (math.sin(ar) * a_w + math.sin(br) * b_w) / total
    return math.degrees(math.atan2(y, x)) % 360.0


# ------------------------------------------------------------------ #
# Coverage sampling helper (used by both _Simulator and slice_sim_result)
# ------------------------------------------------------------------ #

def _coverage_cells_for_move(
    x0: float, y0: float,
    x1: float, y1: float,
    heading_deg: float,
    robot_width_mm: float,
    region: "RegionBounds",
) -> set:
    """Return the set of 100mm grid cells swept by a single movement segment.

    Samples along the centerline at half-cell intervals and at ±robot_width/2
    laterally, matching the full-simulation sampling used by _Simulator.
    """
    cells: set = set()
    half_width = robot_width_mm / 2.0
    perp_rad = math.radians(heading_deg + 90.0)
    perp_x = math.cos(perp_rad)
    perp_y = math.sin(perp_rad)
    lateral_offsets = (-half_width, 0.0, half_width)
    dist = math.sqrt((x1 - x0) ** 2 + (y1 - y0) ** 2)
    n_samples = max(2, int(dist / (_COVERAGE_GRID_CELL_MM / 2)) + 1)
    for i in range(n_samples + 1):
        t = i / n_samples
        cx = x0 + t * (x1 - x0)
        cy = y0 + t * (y1 - y0)
        for offset in lateral_offsets:
            x = cx + offset * perp_x
            y = cy + offset * perp_y
            if region.contains(x, y):
                cells.add((
                    int(math.floor(x / _COVERAGE_GRID_CELL_MM)),
                    int(math.floor(y / _COVERAGE_GRID_CELL_MM)),
                ))
    return cells


# ------------------------------------------------------------------ #
# Internal simulator
# ------------------------------------------------------------------ #

from ..parsing.block_program import BlockNode, BlockProgram, MAGNET_BLOCK_TYPES, SENSOR_BLOCK_TYPES


class _Simulator:
    def __init__(self, context: PlaygroundContext):
        self.ctx = context
        self.x = context.spawn_x
        self.y = context.spawn_y
        self.heading = context.spawn_heading
        self.step = 0
        self.path: list[PathStep] = []

        # Magnet state
        self.magnet_active = False
        self.magnet_fires_at_step: Optional[int] = None

        # Per-object tracking
        self.min_dist_to_objects: dict[str, float] = {
            obj_id: _dist(context.spawn_x, context.spawn_y, obj.x, obj.y)
            for obj_id, obj in context.objects.items()
        }
        self.first_tol_steps: dict[str, Optional[int]] = {
            obj_id: None for obj_id in context.objects
        }
        self.first_seg_steps: dict[str, Optional[int]] = {
            obj_id: None for obj_id in context.objects
        }

        # Per-region coverage
        self.region_cells: dict[str, set] = {
            region_id: set() for region_id in context.regions
        }
        self.regions_entered: set[str] = set()

        # Boundary
        self.exits_boundary = False
        self.min_dist_center = math.sqrt(context.spawn_x**2 + context.spawn_y**2)

        # Loop capping
        self.loop_was_capped = False
        self.loop_cap_steps: list[int] = []      # stage 0b: per-span fidelity
        self.unknown_reporter_blocks: list[str] = []   # stage 0b: recorded, not raised

        # Task 3 Part A: inline broadcast execution
        self.receivers: dict[str, list] = {}     # BROADCAST_OPTION -> receiver stacks
        self.active_broadcasts: set[str] = set()  # recursion guard
        # OI-23 procedures build (2026-08-24): proccode -> body (the
        # definition's next-chain). Calls execute the body inline,
        # synchronously — a stall or forever inside the body faithfully
        # stalls/stops the caller.
        self.procedures: dict[str, object] = {}
        self._active_procs: set[tuple] = set()      # recursion guard
        self.execution_flags: list[str] = []      # program-level fidelity flags
        self.fabricated_steps: list[int] = []     # Part D: fallback-motion steps
        self.color_detections: list[tuple] = []   # sensing: (step, eye, color) True-evals

        # Sensing build Phase 2 (2026-08-19)
        self.object_contacts: dict[str, int] = {}  # target id -> first contact step
        self.pending_sensor_hats: list = []           # deferred sensor-hat stacks (fire on detection)
        self._sensor_hats_latched: set = set()        # hats with a mid-move false->true transition
        self._hat_prev_state: dict = {}               # id(hat) -> condition at last check
        self.sensor_hats_fired: dict = {}             # hat block_id -> [fire/restart steps]
        self._in_sensor_hat = False                   # reentrancy guard
        self._active_hat = None                       # hat whose stack is executing
        # OI-7 lockout (reviewer-probed rule, built 2026-08-25): when creation
        # order resolves, the most recently created when_started stack owns
        # the drivetrain OUTRIGHT — losers' drivetrain commands are no-ops.
        self.lockout_losers: frozenset = frozenset()  # losing when_started ids
        self.stack_lockout_winner = None
        self._current_root_id = None                  # top-level stack being run
        # VR-Seq (Stage 2): the cooperative Sequencer, when active. None in
        # sequential mode — every _coop() branch then takes the legacy path.
        self._sequencer = None
        self._current_thread_idx = None               # cooperative: thread index
        self.loop_iteration_time_s = 0.0              # deferred wall clock (spec §8)
        self.motions_superseded = 0                   # measured-policy provenance
        self.drivetrain_contentions = 0
        self.time_budget_s = None                     # observed-run wall budget
        # Predicate bracketing (§12.4/G-close-out step 2, 2026-08-26):
        # None = model; "floor" = movable targets undetectable after first
        # disturbance; "ceiling" = movable-consulting boolean predicates
        # forced TRUE after first disturbance. Verdict invariance across the
        # bracket clears a run; divergence U-gates it.
        self.movable_predicates = None
        # A3 rotation build (reviewer-directed 2026-08-26): VEX cumulative
        # drive rotation, CW-positive, 0 at spawn — heading mod 360 loses
        # revolutions; turn_to_rotation and the drive_rotation reporter
        # need the accumulator.
        self.drive_rotation_deg = 0.0
        self.loops_exercised: dict = {}     # A2: block_id -> iterations run
        self.branches_exercised: dict = {}  # A2: block_id -> [arms taken]
        self.structure_trace: list = []     # A2: (thread, event, block, detail)

        # Test-case harness (sensing Phase 5): everything below is inert
        # unless the card's testcase_physics section enables it.
        tp = context.testcase_physics or {}
        self.push_model: str | None = tp.get("push_model")
        # The push model MUTATES piece positions — isolate copies per run.
        self.live_pieces: list[ObjectRef] = (
            [_copy.copy(p) for p in context.pieces] if self.push_model
            else list(context.pieces))
        self.pieces_cleared: dict[str, int] = {}   # piece id -> step pushed off
        self.forever_unroll: int = int(tp.get("loop_unroll") or _FOREVER_UNROLL)
        # Faithful forever nesting (reviewer ruling 2026-08-24, OI-24): a
        # forever NEVER exits in reality (absent break), so once an inner
        # forever runs to its unroll cap, every ENCLOSING loop stops
        # iterating — the outer loop would never have reached iteration 2.
        # forever{A; forever{B}} therefore executes A once then B capped:
        # EXACT semantics, and it collapses CROW-C015-style nesting (depth
        # 47, 20^depth blowup) to linear cost. Scoped deliberately to
        # forever: a capped repeat_until/while MIGHT have exited legitimately,
        # so their caps do not stop outer loops. Cleared per top-level stack;
        # saved/restored around sensor-hat firing (parallel programs).
        self._forever_completed: bool = False
        self.execution_budget: int = int(context.execution_budget_blocks
                                         or _EXECUTION_BUDGET_BLOCKS)
        self.blocks_executed: int = 0
        self.max_unroll: int = int(tp.get("loop_unroll") or _MAX_UNROLL_ITERATIONS)
        # Late materialization (Option A): pieces awaiting activation are
        # invisible to sensors, contact, and the push model. Relative pieces
        # resolve their position against the robot's pose at activation.
        self._pending_piece_ids: set[str] = {
            p.object_id for p in self.live_pieces
            if p.active_from_step > 0 or p.rel_ahead_mm is not None}
        self.piece_positions: dict[str, tuple[float, float]] = {
            p.object_id: (p.x, p.y) for p in self.live_pieces
            if p.object_id not in self._pending_piece_ids}
        self.sensor_first_eval: dict[str, tuple[int, str]] = {}
        self._maybe_activate_pieces()

        # Movement tracking — used to guard sensor-conditioned if_then branches.
        # Position-dependent sensors (optical, bumper, distance) cannot fire at
        # spawn. If the robot has not moved at all when an if_then with a sensor
        # condition is reached, the branch body is unreachable and should not be
        # executed (doing so produces phantom movement).
        self.has_moved = False

        # Velocity state — updated by set_drive/turn_velocity blocks
        self.drive_velocity_mm_per_s: float = _DEFAULT_DRIVE_VELOCITY_MM_PER_S
        self.turn_velocity_deg_per_s: float = _DEFAULT_TURN_VELOCITY_DEG_PER_S

        # Pending continuous motion — set by bare drive/turn, consumed by wait
        # (velocity x time), cleared by any drivetrain command, or resolved at
        # normal program end by finish_pending_motion().
        self.pending_drive_dir: float | None = None  # +1 fwd, -1 rev
        self.pending_turn_dir: float | None = None   # +1 left/CCW, -1 right/CW
        self.pending_drive_block = None              # the arming block, for step attribution
        self.pending_turn_block = None

        # Pen drawing state
        self.pen_down: bool = False
        self.pen_color: str = "black"
        self.pen_width_name: str = "medium"
        self.pen_segments: list = []  # (x0, y0, x1, y1, color, width_name)

        # Simulated timer (accumulates from explicit wait blocks)
        self.sim_time_s: float = 0.0   # total elapsed simulation time
        self.timer_s: float = 0.0     # resettable timer (reset_timer zeroes this)

        # Variable store — used by set/change variable blocks and by _eval_expression
        self.variables: dict[str, float] = {}

    # ---------------------------------------------------------------- #
    # Block execution
    # ---------------------------------------------------------------- #

    def _flag(self, name: str) -> None:
        if name not in self.execution_flags:
            self.execution_flags.append(name)

    def _loop_tick(self, iter_start_time: float) -> None:
        """60Hz loop clock (measured 60.15Hz, SCHEDULING_MODEL §11): VEX's
        forked control blocks give every loop iteration a 5ms stack timer +
        requestRedraw, rate-limiting to ~one iteration per tick. When
        enabled, top an iteration's elapsed time up to the tick floor —
        iterations whose body already consumed >= a tick (motion, waits)
        cost nothing extra."""
        if self.loop_iteration_time_s <= 0:
            return
        elapsed = self.sim_time_s - iter_start_time
        if elapsed < self.loop_iteration_time_s:
            top_up = self.loop_iteration_time_s - elapsed
            self.sim_time_s += top_up
            self.timer_s += top_up

    def _coop(self) -> bool:
        """True when the executing code should PARK on the Sequencer rather
        than run motion inline: cooperative mode, and not inside a sensor-hat
        stack (hats stay inline in phase 1 — spec §2.5)."""
        return (self._sequencer is not None and not self._in_sensor_hat
                and self._active_hat is None)

    def execute_stack(self, node: Optional[BlockNode]):
        """GENERATOR (VR-Seq Stage 1, 2026-08-26): yields at the scheduler's
        yield points (loop back-edges; later, motion parks). Sequential-mode
        drivers drain it — in that mode every yield is a no-op, preserving
        the pre-generator behavior byte-for-byte (gate G1)."""
        current = node
        while current is not None:
            yield from self.execute_block(current)
            current = current.next

    def _maybe_activate_pieces(self) -> None:
        """Late materialization (Option A, reviewer-approved 2026-08-19):
        activate pending pieces whose step has arrived, resolving relative
        placements against the robot's CURRENT pose — the piece appears
        right before the tested code fires, wherever the robot is by then."""
        if not self._pending_piece_ids:
            return
        for piece in self.live_pieces:
            if piece.object_id not in self._pending_piece_ids:
                continue
            if self.step < piece.active_from_step:
                continue
            if piece.rel_ahead_mm is not None:
                ang = math.radians(self.heading + piece.rel_bearing_deg)
                piece.x = self.x + piece.rel_ahead_mm * math.cos(ang)
                piece.y = self.y + piece.rel_ahead_mm * math.sin(ang)
            self._pending_piece_ids.discard(piece.object_id)
            self.piece_positions[piece.object_id] = (piece.x, piece.y)

    def _sensor_targets(self) -> "list[ObjectRef]":
        """Bodies sensors can currently perceive: named objects plus live
        pieces, minus pieces cleared off the island (testcase push model) or
        not yet materialized (Option A) — a cleared piece vanishes from every
        sensor, which is itself the stop cue some strategies rely on (bumper
        releases, eye loses the object)."""
        targets = list(self.ctx.objects.values()) + [
            p for p in self.live_pieces
            if p.object_id not in self.pieces_cleared
            and p.object_id not in self._pending_piece_ids]
        if self.movable_predicates == "floor" \
                and self._movable_world_disturbed():
            targets = [t for t in targets if not getattr(t, "movable", False)]
        return targets

    def _hat_detects(self, hat: BlockNode) -> bool:
        """Whether a deferred sensor hat's trigger condition holds at the
        current (possibly virtual) pose. Eye hats: modeled eye presence.
        Bumper hats (Phase 4): bumper contact. Timer hats (OI-23 build,
        2026-08-24): the resettable timer has crossed the threshold —
        monotonic between resets, so the between-blocks check never misses
        a crossing (fires at most one block late)."""
        if hat.block_type == _HAT_TIMER:
            return self.timer_s >= self._get_numeric(hat, "AMOUNT")
        if self.movable_predicates == "ceiling" \
                and self._movable_world_disturbed():
            return True
        if hat.block_type == _HAT_BUMPER:
            return self._bumper_pressed(hat.get_field("BUMPER") or "")
        return self._eye_near_object(self._eye_from_block(hat))

    def _bumper_pressed(self, selector: str) -> bool:
        if self.movable_predicates == "ceiling" \
                and self._movable_world_disturbed():
            return True
        """Bumper switch state (sensing Phase 4): pressed when the bumper's
        mount point is in contact with a declared 3D body (surface reached).
        Mount geometry comes from the shared robot card; no card = no model
        (callers guard). Selector 'leftbumper'/'rightbumper'; anything else
        checks both."""
        spec = self.ctx.sensor_specs.get("bumpers") or {}
        sel = selector.lower()
        names = [n for n in ("left_bumper", "right_bumper")
                 if isinstance(spec.get(n), dict)]
        if "left" in sel:
            names = [n for n in names if n == "left_bumper"]
        elif "right" in sel:
            names = [n for n in names if n == "right_bumper"]
        if not names:
            return False
        rad = math.radians(self.heading)
        fx, fy = math.cos(rad), math.sin(rad)      # forward unit
        lx, ly = -fy, fx                           # left unit
        for name in names:
            mount = spec[name]
            fwd = float(mount.get("mount_forward_mm", 0.0) or 0.0)
            lat = float(mount.get("mount_lateral_mm", 0.0) or 0.0)
            bx = self.x + fwd * fx + lat * lx
            by = self.y + fwd * fy + lat * ly
            for target in self._sensor_targets():
                if target.body_radius_mm is None:
                    continue
                if _dist(bx, by, target.x, target.y) <= target.body_radius_mm:
                    if spec.get("assumed"):
                        self._flag("sensor_model_assumed")
                    contact = self.object_contacts.get(target.object_id)
                    if target.movable and contact is not None and contact < self.step:
                        self._flag("sensor_reading_stale")
                    return True
        return False

    _HAT_SAMPLE_MM = 50.0   # mid-move detection sampling (simulation quality constant)

    def _latch_sensor_hats_along(self, x0: float, y0: float, x1: float, y1: float) -> None:
        """Sample the just-traversed segment for deferred sensor-hat
        detections (sensing Phases 2/4). Hats are asynchronous interrupts: a
        body the cone sweeps over — or the bumper hits — MID-DRIVE must
        latch the hat even though execution joins at the next block boundary
        — the same sequential approximation used for broadcast concurrency.
        Virtual positions; state restored."""
        if not self.pending_sensor_hats:
            return
        n = max(1, int(_dist(x0, y0, x1, y1) / self._HAT_SAMPLE_MM))
        sx, sy = self.x, self.y
        try:
            for hat in self.pending_sensor_hats:
                if hat is self._active_hat:
                    continue   # the active hat restarts via the _move pre-scan
                # Edge-triggered (reviewer ruling 2026-08-24): the real hat
                # re-fires on every NEW detection event, not once. Walk the
                # samples carrying the hat's previous condition; a
                # false->true transition anywhere along the move latches a
                # firing event; the final sample becomes the new prev.
                prev = self._hat_prev_state.get(id(hat), False)
                for i in range(n + 1):
                    t = i / n
                    self.x = x0 + (x1 - x0) * t
                    self.y = y0 + (y1 - y0) * t
                    now = self._hat_detects(hat)
                    if now and not prev:
                        self._sensor_hats_latched.add(id(hat))
                    prev = now
                self._hat_prev_state[id(hat)] = prev
        finally:
            self.x, self.y = sx, sy

    def fire_ready_sensor_hats(self) -> None:
        """Fire any deferred sensor-hat stack with a NEW detection event —
        a mid-move false->true transition (latched) or an edge at the
        current pose. EDGE-TRIGGERED AND RE-ARMING (reviewer ruling
        2026-08-24, replacing the fires-at-most-once modelling choice): the
        real runtime continually checks and re-runs the hat program on
        every new detection event — e.g. a hat whose motion disturbs pieces
        can re-trigger repeatedly. In our static world, re-fires happen on
        genuine re-entries of the condition (a continuously-true condition
        is ONE edge, so no infinite loops; the execution budget backstops).
        """
        if not self.pending_sensor_hats or self._in_sensor_hat:
            return
        ready = []
        for h in self.pending_sensor_hats:
            if id(h) in self._sensor_hats_latched:
                ready.append(h)
                continue
            now = self._hat_detects(h)
            if now and not self._hat_prev_state.get(id(h), False):
                ready.append(h)
            self._hat_prev_state[id(h)] = now
        if not ready:
            return
        self._in_sensor_hat = True
        saved_forever = self._forever_completed   # hats are parallel programs
        try:
            for hat in ready:
                self._sensor_hats_latched.discard(id(hat))
                self._forever_completed = False
                # RESTART semantics (reviewer probe 2026-08-24): a new
                # detection edge during the hat's own execution abandons the
                # current block (the in-flight move truncates at the
                # detection point — see the _move pre-scan) and re-runs the
                # script from the top. Restarts are capped like loop unrolls
                # (the real cascade can be endless; we stop watching and
                # flag) and the execution budget backstops everything.
                self._active_hat = hat
                restarts = 0
                try:
                    while True:
                        self.sensor_hats_fired.setdefault(
                            hat.block_id, []).append(self.step)
                        try:
                            # hats never park in phase 1 — drain the
                            # generator inline (loop-yields are no-ops here)
                            for _ in self.execute_stack(hat.next):
                                pass
                            break
                        except _HatRestartSignal:
                            restarts += 1
                            if restarts >= self.forever_unroll:
                                self._flag("hat_restart_capped")
                                break
                        except _GateSignal:
                            break   # gated hat stack stalls; stays armed
                finally:
                    self._active_hat = None
                # condition state AFTER the hat's own motion becomes the new
                # baseline — still-true does not re-fire; a later re-entry does
                self._hat_prev_state[id(hat)] = self._hat_detects(hat)
        finally:
            self._forever_completed = saved_forever
            self._in_sensor_hat = False

    def execute_block(self, block: BlockNode):
        # GENERATOR (VR-Seq Stage 1) — see execute_stack. All `return`s are
        # generator returns; loop branches yield per iteration.
        self.blocks_executed += 1
        if self.blocks_executed > self.execution_budget:
            self._flag("execution_budget_exhausted")
            raise _BudgetSignal()
        if self.time_budget_s is not None \
                and self.sim_time_s >= self.time_budget_s:
            # the observed run duration elapsed: the real run was ended
            # here — halt everything, no terminal runoff (like a stop)
            self._flag("time_budget_exhausted")
            raise _BudgetSignal()
        self._maybe_activate_pieces()
        self.fire_ready_sensor_hats()
        bt = block.block_type

        # ---- Magnet ----
        if bt in MAGNET_BLOCK_TYPES:
            action = (block.get_field("ACTION") or block.get_field("STATE") or "").lower()
            if action == "boost" and not self.magnet_active:
                self.magnet_active = True
                self.magnet_fires_at_step = self.step
                self._record_step(block, magnet_fires=True)
                self.step += 1
            return

        # ---- OI-7 lockout gate (2026-08-25) ----
        # The winning when_started stack owns the drivetrain OUTRIGHT
        # (reviewer probe: losers' drives were completely absent, never
        # executed even briefly). Suppress every drivetrain command executed
        # in a losing stack's scope — velocity setters included — skipped
        # instantly with no state change. Detection-hat stacks are outside
        # OI-7's scope (_active_hat set): their restart semantics govern.
        if (bt.startswith("pg_drivetrain_")
                and self._current_root_id in self.lockout_losers
                and self._active_hat is None):
            return

        # ---- Set velocity ----
        if bt == "pg_drivetrain_set_drive_velocity":
            # Clamped to a real percentage: the sample contains VELOCITY = inf and
            # 123456789.  Unclamped, `inf` persists in simulator state and
            # `inf * 0` (a zero-length wait) yields NaN, which silently poisons
            # every downstream metric rather than producing a large number.
            raw_pct = self._get_numeric(block, "VELOCITY")
            if raw_pct == 0:
                self._flag("zero_velocity_assumed")
            pct = _clamp_percent(raw_pct or 50.0)
            self.drive_velocity_mm_per_s = pct * 9.88  # calibrated 2026-08-19 (OI-16)
            return

        if bt == "pg_drivetrain_set_turn_velocity":
            raw_pct = self._get_numeric(block, "VELOCITY")
            if raw_pct == 0:
                self._flag("zero_velocity_assumed")
            pct = _clamp_percent(raw_pct or 50.0)
            self.turn_velocity_deg_per_s = pct * 4.16  # calibrated 2026-08-19 (OI-16)
            return

        # ---- Drive for distance ----
        if bt == "pg_drivetrain_drive_for":
            self._clear_pending_motion()
            direction = (block.get_field("DIRECTION") or "fwd").lower()
            dist_mm = self._get_discrete(block, "AMOUNT")
            units = block.get_field("UNITS") or "mm"
            dist_mm = _to_mm(dist_mm, units)
            if direction in ("reverse", "rev", "back", "backward"):
                dist_mm = -dist_mm
            if self._coop():
                # VR-Seq: blocking motion parks the thread (STATUS_PROMISE_WAIT)
                self._clear_pending_motion()
                self._sequencer.notify_drivetrain_command()
                yield _Park("motion", block, mode="drive",
                            sign=1.0 if dist_mm >= 0 else -1.0,
                            magnitude=abs(dist_mm))
                return
            self._move(dist_mm, block)
            return

        # ---- Continuous drive (no distance) ----
        if bt == "pg_drivetrain_drive":
            direction = (block.get_field("DIRECTION") or "fwd").lower()
            sign = -1.0 if direction in ("reverse", "rev", "back", "backward") else 1.0
            # Continuous-motion semantics (reviewer decision, refined
            # 2026-08-18): the drive continues until the next DRIVETRAIN
            # command activates. Arm pending motion: a later `wait` converts
            # it to velocity × time (velocity setters do not clear pending —
            # a speed change applies to the continuing motion), any drivetrain
            # command clears it, instant blocks pass through leaving it armed.
            # Pending still armed at normal program end = the robot drives
            # indefinitely until failure (finish_pending_motion).
            self._clear_pending_motion()
            if self._coop():
                self._sequencer.notify_drivetrain_command()
            self.pending_drive_dir = sign
            self.pending_drive_block = block
            return

        # ---- Continuous turn (no angle) ----
        if bt == "pg_drivetrain_turn":
            turn_dir = (block.get_field("TURNDIRECTION") or "left").lower()
            sign = 1.0 if turn_dir == "left" else -1.0  # left=CCW=+heading in math convention
            # Continuous-motion semantics (refined 2026-08-18): the turn
            # continues until the next drivetrain command. Arm pending
            # rotation; `wait` converts it to turn-velocity × time, any
            # drivetrain command clears it, instant blocks leave it armed.
            # Pending still armed at normal program end -> nominal 90°
            # fallback (finish_pending_motion).
            self._clear_pending_motion()
            if self._coop():
                self._sequencer.notify_drivetrain_command()
            self.pending_turn_dir = sign
            self.pending_turn_block = block
            return

        # ---- Wait — consume pending continuous motion ----
        if bt == "pg_control_wait":
            wait_s = self._get_discrete(block, "TIME")  # walks into child NUM field
            if wait_s <= 0:
                return
            if self._coop():
                # VR-Seq: the wait parks the THREAD; armed motion continues
                # via the slice mechanism (WREN-C048 falls out of it)
                yield _Park("time", block, seconds=wait_s)
                return
            self.sim_time_s += wait_s
            self.timer_s += wait_s
            if self.pending_drive_dir is not None:
                # Reviewer ruling (2026-08-24, WREN-C048): the wait does NOT
                # stop the drivetrain — a bare drive KEEPS DRIVING after the
                # wait expires until another drivetrain command intervenes
                # (or terminal runoff at program end). Commit the
                # wait-duration motion and LEAVE the drive pending.
                dist_mm = self.pending_drive_dir * self.drive_velocity_mm_per_s * wait_s
                self._move(dist_mm, block, add_time=False)
            elif self.pending_turn_dir is not None:
                # same ruling: the turn keeps turning after the wait
                angle = self.pending_turn_dir * self.turn_velocity_deg_per_s * wait_s
                self.heading = (self.heading + angle) % 360
                self.drive_rotation_deg -= angle
                self._record_step(block)
                self.step += 1
            # else: pure pause with no pending motion → no-op
            return

        # ---- Turn by angle ----
        if bt == "pg_drivetrain_turn_for":
            self._clear_pending_motion()
            turn_dir = (block.get_field("TURNDIRECTION") or "right").lower()
            angle = self._get_discrete(block, "AMOUNT")
            units = block.get_field("UNITS") or "deg"
            if "pct" in units or "percent" in units:
                angle = angle * 3.6
            if self._coop():
                self._sequencer.notify_drivetrain_command()
                # sign convention matches the legacy heading update below:
                # left = CCW = +heading; a negative AMOUNT inverts
                sign = (1.0 if turn_dir == "left" else -1.0) \
                    * (1.0 if angle >= 0 else -1.0)
                yield _Park("motion", block, mode="turn",
                            sign=sign, magnitude=abs(angle))
                return
            dt = abs(angle) / max(self.turn_velocity_deg_per_s, 1e-9)
            self.sim_time_s += dt
            self.timer_s += dt
            if turn_dir == "left":
                self.heading = (self.heading + angle) % 360
                self.drive_rotation_deg -= angle
            else:
                self.heading = (self.heading - angle) % 360
                self.drive_rotation_deg += angle
            self._record_step(block)
            self.step += 1
            return

        # ---- Turn to absolute heading ----
        # ---- Turn to an absolute heading ----
        if bt == "pg_drivetrain_turn_to_heading":
            self._clear_pending_motion()
            card_heading = self._get_discrete(block, "HEADING", "ANGLE", "AMOUNT")
            target = card_heading_to_math(card_heading)
            # A3 rotation build (2026-08-26): the turn takes TIME — the
            # shortest-path delta at the calibrated turn velocity (was
            # instant; contaminated the duration channel for 530 runs)
            delta = (target - self.heading + 180.0) % 360.0 - 180.0
            if self._coop():
                self._sequencer.notify_drivetrain_command()
                yield _Park("motion", block, mode="turn", sign=1.0 if delta >= 0 else -1.0, magnitude=abs(delta))
                return
            dt = abs(delta) / max(self.turn_velocity_deg_per_s, 1e-9)
            self.sim_time_s += dt
            self.timer_s += dt
            self.drive_rotation_deg -= delta
            self.heading = target
            self._record_step(block)
            self.step += 1
            return

        # ---- Turn to an absolute cumulative rotation ----
        #
        # `turn to rotation` sweeps a cumulative measure, so it may pass through
        # several full revolutions where `turn to heading` takes the short way
        # round.  The robot turns in place either way, so the PATH is identical
        # and only the FINAL heading matters here — which is the rotation value
        # reduced modulo 360.  The distinction would matter for elapsed time and
        # for the `drive rotation` sensor, neither of which is modelled yet.
        if bt == "pg_drivetrain_turn_to_rotation":
            self._clear_pending_motion()
            rotation = self._get_discrete(block, "ROTATION", "AMOUNT", "ANGLE")
            # A3 rotation build (2026-08-26): rotation is CUMULATIVE (CW+,
            # 0 at spawn) — the turn magnitude is the delta from the
            # accumulator (heading mod 360 loses revolutions), and it takes
            # time. The heading endpoint expression is kept bit-identical
            # to the legacy form (spawn is VEX heading 0, so the absolute
            # and spawn-relative readings coincide — attribution note).
            delta_vex = rotation - self.drive_rotation_deg
            if self._coop():
                self._sequencer.notify_drivetrain_command()
                yield _Park("motion", block, mode="turn", sign=-1.0 if delta_vex >= 0 else 1.0, magnitude=abs(delta_vex))
                return
            dt = abs(delta_vex) / max(self.turn_velocity_deg_per_s, 1e-9)
            self.sim_time_s += dt
            self.timer_s += dt
            self.drive_rotation_deg = rotation
            self.heading = card_heading_to_math(rotation % 360.0)
            self._record_step(block)
            self.step += 1
            return

        # ---- Gyro calibration — relabels the heading, moves nothing ----
        #
        # `set drive heading` / `set drive rotation` set what the gyro REPORTS.
        # They were previously routed through the turn_to_heading branch, which
        # physically rotated the robot for a block whose own description is
        # "Sets the gyro's current heading to a specified value".
        if bt in ("pg_drivetrain_set_heading", "pg_drivetrain_set_drive_heading",
                  "pg_drivetrain_set_drive_rotation"):
            self._clear_pending_motion()
            return

        # ---- Stop ----
        if bt in ("pg_drivetrain_stop", "pg_drivetrain_stop_driving"):
            self._clear_pending_motion()
            if self._coop():
                self._sequencer.notify_drivetrain_command()
            self._record_step(block)
            self.step += 1
            return

        # ---- Control flow ----
        if bt == "pg_control_break":
            raise _BreakSignal()

        if bt == "pg_control_stop_project":
            raise _StopSignal()

        # ---- Pen drawing ----
        if bt == "pg_looks_move_pen":
            pos = (block.get_field("POSITION") or "down").lower()
            self.pen_down = pos == "down"
            return

        if bt == "pg_looks_set_pen_color":
            self.pen_color = (block.get_field("COLOR") or "black").lower()
            return

        if bt == "pg_looks_set_pen_width":
            self.pen_width_name = (block.get_field("WIDTH") or "medium").lower()
            return

        if bt in ("pg_looks_set_pen_color_plus", "pg_looks_fill_color_plus"):
            # Custom color — no meaningful field to extract; just acknowledge.
            return

        # ---- Timer ----
        if bt == "pg_sensing_reset_timer":
            self.timer_s = 0.0
            return

        # pg_sensing_timer_value is a reporter block (value, not statement) —
        # it has no standalone execution effect; it will be used by _eval_expression
        # when the expression evaluator is added (Tier 2).

        # ---- Procedures (OI-23 build, 2026-08-24: inline expansion) ----
        if bt == "procedures_call":
            name = (block.mutation or {}).get("proccode") or ""
            body = self.procedures.get(name)
            if body is None:
                # call to a definition that doesn't exist (deleted, or the
                # mutation was unreadable) — no-op, named flag
                self._flag("procedure_undefined")
                return
            call_key = (self._current_thread_idx, name)
            if call_key in self._active_procs:
                # VEX would recurse; unrolling recursion needs a depth model
                # we don't have — suppress the nested call, flag it
                self._flag("procedure_recursion_suppressed")
                return
            self._active_procs.add(call_key)
            try:
                yield from self.execute_stack(body)
            finally:
                self._active_procs.discard(call_key)
            return
        if bt in ("procedures_definition", "procedures_prototype"):
            return   # bodies execute only via their calls

        # ---- Broadcast events (task 3 Part A: inline execution) ----
        if bt in ("pg_events_broadcast", "pg_events_broadcast_and_wait"):
            key = block.get_field("BROADCAST_OPTION") or ""
            stacks = self.receivers.get(key, [])
            if not stacks:
                return  # no matching receiver -> no-op, as before
            if key in self.active_broadcasts:
                # A receiver (re-)broadcasting its own active event would loop
                # forever; suppress and record.
                self._flag("broadcast_recursion_suppressed")
                return
            if len(stacks) > 1:
                self._flag("broadcast_multiple_receivers")
            if bt == "pg_events_broadcast":
                # Fire-and-forget in reality; inline is an approximation (closer
                # than document order, but still sequential).
                self._flag("broadcast_concurrency_approximated")
            self.active_broadcasts.add(key)
            try:
                for stack in stacks:   # document order
                    try:
                        yield from self.execute_stack(stack)
                    except _GateSignal:
                        # A gated receiver stalls without stalling its
                        # broadcaster (they run in parallel in reality).
                        pass
            finally:
                self.active_broadcasts.discard(key)
            return

        # ---- Variables ----
        if bt in ("pg_variables_set_variable", "variables_set"):
            name = block.get_field("VARIABLE") or ""
            val = self._eval_expression(block.values[0]) if block.values else 0
            self.variables[name] = float(val)
            return

        if bt in ("pg_variables_change_variable", "variables_change", "math_change"):
            name = block.get_field("VARIABLE") or ""
            delta = float(self._eval_expression(block.values[0])) if block.values else 0
            self.variables[name] = self.variables.get(name, 0) + delta
            return

        if bt == "pg_variables_set_boolean_variable":
            name = block.get_field("VARIABLE") or ""
            val = self._eval_expression(block.values[0]) if block.values else False
            self.variables[name] = float(bool(val))
            return

        # ---- Wait until condition ----
        # Ratified OI-3 semantics (reviewer 2026-08-19, replacing the legacy
        # 50mm-probe fabrication): wait_until produces NO self-motion — it is
        # an execution gate. With pending continuous motion armed, the motion
        # simply continues while the gate holds: march the position in fine
        # virtual increments until the condition turns true, then commit the
        # single real move. A condition that never turns true gates the stack
        # — the code below never executes (flag wait_until_unmet) — after the
        # armed drive physically runs off the field (runoff, as at program
        # end). Without pending motion, position-based conditions can never
        # change: evaluate once, gate on false.
        if bt == "pg_control_wait_until":
            def _cond() -> bool:
                return bool(block.values and self._eval_expression(block.values[0]))
            if _cond():
                return
            if self._coop():
                try:
                    # VR-Seq: park until the Sequencer sees the condition go
                    # true at a slice boundary (it splits slices at motion
                    # crossings via the _march_* solvers)
                    yield _Park("cond", block)
                    return
                except _CondUnmet:
                    # no live thread or motion can ever satisfy it — the
                    # legacy unmet path: fabricate the runoff, flag, gate
                    if self.pending_drive_dir is not None:
                        sign = self.pending_drive_dir
                        cap_mm = 4.0 * max(self.ctx.field_radius, 1.0)
                        self.pending_drive_dir = None
                        self.fabricated_steps.append(self.step)
                        self._move(sign * cap_mm, block)
                    self._flag("wait_until_unmet")
                    raise _GateSignal()
            if self.pending_drive_dir is not None:
                sign = self.pending_drive_dir
                cap_mm = 4.0 * max(self.ctx.field_radius, 1.0)
                dist = self._march_drive_until(sign, cap_mm, _cond)
                self.pending_drive_dir = None
                if dist is not None:
                    self._move(sign * dist, block)      # real motion: velocity held to condition
                    return
                self.fabricated_steps.append(self.step)  # runoff magnitude is a fallback
                self._move(sign * cap_mm, block)
                self._flag("wait_until_unmet")
                raise _GateSignal()
            if self.pending_turn_dir is not None:
                sign = self.pending_turn_dir
                angle = self._march_turn_until(sign, _cond)
                self.pending_turn_dir = None
                if angle is not None:
                    dt = abs(angle) / max(self.turn_velocity_deg_per_s, 1e-9)
                    self.sim_time_s += dt
                    self.timer_s += dt
                    self.heading = (self.heading + sign * angle) % 360
                    self.drive_rotation_deg -= sign * angle
                    self._record_step(block)
                    self.step += 1
                    return
                self._flag("wait_until_unmet")
                raise _GateSignal()
            self._flag("wait_until_unmet")
            raise _GateSignal()

        # ---- Loops ----
        if "forever" in bt:
            self.loop_was_capped = True
            self.loop_cap_steps.append(self.step)   # stage 0b: per-span fidelity
            broke = False
            for _ in range(self.forever_unroll):
                _t0 = self.sim_time_s
                self.loops_exercised[block.block_id] = self.loops_exercised.get(block.block_id, 0) + 1
                self.structure_trace.append((self._current_thread_idx, "LOOP_ITER", block.block_id, None))
                try:
                    for child in block.children:
                        yield from self.execute_stack(child)
                except _BreakSignal:
                    self.loop_was_capped = False
                    broke = True
                    break
                self._loop_tick(_t0)
                yield   # VR-Seq: loop back-edge yield (scratch-vm rule)
                if self._forever_completed:
                    break   # inner forever capped: this loop never re-iterates
            if not broke:
                self._forever_completed = True
            return

        if "repeat" in bt and "until" not in bt:
            raw = self._first_numeric_raw(block, "TIMES")
            if not math.isfinite(raw):
                # reviewer-probed 2026-08-24: `repeat Infinity` LOOPS like
                # forever in VEX VR (it does not hang). Same capped-forever
                # treatment, including the nesting signal.
                self._flag("nonfinite_numeric_clamped")
                self.loop_was_capped = True
                self.loop_cap_steps.append(self.step)
                broke = False
                for _ in range(self.forever_unroll):
                    _t0 = self.sim_time_s
                    self.loops_exercised[block.block_id] = self.loops_exercised.get(block.block_id, 0) + 1
                    self.structure_trace.append((self._current_thread_idx, "LOOP_ITER", block.block_id, None))
                    try:
                        for child in block.children:
                            yield from self.execute_stack(child)
                    except _BreakSignal:
                        self.loop_was_capped = False
                        broke = True
                        break
                    self._loop_tick(_t0)
                    yield   # VR-Seq: loop back-edge yield
                    if self._forever_completed:
                        break
                if not broke:
                    self._forever_completed = True
                return
            raw_n = max(0, int(raw))
            n = min(raw_n, self.max_unroll)
            if raw_n > self.max_unroll:
                self.loop_was_capped = True
                self.loop_cap_steps.append(self.step)   # stage 0b: per-span fidelity
            for _ in range(n):
                _t0 = self.sim_time_s
                self.loops_exercised[block.block_id] = self.loops_exercised.get(block.block_id, 0) + 1
                self.structure_trace.append((self._current_thread_idx, "LOOP_ITER", block.block_id, None))
                try:
                    for child in block.children:
                        yield from self.execute_stack(child)
                except _BreakSignal:
                    break
                self._loop_tick(_t0)
                yield   # VR-Seq: loop back-edge yield
                if self._forever_completed:
                    break   # faithful nesting: inner forever never returns
            return

        if "repeat_until" in bt:
            self.loop_was_capped = True
            self.loop_cap_steps.append(self.step)   # stage 0b: per-span fidelity
            for _ in range(self.forever_unroll):
                cond = bool(self._eval_expression(block.values[0])) if block.values else False
                if cond:
                    self.loop_was_capped = False
                    break
                _t0 = self.sim_time_s
                self.loops_exercised[block.block_id] = self.loops_exercised.get(block.block_id, 0) + 1
                self.structure_trace.append((self._current_thread_idx, "LOOP_ITER", block.block_id, None))
                try:
                    for child in block.children:
                        yield from self.execute_stack(child)
                except _BreakSignal:
                    self.loop_was_capped = False
                    break
                self._loop_tick(_t0)
                yield   # VR-Seq: loop back-edge yield
                if self._forever_completed:
                    break   # faithful nesting: inner forever never returns
            return

        if "while" in bt:
            self.loop_was_capped = True
            self.loop_cap_steps.append(self.step)   # stage 0b: per-span fidelity
            for _ in range(self.forever_unroll):
                cond = bool(self._eval_expression(block.values[0])) if block.values else True
                if not cond:
                    self.loop_was_capped = False
                    break
                _t0 = self.sim_time_s
                self.loops_exercised[block.block_id] = self.loops_exercised.get(block.block_id, 0) + 1
                self.structure_trace.append((self._current_thread_idx, "LOOP_ITER", block.block_id, None))
                try:
                    for child in block.children:
                        yield from self.execute_stack(child)
                except _BreakSignal:
                    self.loop_was_capped = False
                    break
                self._loop_tick(_t0)
                yield   # VR-Seq: loop back-edge yield
                if self._forever_completed:
                    break   # faithful nesting: inner forever never returns
            return

        # ---- Conditionals — evaluate condition ----
        if "if" in bt:
            # NAME-BOUND branches (CROW-C117 fix, 2026-08-24): positional
            # pairing mis-binds when an earlier slot is empty — an else-only
            # if_then_else executed its else body AS the if-branch. Slot
            # naming: if_then/if_then_else use CONDITION/SUBSTACK/SUBSTACK2;
            # if_elseif_else uses CONDITION1/SUBSTACK1/.../SUBSTACK_ELSE.
            # An EMPTY condition slot evaluates false (VEX semantics) and
            # falls through to the else.
            stmts = getattr(block, "statements", None) or {}
            vs = getattr(block, "value_slots", None) or {}
            if stmts or vs:
                if "elseif" in bt:
                    pairs = []
                    i = 1
                    while (f"CONDITION{i}" in vs) or (f"SUBSTACK{i}" in stmts):
                        pairs.append((vs.get(f"CONDITION{i}"),
                                      stmts.get(f"SUBSTACK{i}")))
                        i += 1
                    else_branch = stmts.get("SUBSTACK_ELSE")
                else:
                    pairs = [(vs.get("CONDITION"), stmts.get("SUBSTACK"))]
                    else_branch = stmts.get("SUBSTACK2") if "else" in bt else None
                for arm_i, (cond, body) in enumerate(pairs):
                    if cond is not None and bool(self._eval_expression(cond)):
                        self.branches_exercised.setdefault(
                            block.block_id, []).append(f"arm{arm_i}")
                        self.structure_trace.append(
                            (self._current_thread_idx, "BRANCH_ARM", block.block_id, f"arm{arm_i}"))
                        if body is not None:
                            yield from self.execute_stack(body)
                        return
                self.branches_exercised.setdefault(
                    block.block_id, []).append("else")
                self.structure_trace.append(
                    (self._current_thread_idx, "BRANCH_ARM", block.block_id, "else"))
                if else_branch is not None:
                    yield from self.execute_stack(else_branch)
                return
            # Legacy positional fallback (no slot info in the parse)
            if not block.values:
                if block.children:
                    yield from self.execute_stack(block.children[0])
                return
            executed = False
            for i, val_block in enumerate(block.values):
                if bool(self._eval_expression(val_block)):
                    self.branches_exercised.setdefault(
                        block.block_id, []).append(f"arm{i}")
                    self.structure_trace.append(
                        (self._current_thread_idx, "BRANCH_ARM", block.block_id, f"arm{i}"))
                    if i < len(block.children):
                        yield from self.execute_stack(block.children[i])
                    executed = True
                    break
            if not executed and len(block.children) > len(block.values):
                self.branches_exercised.setdefault(
                    block.block_id, []).append("else")
                self.structure_trace.append(
                    (self._current_thread_idx, "BRANCH_ARM", block.block_id, "else"))
                yield from self.execute_stack(block.children[-1])
            return

        # Unknown statements must not be certified by a broad family prefix.
        from ..parsing.block_registry import _simulator_status_map
        if bt not in _simulator_status_map:
            self._flag("unmodeled_blocks")

    # ---------------------------------------------------------------- #
    # Movement
    # ---------------------------------------------------------------- #

    # Maximum drive distance we'll simulate in one step (10× field diameter).
    # Values beyond this (e.g. 9e+67 from student typos) would cause the
    # coverage sampler to loop for an astronomically long time.
    _MAX_MOVE_MM = 33_000.0

    def _clear_pending_motion(self) -> None:
        """Discard any pending continuous drive/turn (overridden by the next drivetrain command)."""
        self.pending_drive_dir = None
        self.pending_turn_dir = None
        self.pending_drive_block = None
        self.pending_turn_block = None

    # Virtual-march granularity for wait_until condition resolution (simulation
    # quality constants, like _FOREVER_UNROLL — not playground thresholds).
    _WAIT_MARCH_MM = 10.0
    _WAIT_MARCH_DEG = 2.0

    def _march_drive_until(self, sign: float, cap_mm: float, cond) -> float | None:
        """Distance at which cond first turns true while driving straight from
        the current pose, or None if it never does within cap_mm. Marches a
        VIRTUAL position (state restored) so no path steps are fabricated —
        the caller commits one real move."""
        rad = math.radians(self.heading)
        dx, dy = math.cos(rad), math.sin(rad)
        sx, sy = self.x, self.y
        try:
            d = self._WAIT_MARCH_MM
            while d <= cap_mm:
                self.x = sx + sign * d * dx
                self.y = sy + sign * d * dy
                if cond():
                    return d
                d += self._WAIT_MARCH_MM
            return None
        finally:
            self.x, self.y = sx, sy

    def _march_turn_until(self, sign: float, cond) -> float | None:
        """Angle (deg) at which cond first turns true while turning in place,
        or None if a full revolution never satisfies it."""
        sh = self.heading
        try:
            a = self._WAIT_MARCH_DEG
            while a <= 360.0:
                self.heading = (sh + sign * a) % 360
                if cond():
                    return a
                a += self._WAIT_MARCH_DEG
            return None
        finally:
            self.heading = sh

    def finish_pending_motion(self) -> None:
        """Reviewer decision (2026-08-18, OI-3): pending continuous motion
        still armed when the program ends normally means the real robot keeps
        driving indefinitely until failure. Drive: a runoff distance derived
        from field geometry (4 x field radius — guarantees exiting the island
        from any interior point on any heading; clamped by _MAX_MOVE_MM).
        Turn: the nominal 90°. Both are fabricated — the magnitude is a
        modelling choice pending the §8 probe."""
        if self.pending_drive_dir is not None and self.pending_drive_block is not None:
            sign = self.pending_drive_dir
            block = self.pending_drive_block
            self._clear_pending_motion()
            cap_mm = 4.0 * max(self.ctx.field_radius, 1.0)
            # Sensing Phase 2: a still-armed hat can preempt the indefinite
            # drive — "drive until the eye sees something, then do the hat
            # stack" is real program shape (WREN-C040). March virtually to the
            # first detection; the distance driven to that point is REAL
            # modeled motion, and the hat stack's first drivetrain command
            # supersedes the pending drive as usual.
            if self.pending_sensor_hats and not self._in_sensor_hat:
                d = self._march_drive_until(
                    sign, cap_mm,
                    lambda: any(self._hat_detects(h)
                                for h in self.pending_sensor_hats))
                if d is not None:
                    self._move(sign * d, block)
                    self.fire_ready_sensor_hats()
                    if self.pending_drive_dir is None:
                        return   # hat stack superseded the drive
                    sign = self.pending_drive_dir
                    block = self.pending_drive_block
                    self._clear_pending_motion()
            self.fabricated_steps.append(self.step)
            self._move(sign * cap_mm, block)
        elif self.pending_turn_dir is not None and self.pending_turn_block is not None:
            sign = self.pending_turn_dir
            block = self.pending_turn_block
            self._clear_pending_motion()
            self.fabricated_steps.append(self.step)
            self.heading = (self.heading + sign * 90.0) % 360
            self.drive_rotation_deg -= sign * 90.0
            self._record_step(block)
            self.step += 1

    def _move(self, dist_mm: float, block: BlockNode, add_time: bool = True) -> None:
        self.has_moved = True
        # Clamp to prevent coverage-sampling hang on absurd input values
        if abs(dist_mm) > self._MAX_MOVE_MM:
            dist_mm = math.copysign(self._MAX_MOVE_MM, dist_mm)
        restart_after_move = False
        if self._active_hat is not None:
            # Restart pre-scan (reviewer probe 2026-08-24): the hat's own
            # drive abandons AT the point a new detection edge occurs —
            # truncate this move there, then restart the script.
            hat = self._active_hat
            rad0 = math.radians(self.heading)
            ex, ey = math.cos(rad0), math.sin(rad0)
            n = max(1, int(abs(dist_mm) / self._HAT_SAMPLE_MM))
            sx, sy = self.x, self.y
            prev = self._hat_prev_state.get(id(hat), False)
            cut = None
            try:
                for i in range(n + 1):
                    d = dist_mm * i / n
                    self.x = sx + d * ex
                    self.y = sy + d * ey
                    now = self._hat_detects(hat)
                    if now and not prev:
                        cut = d
                        break
                    prev = now
            finally:
                self.x, self.y = sx, sy
            if cut is not None:
                dist_mm = cut
                self._hat_prev_state[id(hat)] = True
                restart_after_move = True
            else:
                self._hat_prev_state[id(hat)] = prev
        if add_time and self.time_budget_s is not None:
            # observed-run budget: a single long move is truncated at the
            # wall time where the real run was ended
            rem = self.time_budget_s - self.sim_time_s
            max_mm = max(0.0, rem) * max(self.drive_velocity_mm_per_s, 1e-9)
            if abs(dist_mm) > max_mm:
                dist_mm = (1.0 if dist_mm >= 0 else -1.0) * max_mm
        if add_time:
            # OI-23 timer build (2026-08-24): movement consumes clock time at
            # the calibrated velocity (fixes the timer_value defect). Callers
            # that already accounted the interval (wait-with-pending-drive)
            # pass add_time=False.
            dt = abs(dist_mm) / max(self.drive_velocity_mm_per_s, 1e-9)
            self.sim_time_s += dt
            self.timer_s += dt
        prev_x, prev_y = self.x, self.y
        rad = math.radians(self.heading)
        self.x += dist_mm * math.cos(rad)
        self.y += dist_mm * math.sin(rad)

        # Boundary — use hex polygon check when vertices are available, else circle fallback
        dist_center = math.sqrt(self.x**2 + self.y**2)
        if dist_center < self.min_dist_center:
            self.min_dist_center = dist_center
        if self.ctx.field_hex_vertices:
            if not _point_in_convex_polygon(self.x, self.y, self.ctx.field_hex_vertices):
                self.exits_boundary = True
        elif dist_center > self.ctx.field_radius:
            self.exits_boundary = True

        # Named objects: update min distance + tolerance detection
        for obj_id, obj in self.ctx.objects.items():
            dp = _dist(self.x, self.y, obj.x, obj.y)
            if dp < self.min_dist_to_objects[obj_id]:
                self.min_dist_to_objects[obj_id] = dp
            if dp <= obj.tolerance and self.first_tol_steps[obj_id] is None:
                self.first_tol_steps[obj_id] = self.step
            seg_r = obj.segmentation_radius if obj.segmentation_radius > 0 else obj.tolerance
            if dp <= seg_r and self.first_seg_steps[obj_id] is None:
                self.first_seg_steps[obj_id] = self.step

        # Kinematic push model (sensing Phase 5 — TESTCASE ONLY, inert in the
        # main sim; hybrid ruling 2026-08-19 + "assume the most favorable
        # condition"): a piece the robot's advancing front reaches stays
        # pinned ahead of the robot for the rest of the forward move; it is
        # CLEARED (disappears) when its centre crosses the island edge.
        # Turns/reverse naturally drop the piece where it was left.
        if self.push_model == "kinematic":
            half_w_p = self.ctx.robot_width_mm / 2.0
            mvx, mvy = self.x - prev_x, self.y - prev_y
            for piece in self.live_pieces:
                if piece.body_radius_mm is None or piece.object_id in self.pieces_cleared \
                        or piece.object_id in self._pending_piece_ids:
                    continue
                pin = piece.body_radius_mm + half_w_p
                advancing = (mvx * (piece.x - prev_x) + mvy * (piece.y - prev_y)) > 0.0
                if advancing and _point_segment_dist(
                        piece.x, piece.y, prev_x, prev_y, self.x, self.y) <= pin:
                    rad_p = math.radians(self.heading)
                    piece.x = self.x + pin * math.cos(rad_p)
                    piece.y = self.y + pin * math.sin(rad_p)
                    off = (not _point_in_convex_polygon(piece.x, piece.y,
                                                        self.ctx.field_hex_vertices)
                           if self.ctx.field_hex_vertices
                           else _dist(piece.x, piece.y, 0.0, 0.0) > self.ctx.field_radius)
                    if off:
                        self.pieces_cleared[piece.object_id] = self.step

        # Contact tracking (sensing Phase 2, hybrid ruling 2026-08-19): first
        # body contact with a movable target marks its position stale from
        # then on — the main sim never MOVES objects; sensor readings against
        # stale targets carry sensor_reading_stale. Contact is evaluated
        # along the whole traversed segment (the robot occupies every point
        # of a drive — the C031 lesson), not just the endpoint.
        half_w = self.ctx.robot_width_mm / 2.0
        for target in self._sensor_targets():
            if target.body_radius_mm is None or not target.movable:
                continue
            if target.object_id in self.object_contacts:
                continue
            if _point_segment_dist(target.x, target.y, prev_x, prev_y,
                                   self.x, self.y) <= target.body_radius_mm + half_w:
                self.object_contacts[target.object_id] = self.step

        # Named regions: sample coverage along movement path (footprint-aware).
        # Track which regions the path actually passes through (not just endpoint).
        traversed_regions: set[str] = set()
        for region_id, region in self.ctx.regions.items():
            cells_before = len(self.region_cells[region_id])
            self._sample_region_coverage(prev_x, prev_y, self.x, self.y, self.heading, region_id, region)
            if len(self.region_cells[region_id]) > cells_before:
                traversed_regions.add(region_id)

        if self.pen_down:
            self.pen_segments.append((prev_x, prev_y, self.x, self.y,
                                      self.pen_color, self.pen_width_name))

        self._record_step(block, traversed_regions=traversed_regions)
        self.step += 1
        self._latch_sensor_hats_along(prev_x, prev_y, self.x, self.y)
        if restart_after_move:
            raise _HatRestartSignal()

    def _record_step(
        self,
        block: BlockNode,
        magnet_fires: bool = False,
        traversed_regions: set[str] | None = None,
    ) -> PathStep:
        # Regions at the endpoint; union with any regions traversed during movement
        current_regions = frozenset(
            rid for rid, region in self.ctx.regions.items()
            if region.contains(self.x, self.y)
        )
        if traversed_regions:
            current_regions = current_regions | frozenset(traversed_regions)
        self.regions_entered.update(current_regions)

        # Which objects are within tolerance
        current_tol = frozenset(
            oid for oid, obj in self.ctx.objects.items()
            if _dist(self.x, self.y, obj.x, obj.y) <= obj.tolerance
        )

        ps = PathStep(
            step=self.step,
            x=self.x,
            y=self.y,
            heading=self.heading,
            block_type=block.block_type,
            block_id=block.block_id,
            regions_entered=current_regions,
            objects_in_tolerance=current_tol,
            magnet_fires=magnet_fires,
            thread_id=self._current_thread_idx,
        )
        self.path.append(ps)
        return ps

    def _sample_region_coverage(
        self,
        x0: float, y0: float,
        x1: float, y1: float,
        heading_deg: float,
        region_id: str,
        region: RegionBounds,
    ) -> None:
        """Sample region coverage along the movement path, accounting for robot width.

        For each point along the center-line, samples across the full robot width
        perpendicular to the heading direction.  This reflects that students are
        reasoning about the robot as a physical object with a known width (~51mm)
        when planning sweep strategies.

        Lateral samples: center ± width/2 (3 points), which is sufficient given
        the 100mm grid cell — the robot width (50.8mm) extends at most into one
        additional cell on each side.
        """
        self.region_cells[region_id].update(
            _coverage_cells_for_move(x0, y0, x1, y1, heading_deg, self.ctx.robot_width_mm, region)
        )

    def _sanitize_numeric(self, v: float) -> float:
        """Non-finite guard (Stage-1 validation campaign, 2026-08-21: student
        math can yield infinity — e.g. divide-by-zero feeding repeat TIMES —
        which crashed int() conversion). Infinities clamp to a huge finite
        value (sign kept) so downstream caps bind — an infinite repeat count
        behaves like forever under the unroll cap, an infinite distance runs
        off-island and truncates; NaN poisons arithmetic, so it becomes the
        neutral 0.0. Either way the program-level flag records it."""
        if math.isfinite(v):
            return v
        self._flag("nonfinite_numeric_clamped")
        if math.isnan(v):
            return 0.0
        return math.copysign(1e9, v)

    def _get_numeric(self, block: BlockNode, field_name: str) -> float:
        return self._sanitize_numeric(self._get_numeric_raw(block, field_name))

    def _get_numeric_raw(self, block: BlockNode, field_name: str) -> float:
        val = block.get_field(field_name)
        if val is not None:
            try:
                return float(val)
            except (ValueError, TypeError):
                pass
        # OI-14 companion (2026-08-18): value slots may now hold REAL reporter
        # blocks (variables, operators, random) — evaluate them, not just
        # shadow literals.
        if block.values:
            try:
                return float(self._eval_expression(block.values[0]))
            except (ValueError, TypeError):
                pass
        for vn in block.values:
            for f in vn.fields:
                if f.name == "NUM":
                    try:
                        return float(f.value)
                    except (ValueError, TypeError):
                        pass
        return 0.0

    def _first_numeric_raw(self, block: BlockNode, *field_names: str) -> float:
        """_first_numeric without sanitization — callers that must SEE a
        non-finite value (repeat's forever-equivalence, the discrete-stall
        guard) use this."""
        for name in field_names:
            val = block.get_field(name)
            if val is not None:
                try:
                    return float(val)
                except (ValueError, TypeError):
                    pass
        return self._get_numeric_raw(block, field_names[0] if field_names else "")

    def _get_discrete(self, block: BlockNode, *field_names: str) -> float:
        """Discrete motion/time parameter (reviewer-probed 2026-08-24): a
        non-finite value HANGS the block in VEX VR — the robot does nothing
        and the stack never progresses. Modeled as a gate (the stack stalls;
        parallel stacks continue), flagged nonfinite_parameter_stall.
        Percent parameters are different: VEX maxes them out (see the
        velocity clamp) and execution continues."""
        raw = self._first_numeric_raw(block, *field_names)
        if not math.isfinite(raw):
            self._flag("nonfinite_parameter_stall")
            raise _GateSignal()
        return raw

    def _first_numeric(self, block: BlockNode, *field_names: str) -> float:
        """First of `field_names` that is actually PRESENT on the block.

        `_get_numeric(a) or _get_numeric(b)` cannot be used for headings: a
        legitimate value of 0 is falsy, so "turn to heading 0" would silently
        fall through to the next field name.  This checks presence instead of
        truthiness, and only falls back to the shared NUM-scan once.
        """
        for name in field_names:
            val = block.get_field(name)
            if val is not None:
                try:
                    return float(val)
                except (ValueError, TypeError):
                    pass
        # Blockly puts numeric inputs in shadow <value> blocks rather than
        # <field>, so the named lookups above miss them entirely.
        return self._get_numeric(block, field_names[0] if field_names else "")

    def _eval_expression(self, block: BlockNode) -> float | bool | str:
        try:
            return self._eval_expression_unchecked(block)
        except (ArithmeticError, ValueError, TypeError, RecursionError):
            self._flag("invalid_expression")
            raise _GateSignal()

    def _eval_expression_unchecked(self, block: BlockNode) -> float | bool | str:
        """Recursively evaluate a reporter (value) block.

        Returns a Python int, float, bool, or str.  Unrecognized blocks return 0.
        """
        bt = block.block_type

        # ---- Literals ----
        # math_number_string and math_whole_number are VEX additions beyond
        # stock Blockly (OI-13 fix, 2026-08-18); math_positive_number_only
        # joined from the Spring26 sample (when_timer thresholds, OI-23
        # build 2026-08-24) — all are numeric literals.
        if bt in ("math_number", "math_positive_number",
                  "math_whole_number", "math_number_string",
                  "math_positive_number_only"):
            try:
                return float(block.get_field("NUM") or 0)
            except (ValueError, TypeError):
                return 0.0

        # ---- Position sensors ----
        if bt == "pg_sensing_position":
            # A3 close corrected (2026-08-26 review): honour UNITS — the
            # reporter previously returned raw mm regardless of the field
            axis = (block.get_field("AXIS") or "X").upper()
            val = self.x if axis == "X" else self.y
            unit = (block.get_field("UNITS") or block.get_field("UNIT")
                    or "mm").lower()
            return val / 25.4 if "inch" in unit else val

        if bt in ("pg_sensing_position_angle", "pg_sensing_drive_heading"):
            # A3 close corrected (2026-08-26 review): report the VEX/card
            # convention (0 = the card's zero, what the student's blocks
            # compare against), not the internal math heading — the inverse
            # of card_heading_to_math
            return (180.0 - self.heading) % 360.0

        if bt == "pg_sensing_drive_rotation":
            # A3 rotation build (2026-08-26): true cumulative rotation
            # (VEX convention, CW-positive, 0 at spawn)
            return self.drive_rotation_deg

        if bt == "pg_sensing_drive_is_done":
            # sequential mode is synchronous (always done). Under the
            # cooperative scheduler a SIBLING thread can poll while a
            # blocking motion is in flight — done = no active motion.
            if self._sequencer is not None:
                return self._sequencer.active is None
            return True

        if bt == "pg_sensing_drive_is_moving":
            if self._sequencer is not None:
                return (self._sequencer.active is not None
                        or self.pending_drive_dir is not None
                        or self.pending_turn_dir is not None)
            return False  # sequential mode is synchronous

        # ---- Timer ----
        if bt == "pg_sensing_timer_value":
            return self.timer_s

        # ---- Variables ----
        if bt in ("pg_variables_variable", "pg_variables_boolean_variable"):
            name = block.get_field("VARIABLE") or ""
            return self.variables.get(name, 0)

        # ---- Arithmetic operators ----
        if bt == "pg_operator_math":
            a = float(self._eval_expression(block.values[0])) if block.values else 0.0
            b = float(self._eval_expression(block.values[1])) if len(block.values) > 1 else 0.0
            op = block.get_field("OPERATOR") or "+"
            if op == "+": return a + b
            if op == "-": return a - b
            if op == "*": return a * b
            if op == "/": return a / b if b != 0 else 0.0
            return 0.0

        if bt == "pg_operator_remainder":
            a = float(self._eval_expression(block.values[0])) if block.values else 0.0
            b = float(self._eval_expression(block.values[1])) if len(block.values) > 1 else 1.0
            return a % b if b != 0 else 0.0

        if bt == "pg_operator_random":
            lo = int(float(self._eval_expression(block.values[0]))) if block.values else 0
            hi = int(float(self._eval_expression(block.values[1]))) if len(block.values) > 1 else 1
            # Deterministic midpoint, NOT random.randint (2026-08-18): replay
            # identity requires deterministic paths (the frozen-fixture tripwire
            # and the old project's BUG-14 lesson). The midpoint is the expected
            # value of the student's declared range.
            return float((min(lo, hi) + max(lo, hi)) / 2.0)

        if bt == "pg_operator_round":
            val = float(self._eval_expression(block.values[0])) if block.values else 0.0
            return float(round(val))

        if bt == "pg_operator_function":
            fn = (block.get_field("OPERATOR") or "abs").lower()
            val = float(self._eval_expression(block.values[0])) if block.values else 0.0
            _fn_map = {
                "abs": abs, "floor": math.floor, "ceiling": math.ceil,
                "sqrt": math.sqrt, "sin": math.sin, "cos": math.cos,
                "tan": math.tan, "asin": math.asin, "acos": math.acos,
                "atan": math.atan, "ln": math.log,
                "log": math.log10, "e^": math.exp,
                "10^": lambda v: 10 ** v, "negative": lambda v: -v,
            }
            fn_callable = _fn_map.get(fn)
            if fn_callable:
                try:
                    return float(fn_callable(val))
                except (ValueError, ZeroDivisionError):
                    return 0.0
            return val

        if bt == "pg_operator_function_atan2":
            y = float(self._eval_expression(block.values[0])) if block.values else 0.0
            x = float(self._eval_expression(block.values[1])) if len(block.values) > 1 else 1.0
            return math.degrees(math.atan2(y, x))

        # ---- Comparison operators ----
        if bt == "pg_operator_comparison":
            a = self._eval_expression(block.values[0]) if block.values else 0
            b = self._eval_expression(block.values[1]) if len(block.values) > 1 else 0
            op = block.get_field("OPERATOR") or "="
            try:
                a_f, b_f = float(a), float(b)
                a, b = a_f, b_f
            except (TypeError, ValueError):
                a, b = str(a), str(b)
            if op in ("=", "=="): return a == b
            if op == "<":         return a < b
            if op in ("<=", "≤"): return a <= b
            if op == ">":         return a > b
            if op in (">=", "≥"): return a >= b
            return False

        if bt == "pg_operator_range":
            # lo OP val OP hi — both operators stored in OPERATOR field as e.g. "< val <"
            # values[0]=lo, values[1]=val, values[2]=hi
            lo  = float(self._eval_expression(block.values[0])) if block.values else 0.0
            val = float(self._eval_expression(block.values[1])) if len(block.values) > 1 else 0.0
            hi  = float(self._eval_expression(block.values[2])) if len(block.values) > 2 else 0.0
            return min(lo, hi) <= val <= max(lo, hi)

        # ---- Logical operators ----
        if bt == "pg_operator_and_or":
            a = bool(self._eval_expression(block.values[0])) if block.values else True
            b = bool(self._eval_expression(block.values[1])) if len(block.values) > 1 else True
            op = (block.get_field("OPERATOR") or "and").lower()
            return a and b if op == "and" else a or b

        if bt == "pg_operator_not":
            val = self._eval_expression(block.values[0]) if block.values else True
            return not bool(val)

        # ---- String operators ----
        if bt == "pg_operator_join":
            a = str(self._eval_expression(block.values[0])) if block.values else ""
            b = str(self._eval_expression(block.values[1])) if len(block.values) > 1 else ""
            return a + b

        if bt == "pg_operator_length":
            s = str(self._eval_expression(block.values[0])) if block.values else ""
            return float(len(s))

        if bt == "pg_operator_contains":
            s    = str(self._eval_expression(block.values[0])) if block.values else ""
            term = str(self._eval_expression(block.values[1])) if len(block.values) > 1 else ""
            return term in s

        if bt == "pg_operator_find":
            pos = int(float(self._eval_expression(block.values[0]))) if block.values else 1
            s   = str(self._eval_expression(block.values[1])) if len(block.values) > 1 else ""
            return s[pos - 1] if 0 < pos <= len(s) else ""

        if bt == "pg_operator_convert":
            val = self._eval_expression(block.values[0]) if block.values else 0
            typ = (block.get_field("TYPE") or "number").lower()
            return str(val) if typ in ("text", "string") else float(val)

        # ---- Tier 3 sensing — floor color ----
        # Sensing build Phase 1 (2026-08-19, OI-10 + OI-5 partial): the check
        # reads the corpus field name COLORS (legacy COLOR fallback), resolves
        # WHICH eye from the OPTICAL field, evaluates at the EYE POINT (centre
        # + calibrated forward offset along heading, from the robot card), and
        # matches card color_zones honoring per-eye applicability and ring
        # bands. The old check read a field no corpus block carries, used the
        # robot centre, and fired red only outside the island edge — i.e.
        # after the robot had already left.
        if bt in ("pg_sensing_optical_color", "pg_sensing_optical_detected_color_is"):
            self.sensor_first_eval.setdefault(block.block_id, (self.step, bt))
            color = (block.get_field("COLORS") or block.get_field("COLOR") or "").lower()
            eye = self._eye_from_block(block)
            detected = self._eye_detected_color(eye)
            if color in ("", "none"):
                return detected is None
            if detected == color:
                entry = (self.step, eye, detected)
                if not self.color_detections or self.color_detections[-1] != entry:
                    self.color_detections.append(entry)
                return True
            return False

        # ---- Tier 3 sensing — object proximity ----
        if bt in ("pg_sensing_optical_near_object", "pg_sensing_eye", "pg_sensing_optical"):
            self.sensor_first_eval.setdefault(block.block_id, (self.step, bt))
            return self._eye_near_object(self._eye_from_block(block))

        # ---- Tier 3 sensing — bumper switch (Phase 4, 2026-08-19) ----
        # Modeled only when the robot card declares bumper mounts; without a
        # card the block falls to the unknown-reporter path as before.
        if bt in ("pg_sensing_bumper", "pg_sensing_bumper_pressed",
                  "pg_sensing_bumper_near") \
                and isinstance(self.ctx.sensor_specs.get("bumpers"), dict):
            self.sensor_first_eval.setdefault(block.block_id, (self.step, bt))
            return self._bumper_pressed(block.get_field("BUMPER") or "")

        # ---- Tier 3 sensing — distance sensor (Phase 3, 2026-08-19) ----
        # Docs-verified banded cone (10 deg <1000mm, 5 deg 1000-2000, 2 deg
        # beyond, 3000mm max; nearest object SURFACE). Modeled only when the
        # robot card declares front_distance; otherwise the block falls to
        # the unknown-reporter path as before.
        if bt.startswith("pg_sensing_distance") \
                and isinstance(self.ctx.sensor_specs.get("front_distance"), dict):
            self.sensor_first_eval.setdefault(block.block_id, (self.step, bt))
            hits = self._distance_hits()
            if hits is not None:
                if bt in ("pg_sensing_distance_found", "pg_sensing_distance"):
                    if self.movable_predicates == "ceiling" \
                            and self._movable_world_disturbed():
                        return True
                    return bool(hits)
                spec = self.ctx.sensor_specs["front_distance"]
                d = hits[0][0] if hits else float(
                    spec.get("no_object_reading_mm", spec.get("range_mm", 0.0)))
                unit = (block.get_field("UNIT") or block.get_field("UNITS")
                        or "mm").lower()
                return d / 25.4 if "inch" in unit else d

        # Fallback: unrecognized reporter — RECORDED (stage 0b), never raised;
        # raising is population-changing and is a separate attributed change.
        if bt not in self.unknown_reporter_blocks:
            self.unknown_reporter_blocks.append(bt)
        return 0

    # ---------------------------------------------------------------- #
    # Eye-sensor geometry (sensing build Phase 1, 2026-08-19)
    # ---------------------------------------------------------------- #

    @staticmethod
    def _eye_from_block(block: BlockNode) -> str:
        """Which eye the block addresses: "down" | "front" (front default)."""
        raw = (block.get_field("OPTICAL") or "").lower()
        return "down" if "down" in raw else "front"

    def _eye_point(self, eye: str) -> tuple[float, float]:
        """The eye's ground point: robot centre + the eye's forward offset
        along the current heading. Offsets come from the shared robot card
        (sensor_specs); no spec = centre (offset 0)."""
        spec = self.ctx.sensor_specs.get(f"{eye}_eye") or {}
        off = spec.get("forward_offset_mm")
        if off is None:
            off = spec.get("mount_forward_mm", 0.0)
        off = float(off or 0.0)
        rad = math.radians(self.heading)
        return self.x + off * math.cos(rad), self.y + off * math.sin(rad)

    def _eye_detected_color(self, eye: str) -> str | None:
        """The color the given eye detects, or None. Card zones are matched
        in declaration order, honoring per-eye applicability and ring bands;
        the front eye additionally reports the color of the nearest body in
        its assumed cone (Phase 2). Cards with no color_zones keep the legacy
        semantics (boundary color outside the island-edge polygon)."""
        ex, ey = self._eye_point(eye)
        for cz in self.ctx.color_zones:
            if cz.eye is not None and cz.eye != eye:
                continue
            if self._zone_contains(cz, ex, ey):
                return cz.color
        if eye == "front":
            hits = self._front_cone_hits()
            if hits:
                return hits[0][1].color   # None when the body's color is unknown
        if not self.ctx.color_zones and self.ctx.field_hex_vertices:
            if not _point_in_convex_polygon(ex, ey, self.ctx.field_hex_vertices):
                return self.ctx.field_boundary_color
        return None

    @staticmethod
    def _zone_contains(cz: ColorZone, x: float, y: float) -> bool:
        if cz.band_outer_vertices and cz.band_inner_vertices:
            return (_point_in_convex_polygon(x, y, cz.band_outer_vertices)
                    and not _point_in_convex_polygon(x, y, cz.band_inner_vertices))
        if cz.polygon_vertices:
            return _point_in_convex_polygon(x, y, cz.polygon_vertices)
        return False

    def _eye_near_object(self, eye: str) -> bool:
        if self.movable_predicates == "ceiling" \
                and self._movable_world_disturbed():
            return True
        """Object presence for the given eye. Down eye is floor-tuned (VEX
        docs via reviewer 2026-08-19): only a 3D body under the eye point or
        a floor marking the card declares a defined object (the red line —
        reviewer ruling) registers. Front eye: assumed cone against declared
        3D bodies; legacy omnidirectional fallback without a robot card."""
        if eye == "down":
            ex, ey = self._eye_point("down")
            for target in self._sensor_targets():
                if target.body_radius_mm is not None and \
                        _dist(ex, ey, target.x, target.y) <= target.body_radius_mm:
                    contact = self.object_contacts.get(target.object_id)
                    if target.movable and contact is not None and contact < self.step:
                        self._flag("sensor_reading_stale")
                    return True
            for cz in self.ctx.color_zones:
                if cz.registers_as_object and cz.eye in (None, "down") \
                        and self._zone_contains(cz, ex, ey):
                    return True
            return False
        hits = self._front_cone_hits()
        if hits is not None:
            return bool(hits)
        for obj in self.ctx.objects.values():
            if _dist(self.x, self.y, obj.x, obj.y) <= obj.tolerance:
                return True
        return False

    def _movable_world_disturbed(self) -> bool:
        """Hybrid-ruling completion (reviewer diagnoses CROW-C072 and the
        C018/C040 cluster, 2026-08-24): the real world has diverged from
        the card once EITHER (a) any movable contact has occurred, or
        (b) the robot has entered a region the card marks disturbs_world
        (the debris zone: physics scatters pieces unpredictably, often in
        front of the robot and potentially out to the boundary). After
        either, every movable-sensitive sensor evaluation is conditional —
        negative readings and unfired-hat predictions included."""
        if self.object_contacts:
            return True
        return any(self.ctx.regions[rid].disturbs_world
                   for rid, cells in self.region_cells.items() if cells)

    def _distance_hits(self) -> "list[tuple[float, ObjectRef]] | None":
        """Targets in the distance sensor's banded cone from the current
        pose, as (surface_distance, target) nearest-first. None when the
        robot card declares no usable model. The cone NARROWS with range
        (fov_bands, docs-verified); surface distance = centre distance minus
        body radius."""
        spec = self.ctx.sensor_specs.get("front_distance") or {}
        if spec and self._movable_world_disturbed():
            self._flag("sensor_reading_stale")
        rng = float(spec.get("range_mm") or 0.0)
        bands = [b for b in (spec.get("fov_bands") or [])
                 if isinstance(b, dict) and b.get("fov_deg")]
        if rng <= 0.0 or not bands:
            return None
        mount = float(spec.get("mount_forward_mm") or 0.0)
        rad = math.radians(self.heading)
        dxu, dyu = math.cos(rad), math.sin(rad)
        ox, oy = self.x + mount * dxu, self.y + mount * dyu
        hits: list[tuple[float, ObjectRef]] = []
        for target in self._sensor_targets():
            if target.body_radius_mm is None:
                continue
            vx, vy = target.x - ox, target.y - oy
            along = vx * dxu + vy * dyu
            if along <= 0.0 or along - target.body_radius_mm > rng:
                continue
            fov = None
            for band in bands:
                if along <= float(band.get("max_mm", rng)):
                    fov = float(band["fov_deg"])
                    break
            if fov is None:
                fov = float(bands[-1]["fov_deg"])
            spread = math.tan(math.radians(fov / 2.0))
            perp = abs(vx * dyu - vy * dxu)
            if perp <= target.body_radius_mm + along * spread:
                hits.append((max(0.0, along - target.body_radius_mm), target))
        hits.sort(key=lambda h: h[0])
        if hits and spec.get("assumed"):
            self._flag("sensor_model_assumed")
        for _, target in hits:
            contact = self.object_contacts.get(target.object_id)
            if target.movable and contact is not None and contact < self.step:
                self._flag("sensor_reading_stale")
                break
        return hits

    # ------------------------------------------------------------ #
    # Front-eye cone model (sensing build Phase 2, 2026-08-19)
    # ------------------------------------------------------------ #

    def _front_cone_hits(self) -> "list[tuple[float, ObjectRef]] | None":
        """Targets inside the front eye's assumed cone from the current pose,
        as (surface_distance, target) sorted nearest-first. None when the
        robot card declares no front-eye model (legacy callers fall back).
        Cone parameters (fov_deg, range_mm, mount) come from the card —
        ASSUMED values, so every consumer flags sensor_model_assumed."""
        spec = self.ctx.sensor_specs.get("front_eye") or {}
        rng = float(spec.get("range_mm") or 0.0)
        fov = float(spec.get("fov_deg") or 0.0)
        if rng <= 0.0 or fov <= 0.0:
            return None
        if self._movable_world_disturbed():
            self._flag("sensor_reading_stale")
        mount = float(spec.get("mount_forward_mm") or 0.0)
        rad = math.radians(self.heading)
        dxu, dyu = math.cos(rad), math.sin(rad)
        ox, oy = self.x + mount * dxu, self.y + mount * dyu
        spread = math.tan(math.radians(fov / 2.0))
        hits: list[tuple[float, ObjectRef]] = []
        for target in self._sensor_targets():
            if target.body_radius_mm is None:
                continue
            vx, vy = target.x - ox, target.y - oy
            along = vx * dxu + vy * dyu
            if along <= 0.0 or along - target.body_radius_mm > rng:
                continue
            perp = abs(vx * dyu - vy * dxu)
            if perp <= target.body_radius_mm + along * spread:
                hits.append((max(0.0, along - target.body_radius_mm), target))
        hits.sort(key=lambda h: h[0])
        if hits and spec.get("assumed"):
            self._flag("sensor_model_assumed")
        for _, target in hits:
            contact = self.object_contacts.get(target.object_id)
            if contact is not None and contact < self.step:
                self._flag("sensor_reading_stale")
                break
        return hits

    # ---------------------------------------------------------------- #
    # Build result
    # ---------------------------------------------------------------- #

    def build_result(self) -> SimulationResult:
        # Region coverage fractions
        coverage_fracs = {}
        cells_visited = {}
        for region_id, cells in self.region_cells.items():
            region = self.ctx.regions[region_id]
            total = region.total_grid_cells
            coverage_fracs[region_id] = min(1.0, len(cells) / total) if total > 0 else 0.0
            cells_visited[region_id] = len(cells)

        # Net displacement from spawn
        net_disp = _dist(self.x, self.y, self.ctx.spawn_x, self.ctx.spawn_y)

        return SimulationResult(
            path=self.path,
            final_x=self.x,
            final_y=self.y,
            final_heading=self.heading,
            min_distance_to_objects=dict(self.min_dist_to_objects),
            first_object_tolerance_steps=dict(self.first_tol_steps),
            first_object_segmentation_steps=dict(self.first_seg_steps),
            region_coverage_fractions=coverage_fracs,
            region_cells_visited=cells_visited,
            regions_entered=set(self.regions_entered),
            magnet_fires_at_step=self.magnet_fires_at_step,
            net_displacement_from_spawn=net_disp,
            exits_field_boundary=self.exits_boundary,
            min_distance_from_center=self.min_dist_center,
            loop_was_capped=self.loop_was_capped,
            loop_cap_steps=list(self.loop_cap_steps),
            unknown_reporter_blocks=list(self.unknown_reporter_blocks),
            pen_segments=list(self.pen_segments),
            origin_x=self.ctx.spawn_x,
            origin_y=self.ctx.spawn_y,
            origin_heading=self.ctx.spawn_heading,
            execution_flags=list(self.execution_flags),
            fabricated_steps=list(self.fabricated_steps),
            color_detections=list(self.color_detections),
            object_contacts=dict(self.object_contacts),
            pieces_cleared=dict(self.pieces_cleared),
            piece_positions=dict(self.piece_positions),
            sensor_first_eval=dict(self.sensor_first_eval),
            sensor_hats_fired={k: list(v) for k, v in self.sensor_hats_fired.items()},
            blocks_executed=self.blocks_executed,
            sim_time_s=self.sim_time_s,
            stack_lockout_winner=self.stack_lockout_winner,
            scheduler="cooperative" if self._sequencer is not None
            else "sequential",
            motions_superseded=self.motions_superseded,
            drivetrain_contentions=self.drivetrain_contentions,
            drive_rotation_deg=self.drive_rotation_deg,
            loops_exercised=dict(self.loops_exercised),
            branches_exercised={k: list(v)
                                for k, v in self.branches_exercised.items()},
            variables=dict(self.variables),
            structure_trace=list(self.structure_trace),
        )


# ------------------------------------------------------------------ #
# Utilities
# ------------------------------------------------------------------ #

def _dist(x1: float, y1: float, x2: float, y2: float) -> float:
    return math.sqrt((x1 - x2) ** 2 + (y1 - y2) ** 2)


def _point_segment_dist(px: float, py: float, ax: float, ay: float,
                        bx: float, by: float) -> float:
    """Closest distance from point p to segment a->b (sensing Phase 2)."""
    dx, dy = bx - ax, by - ay
    seg_len_sq = dx * dx + dy * dy
    if seg_len_sq == 0.0:
        return _dist(px, py, ax, ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg_len_sq))
    return _dist(px, py, ax + t * dx, ay + t * dy)


def _count_polygon_grid_cells(
    vertices: list[tuple[float, float]],
    x_min: float, x_max: float, y_min: float, y_max: float,
) -> int:
    """Count 100mm grid cells whose centre falls inside a convex polygon.

    Pure geometry: the same playground region gives the same count on every run,
    but the per-request config copy rebuilds the region each time, so the result
    is memoized on the (hashable) vertices and bounds rather than on the region
    object. The count is a plain int, so nothing observable changes.
    """
    return _count_polygon_grid_cells_cached(tuple(vertices), x_min, x_max, y_min, y_max)


@functools.lru_cache(maxsize=256)
def _count_polygon_grid_cells_cached(
    vertices: tuple[tuple[float, float], ...],
    x_min: float, x_max: float, y_min: float, y_max: float,
) -> int:
    """Iterate over the polygon's AABB and test each cell centre. The AABB
    bounds are passed in to avoid recomputing them."""
    cell = _COVERAGE_GRID_CELL_MM
    i_min = int(math.floor(x_min / cell))
    i_max = int(math.ceil(x_max / cell))
    j_min = int(math.floor(y_min / cell))
    j_max = int(math.ceil(y_max / cell))
    count = 0
    for i in range(i_min, i_max):
        cx = (i + 0.5) * cell
        for j in range(j_min, j_max):
            cy = (j + 0.5) * cell
            if _point_in_convex_polygon(cx, cy, vertices):
                count += 1
    return count


def _point_in_convex_polygon(x: float, y: float, vertices: list[tuple[float, float]]) -> bool:
    """Return True if (x, y) is inside the convex polygon defined by ordered vertices.

    Uses the cross-product sign test: for a convex polygon with vertices listed
    counter-clockwise (or all clockwise), a point is inside iff it lies on the same
    side of every edge. The inner hex vertices in mm_yaml are ordered top → top_right
    → … → top_left, which is clockwise in SVG-y-up space, so the sign is consistent.
    """
    n = len(vertices)
    sign = None
    for i in range(n):
        x1, y1 = vertices[i]
        x2, y2 = vertices[(i + 1) % n]
        cross = (x2 - x1) * (y - y1) - (y2 - y1) * (x - x1)
        if cross == 0.0:
            continue
        s = cross > 0
        if sign is None:
            sign = s
        elif s != sign:
            return False
    return True


def _to_mm(distance: float, units: str) -> float:
    u = units.lower()
    if u in ("mm", "millimeter", "millimeters"):
        return distance
    if u in ("cm", "centimeter", "centimeters"):
        return distance * 10.0
    if u in ("m", "meter", "meters"):
        return distance * 1000.0
    if u in ("in", "inch", "inches"):
        return distance * 25.4
    return distance
