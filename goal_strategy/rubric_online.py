"""Per-run purpose-2 rubric composition for the online API.

PROVISIONAL. In the source project purpose-2 ships as
``rubric_status = provisional_stage2E`` and is under active human validation
(Stage 2E). This module composes the SAME inputs the offline sweep feeds
``rubric_combiner.combine_run`` (production code evidence plus per-scenario
battery evidence), routed through an in-memory CSV round-trip so the online
path matches the ``stage2_code_evidence.csv`` and
``stage3_battery_evidence.csv`` semantics exactly. Callers opt in through
``include_rubric`` and must treat the levels as provisional, never as settled
per-run feedback.

The composition never re-simulates the production run: it reuses the shared
execution artifact's parsed program and simulation for the code channel, and
runs the battery once (its own designed worlds) for the scenario channel,
exactly as ``battery_sweep`` does offline.
"""
from __future__ import annotations

import csv
import io

from .rubric_combiner import combine_run, load_claims
from .rubric_evidence import (calibration_audit, card_geometry_targets,
                              code_evidence, smc_lower_columns)

RUBRIC_STATUS = "provisional_stage2E"

# Exact column order of stage2_code_evidence.csv (rung_sweep.CE_HEADER), so a
# round-tripped row is indistinguishable from the offline producer the
# combiner was validated against.
_CE_HEADER = [
    "run_id", "config_version",
    "sensing_in_executable", "sensing_in_recurrent",
    "has_loops", "has_conditionals", "has_procedures", "has_variables",
    "ceilings", "max_arm_alternations", "coordination_relations",
    "coordination_detail", "wait_release_total",
    "state_terminated_motion_fraction",
    "exercised_loops_fixed", "exercised_loops_state", "exercised_loops_forever",
    "exercised_conditionals", "max_nesting_depth", "state_controlled_termination",
    "state_gated_drivetrain", "computed_motion_params",
    "procedure_calls", "procedure_reused", "variable_sets", "variable_reads",
    "duplicated_sequences", "calibrated_param_matches", "motion_literal_count",
    "fixed_motion_specificity", "distinct_drive_clusters", "distinct_turn_clusters",
    "canonical_prop", "fine_value_count", "canonical_ambiguous_matches",
    "state_gated_drivetrain_executed", "gated_sensor_fields",
]


def _roundtrip(rows, fieldnames):
    """Write dict rows to CSV and read them back, so every value carries the
    same string typing the offline combiner consumes (booleans become
    'True'/'False', None becomes '', numbers become their text). This is what
    keeps the online scores identical to the sweep's."""
    if not rows:
        return []
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=fieldnames, extrasaction="ignore")
    writer.writeheader()
    for row in rows:
        writer.writerow(row)
    buf.seek(0)
    return list(csv.DictReader(buf))


def _code_row(program, sim, config_version, playground, configs_dir):
    """The stage2_code_evidence row for one run (rung_sweep's writerow shape)
    plus the ceilings dict combine_run takes directly."""
    from .config import load_configs
    ce = code_evidence(program, sim)
    card = load_configs(playground, configs_dir).card
    claims = load_claims(playground, configs_dir)
    geo = card_geometry_targets(card)
    tol = float(claims.get("calibration_tolerance_pct") or 10.0)
    palette = claims.get("smc_vocabulary") or {}
    spec_rule = claims.get("smc_specificity") or {}
    values = [
        "", config_version,
        ce.sensing_in_executable, ce.sensing_in_recurrent,
        ce.has_loops, ce.has_conditionals, ce.has_procedures, ce.has_variables,
        ";".join(f"{k}:{v}" for k, v in sorted(ce.ceilings.items())),
        ce.max_arm_alternations, ce.construct_coordination_relations,
        "|".join(ce.coordination_detail), sum(ce.wait_release_counts.values()),
        ("" if ce.state_terminated_motion_fraction is None
         else round(ce.state_terminated_motion_fraction, 3)),
        ce.exercised_loops_fixed, ce.exercised_loops_state,
        ce.exercised_loops_forever, ce.exercised_conditional_count,
        ce.max_nesting_depth, ce.state_controlled_termination,
        ce.state_gated_drivetrain_count, ce.computed_motion_param_count,
        ce.procedure_metrics.get("calls", 0),
        ce.procedure_metrics.get("reused", 0),
        ce.variable_metrics.get("sets", 0),
        ce.variable_metrics.get("reads", 0),
        ce.duplicated_sequence_count,
        *calibration_audit(program, geo, tol),
        *smc_lower_columns(program, geo, tol, palette, spec_rule),
        ce.state_gated_drivetrain_executed, ";".join(ce.gated_sensor_fields),
    ]
    prod = _roundtrip([dict(zip(_CE_HEADER, values))], _CE_HEADER)[0]
    return prod, dict(ce.ceilings)


def _battery_rows(program, report, program_id, config_version,
                  playground, configs_dir):
    """Non-abstained per-scenario rubric evidence rows, and stays_on_island by
    scenario, from a battery report (run with collect_sims=True). The report is
    shared with the other online channels so the battery runs once per call."""
    from .battery_evidence import scenario_evidence
    from .battery_sweep import _evidence_row
    from .testcases import load_scenarios
    if report is None or not report.eligible:
        return [], {}
    cards = {c["scenario_id"]: c for c in load_scenarios(playground, configs_dir)}
    arts = {(a.scenario_id, a.construct): a for a in report.artifacts}
    ident = {"run_id": program_id, "cohort": "", "session": "", "run_seq": "",
             "config_version": config_version, "channel": "goal"}
    rows, stays = [], {}
    for res in report.scenarios:
        art = arts.get((res.scenario_id, res.construct))
        if art is None:
            continue
        ev = scenario_evidence(program, res, art, cards.get(res.scenario_id, {}))
        if ev.abstained:
            continue
        rows.append(_evidence_row(ident, ev))
        for chk in res.checks:
            if (chk.name == "stays_on_island" and chk.status == "measured"
                    and chk.value is not None):
                stays[res.scenario_id] = float(chk.value)
    return (_roundtrip(rows, list(rows[0].keys())) if rows else []), stays


def rubric_dimensions(program, sim, program_id, config_version,
                      playground="castle_crashers", configs_dir=None,
                      *, report=None, workspace_xml=None):
    """[DimensionEvidence] for one run under the claims card, or None when
    there is no parsed program to score. Pass `report` (a collect_sims battery
    report) to share the single battery run with the other online channels;
    otherwise a `workspace_xml` runs one here."""
    if program is None:
        return None
    if report is None:
        from .testcases import run_battery
        report = run_battery(workspace_xml or "", program_id,
                             playground=playground, configs_dir=configs_dir,
                             collect_sims=True)
    prod, ceilings = _code_row(program, sim, config_version, playground,
                               configs_dir)
    batt_rows, stays = _battery_rows(program, report, program_id,
                                     config_version, playground, configs_dir)
    claims = load_claims(playground, configs_dir)
    return combine_run(program_id, batt_rows, prod, ceilings, claims, stays)


def rubric_to_dict(dims):
    """The provisional purpose-2 envelope for result['rubric']. Strict-JSON
    primitives only, so it composes with the rest of the serialized result."""
    if dims is None:
        return None
    return {
        "provisional": True,
        "status": RUBRIC_STATUS,
        "dimensions": {
            de.dimension: {
                "level": de.label,
                "ceiling": de.ceiling,
                "borderline": de.borderline,
                "u_reason": de.u_reason,
                "fired": [{"evidence": name, "level": level, "strength": strength}
                          for (name, level, _weight, strength) in de.fired],
                "negatives": [name for name, _level in de.negatives],
            }
            for de in dims
        },
    }
