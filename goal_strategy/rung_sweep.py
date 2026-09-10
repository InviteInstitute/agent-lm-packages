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
from pathlib import Path


def identity_columns() -> list[str]:
    return ["run_id", "cohort", "school", "date", "session", "run_seq",
            "has_params", "validation_307", "dev_corpus_overlap",
            "config_version", "pipeline_version", "playground"]


def indicator_columns(playground: str = "castle_crashers", configs_dir=None) -> list[str]:
    cols = []
    for goal in load_configs(playground, configs_dir).goals:
        for ind in goal.intent + goal.attainment:
            base = f"{goal.id}__{ind.name}"
            cols += [f"{base}__value", f"{base}__rung", f"{base}__channel",
                     f"{base}__flags", f"{base}__abstain_reason"]
    return cols


def sweep(out_path: str, playground: str = "castle_crashers", configs_dir=None) -> dict:
    from .ccp_runs import stack_precedence_map

    runs = load_ccp_runs()
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

    header = identity_columns() + indicator_columns(playground, configs_dir)
    n = 0
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for r in runs:
            p = r.playground_params or {}
            prof = _profile(r.workspace_xml or "", r.run_id, p, playground, configs_dir=configs_dir,
                            stack_precedence=prec.get(r.run_id))
            row = {
                "run_id": r.run_id, "cohort": r.cohort, "school": r.school,
                "date": r.date, "session": r.derived_session_id,
                "run_seq": r.run_seq, "has_params": bool(r.playground_params),
                "validation_307": r.run_id in validation,
                "dev_corpus_overlap": r.dev_corpus_overlap,
                "config_version": prof.config_version,
                "pipeline_version": PIPELINE_VERSION, "playground": playground,
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
            n += 1
            if n % 500 == 0:
                print(f"  {n}/{len(runs)}")
    return {"runs": n, "validation_307": len(validation)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--playground", default="castle_crashers")
    parser.add_argument("--configs-dir")
    args = parser.parse_args(argv)
    print("DONE", sweep(args.out, args.playground, args.configs_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
