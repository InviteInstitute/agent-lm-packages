"""Data assembly for the review viz — pure Python, no streamlit/plotly.

Reads profile() and timeline() plus the parsed program and simulator result; it
never reimplements an indicator, rung assignment, or threshold, and no
playground entity name or numeric threshold appears here — geometry, zones,
labels, and edges all come from the cards via load_configs / resolve_reference.
"""
from __future__ import annotations

from goal_strategy.paths import data_path, require_data

import json
import math
import sys
from dataclasses import asdict
from pathlib import Path


from goal_strategy.detector.parsing.parse_blocks import parse_workspace
from goal_strategy.detector.simulation.simulate_path import (
    _HAT_EYE,
    _HAT_RECEIVER,
    _HAT_STARTED,
    _TRUSTED_HATS,
    simulate_path,
)
from goal_strategy.config import load_configs
from goal_strategy.indicators import (_STATE_ACTIVE_FROM_STEP,
                                          _attachment_structures, _distance,
                                          _point_rect_dist, resolve_reference)
from goal_strategy.profile import _profile
from goal_strategy.timeline import ORIGIN_STEP, timeline_result

_BROADCAST_TYPES = ("pg_events_broadcast", "pg_events_broadcast_and_wait")

FLAG_GROUPS = {
    "trust": ["trigger_unfaithful", "trigger_unsimulated",
              "concurrent_stacks_unverified", "broadcast_concurrency_approximated",
              "broadcast_recursion_suppressed", "broadcast_multiple_receivers",
              "conditional_hat_suppressed", "unmodeled_blocks",
              "nonfinite_numeric_clamped", "nonfinite_parameter_stall",
              "switch_syntax_error", "foreign_playground_block",
              "procedure_undefined", "procedure_recursion_suppressed"],
    "fabrication": ["fabricated_motion", "boundary_exit_fabricated"],
    # Sensing build (2026-08-19): modeled-sensor confidence flags + the
    # wait_until gate marker.
    "sensing": ["sensor_model_assumed", "sensor_reading_stale",
                "wait_until_unmet"],
    "scope": ["simulated_attainment", "no_declared_intent",
              "outcome_field_absent", "simulated_fallback",
              "evidence_post_sim_exit", "attachment_boundary_marginal",
              "execution_budget_exhausted", "timer_hat_unfired",
              "hat_restart_capped"],
}


def load_corpus(parquet_path: str | None = None, playground: str = "castle_crashers"):
    """One (program_id, workspace_xml, playground_params) per session.
    Wrong-playground sessions are excluded per the card's corpus_filter
    (reviewer decision, 2026-08-18)."""
    import pandas as pd
    required = (load_configs(playground).card.get("corpus_filter") or {}) \
        .get("required_outcome_field")
    path = parquet_path or str(data_path() / "final_code_states.parquet")
    out = []
    for row in pd.read_parquet(require_data(path)).to_dict("records"):
        xml = row.get("workspace_xml")
        params = row.get("playground_params")
        params = json.loads(params) if isinstance(params, str) and params else {}
        if required is not None and required not in params:
            continue
        out.append((
            f"{row['student_study_id']}_{row['derived_session_id']}",
            xml if isinstance(xml, str) else "",
            params,
        ))
    return out


# Human labels are a property of the VEX block set, not of a playground —
# derived at load time from the vendored blocks.csv (via the registry's
# display-name map) so they can never drift from the CSV they came from.
from goal_strategy.detector.parsing import block_registry as _block_registry

_BLOCK_LABELS: dict[str, str] = dict(_block_registry._display_name_map)


def _block_label(block_type: str) -> str:
    return _BLOCK_LABELS.get(block_type) or block_type


def _fields_summary(node) -> str:
    parts = [f.value for f in node.fields
             if f.value and not f.name.endswith("_mutator")]
    for value_node in node.values:
        literal = next((f.value for f in value_node.fields
                        if f.name in ("NUM", "TEXT") and f.value), None)
        if literal is not None:
            parts.append(literal)
        else:
            # A real reporter block (variable, operator, sensor…) — show it as
            # the student sees it, not the obscured shadow default (OI-14).
            inner = " ".join(f.value for f in value_node.fields if f.value)
            parts.append(f"⟨{_block_label(value_node.block_type)}"
                         f"{(' ' + inner) if inner else ''}⟩")
    return " ".join(parts)


def _walk_rows(node, depth, rows, steps_by_block):
    while node is not None:
        rows.append({
            "block_id": node.block_id,
            "block_type": node.block_type,
            "label": _block_label(node.block_type),
            "fields": _fields_summary(node),
            "depth": depth,
            "steps": steps_by_block.get(node.block_id, []),
        })
        for child in node.children:
            _walk_rows(child, depth + 1, rows, steps_by_block)
        node = node.next


def _stack_groups(program, full_sim, cfg, treatment):
    """Block-tree stack groups (§B2): handlers with ordinals, receivers with
    their inline broadcast site, untrusted hats marked, orphans last."""
    steps_by_block: dict[str, list[int]] = {}
    for i, ps in enumerate(full_sim.path if full_sim else []):
        steps_by_block.setdefault(ps.block_id, []).append(i)

    # broadcast sites: event name -> (stack_index, block_id) of first broadcaster
    broadcast_sites = {}
    handlers = program.event_handler_stacks
    for si, root in enumerate(handlers):
        node_stack = [root]
        while node_stack:
            node = node_stack.pop()
            while node is not None:
                if node.block_type in _BROADCAST_TYPES:
                    event = node.get_field("BROADCAST_OPTION") or ""
                    broadcast_sites.setdefault(event, (si, node.block_id))
                node_stack.extend(node.children)
                node = node.next

    exec_flags = list(full_sim.execution_flags) if full_sim else []
    started_count = sum(1 for r in handlers if r.block_type == _HAT_STARTED)
    groups = []
    ordinal = 0
    for si, root in enumerate(handlers):
        rows: list[dict] = []
        _walk_rows(root.next, 1, rows, steps_by_block)
        hat_fields = _fields_summary(root)
        group = {
            "kind": "handler",
            "hat_type": root.block_type,
            "hat_label": _block_label(root.block_type)
                         + (f" {hat_fields}" if hat_fields else ""),
            "ordinal": None,
            "note": "",
            "trust_flags": [],
            "rows": rows,
        }
        if root.block_type == _HAT_RECEIVER:
            event = root.get_field("BROADCAST_OPTION") or ""
            site = broadcast_sites.get(event)
            fired = any(r["steps"] for r in rows)
            if site is None:
                group["note"] = "never triggered — no broadcast for this event"
            elif fired:
                group["note"] = f"runs inline at its broadcast site (stack {site[0] + 1})"
                group["inline_from_block"] = site[1]
            else:
                group["note"] = (f"broadcast site authored (stack {site[0] + 1}) "
                                 "— produced no path steps")
                group["inline_from_block"] = site[1]
        elif root.block_type not in _TRUSTED_HATS:
            flag = ("trigger_unfaithful" if root.block_type == _HAT_EYE else "trigger_unsimulated")
            fired = bool(full_sim and full_sim.sensor_hats_fired.get(root.block_id))
            if flag in exec_flags:
                group["trust_flags"].append(flag)
                group["note"] = f"{'SUPPRESSED' if treatment in ('suppress', 'abstain') else 'FORCED'} · {flag}"
            else:
                group["note"] = "modeled sensor trigger · fired" if fired else "modeled sensor trigger · not fired"
            if fired or flag in exec_flags and treatment == "execute":
                ordinal += 1
                group["ordinal"] = ordinal
        else:
            ordinal += 1
            group["ordinal"] = ordinal
            if root.block_type == _HAT_STARTED and started_count > 1 \
                    and "concurrent_stacks_unverified" in exec_flags:
                group["trust_flags"].append("concurrent_stacks_unverified")
        if any(r["block_type"] in _BROADCAST_TYPES for r in rows):
            group["trust_flags"].extend(
                f for f in ("broadcast_concurrency_approximated",
                            "broadcast_recursion_suppressed",
                            "broadcast_multiple_receivers") if f in exec_flags)
        groups.append(group)

    for root in program.orphan_stacks:
        rows = []
        _walk_rows(root, 1, rows, steps_by_block)
        groups.append({"kind": "orphan", "hat_type": None,
                       "hat_label": "Unattached blocks", "ordinal": None,
                       "note": "never executed", "trust_flags": [], "rows": rows})
    return groups


def _zone_bands(cfg):
    """Card-declared engagement zones plus the undescribed complement, for every
    goal-card binding that opts into zones_ref. Generic — nothing named here."""
    bands = []
    for goal in cfg.goals:
        for spec in (*goal.intent, *goal.attainment):
            if "zones_ref" not in spec.binding:
                continue
            zones = resolve_reference(spec.binding["zones_ref"], spec.binding, cfg.card)
            axis = spec.binding.get("zone_axis", "y")
            zone_flags = spec.binding.get("zone_flags", {})
            obj_id = spec.binding.get("object")
            obj = cfg.context.objects[obj_id]
            center = getattr(obj, axis)
            tol = float(obj.tolerance)
            lo_range = center - tol
            hi_range = center + tol
            declared = []
            for name, zone in zones.items():
                z_lo = zone.get(f"{axis}_min", -math.inf)
                z_hi = zone.get(f"{axis}_max", math.inf)
                hi_range = max(hi_range, z_lo + tol if math.isinf(z_hi) else z_hi)
                declared.append((max(z_lo, lo_range), min(z_hi, hi_range), name))
            declared = [d for d in sorted(declared) if d[0] < d[1]]
            entry = {"object": obj_id, "axis": axis, "range": [lo_range, hi_range],
                     "bands": []}
            cursor = lo_range
            for z_lo, z_hi, name in declared:
                if z_lo > cursor:
                    entry["bands"].append({"label": "undescribed", "lo": cursor,
                                           "hi": z_lo, "kind": "undescribed"})
                entry["bands"].append({
                    "label": name, "lo": z_lo, "hi": min(z_hi, hi_range),
                    "kind": "flagged" if name in zone_flags else "described"})
                cursor = max(cursor, z_hi)
            if cursor < hi_range:
                entry["bands"].append({"label": "undescribed", "lo": cursor,
                                       "hi": hi_range, "kind": "undescribed"})
            bands.append(entry)
    return bands


def _qualifying_steps(cfg, full_sim):
    """Steps the walkthrough highlights as engagement moments: state active
    and within tolerance (state_active_within_radius), or the magnet point
    within attach reach of a declared structure
    (state_active_attachment_clearance — OI-21 near-contact model)."""
    steps = set()
    if full_sim is None:
        return steps
    for goal in cfg.goals:
        for spec in (*goal.intent, *goal.attainment):
            if spec.indicator not in ("state_active_within_radius",
                                      "state_active_attachment_clearance"):
                continue
            accessor = _STATE_ACTIVE_FROM_STEP.get(spec.binding.get("state"))
            active_from = accessor(full_sim) if accessor else None
            if active_from is None:
                continue
            if spec.indicator == "state_active_attachment_clearance":
                structures = _attachment_structures(cfg.card, spec.binding["object"])
                mount = float((cfg.context.sensor_specs.get("magnet") or {})
                              .get("mount_forward_mm") or 0.0)
                if not structures:
                    continue
                for i, ps in enumerate(full_sim.path):
                    if ps.step < active_from:
                        continue
                    h = math.radians(ps.heading)
                    mx, my = ps.x + mount * math.cos(h), ps.y + mount * math.sin(h)
                    margin = min((_point_rect_dist(mx, my, geo) if kind == "rect"
                                  else _distance(mx, my, geo[0], geo[1])) - gap
                                 for kind, geo, gap in structures)
                    if margin <= 0.0:
                        steps.add(i)
                continue
            obj = cfg.context.objects[spec.binding["object"]]
            for i, ps in enumerate(full_sim.path):
                if ps.step >= active_from and \
                        _distance(ps.x, ps.y, obj.x, obj.y) <= obj.tolerance:
                    steps.add(i)
    return steps


def walkthrough_payload(program_id: str, workspace_xml: str,
                        playground_params: dict | None,
                        playground: str = "castle_crashers",
                        treatment: str = "execute") -> dict:
    """Everything View 1 serialises into its self-contained HTML page."""
    from goal_strategy.execution import prepare_execution
    execution = prepare_execution(workspace_xml, program_id, playground_params,
                                  playground, conditional_hats=treatment)
    cfg, program, full = execution.config, execution.program, execution.context.full_sim
    prof = _profile(workspace_xml, program_id, playground_params, playground,
                    _execution=execution)
    tl = timeline_result(workspace_xml, program_id, playground_params,
                         playground, _execution=execution)

    polygon = (cfg.card.get("field_boundary") or {}).get("polygon_mm") or []
    qualifying = _qualifying_steps(cfg, full)
    fabricated = set(full.fabricated_steps) if full else set()
    exit_idx = tl.boundary_exit_step

    path = []
    for i, ps in enumerate(full.path if full else []):
        path.append({"step": i, "x": ps.x, "y": ps.y,
                     "block_id": ps.block_id, "block_type": ps.block_type,
                     "fabricated": i in fabricated,
                     "qualifying": i in qualifying,
                     "post_exit": exit_idx is not None and i > exit_idx and not prof.boundary_exit_overridden})

    gps_spec = (cfg.card.get("outcome_metrics") or {}).get("final_gps_position") or {}
    gx = (playground_params or {}).get(gps_spec.get("x_field"))
    gy = (playground_params or {}).get(gps_spec.get("y_field"))
    try:
        gps_final = [float(gx), float(gy)]
        if not all(math.isfinite(v) for v in gps_final):
            gps_final = None
    except (TypeError, ValueError, OverflowError):
        gps_final = None

    goals = []
    for g_ev in prof.goals:
        goals.append({"goal": g_ev.goal, "indicators": [
            {**asdict(ind), "kind": kind}
            for kind, inds in (("intent", g_ev.intent), ("attainment", g_ev.attainment))
            for ind in inds]})

    return {
        "program_id": program_id,
        "playground": playground,
        "treatment": treatment,
        "config_version": prof.config_version,
        "parse_failed": program is None,
        "workspace_xml": workspace_xml or "",
        "stacks": _stack_groups(program, full, cfg, treatment) if program else [],
        "path": path,
        "origin": {"x": full.origin_x, "y": full.origin_y} if full
                  else {"x": cfg.context.spawn_x, "y": cfg.context.spawn_y},
        "geometry": {
            "boundary": polygon,
            "regions": [{"id": rid, "x_min": r.x_min, "x_max": r.x_max,
                         "y_min": r.y_min, "y_max": r.y_max}
                        for rid, r in cfg.context.regions.items()],
            "objects": [{"id": oid, "x": o.x, "y": o.y, "tolerance": o.tolerance}
                        for oid, o in cfg.context.objects.items()]
                       # castle pieces (sensing build): drawn like objects,
                       # body radius as the circle — they are what the
                       # modeled sensors actually see
                       + [{"id": p.object_id, "x": p.x, "y": p.y,
                           "tolerance": p.body_radius_mm or 0, "piece": True}
                          for p in cfg.context.pieces],
            "spawn": [cfg.context.spawn_x, cfg.context.spawn_y],
            "zone_bands": _zone_bands(cfg),
        },
        "sim_final": [full.final_x, full.final_y] if full else None,
        "gps_final": gps_final,
        "fidelity": {"sim_off": prof.sim_final_off_island,
                     "gps_off": prof.gps_final_off_island,
                     "agreement": prof.off_island_agreement,
                     "error_mm": prof.gps_final_error_mm,
                     "reason": prof.gps_final_error_reason},
        "exit_step": exit_idx,
        "boundary_exit_fabricated": prof.boundary_exit_fabricated,
        "events": [asdict(e) for e in tl.events],
        "color_detections": list(full.color_detections) if full else [],
        "object_contacts": dict(full.object_contacts) if full else {},
        "post_exit_events": [asdict(e) for e in tl.post_exit_events],
        "goals": goals,
        "flag_groups": {**FLAG_GROUPS, "other": sorted({f for g in prof.goals
            for i in g.intent + g.attainment for f in i.flags}
            - {f for group in FLAG_GROUPS.values() for f in group})},
        "unknown_reporter_blocks": list(full.unknown_reporter_blocks) if full else [],
        "orphan_block_count": prof.orphan_block_count,
        "fabricated_motion": prof.fabricated_motion,
        "n_top_level_stacks": (len(program.event_handler_stacks)
                               + len(program.orphan_stacks)) if program else 0,
        "n_handler_stacks": len(program.event_handler_stacks) if program else 0,
    }


def is_conditional_hat_program(workspace_xml: str, program_id: str) -> bool:
    program = parse_workspace(workspace_xml or "", program_id)
    if program is None:
        return False
    return any(r.block_type not in _TRUSTED_HATS
               for r in program.event_handler_stacks)


def cohort_table(playground: str = "castle_crashers"):
    """One row per program: rungs, values, flags, fidelity, first event steps."""
    import pandas as pd
    rows = []
    for program_id, xml, params in load_corpus():
        prof = _profile(xml, program_id, params, playground)
        tl = timeline_result(xml, program_id, params, playground)
        row = {
            "program_id": program_id,
            "boundary_exceeded": prof.boundary_exceeded,
            "boundary_exit_step": prof.boundary_exit_step,
            "boundary_exit_fabricated": prof.boundary_exit_fabricated,
            "fabricated_motion": prof.fabricated_motion,
            "orphan_block_count": prof.orphan_block_count,
            "sim_final_off_island": prof.sim_final_off_island,
            "gps_final_off_island": prof.gps_final_off_island,
            "off_island_agreement": prof.off_island_agreement,
            "gps_final_error_mm": prof.gps_final_error_mm,
            "gps_final_error_reason": prof.gps_final_error_reason,
            "config_version": prof.config_version,
        }
        all_flags = set()
        for goal in prof.goals:
            for ind in goal.intent + goal.attainment:
                base = f"{goal.goal}__{ind.name}"
                row[f"{base}__rung"] = ind.rung
                row[f"{base}__value"] = ind.value
                all_flags.update(ind.flags)
        row["flags"] = ";".join(sorted(all_flags))
        for ev in tl.events:
            key = f"first_event_step__{ev.indicator}"
            if key not in row:
                row[key] = ev.step
        rows.append(row)
    return pd.DataFrame(rows)


def indicator_catalog(playground: str = "castle_crashers"):
    """(goal, name, kind, edges, labels, …rung card facts) per card indicator —
    View 3 and the rung-review page. `provenance` is the card-authored note;
    `design_informed` is derived: a reference-resolved ladder, or a note
    starting with "design"."""
    cfg = load_configs(playground)
    out = []
    for goal in cfg.goals:
        for kind, specs in (("intent", goal.intent), ("attainment", goal.attainment)):
            for spec in specs:
                r = spec.rungs
                out.append({
                    "goal": goal.id, "name": spec.name, "kind": kind,
                    "edges": list(r.edges) if r else [],
                    "labels": list(r.labels) if r else [],
                    "rung_kind": r.kind if r else None,
                    "direction": r.direction if r else None,
                    "reference": r.reference if r else None,
                    "absent_label": r.absent_label if r else None,
                    "provenance": r.provenance if r else None,
                    "design_informed": bool(r) and (
                        r.reference is not None
                        or (r.provenance or "").startswith("design")),
                    "flag_rules": [dict(fr) for fr in spec.flag_rules],
                })
    return out
