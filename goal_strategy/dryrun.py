"""Stage 1 of VALIDATION_PLAN.md — the online dry-run sweep.

Runs every row of the ccp_run_dataset through the full pipeline
(parse -> simulate -> profile) inside a crash-catching harness and writes a
per-run classification: what WOULD have happened had the pipeline been
running online this term.

Classes:
- ``crashed``       — any uncaught exception anywhere in the pipeline.
                      Stage-1 exit criterion: ZERO of these.
- ``parse_failed``  — the workspace XML did not parse (OI-14 lesson: each is
                      a parser gap to investigate, never student noise).
- ``profiled_with_abstentions`` — a profile was delivered but at least one
                      indicator abstained (reasons recorded).
- ``profiled_clean`` — full profile, no abstentions.
- ``timed_out``     — exceeded the per-run wall budget even under the
                      simulator's execution budget (belt-and-braces guard;
                      any occurrence is a finding).

Usage:
    python -m goal_strategy.dryrun --out data/ccp_run_dataset/stage1_dryrun.csv
"""
from __future__ import annotations

import argparse
import csv
import re
import signal
import sys
import traceback
import time
from pathlib import Path
from .config import load_configs
from .serialize import PIPELINE_VERSION

from .ccp_runs import load_ccp_runs


def _block_types(xml: str) -> set:
    return set(re.findall(r'type="([^"]+)"', xml or ""))


class _WallTimeout(Exception):
    pass


def sweep(runs, out_csv: str, per_run_seconds: int = 30,
          playground="castle_crashers", configs_dir=None) -> dict:
    if per_run_seconds <= 0:
        raise ValueError("per_run_seconds must be positive")
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    start = time.monotonic()
    try:
        return _sweep(runs, out_csv, per_run_seconds, playground, configs_dir)
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, previous_handler)
        delay, interval = previous_timer
        if delay:
            signal.setitimer(signal.ITIMER_REAL, max(0.001, delay - (time.monotonic() - start)), interval)


def _sweep(runs, out_csv, per_run_seconds, playground, configs_dir):
    cfg = load_configs(playground, configs_dir)
    from .ccp_runs import stack_precedence_map
    # OI-7 PAUSED (2026-08-25, reviewer parallel-execution investigation +
    # arbitration adjudication: sequential-sum beats every exclusive-owner
    # policy against GPS — see PARALLEL_EXECUTION.md). Machinery stays;
    # flip to stack_precedence_map(...) only after the scheduling probes.
    prec = {}
    from .profile import _profile

    signal.signal(signal.SIGALRM, lambda *_: (_ for _ in ()).throw(_WallTimeout()))
    counts = {"profiled_clean": 0, "profiled_with_abstentions": 0,
              "parse_failed": 0, "crashed": 0, "timed_out": 0}
    Path(out_csv).parent.mkdir(parents=True, exist_ok=True)
    with open(out_csv, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["run_id", "cohort", "run_seq", "has_params",
                    "classification", "flags", "abstain_reasons",
                    "block_types", "error", "playground", "config_version", "pipeline_version"])
        for i, r in enumerate(runs):
            flags: set = set()
            reasons: set = set()
            cls, err = "profiled_clean", ""
            try:
                signal.alarm(per_run_seconds)
                prof = _profile(r.workspace_xml or "", r.run_id,
                                r.playground_params, playground, configs_dir=configs_dir,
                                stack_precedence=prec.get(r.run_id))
                for goal in prof.goals:
                    for ind in goal.intent + goal.attainment:
                        flags.update(ind.flags or [])
                        if ind.abstained:
                            reasons.add(ind.abstain_reason or "unspecified")
                if any(x.abstain_reason == "no_code"
                       for g in prof.goals for x in g.intent + g.attainment):
                    cls = "parse_failed"
                elif reasons:
                    cls = "profiled_with_abstentions"
            except _WallTimeout:
                cls = "timed_out"
            except Exception as exc:                     # noqa: BLE001
                cls = "crashed"
                err = f"{type(exc).__name__}: {exc} | " + \
                    traceback.format_exc().strip().splitlines()[-1]
            finally:
                signal.alarm(0)
            counts[cls] += 1
            w.writerow([r.run_id, r.cohort, r.run_seq,
                        bool(r.playground_params), cls,
                        ";".join(sorted(flags)), ";".join(sorted(reasons)),
                        ";".join(sorted(_block_types(r.workspace_xml))), err, playground, cfg.config_version, PIPELINE_VERSION])
            if (i + 1) % 100 == 0:
                fh.flush()
                print(f"  {i + 1}/{len(runs)}  {counts}", flush=True)
    return counts


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--playground", default="castle_crashers")
    ap.add_argument("--configs-dir")
    ap.add_argument("--per-run-seconds", type=int, default=30)
    args = ap.parse_args(argv)
    runs = load_ccp_runs()
    print(f"sweeping {len(runs)} runs", flush=True)
    counts = sweep(runs, args.out, args.per_run_seconds, args.playground, args.configs_dir)
    print("DONE", counts, flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
