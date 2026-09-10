"""Stage 2 of VALIDATION_PLAN.md — the fidelity sweep.

Profiles every telemetry-bearing run, records the OI-2 fidelity metrics and
an AUTOMATED attribution-taxonomy verdict per run, and tags the ruled
validation set (last telemetry run per session, n=307).

Taxonomy (applied in order; mirrors the dev-corpus OI-2 accounting):
  agree            — within card thresholds (on-island 71.2mm; off-island
                     binary agreement)
  override         — profile applied the sim-exit outcome override (drift)
  stopped          — project_stopped_by_user (D1: sim projects full code;
                     final-XY matching waived)
  capped           — loop cap / execution budget curtailed the projection
  stalled          — nonfinite_parameter_stall gated a stack (VEX hang)
  edge_slip        — off-island status disagrees but GPS is within the card
                     edge-slip bound of the trajectory
  sensor_uncertainty — the run's behavior turned on a sensing question our
                     deterministic model cannot decide: stale reads,
                     unfired timer hats, unmet wait-untils, a DETECTION
                     hat (eye/bumper) present that never fired in sim on a
                     disagreeing run, OR a detection hat that fired while
                     the robot contacted movable pieces (physics feedback
                     re-triggers are unreconstructable). Merged from the
                     former detection_physics + sensor_cond lanes
                     (reviewer ruling 2026-08-24: whether the hat fired is
                     mechanism detail — the attribution is the same, our
                     sensing falls short of the actual environment; the
                     detail survives in the flags column). Precedents:
                     dev WREN-C018 hand attribution (OI-5), WREN-C040,
                     WREN-C018.
  edge_zone_possible — no specific mechanism, but the path traversed the
                     card's edge divergence zone (the slip quirk): a named
                     PLAUSIBLE cause, deliberately a soft lane — possible,
                     never established (reviewer rulings 2026-08-24)
  UNATTRIBUTED     — none of the above: the D7 lane (sim_unverified
                     candidates), the queue the reviewer works down.

Usage:
    python -m goal_strategy.fidelity_sweep --out data/ccp_run_dataset/stage2_fidelity.csv
"""
from __future__ import annotations

import argparse
from pathlib import Path
import csv
import sys
from collections import defaultdict

from .ccp_runs import load_ccp_runs


def _trajectory_distance(sim, gx, gy):
    from .indicators import _polyline_min_distance
    pts = [(sim.origin_x, sim.origin_y)] + [(p.x, p.y) for p in sim.path]
    return _polyline_min_distance(pts, float(gx), float(gy))


def sweep(out_csv: str, scheduler: str | None = None, playground="castle_crashers", configs_dir=None) -> dict:
    from goal_strategy.detector.parsing.parse_blocks import parse_workspace
    from goal_strategy.detector.simulation.simulate_path import simulate_path
    from .config import load_configs
    from .profile import _profile

    cfg = load_configs(playground, configs_dir)
    from .execution import prepare_execution
    from .serialize import PIPELINE_VERSION
    all_runs = load_ccp_runs()
    # OI-7 lockout (2026-08-25): precedence recovered over WHOLE sessions
    # (non-telemetry snapshots included — they carry creation evidence)
    from .ccp_runs import stack_precedence_map
    # OI-7 PAUSED (2026-08-25, reviewer parallel-execution investigation +
    # arbitration adjudication: sequential-sum beats every exclusive-owner
    # policy against GPS — see docs/archive/PARALLEL_EXECUTION.md). Machinery stays;
    # flip to stack_precedence_map(...) only after the scheduling probes.
    prec = {}
    runs = [r for r in all_runs if r.playground_params]
    last_tel = {}
    for r in runs:                       # runs are session-ordered by run_seq
        last_tel[r.derived_session_id] = r.run_id
    validation = set(last_tel.values())

    counts = defaultdict(int)
    Path(out_csv).parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["run_id", "cohort", "school", "date", "session", "run_seq",
                    "validation_307", "dev_corpus_overlap",
                    "sim_off", "gps_off", "agreement", "error_mm",
                    "gps_to_trajectory_mm", "overridden", "stopped",
                    "weight_cleared", "verdict", "edge_zone_traversed",
                    "flags", "playground", "config_version", "pipeline_version"])
        for i, r in enumerate(runs):
            p = r.playground_params
            execution = prepare_execution(r.workspace_xml, r.run_id, p, playground,
                                          configs_dir=configs_dir, scheduler=scheduler)
            prof = _profile(r.workspace_xml, r.run_id, p, playground, _execution=execution)
            flags = sorted({f for g in prof.goals for ind in g.intent + g.attainment for f in ind.flags})
            traj = prof.gps_to_trajectory_mm
            edge_zone = prof.edge_zone_traversed
            stopped = bool(p.get("project_stopped_by_user"))
            verdict = "stopped" if prof.fidelity_verdict == "early_stop" else prof.fidelity_verdict
            counts[verdict] += 1
            w.writerow([r.run_id, r.cohort, r.school, r.date,
                        r.derived_session_id, r.run_seq,
                        r.run_id in validation, r.dev_corpus_overlap,
                        prof.sim_final_off_island, prof.gps_final_off_island,
                        prof.off_island_agreement,
                        "" if prof.gps_final_error_mm is None
                        else round(prof.gps_final_error_mm, 1),
                        "" if traj is None else round(traj, 1),
                        prof.boundary_exit_overridden, stopped,
                        p.get("weight_cleared"), verdict, edge_zone,
                        ";".join(flags), playground, prof.config_version, PIPELINE_VERSION])
            if (i + 1) % 200 == 0:
                fh.flush()
                print(f"  {i + 1}/{len(runs)}  {dict(counts)}", flush=True)
    return dict(counts)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--scheduler", default=None,
                    choices=["sequential", "cooperative"])
    ap.add_argument("--playground", default="castle_crashers")
    ap.add_argument("--configs-dir")
    args = ap.parse_args(argv)
    print("Stage-2 fidelity sweep", flush=True)
    counts = sweep(args.out, scheduler=args.scheduler, playground=args.playground, configs_dir=args.configs_dir)
    print("DONE", counts, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
