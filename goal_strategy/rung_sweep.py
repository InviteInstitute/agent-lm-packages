"""Stage 2 of VALIDATION_PLAN.md — the rung sweep (OI-9's data layer).

Profiles ALL ccp runs (telemetry-bearing or not: code- and simulation-channel
indicators compute without a blob; outcome-channel indicators abstain cleanly,
and displacement_from_spawn falls back to sim with its existing flags) and
emits one flat row per run in the cli.py column shape —
{goal}__{indicator}__value/__rung/__channel/__flags/__abstain_reason — plus
identity/join columns. The rung-review viz page consumes the CSV; fidelity
verdicts are joined there from stage2_fidelity.csv, never duplicated here.

Read-only consumer of _profile: no simulator or profile changes, not a §6
event.

Usage:
    python -m goal_strategy.rung_sweep --out data/ccp_run_dataset/stage2_rungs.csv
"""
from __future__ import annotations

import argparse
import csv

from .ccp_runs import load_ccp_runs
from .config import load_configs
from .profile import _profile
from .serialize import PIPELINE_VERSION


def identity_columns() -> list[str]:
    # pipeline_version + playground are versioned identity columns (the port's
    # output-versioning scheme): config_version fingerprints the cards, and
    # pipeline_version the execution/evidence semantics that produced the row.
    return ["run_id", "cohort", "school", "date", "session", "run_seq",
            "has_params", "validation_307", "dev_corpus_overlap",
            "config_version", "pipeline_version", "playground"]


def indicator_columns(playground: str = "castle_crashers") -> list[str]:
    cols = []
    for goal in load_configs(playground).goals:
        for ind in goal.intent + goal.attainment:
            base = f"{goal.id}__{ind.name}"
            cols += [f"{base}__value", f"{base}__rung", f"{base}__channel",
                     f"{base}__flags", f"{base}__abstain_reason"]
    return cols


def sweep(out_path: str, playground: str = "castle_crashers") -> dict:
    from .ccp_runs import stack_precedence_map

    runs = load_ccp_runs()
    # OI-28 (2026-08-28): same execution model as the fidelity sweep —
    # the measured 60Hz clock with each run's observed duration as the
    # wall-clock budget (session median where missing, flagged).
    from .ccp_runs import budget_for, duration_budgets
    sess_med, glob_med = duration_budgets(runs)
    # OI-7 PAUSED (2026-08-25, reviewer parallel-execution investigation +
    # arbitration adjudication: sequential-sum beats every exclusive-owner
    # policy against GPS — see docs/archive/PARALLEL_EXECUTION.md). Machinery stays;
    # flip to stack_precedence_map(...) only after the scheduling probes.
    prec = {}
    # validation-307: last telemetry run per session (same rule as
    # fidelity_sweep — runs arrive session-ordered by run_seq)
    last_tel = {}
    for r in runs:
        if r.playground_params:
            last_tel[r.derived_session_id] = r.run_id
    validation = set(last_tel.values())

    header = identity_columns() + indicator_columns(playground)
    # Production-side rubric code evidence (reviewer-ruled 2026-09-05):
    # emitted in the SAME pass so the D-c production-vs-battery claims
    # never require re-simulating. One row per run.
    from pathlib import Path as _P
    from .rubric_evidence import (calibration_audit, card_geometry_targets,
                                  code_evidence,
                                  smc_lower_columns as _smc_lower_columns)
    from .rubric_combiner import load_claims
    from .config import _DEFAULT_CONFIGS_DIR as _CFG, _load_yaml as _ly
    from pathlib import Path as _P2
    _pg = _ly(_P2(_CFG) / "playgrounds" / f"{playground}.yaml")
    _geo = card_geometry_targets(_pg)
    _claims = load_claims(playground)
    _tol = float(_claims.get("calibration_tolerance_pct") or 10.0)
    _palette = _claims.get("smc_vocabulary") or {}
    _spec_rule = _claims.get("smc_specificity") or {}
    _op = _P(out_path)
    ce_path = _op.with_name("stage2_code_evidence.csv")
    CE_HEADER = ["run_id", "config_version",
                 "sensing_in_executable", "sensing_in_recurrent",
                 "has_loops", "has_conditionals", "has_procedures",
                 "has_variables", "ceilings",
                 "max_arm_alternations", "coordination_relations",
                 "coordination_detail", "wait_release_total",
                 "state_terminated_motion_fraction",
                 "exercised_loops_fixed", "exercised_loops_state",
                 "exercised_loops_forever", "exercised_conditionals",
                 "max_nesting_depth", "state_controlled_termination",
                 "state_gated_drivetrain", "computed_motion_params",
                 "procedure_calls", "procedure_reused",
                 "variable_sets", "variable_reads",
                 "duplicated_sequences",
                 "calibrated_param_matches", "motion_literal_count",
                 # SMC lower-scale restructure (2026-09-09): ONE ordinal
                 # indicator + its vocabulary diagnostics (ingredients,
                 # never separate scoring variables) + the route-A
                 # contamination annotation.
                 "fixed_motion_specificity",
                 "distinct_drive_clusters", "distinct_turn_clusters",
                 "canonical_prop", "fine_value_count",
                 "canonical_ambiguous_matches",
                 # OI-33 ruling (2026-09-10): executed state-gating is
                 # the SMC-2 scoring variant; the sensor-field list is
                 # the mis-wired-sensor diagnostic.
                 "state_gated_drivetrain_executed", "gated_sensor_fields"]
    ce_fh = open(ce_path, "w", newline="")
    ce_w = csv.writer(ce_fh)
    ce_w.writerow(CE_HEADER)
    n = 0
    with open(out_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for r in runs:
            p = r.playground_params or {}
            _b, _imp = budget_for(r, sess_med, glob_med)
            prof = _profile(r.workspace_xml or "", r.run_id, p,
                            stack_precedence=prec.get(r.run_id),
                            run_duration_s=_b, duration_imputed=_imp)
            row = {
                "run_id": r.run_id, "cohort": r.cohort, "school": r.school,
                "date": r.date, "session": r.derived_session_id,
                "run_seq": r.run_seq, "has_params": bool(r.playground_params),
                "validation_307": r.run_id in validation,
                "dev_corpus_overlap": r.dev_corpus_overlap,
                "config_version": prof.config_version,
                "pipeline_version": PIPELINE_VERSION,
                "playground": playground,
            }
            for goal in prof.goals:
                for ind in goal.intent + goal.attainment:
                    base = f"{goal.goal}__{ind.name}"
                    row[f"{base}__value"] = ind.value
                    row[f"{base}__rung"] = ind.rung
                    row[f"{base}__channel"] = ind.channel
                    row[f"{base}__flags"] = ";".join(ind.flags)
                    row[f"{base}__abstain_reason"] = ind.abstain_reason
            w.writerow([row.get(c, "") for c in header])
            sim = getattr(prof, "full_sim", None)
            program = getattr(prof, "parsed_program", None)
            if sim is not None and program is not None:
                ce = code_evidence(program, sim)
                ce_w.writerow([
                    r.run_id, prof.config_version,
                    ce.sensing_in_executable, ce.sensing_in_recurrent,
                    ce.has_loops, ce.has_conditionals, ce.has_procedures,
                    ce.has_variables,
                    ";".join(f"{k}:{v}" for k, v in sorted(ce.ceilings.items())),
                    ce.max_arm_alternations,
                    ce.construct_coordination_relations,
                    "|".join(ce.coordination_detail),
                    sum(ce.wait_release_counts.values()),
                    ("" if ce.state_terminated_motion_fraction is None
                     else round(ce.state_terminated_motion_fraction, 3)),
                    ce.exercised_loops_fixed, ce.exercised_loops_state,
                    ce.exercised_loops_forever, ce.exercised_conditional_count,
                    ce.max_nesting_depth, ce.state_controlled_termination,
                    ce.state_gated_drivetrain_count,
                    ce.computed_motion_param_count,
                    ce.procedure_metrics.get("calls", 0),
                    ce.procedure_metrics.get("reused", 0),
                    ce.variable_metrics.get("sets", 0),
                    ce.variable_metrics.get("reads", 0),
                    ce.duplicated_sequence_count,
                    *calibration_audit(program, _geo, _tol),
                    *_smc_lower_columns(program, _geo, _tol,
                                        _palette, _spec_rule),
                    ce.state_gated_drivetrain_executed,
                    ";".join(ce.gated_sensor_fields)])
            n += 1
            if n % 500 == 0:
                print(f"  {n}/{len(runs)}")
                ce_fh.flush()
    ce_fh.close()
    return {"runs": n, "validation_307": len(validation)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--playground", default="castle_crashers")
    args = parser.parse_args(argv)
    print("DONE", sweep(args.out, args.playground))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
