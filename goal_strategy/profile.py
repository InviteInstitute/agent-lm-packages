"""profile() — the public API: one student program in, one GoalProfile out.

Pure and stateless; configs load once (lru_cache) at first call. Never raises on
malformed XML or missing playground_params — indicators abstain with a reason.
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass, field
from typing import Optional, Sequence

from goal_strategy.detector.parsing.parse_blocks import parse_workspace
from goal_strategy.detector.simulation.simulate_path import (
    SimulationResult,
    simulate_path,
    slice_sim_result,
)

from .codefacts import extract_code_facts
from .config import GoalSpec, IndicatorSpec, LoadedConfig, load_configs
from .indicators import _polyline_min_distance
from .indicators import REGISTRY, EvalContext, IndicatorResult


@dataclass
class Indicator:
    name: str
    channel: str                      # "code" | "simulation" | "outcome"
    value: float | bool | str | None  # continuous where one exists — always populated
    rung: str | None
    rung_edges: list                  # echoed for auditability
    abstained: bool
    abstain_reason: str | None
    flags: list[str]


@dataclass
class GoalEvidence:
    goal: str
    intent: list[Indicator]
    attainment: list[Indicator]       # may be EMPTY — a modelling statement, not a gap


@dataclass
class GoalProfile:
    program_id: str
    playground: str
    goals: list[GoalEvidence]
    boundary_exceeded: bool           # critical failure — NOT a goal
    boundary_exit_step: int | None
    outcome_available: bool
    config_version: str
    # Task-3 two-tier fidelity metric against the real run's GPS (revised):
    # tier (a) — did sim and reality agree on whether the robot's final position
    # is off the island; tier (b) — coordinate error, computed ONLY when both
    # agree it stayed on (coordinates are not comparable once either is off).
    sim_final_off_island: bool | None = None
    gps_final_off_island: bool | None = None
    off_island_agreement: bool | None = None
    gps_final_error_mm: float | None = None
    gps_final_error_reason: str | None = None   # why null, e.g. off_island_position_not_comparable
    # Descriptive-only orphan count (no flags, no indicator effect).
    orphan_block_count: int | None = None
    # Task-3 Part D: the program contains fallback-invented motion; and the §6a
    # truncation point itself sits on an invented step (contaminated boundary).
    fabricated_motion: bool = False
    boundary_exit_fabricated: bool = False
    # Outcome-override (reviewer ruling 2026-08-19, card-driven): the sim
    # reported an exit but the measured outcome ended on-island on a
    # non-stopped run — the exit is judged dead-reckoning drift; the FULL
    # program was scored, with post-exit-dependent evidence flagged
    # evidence_post_sim_exit. boundary_exceeded stays True (a fact of the
    # simulation); this field records that scoring deferred to the outcome.
    boundary_exit_overridden: bool = False
    fidelity_verdict: str = "not_applicable"
    gps_to_trajectory_mm: float | None = None
    edge_zone_traversed: bool = False


def profile(workspace_xml: str, program_id: str,
            playground_params: dict | None = None,
            playground: str = "castle_crashers") -> GoalProfile:
    return _profile(workspace_xml, program_id, playground_params, playground)


def _profile(workspace_xml: str, program_id: str,
             playground_params: dict | None = None,
             playground: str = "castle_crashers",
             truncate: bool = True,
             configs_dir: str | None = None,
             conditional_hats: str | None = None,
             stack_precedence: str | None = None,
             scheduler: str | None = None,
             _execution=None) -> GoalProfile:
    """profile() plus the internal knobs: full-path scoring for the design-time
    regression pins, an alternate configs directory for tests, and the task-3
    Part-B conditional-hat treatment — "execute" (B1, default), "suppress" (B2),
    or "abstain" (B3: B2's path, simulation channel abstains). Defaults to B1 so
    nothing changes silently; also settable via VEX_GOAL_PROFILES_CONDITIONAL_HATS.
    `stack_precedence` is the OI-7 winning when_started block id recovered from
    longitudinal snapshots (see simulate_path) — None (the default, and the only
    value the dev-corpus path ever passes) is byte-identical to pre-lockout
    behavior.
    """
    from .execution import prepare_execution
    execution = _execution or prepare_execution(
        workspace_xml, program_id, playground_params, playground, truncate,
        configs_dir, conditional_hats, stack_precedence, scheduler)
    cfg, program, ectx = execution.config, execution.program, execution.context
    full_sim, scored_sim = ectx.full_sim, ectx.scored_sim
    code_facts = ectx.code_facts
    treatment = ectx.conditional_hat_treatment
    boundary_exceeded = ectx.boundary_exceeded
    boundary_exit_step = ectx.boundary_exit_step
    exit_idx = execution.exit_index
    boundary_exit_overridden = execution.boundary_exit_overridden

    goals = [_evaluate_goal(goal_spec, ectx) for goal_spec in cfg.goals]

    if boundary_exit_overridden and exit_idx is not None:
        # Reviewer ruling (2026-08-19): full-program evidence stands, but any
        # sim-channel indicator whose value the post-exit path CHANGED is
        # marked conditional — we are less confident in evidence established
        # after the point where sim and reality disagreed.
        trunc_ctx = EvalContext(
            program_id=program_id, playground=playground,
            card=cfg.card, context=cfg.context, block_families=cfg.block_families,
            code_facts=code_facts, full_sim=full_sim,
            scored_sim=slice_sim_result(full_sim, 0, exit_idx + 1,
                                        context=cfg.context),
            playground_params=playground_params,
            boundary_exceeded=boundary_exceeded,
            boundary_exit_step=boundary_exit_step,
            conditional_hat_treatment=treatment,
        )
        for g_full, g_trunc in zip(goals,
                                   (_evaluate_goal(gs, trunc_ctx) for gs in cfg.goals)):
            for i_full, i_trunc in zip(g_full.intent + g_full.attainment,
                                       g_trunc.intent + g_trunc.attainment):
                if i_full.channel == "simulation" and not i_full.abstained \
                        and (i_full.value, i_full.rung) != (i_trunc.value, i_trunc.rung) \
                        and "evidence_post_sim_exit" not in i_full.flags:
                    i_full.flags.append("evidence_post_sim_exit")

    fidelity = _final_position_fidelity(
        cfg.card, full_sim, playground_params,
        boundary_exceeded and not boundary_exit_overridden)
    result = GoalProfile(
        program_id=program_id,
        playground=playground,
        goals=goals,
        boundary_exceeded=boundary_exceeded,
        boundary_exit_step=boundary_exit_step,
        outcome_available=bool(playground_params),
        config_version=cfg.config_version,
        sim_final_off_island=fidelity["sim_off"],
        gps_final_off_island=fidelity["gps_off"],
        off_island_agreement=fidelity["agreement"],
        gps_final_error_mm=fidelity["error_mm"],
        gps_final_error_reason=fidelity["reason"],
        orphan_block_count=program.orphan_block_count if program else None,
        fabricated_motion=bool(full_sim and full_sim.fabricated_steps),
        boundary_exit_fabricated=(full_sim is not None
                                  and boundary_exit_step is not None
                                  and boundary_exit_step in full_sim.fabricated_steps),
        boundary_exit_overridden=boundary_exit_overridden,
    )

    from .fidelity import assess
    detail = assess(cfg, program, full_sim, result, playground_params)
    result.fidelity_verdict = detail["verdict"]
    result.gps_to_trajectory_mm = detail["trajectory_mm"]
    result.edge_zone_traversed = detail["edge_zone"]
    for goal in goals:
        for indicator in goal.intent + goal.attainment:
            if indicator.abstained:
                continue
            if detail["verdict"] == "early_stop" and indicator.channel == "outcome":
                indicator.flags.append("early_stop_outcome")
            if detail["verdict"] == "UNATTRIBUTED" and indicator.channel == "simulation":
                indicator.flags.append("sim_unverified")
            indicator.flags = sorted(set(indicator.flags))
    return result


def _final_position_fidelity(card: dict, full_sim: Optional[SimulationResult],
                             playground_params: dict | None,
                             boundary_exceeded: bool = False) -> dict:
    """Two-tier §3b fidelity metric against the real run's GPS.

    Tier (a): sim vs GPS agreement on whether the run ENDED off the island.
    §6a-consistency (reviewer-adopted 2026-08-19): a simulated path that exits
    the island ends there — the run-to-failure semantics say the real robot
    falls at the exit point, and everything the wall-less simulator does
    afterwards is fiction. So sim_off = boundary_exceeded, not a test of the
    fictional full-path final. Tier (b): coordinate error in mm, only when both
    sides agree the robot stayed on throughout.
    """
    out = {"sim_off": None, "gps_off": None, "agreement": None,
           "error_mm": None, "reason": None}
    if full_sim is None:
        out["reason"] = "no_simulation"
        return out
    polygon = (card.get("field_boundary") or {}).get("polygon_mm")
    if polygon:
        out["sim_off"] = boundary_exceeded
    if (playground_params or {}).get("project_stopped_by_user"):
        out["reason"] = "early_stop"
        return out
    spec = (card.get("outcome_metrics") or {}).get("final_gps_position") or {}
    gx = (playground_params or {}).get(spec.get("x_field"))
    gy = (playground_params or {}).get(spec.get("y_field"))
    if gx is None or gy is None:
        out["reason"] = "gps_unavailable"
        return out
    try:
        gx, gy = float(gx), float(gy)
    except (TypeError, ValueError, OverflowError):
        out["reason"] = "gps_unavailable"
        return out
    if not all(math.isfinite(v) for v in (gx, gy)):
        out["reason"] = "gps_invalid"
        return out
    if not polygon:
        error = math.hypot(full_sim.final_x - gx, full_sim.final_y - gy)
        out["error_mm"] = error if math.isfinite(error) else None
        out["reason"] = None if math.isfinite(error) else "gps_invalid"
        return out
    out["gps_off"] = not _on_island(gx, gy, polygon, _fall_off_tolerance(card))
    out["agreement"] = out["sim_off"] == out["gps_off"]
    if out["sim_off"] or out["gps_off"]:
        out["reason"] = "off_island_position_not_comparable"
        return out
    error = math.hypot(full_sim.final_x - gx, full_sim.final_y - gy)
    out["error_mm"] = error if math.isfinite(error) else None
    out["reason"] = None if math.isfinite(error) else "gps_invalid"
    return out


def _evaluate_goal(goal: GoalSpec, ectx: EvalContext) -> GoalEvidence:
    intent = [_evaluate_indicator(spec, ectx, attainment=False) for spec in goal.intent]
    attainment = [_evaluate_indicator(spec, ectx, attainment=True) for spec in goal.attainment]
    _apply_flag_rules(goal, intent + attainment)
    return GoalEvidence(goal=goal.id, intent=intent, attainment=attainment)


def _evaluate_indicator(spec: IndicatorSpec, ectx: EvalContext,
                        attainment: bool) -> Indicator:
    exec_flags = list(ectx.full_sim.execution_flags) if ectx.full_sim else []
    result = REGISTRY[spec.indicator](ectx, spec.binding)
    if isinstance(result.value, float) and not math.isfinite(result.value):
        reason = "outcome_field_invalid" if result.channel == "outcome" else "simulation_value_invalid"
        result = IndicatorResult(None, None, result.channel, abstained=True, abstain_reason=reason)
    # B3 (available behind the flag; withdrawn as default — see FINDINGS): an
    # untrusted hat had a pathway to execution, so the simulation channel
    # abstains, with the reason split by why the trigger can't be trusted.
    # Code and outcome channels are unaffected.
    if (ectx.conditional_hat_treatment == "abstain"
            and result.channel == "simulation" and not result.abstained):
        reason = ("trigger_unsimulated" if "trigger_unsimulated" in exec_flags
                  else "trigger_unfaithful" if "trigger_unfaithful" in exec_flags
                  else None)
        if reason:
            result = IndicatorResult(None, None, "simulation", abstained=True,
                                     abstain_reason=reason)
    rung = None
    if spec.rungs is not None and not result.abstained:
        rung = spec.rungs.evaluate(result.raw)
    flags = list(result.flags)
    if attainment and result.channel == "simulation" and not result.abstained \
            and "simulated_attainment" not in flags:
        flags.append("simulated_attainment")
    if result.channel == "simulation" and not result.abstained:
        for exec_flag in exec_flags:
            if exec_flag not in flags:
                flags.append(exec_flag)
        if ectx.full_sim.fabricated_steps and "fabricated_motion" not in flags:
            flags.append("fabricated_motion")
    return Indicator(
        name=spec.name,
        channel=result.channel,
        value=result.value,
        rung=rung,
        rung_edges=list(spec.rungs.edges) if spec.rungs else [],
        abstained=result.abstained,
        abstain_reason=result.abstain_reason,
        flags=sorted(set(flags)),
    )


def _apply_flag_rules(goal: GoalSpec, indicators: list[Indicator]) -> None:
    by_name = {ind.name: ind for ind in indicators}
    for spec in (*goal.intent, *goal.attainment):
        for rule in spec.flag_rules:
            this = by_name[spec.name]
            other = by_name.get(rule["other_indicator"])
            if (this.rung in rule["when_rung_in"] and other is not None
                    and other.rung in rule["other_rung_in"]
                    and rule["flag"] not in this.flags):
                this.flags.append(rule["flag"])


def _fall_off_tolerance(card: dict) -> float:
    """Any-part-on-island rule (reviewer-confirmed 2026-08-18; refined to the
    half-diagonal 2026-08-19): the robot stays on the island while ANY part of
    its body is on it, so a CENTRE coordinate may sit up to half the body
    diagonal beyond the field_boundary polygon — the maximum reach over all
    orientations. Card-driven — no constant lives here. (Corpus-verified: the
    half-length -> half-diagonal refinement changes zero classifications.)"""
    robot = card.get("robot") or {}
    half_l = float(robot.get("length_mm", 0.0)) / 2.0
    half_w = float(robot.get("width_mm", 0.0)) / 2.0
    return math.hypot(half_l, half_w)


def _on_island(x: float, y: float, polygon: Sequence[Sequence[float]],
               tolerance: float = 0.0) -> bool:
    """Inside the polygon, or within `tolerance` mm beyond its nearest edge."""
    if _point_in_polygon(x, y, polygon):
        return True
    if tolerance <= 0:
        return False
    n = len(polygon)
    best = math.inf
    for i in range(n):
        x0, y0 = polygon[i]
        x1, y1 = polygon[(i + 1) % n]
        dx, dy = x1 - x0, y1 - y0
        t = max(0.0, min(1.0, ((x - x0) * dx + (y - y0) * dy) / (dx * dx + dy * dy)))
        best = min(best, math.hypot(x - (x0 + t * dx), y - (y0 + t * dy)))
    return best <= tolerance


def _point_in_polygon(x: float, y: float,
                      polygon: Sequence[Sequence[float]]) -> bool:
    """Even-odd ray cast; works for non-convex polygons. On-edge counts inside."""
    inside = False
    n = len(polygon)
    for i in range(n):
        x0, y0 = polygon[i]
        x1, y1 = polygon[(i + 1) % n]
        if (y0 > y) != (y1 > y):
            x_cross = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
            if x == x_cross:
                return True
            if x < x_cross:
                inside = not inside
        elif y0 == y == y1 and min(x0, x1) <= x <= max(x0, x1):
            return True
    return inside


def _find_boundary_exit(sim: SimulationResult,
                        polygon: Sequence[Sequence[float]],
                        tolerance: float = 0.0) -> tuple[bool, Optional[int]]:
    """Origin-seeded scan (spec §3): the spawn state precedes path[0] and must be
    checked first. `tolerance` implements the any-part-on-island rule for the
    centre-point path. Returns (boundary_exceeded, index into sim.path of the
    first off-island step; None when the origin itself is off)."""
    if not _on_island(sim.origin_x, sim.origin_y, polygon, tolerance):
        return True, None
    for i, ps in enumerate(sim.path):
        if not _on_island(ps.x, ps.y, polygon, tolerance):
            return True, i
    return False, None
