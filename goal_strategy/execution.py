"""Shared parsed program, execution and outcome-dependent scoring scope."""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Optional

from .config import LoadedConfig, load_configs
from .codefacts import extract_code_facts
from .indicators import EvalContext, _polyline_min_distance
from .detector.parsing.parse_blocks import parse_workspace
from .detector.parsing.block_program import BlockProgram
from .detector.simulation.simulate_path import simulate_path, slice_sim_result


@dataclass
class Execution:
    config: LoadedConfig
    program: BlockProgram | None
    context: EvalContext
    exit_index: int | None
    boundary_exit_overridden: bool


def prepare_execution(workspace_xml, program_id, playground_params=None,
                      playground="castle_crashers", truncate=True, configs_dir=None,
                      conditional_hats=None, stack_precedence=None, scheduler=None,
                      run_duration_s=None, duration_imputed=False):
    from .profile import _find_boundary_exit, _fall_off_tolerance, _on_island
    cfg = load_configs(playground, configs_dir)
    treatment = (conditional_hats
                 or os.environ.get("GOAL_STRATEGY_CONDITIONAL_HATS")
                 or os.environ.get("VEX_GOAL_PROFILES_CONDITIONAL_HATS")
                 or "execute").lower()

    program = parse_workspace(workspace_xml or "", program_id)
    code_facts = extract_code_facts(program, cfg.block_families) if program else None
    sim_mode = "suppress" if treatment in ("suppress", "abstain") else "execute"

    # Program-rejecting blocks (reviewer ruling 2026-08-24): invalid Switch
    # text makes VEX error immediately and execute NOTHING — the faithful
    # model is no simulation at all, with the rejection as the sim channel's
    # abstain reason. Checked over the WHOLE workspace (orphans included:
    # the rejection is project-level).
    sim_unavailable_reason = "no_simulation"
    rejected = False
    if program is not None and cfg.capabilities:
        from .config import resolve_capability
        for bt in sorted({b.block_type
                   for b in program.iter_all_blocks_including_orphans()}):
            entry = resolve_capability(bt, cfg.capabilities)
            if entry.get("rejects_program"):
                rejected = True
                sim_unavailable_reason = entry.get("flag", "program_rejected")
                break
    # VR-Seq (2026-08-26): execution model resolves explicit arg -> card
    # `simulation.scheduler` -> sequential. The card flip is the §6 event
    # that makes cooperative the default (close-out step 5).
    sched = (scheduler
             or (cfg.card.get("simulation") or {}).get("scheduler")
             or "sequential")
    # OI-28 (2026-08-28): the measured 60Hz loop clock, card-declared as
    # `simulation.loop_clock_hz`. It is enabled ONLY when the caller also
    # supplies the run's observed duration as the wall-clock budget — the
    # clock without a budget leaves the unroll caps governing, which is
    # strictly worse than clock-off. Callers with no duration (the public
    # profile(), the streaming path) are therefore unchanged.
    _hz = (cfg.card.get("simulation") or {}).get("loop_clock_hz")
    _clock = ({"loop_iteration_time_s": 1.0 / float(_hz),
               "time_budget_s": float(run_duration_s)}
              if _hz and run_duration_s else {})
    full_sim = (simulate_path(program, cfg.context, conditional_hats=sim_mode,
                              stack_precedence=stack_precedence,
                              scheduler=sched, **_clock)
                if program is not None and not rejected else None)
    if full_sim is not None and _clock and duration_imputed:
        # the budget is a SESSION MEDIAN, not this run's observed duration
        # (reviewer ruling 2026-08-28: impute, flag, no sensitivity sweep)
        full_sim.execution_flags.append("duration_imputed")

    # D2 gates (Stage 1, 2026-08-21; foreign layer 2026-08-24): over the
    # ACTIVE blocks (orphans degrade nothing) —
    # 1. a block OUTSIDE the robot model's available set is FOREIGN code
    #    (transferred from another playground): VEX runs the program and the
    #    block produces no behavior (reviewer probe) — our no-op is faithful;
    #    flagged foreign_playground_block, not unmodeled.
    # 2. a block whose registry class is unsimulable flags the sim channel by
    #    name — nothing the simulator cannot model passes silently (the
    #    procedures_call lesson).
    if program is not None and full_sim is not None and cfg.capabilities:
        from .config import resolve_capability
        unavailable = set(((cfg.robot or {}).get("available_blocks") or {})
                          .get("unavailable") or [])
        for bt in sorted({b.block_type for b in program.iter_all_blocks()}):
            if bt in unavailable:
                if "foreign_playground_block" not in full_sim.execution_flags:
                    full_sim.execution_flags.append("foreign_playground_block")
                continue
            entry = resolve_capability(bt, cfg.capabilities)
            if entry.get("class") == "unsimulable":
                flag = entry.get("flag", "unmodeled_blocks")
                if flag not in full_sim.execution_flags:
                    full_sim.execution_flags.append(flag)

    if full_sim is not None:
        if full_sim.loop_was_capped:
            full_sim.execution_flags.append("loop_capped")
        if full_sim.unknown_reporter_blocks:
            full_sim.execution_flags.append("unknown_reporter")
        full_sim.execution_flags = sorted(set(full_sim.execution_flags))
    if program is None:
        sim_unavailable_reason = "invalid_xml"

    if full_sim is not None and sched == "cooperative" and sum(
            h.block_type == "pg_events_when_started" for h in program.event_handler_stacks) > 1:
        # Distinct uncertainty worlds, never duplicate the nominal execution.
        floor = simulate_path(program, cfg.context, conditional_hats=sim_mode,
                              scheduler=sched, stack_precedence=stack_precedence,
                              movable_predicates="floor")
        ceiling = simulate_path(program, cfg.context, conditional_hats=sim_mode,
                                scheduler=sched, stack_precedence=stack_precedence,
                                movable_predicates="ceiling")
        if floor.exits_field_boundary != ceiling.exits_field_boundary:
            full_sim.execution_flags = sorted(set(full_sim.execution_flags + ["debris_bracket_divergent"]))

    boundary_exceeded = False
    boundary_exit_step: Optional[int] = None
    boundary_exit_overridden = False
    exit_idx: Optional[int] = None
    scored_sim = full_sim
    polygon = (cfg.card.get("field_boundary") or {}).get("polygon_mm")
    if full_sim is not None and polygon:
        boundary_exceeded, exit_idx = _find_boundary_exit(
            full_sim, polygon, _fall_off_tolerance(cfg.card))
        if boundary_exceeded:
            if exit_idx is None:
                # Origin itself outside the field: no valid scoring scope at all.
                # (Never route an empty range through slice_sim_result — it would
                # fall back to whole-run minima and bleed across the boundary.)
                scored_sim = None
            else:
                boundary_exit_step = full_sim.path[exit_idx].step
                # Outcome-override (reviewer ruling 2026-08-19, card-driven):
                # when the MEASURED outcome says the run ended on-island and
                # the run was not stopped early, a simulated exit is judged an
                # artifact of accumulated dead-reckoning drift — defer to the
                # outcome and score the FULL program. Evidence that depends on
                # the post-exit path is flagged conditional below.
                override_cfg = (cfg.card.get("fidelity_thresholds") or {}) \
                    .get("sim_exit_outcome_override")
                if truncate and isinstance(override_cfg, dict):
                    spec = (cfg.card.get("outcome_metrics") or {}) \
                        .get("final_gps_position") or {}
                    gx = (playground_params or {}).get(spec.get("x_field"))
                    gy = (playground_params or {}).get(spec.get("y_field"))
                    stopped_field = override_cfg.get("stopped_field")
                    stopped = bool((playground_params or {}).get(stopped_field)) \
                        if stopped_field else False
                    try:
                        gps_on = (gx is not None and gy is not None
                                  and math.isfinite(float(gx)) and math.isfinite(float(gy)) and _on_island(
                            float(gx), float(gy), polygon, _fall_off_tolerance(cfg.card)))
                    except (TypeError, ValueError, OverflowError):
                        gps_on = False
                    corroborated = False
                    if gps_on:
                        # The outcome must CORROBORATE the simulated path —
                        # GPS within the card bound of the trajectory. A
                        # genuinely divergent trajectory keeps §6a truncation.
                        bound = float(override_cfg.get(
                            "trajectory_corroboration_mm", 0) or 0)
                        pts = ([(full_sim.origin_x, full_sim.origin_y)]
                               + [(p.x, p.y) for p in full_sim.path])
                        corroborated = bound > 0 and _polyline_min_distance(
                            pts, float(gx), float(gy)) <= bound
                    boundary_exit_overridden = gps_on and corroborated and not stopped
                if truncate and not boundary_exit_overridden:
                    # §6a: truncate at, and including, the first outside step.
                    scored_sim = slice_sim_result(full_sim, 0, exit_idx + 1,
                                                  context=cfg.context)

    ectx = EvalContext(
        program_id=program_id, playground=playground,
        card=cfg.card, context=cfg.context, block_families=cfg.block_families,
        code_facts=code_facts, full_sim=full_sim, scored_sim=scored_sim,
        playground_params=playground_params,
        boundary_exceeded=boundary_exceeded, boundary_exit_step=boundary_exit_step,
        conditional_hat_treatment=treatment,
        sim_unavailable_reason=sim_unavailable_reason,
    )

    return Execution(cfg, program, ectx, exit_idx, boundary_exit_overridden)
