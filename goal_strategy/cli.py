"""Batch profile() over a corpus parquet into a flat review CSV.

Validation-only tooling: this is the sole module in the package that imports
pandas — profile() itself must stay viable in an online request path.

Usage:
    python -m goal_strategy.cli --out profiles.csv \
        [--parquet data/final_code_states.parquet] [--playground castle_crashers]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

from .profile import _profile
from .paths import data_path, require_data
from .serialize import PIPELINE_VERSION


def _load_programs(parquet_path: str, playground: str = "castle_crashers", configs_dir=None):
    """One row per student session. Same program_id join rule as tests/helpers.py
    (intentional small duplication — helpers.py is test-only and not shipped).
    Wrong-playground sessions are excluded per the card's corpus_filter
    (reviewer decision, 2026-08-18)."""
    from .config import load_configs
    required = (load_configs(playground, configs_dir).card.get("corpus_filter") or {}) \
        .get("required_outcome_field")
    for row in pd.read_parquet(require_data(parquet_path)).to_dict("records"):
        xml = row.get("workspace_xml")
        params = row.get("playground_params")
        params = json.loads(params) if isinstance(params, str) and params else {}
        if required is not None and required not in params:
            continue
        yield (
            f"{row['student_study_id']}_{row['derived_session_id']}",
            xml if isinstance(xml, str) else "",
            params,
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parquet", default=str(data_path("final_code_states.parquet")))
    parser.add_argument("--out", required=True)
    parser.add_argument("--playground", default="castle_crashers")
    parser.add_argument("--configs-dir", default=None)
    parser.add_argument("--full-path", action="store_true",
                        help="disable §6a boundary truncation (design-analysis scope)")
    parser.add_argument("--conditional-hats", default=None,
                        choices=["execute", "suppress", "abstain"],
                        help="task-3 Part B treatment (default: execute = status quo)")
    args = parser.parse_args(argv)

    rows = []
    for program_id, xml, params in _load_programs(args.parquet, args.playground, args.configs_dir):
        prof = _profile(xml, program_id, params, args.playground,
                        truncate=not args.full_path, configs_dir=args.configs_dir,
                        conditional_hats=args.conditional_hats)
        row: dict = {
            "program_id": prof.program_id,
            "playground": prof.playground,
            "config_version": prof.config_version,
            "pipeline_version": PIPELINE_VERSION,
            "outcome_available": prof.outcome_available,
            "boundary_exceeded": prof.boundary_exceeded,
            "boundary_exit_step": prof.boundary_exit_step,
            "sim_final_off_island": prof.sim_final_off_island,
            "gps_final_off_island": prof.gps_final_off_island,
            "off_island_agreement": prof.off_island_agreement,
            "gps_final_error_mm": prof.gps_final_error_mm,
            "gps_final_error_reason": prof.gps_final_error_reason,
            "orphan_block_count": prof.orphan_block_count,
            "fabricated_motion": prof.fabricated_motion,
            "boundary_exit_fabricated": prof.boundary_exit_fabricated,
        }
        for goal in prof.goals:
            for ind in goal.intent + goal.attainment:
                base = f"{goal.goal}__{ind.name}"
                row[f"{base}__value"] = ind.value
                row[f"{base}__rung"] = ind.rung
                row[f"{base}__flags"] = ";".join(ind.flags)
                row[f"{base}__abstain_reason"] = ind.abstain_reason
        rows.append(row)

    frame = pd.DataFrame(rows)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(args.out, index=False)
    print(f"wrote {len(frame)} profiles x {len(frame.columns)} columns to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
