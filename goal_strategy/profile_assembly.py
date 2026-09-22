"""Stage-5 profile assembly (reviewer-ruled 2026-09-11).

THE delivery table: one row per run bringing together the GOAL
profile (purpose 1 — bands, scores, certainty, per-channel
indicators, fidelity verdict) and the RUBRIC profile (purpose 2 —
six dimension levels, carried as PROVISIONAL while Stage 2E rubric
validation continues). Downstream analysis looks profiles up here
and joins on run_id / student / session / run_seq with whatever
longitudinal data it considers — the table is the boundary between
the pipeline and analysis (Stage 3 = delivering it, nothing more).

CSV-only (never re-simulates); joins the persisted stage artifacts:
    stage2_rungs.csv           production/sim/observed goal indicators
    stage2_fidelity.csv        sim-vs-telemetry verdict + flags
    stage3_battery.csv         __goal_band__ rows (test-channel bands)
    stage3_battery_evidence.csv  battery route/channel
    stage6_rubric.csv          DimensionEvidence per dimension

A sidecar `<out>.meta.json` records the version fingerprint (card
ids, source-CSV hashes, git head) so any analysis is reproducible
against a named pipeline state.

    python -m goal_strategy.profile_assembly \
        --out data/ccp_run_dataset/stage5_profiles.csv
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
from pathlib import Path

ASSEMBLY_VERSION = "1.0.0"

# The rubric ships PROVISIONAL while Stage 2E rubric validation is
# open (reviewer 2026-09-11: goal labels analysis-ready; rubric levels
# still converging). Per-dimension caveats name the known open items a
# consumer should read before leaning on that dimension.
RUBRIC_STATUS = "provisional_stage2E"
RUBRIC_CAVEATS = {
    "environmental_feedback": "",
    "control_structure": "",
    "spatial_motion": "OI-35 open: sensing-while motion gates invisible "
                      "to both L2 channels (<=135 runs under-credited)",
    "representation": "",
    "task_state_regulation": "",
    "recovery": "restructured 2026-09-11 (family-grain L2); levels "
                "recently re-ruled",
}
DIMS = ["environmental_feedback", "control_structure", "spatial_motion",
        "representation", "task_state_regulation", "recovery"]

# goal indicators carried through (value + rung) from stage2_rungs
GOAL_INDICATORS = [
    ("playground_engagement", "robot_moved"),
    ("clear_debris_zone", "debris_zone_coverage"),
    ("clear_debris_zone", "weight_cleared"),
    ("remain_on_island", "on_island_sim"),
    ("remain_on_island", "on_island_observed"),
    ("engage_plow", "magnet_activation_intent"),
    ("engage_plow", "plow_approach_intent"),
    ("engage_plow", "plow_proximity_execution"),
]
BAND_GOALS = ["clear_debris_zone", "remain_on_island"]


def _read(path):
    with open(path) as fh:
        yield from csv.DictReader(fh)


def _parse_band(row: dict) -> dict:
    detail = row.get("detail") or ""
    nums = dict(re.findall(r"(valid|abst)=(\d+)", detail))
    pm = re.search(r"P=([\d.]+)", detail)
    ann = row.get("annotation") or ""
    return {
        "band": row.get("status") or "",
        "score": row.get("value") or "",
        "certainty": "reduced" if ann.startswith("reduced") else
        ("full" if ann else ""),
        "demotions": ann.split(":", 1)[1] if ann.startswith("reduced")
        else "",
        "valid": nums.get("valid", ""),
        "abstained": nums.get("abst", ""),
        "probability": pm.group(1) if pm else "",
        "flags": ";".join(re.findall(r"FLAG:(\S+)", detail)),
        "u_reason": (row.get("abstain_reason") or ""),
    }


def assemble(data_dir: str | Path, out_csv: str | Path,
             configs_root: str | Path | None = None) -> dict:
    data = Path(data_dir)
    rungs = {r["run_id"]: r for r in _read(data / "stage2_rungs.csv")}
    fid = {r["run_id"]: r for r in _read(data / "stage2_fidelity.csv")} \
        if (data / "stage2_fidelity.csv").exists() else {}
    channel: dict = {}
    for r in _read(data / "stage3_battery_evidence.csv"):
        channel.setdefault(r["run_id"], r.get("channel", ""))
    bands: dict = {}
    for r in _read(data / "stage3_battery.csv"):
        if r.get("scenario") == "__goal_band__":
            bands.setdefault(r["run_id"], {})[r["goal"]] = _parse_band(r)
    rubric: dict = {}
    for r in _read(data / "stage6_rubric.csv"):
        rubric.setdefault(r["run_id"], {})[r["dimension"]] = r

    header = (["run_id", "cohort", "school", "session", "run_seq",
               "has_telemetry", "dev_corpus_overlap", "route",
               "config_version",
               "fidelity_verdict", "fidelity_flags"]
              + [f"{g}__{i}__{k}" for g, i in GOAL_INDICATORS
                 for k in ("value", "rung")]
              + [f"{g}__{k}" for g in BAND_GOALS
                 for k in ("band", "score", "certainty", "demotions",
                           "valid_tests", "abstained_tests",
                           "band_flags", "band_u_reason")]
              + ["remain_on_island__probability"]
              + [f"rubric__{d}__{k}" for d in DIMS
                 for k in ("level", "borderline")]
              + ["rubric_status", "rubric_caveats"])

    n = 0
    with open(out_csv, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(header)
        for rid in sorted(rungs):
            rr = rungs[rid]
            fr = fid.get(rid, {})
            ch = channel.get(rid, "")
            route = ("battery_goal" if ch == "goal" else
                     "battery_rubric_only" if ch == "rubric_only"
                     else "census_only")
            row = [rid, rr.get("cohort", ""), rr.get("school", ""),
                   rr.get("session", ""), rr.get("run_seq", ""),
                   rr.get("has_params", ""),
                   rr.get("dev_corpus_overlap", ""),
                   route, rr.get("config_version", ""),
                   (fr.get("verdict") or "").split(";")[0],
                   fr.get("flags", "")]
            for g, ind in GOAL_INDICATORS:
                base = f"{g}__{ind}"
                row += [rr.get(f"{base}__value", ""),
                        rr.get(f"{base}__rung", "")]
            gb = bands.get(rid, {})
            for g in BAND_GOALS:
                b = gb.get(g)
                if b is None:
                    # no test channel for this run (routed runs are
                    # excluded from the goal rollup BY DESIGN; census
                    # runs never entered the battery)
                    reason = ("excluded_rubric_only_route"
                              if route == "battery_rubric_only" else
                              "no_battery_route"
                              if route == "census_only" else "")
                    row += ["", "", "", "", "", "", "", reason]
                else:
                    row += [b["band"], b["score"], b["certainty"],
                            b["demotions"], b["valid"], b["abstained"],
                            b["flags"], b["u_reason"]]
            roi = gb.get("remain_on_island") or {}
            row += [roi.get("probability", "")]
            rb = rubric.get(rid, {})
            for d in DIMS:
                dr = rb.get(d, {})
                row += [dr.get("level", ""),
                        dr.get("borderline", "")]
            row += [RUBRIC_STATUS,
                    ";".join(f"{d}:{c}" for d, c in
                             RUBRIC_CAVEATS.items() if c)]
            w.writerow(row)
            n += 1

    # sidecar fingerprint
    def sha12(p):
        h = hashlib.sha256()
        with open(p, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()[:12]
    root = Path(configs_root) if configs_root else \
        Path(__file__).resolve().parents[2]
    import yaml
    tc = root / "configs" / "testcases" / "castle_crashers"
    ids = {}
    for fname, key in [("_rollup.yaml", "rollup_id"),
                       ("_claims.yaml", "claims_id"),
                       ("_evidence.yaml", "registry_id"),
                       ("_router.yaml", "router_id")]:
        try:
            ids[key] = (yaml.safe_load(open(tc / fname)) or {}).get(key, "")
        except Exception:
            ids[key] = ""
    try:
        git = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                             cwd=root, capture_output=True, text=True,
                             timeout=5).stdout.strip()
    except Exception:
        git = ""
    meta = {
        "assembly_version": ASSEMBLY_VERSION,
        "rows": n,
        "rubric_status": RUBRIC_STATUS,
        "rubric_caveats": {d: c for d, c in RUBRIC_CAVEATS.items() if c},
        "sources": {p.name: sha12(p) for p in [
            data / "stage2_rungs.csv", data / "stage2_fidelity.csv",
            data / "stage3_battery.csv",
            data / "stage3_battery_evidence.csv",
            data / "stage6_rubric.csv"] if p.exists()},
        **ids,
        "git_head": git,
    }
    with open(str(out_csv) + ".meta.json", "w") as fh:
        json.dump(meta, fh, indent=1)
    return {"rows": n, "out": str(out_csv)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", required=True)
    ap.add_argument("--data",
                    default=str(Path(__file__).resolve().parents[2]
                                / "data" / "ccp_run_dataset"))
    args = ap.parse_args(argv)
    print("DONE", assemble(args.data, args.out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
