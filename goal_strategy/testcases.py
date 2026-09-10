"""Test-case playground harness (sensing build Phase 5, 2026-08-19).

Runs a student's program against authored scenario cards — empty island plus
declared test pieces, with the simulator's testcase-only kinematic push model
and raised loop caps — and reports goal-aligned responsivity that the main
simulation cannot evidence (reviewer §6 of the design discussion: the tests
exist to observe sensor-driven behavior toward MOVABLE, IMPERMANENT objects;
red-line sensing is already sim-evidenced and is not re-tested here).

Everything scenario-specific lives in configs/testcases/<playground>/*.yaml:
piece placements, spawn overrides, check rules and thresholds, and each
check's goal facet. Nothing here names a playground entity.

Check rules:
- behavioral_divergence: the same code is run WITH and WITHOUT the pieces;
  "detects" passes only if the trajectory actually responds (path diverges
  beyond divergence_mm or step counts differ). A blind sweeper that clears a
  piece without reacting fails detects while passing pushes_off — exactly
  the distinction the harness exists to draw.
- min_distance: continuous (segment-level) minimum distance from the path to
  any piece's initial position, against within_mm.
- pieces_cleared: at least `count` pieces pushed off the island.
- on_island: the ROBOT never exits the boundary (the fall-off failure
  condition is handled).

Loop/conditional inference (reviewer ruling: every check is upper-bounded;
each check carries its own rule): when a check fails but the run was
loop-capped and shows the check's progress signal, the result is
CONDITIIONAL, annotated with the card's progress_annotation (e.g.
could_reach_if_run) rather than a hard fail.
"""
from __future__ import annotations

import copy
import math
import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import yaml

from goal_strategy.detector.parsing.parse_blocks import parse_workspace
from goal_strategy.detector.simulation.simulate_path import (
    PlaygroundContext, simulate_path,
)

from .config import configs_root, _load_yaml, ConfigError, load_configs
from .indicators import _segment_closest
from .paths import data_path

# Block types whose information the main sim cannot fully evidence — code
# consulting these qualifies for the battery. Down-eye color (red line) is
# deliberately absent: the sim already models it faithfully (reviewer §6).
_SENSOR_QUALIFIERS_EXACT = frozenset({
    "pg_sensing_bumper", "pg_sensing_bumper_pressed", "pg_sensing_bumper_near",
    "pg_events_when_bumper",
    "pg_sensing_optical_near_object", "pg_sensing_eye", "pg_sensing_optical",
    "pg_events_optical_detect_object",
})
_SENSOR_QUALIFIER_PREFIXES = ("pg_sensing_distance",)


@dataclass(frozen=True)
class CheckResult:
    name: str
    status: str                    # "pass" | "conditional" | "fail"
    facet: str
    annotation: Optional[str] = None
    detail: Optional[str] = None


@dataclass(frozen=True)
class ScenarioResult:
    scenario_id: str
    goal: str
    checks: tuple[CheckResult, ...]
    # Which sensing construct this variant materialized pieces for (Option A,
    # reviewer-approved 2026-08-19): "block_type@block_id" for per-construct
    # variants, "static" for absolute-piece scenarios.
    construct: str = "static"
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True)
class BatteryReport:
    program_id: str
    eligible: bool
    qualifying_blocks: tuple[str, ...]
    scenarios: tuple[ScenarioResult, ...]
    # goal id -> facet -> "pass" | "conditional" | "fail" — the roll-up that
    # feeds unobservable goal evidence (reviewer: fills in what the outcome
    # channel and main sim cannot show).
    goal_mapping: dict = field(default_factory=dict)
    diagnostics: tuple[str, ...] = ()
    config_version: str | None = None


def load_scenarios(playground: str, configs_dir: str | None = None) -> list[dict]:
    base = configs_root(configs_dir) / "testcases" / playground
    if not base.is_dir():
        return []
    out = []
    for path in sorted((p for p in base.iterdir() if p.name.endswith(".yaml")), key=lambda p: p.name):
        card = _load_yaml(path)
        if isinstance(card, dict) and card.get("scenario_id"):
            seen = set()
            for check in card.get("checks") or []:
                if check.get("rule") not in {"behavioral_divergence", "min_distance", "pieces_cleared", "on_island"}:
                    raise ConfigError(f"{path}: unknown check rule {check.get('rule')!r}")
                if not check.get("name") or check["name"] in seen:
                    raise ConfigError(f"{path}: missing or duplicate check name")
                if check.get("requires") and check["requires"] not in seen:
                    raise ConfigError(f"{path}: prerequisite must name an earlier check")
                for key in ("within_mm", "divergence_mm", "count"):
                    if key in check:
                        try:
                            valid = math.isfinite(float(check[key])) and float(check[key]) >= 0
                        except (TypeError, ValueError):
                            valid = False
                        if not valid:
                            raise ConfigError(f"{path}: invalid {key}")
                seen.add(check["name"])
            out.append(card)
    return out


def _iter_blocks(node):
    while node is not None:
        yield node
        for child in node.children:
            yield from _iter_blocks(child)
        for value in node.values:
            yield from _iter_blocks(value)
        node = node.next


def _constructs(program) -> list[dict]:
    out = []
    for block in program.iter_all_blocks() if program else ():
        bt = block.block_type
        qualifies = bt in _SENSOR_QUALIFIERS_EXACT or any(bt.startswith(p) for p in _SENSOR_QUALIFIER_PREFIXES)
        if bt in ("pg_sensing_optical_color", "pg_sensing_optical_detected_color_is"):
            qualifies = "down" not in (block.get_field("OPTICAL") or "").lower()
        if qualifies:
            out.append({"id": block.block_id, "block_type": bt,
                        "kind": "hat" if bt.startswith("pg_events") else "reporter"})
    return out


def qualifying_blocks(program) -> list[str]:
    return sorted({c["block_type"] for c in _constructs(program)})


def _scenario_card(base_card: dict, scenario: dict, with_pieces: bool,
                   activate_at_step: int = 0) -> dict:
    """Overlay a scenario onto the base playground card: empty island (all
    original objects removed), declared test pieces, optional spawn override,
    and the testcase physics switch."""
    card = copy.deepcopy(base_card)
    pieces = scenario.get("pieces") or {}
    if with_pieces and pieces:
        first = next(iter(pieces.values()))
        merged = copy.deepcopy(pieces)
        if activate_at_step:
            for piece in merged.values():
                piece["active_from_step"] = activate_at_step
        card["objects"] = {"test_pieces": {
            "object_type": "target", "movable": True,
            "x": first.get("x", 0), "y": first.get("y", 0), "tolerance": 1,
            "pieces": merged,
        }}
    else:
        card["objects"] = {}
    if scenario.get("spawn"):
        card.setdefault("spawn_points", {})["default_start"] = dict(scenario["spawn"])
    card["testcase_physics"] = dict(scenario.get("testcase_physics") or {})
    return card


def _path_divergence(sim_a, sim_b) -> float:
    if len(sim_a.path) != len(sim_b.path):
        return float("inf")
    worst = 0.0
    for pa, pb in zip(sim_a.path, sim_b.path):
        worst = max(worst, math.hypot(pa.x - pb.x, pa.y - pb.y))
    return worst


def _continuous_min_distance(sim, px: float, py: float) -> float:
    pts = [(sim.origin_x, sim.origin_y)] + [(p.x, p.y) for p in sim.path]
    best = float("inf")
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        d, _, _ = _segment_closest(ax, ay, bx, by, px, py)
        best = min(best, d)
    if pts:
        best = min(best, math.hypot(pts[0][0] - px, pts[0][1] - py))
    return best


def _distance_trend_improving(sim, px: float, py: float) -> bool:
    """Progress signal for capped runs: the closest approach in the final
    third of the path beats the first third's."""
    n = len(sim.path)
    if n < 6:
        return False
    third = n // 3
    first = min(math.hypot(p.x - px, p.y - py) for p in sim.path[:third])
    last = min(math.hypot(p.x - px, p.y - py) for p in sim.path[-third:])
    return last < first


def _evaluate_check(check: dict, positions: list, sim, baseline) -> CheckResult:
    name = str(check.get("name"))
    rule = str(check.get("rule"))
    facet = str(check.get("facet", name))
    annotation = check.get("progress_annotation")

    if rule == "behavioral_divergence":
        div = _path_divergence(sim, baseline)
        ok = div > float(check.get("divergence_mm", 100))
        return CheckResult(name, "pass" if ok else "fail", facet,
                           detail=f"max path divergence {'inf' if math.isinf(div) else round(div)}mm")

    if rule == "min_distance":
        within = float(check.get("within_mm", 180))
        best = min((_continuous_min_distance(sim, px, py)
                    for px, py in positions), default=float("inf"))
        if best <= within:
            return CheckResult(name, "pass", facet, detail=f"min distance {round(best)}mm")
        if sim.loop_was_capped and any(
                _distance_trend_improving(sim, px, py) for px, py in positions):
            return CheckResult(name, "conditional", facet, annotation=annotation,
                               detail=f"capped at {round(best)}mm, closing")
        return CheckResult(name, "fail", facet, detail=f"min distance {round(best)}mm")

    if rule == "pieces_cleared":
        need = int(check.get("count", 1))
        got = len(sim.pieces_cleared)
        if got >= need:
            return CheckResult(name, "pass", facet, detail=f"{got} cleared")
        if sim.loop_was_capped and (got > 0 or sim.object_contacts):
            return CheckResult(name, "conditional", facet, annotation=annotation,
                               detail=f"capped with {got} cleared, contact made")
        return CheckResult(name, "fail", facet, detail=f"{got} cleared")

    if rule == "on_island":
        ok = not sim.exits_field_boundary
        return CheckResult(name, "pass" if ok else "fail", facet,
                           detail="robot stayed on island" if ok else "robot exited")

    raise ConfigError(f"unknown check rule {rule!r}")


_STATUS_RANK = {"pass": 0, "conditional": 1, "fail": 2}


def run_battery(workspace_xml: str, program_id: str,
                playground: str = "castle_crashers",
                configs_dir: str | None = None,
                scheduler: str | None = None,
                _execution=None) -> BatteryReport:
    from .execution import prepare_execution
    execution = _execution or prepare_execution(workspace_xml, program_id, playground=playground,
                                               configs_dir=configs_dir, scheduler=scheduler)
    cfg, program = execution.config, execution.program
    base_card, robot_card = cfg.card, cfg.robot
    scenarios = load_scenarios(playground, configs_dir)
    scheduler = scheduler or (base_card.get("simulation") or {}).get("scheduler") or "sequential"
    version = hashlib.sha256(json.dumps([cfg.config_version, scenarios, scheduler,
        execution.context.conditional_hat_treatment], sort_keys=True).encode()).hexdigest()[:12]
    if execution.context.full_sim is None:
        return BatteryReport(program_id, False, (), (),
                             diagnostics=(execution.context.sim_unavailable_reason,), config_version=version)
    qualifiers = qualifying_blocks(program)
    if not qualifiers:
        return BatteryReport(program_id=program_id, eligible=False,
                             qualifying_blocks=(), scenarios=(), config_version=version)

    results = []
    facet_status: dict[str, dict[str, str]] = {}
    constructs = _constructs(program)
    for scenario in scenarios:
        ctx0 = PlaygroundContext.from_playground_card(
            _scenario_card(base_card, scenario, with_pieces=False), robot_card)
        baseline = simulate_path(program, ctx0, scheduler=scheduler,
                                 conditional_hats="suppress" if execution.context.conditional_hat_treatment in ("suppress", "abstain") else "execute")
        pieces = scenario.get("pieces") or {}
        # Option A (reviewer-approved 2026-08-19): scenarios with RELATIVE
        # piece placements run one variant per sensing construct — pieces
        # materialize at the step the baseline first consulted that construct
        # (hats: step 0, armed from start), placed relative to the robot's
        # pose then. Absolute-piece scenarios (edge_handling) run once,
        # static from t0.
        relative = any(isinstance(p, dict) and p.get("relative")
                       for p in pieces.values())
        if relative:
            variants = []
            for c in constructs:
                step = 0 if c["kind"] == "hat" else \
                    baseline.sensor_first_eval.get(c["id"], (0, ""))[0]
                variants.append((f"{c['block_type']}@{c['id'][:8]}", step))
        else:
            variants = [("static", 0)]
        for construct_label, activate_step in variants:
            ctx = PlaygroundContext.from_playground_card(
                _scenario_card(base_card, scenario, with_pieces=True,
                               activate_at_step=activate_step), robot_card)
            sim = simulate_path(program, ctx, scheduler=scheduler,
                                conditional_hats="suppress" if execution.context.conditional_hat_treatment in ("suppress", "abstain") else "execute")
        # `requires:` (reviewer ruling 2026-08-19): a check whose card names a
        # prerequisite check contributes evidence only when that prerequisite
        # passed — reaching or clearing a piece WITHOUT a detection response
        # is accidental, not evidence ("accidentally knocking the piece off
        # should not be evidence in itself; it should be paired with the
        # detection").
            positions = list(sim.piece_positions.values()) or [
                (p["x"], p["y"]) for p in pieces.values()
                if isinstance(p, dict) and "x" in p and "y" in p]
            evaluated: dict[str, CheckResult] = {}
            ordered = []
            for c in scenario.get("checks") or []:
                cr = _evaluate_check(c, positions, sim, baseline)
                req = c.get("requires")
                if req and cr.status != "fail":
                    prereq = evaluated.get(str(req))
                    if prereq is None or prereq.status != "pass":
                        cr = CheckResult(cr.name, "fail", cr.facet,
                                         detail=f"{cr.detail}; but no {req} response "
                                                "— accidental, not evidence")
                evaluated[cr.name] = cr
                ordered.append(cr)
            checks = tuple(ordered)
            results.append(ScenarioResult(
                scenario_id=str(scenario["scenario_id"]),
                goal=str(scenario.get("goal", "")), checks=checks,
                construct=construct_label,
                diagnostics=tuple(sorted(set(sim.execution_flags + baseline.execution_flags
                    + execution.context.full_sim.execution_flags
                    + (["loop_capped"] if sim.loop_was_capped or baseline.loop_was_capped else [])
                    + (["unknown_reporter"] if sim.unknown_reporter_blocks or baseline.unknown_reporter_blocks else []))))))
            goal = str(scenario.get("goal", ""))
            for cr in checks:
                facets = facet_status.setdefault(goal, {})
                prev = facets.get(cr.facet)
                # best status across scenarios AND constructs wins:
                # capability shown anywhere is shown
                if prev is None or _STATUS_RANK[cr.status] < _STATUS_RANK[prev]:
                    facets[cr.facet] = cr.status

    return BatteryReport(program_id=program_id, eligible=True,
                         qualifying_blocks=tuple(qualifiers),
                         scenarios=tuple(results), goal_mapping=facet_status,
                         config_version=version, diagnostics=tuple(sorted({d for result in results for d in result.diagnostics})))


def _main() -> None:   # pragma: no cover — thin CLI
    import argparse
    import csv
    import json

    ap = argparse.ArgumentParser(description="Run the sensor test-case battery "
                                             "over the corpus (eligible programs only)")
    ap.add_argument("--parquet", default=str(data_path("final_code_states.parquet")))
    ap.add_argument("--out", default=str(data_path("testcases_report.csv")))
    ap.add_argument("--playground", default="castle_crashers")
    ap.add_argument("--configs-dir")
    ap.add_argument("--scheduler", choices=["sequential", "cooperative"])
    args = ap.parse_args()

    import pandas as pd
    from .config import load_configs

    cfg = load_configs(args.playground, args.configs_dir)
    required = (cfg.card.get("corpus_filter") or {}).get("required_outcome_field")
    df = pd.read_parquet(args.parquet)
    rows = []
    for rec in df.to_dict("records"):
        params = rec.get("playground_params")
        params = json.loads(params) if isinstance(params, str) and params else {}
        if required is not None and required not in params:
            continue
        pid = f"{rec['student_study_id']}_{rec['derived_session_id']}"
        xml = rec.get("workspace_xml")
        if not isinstance(xml, str) or not xml.strip():
            continue
        report = run_battery(xml, pid, playground=args.playground, configs_dir=args.configs_dir, scheduler=args.scheduler)
        if not report.eligible:
            continue
        for s in report.scenarios:
            for c in s.checks:
                rows.append({
                    "program_id": pid, "scenario": s.scenario_id,
                    "construct": s.construct, "goal": s.goal,
                    "check": c.name, "facet": c.facet, "status": c.status,
                    "annotation": c.annotation or "", "detail": c.detail or "",
                    "scenario_version": report.config_version, "diagnostics": ";".join(s.diagnostics),
                })
        for goal, facets in report.goal_mapping.items():
            for facet, status in facets.items():
                rows.append({"program_id": pid, "scenario": "__rollup__",
                             "construct": "", "goal": goal, "check": "",
                             "facet": facet, "status": status,
                             "annotation": "", "detail": "", "scenario_version": report.config_version,
                             "diagnostics": ";".join(report.diagnostics)})
    from .serialize import PIPELINE_VERSION
    for row in rows:
        row.update(playground=args.playground, config_version=cfg.config_version,
                   pipeline_version=PIPELINE_VERSION)
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["program_id", "scenario", "construct", "goal",
                                               "check", "facet", "status",
                                               "annotation", "detail", "playground", "config_version", "pipeline_version", "scenario_version", "diagnostics"])
        writer.writeheader()
        writer.writerows(rows)
    print(f"wrote {len(rows)} rows to {args.out}")


if __name__ == "__main__":   # pragma: no cover
    _main()
