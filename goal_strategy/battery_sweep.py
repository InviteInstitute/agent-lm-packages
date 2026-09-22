"""Stage 3 — the purpose-1 battery sweep (battery build, 2026-08-28).

Runs the scenario battery (testcases.run_battery) over every ccp run and
emits long-format rows to stage3_battery.csv, joinable to the stage2 CSVs
on run_id. Row kinds:

- per-check rows: one per (scenario, construct, check), carrying the raw
  observation (`value`, `capped`) for measurement checks;
- `scenario="__goal_band__"` rows: the per-goal RULED band from the
  banded rollup (§4.8, 2026-09-04) — check = the test-channel indicator
  name (cleared_proportion_tests / on_island_tests, card-declared
  2026-09-05), status = band (or U/<reason>),
  value = the flat score, annotation = certainty tier, detail =
  evidence counts + calibrated P(ROI) + surfaced flags;
- `scenario="__ineligible__"`: one marker row for runs with no
  qualifying sensing blocks (researcher population ruling 2026-08-27:
  sensing-qualifying programs only) — distinct from level 0.

Read-only consumer of run_battery + rollup: not a §6 event. NOTE:
config_version hashes the playground/goals/robot/capability cards —
testcase scenario cards and _rollup.yaml are OUTSIDE the hash.

Usage:
    python -m goal_strategy.battery_sweep --out data/ccp_run_dataset/stage3_battery.csv
"""
from __future__ import annotations

import argparse
import csv

from .battery_rollup import banded_invariant, load_rollup_card
from .ccp_runs import load_ccp_runs
from .config import load_configs
from .testcases import run_battery


HEADER = ["run_id", "cohort", "session", "run_seq", "validation_307",
          "dev_corpus_overlap", "config_version", "eligible",
          "scenario", "family", "construct", "goal", "check", "facet",
          "status", "value", "capped", "abstain_reason", "annotation",
          "detail", "channel"]

# Purpose-2 evidence table (B-2), written in the SAME pass from the same
# artifacts so rubric scoring never re-runs the battery: one row per
# (scenario, construct) with the ScenarioEvidence scalars plus the
# scenario-sim CodeEvidence extracts flattened.
EV_HEADER = ["run_id", "cohort", "session", "run_seq", "config_version",
             "scenario", "family", "construct", "channel",
             "abstained", "abstain_reason", "onset_step",
             "response_latency_mm", "engagement_latency_mm",
             "post_clear_action_latency_mm", "boundary_band_entries",
             "corrective_response_present", "behavioral_transition_count",
             "behavioral_seams",
             "task_state_triggered_transition_count",
             "task_phase_return_count", "completion_triggered_transition",
             "reengagement_after_resolution", "correction_reassessment_cycles",
             "code_max_arm_alternations",
             "code_coordination_relations", "code_wait_release_total",
             "code_state_terminated_motion_fraction",
             "code_exercised_loops_fixed", "code_exercised_loops_state",
             "code_exercised_conditionals", "code_max_nesting_depth",
             "code_state_gated_drivetrain", "code_computed_motion_params",
             "code_procedure_calls", "code_variable_sets",
             "code_duplicated_sequences",
             # OI-37 (2026-09-11): the failure step — review context
             # for the failure-scoped evidence window
             "scenario_exit_step"]


def _evidence_row(ident: dict, ev) -> dict:
    code = ev.code
    return {
        "run_id": ident["run_id"], "cohort": ident["cohort"],
        "session": ident["session"], "run_seq": ident["run_seq"],
        "config_version": ident["config_version"],
        "scenario": ev.scenario_id, "family": ev.family,
        "construct": ev.construct,
        "channel": ident.get("channel", "goal"),
        "abstained": ev.abstained, "abstain_reason": ev.abstain_reason or "",
        "onset_step": "" if ev.onset_step is None else ev.onset_step,
        "response_latency_mm": ("" if ev.response_latency_mm is None
                                else round(ev.response_latency_mm, 1)),
        "engagement_latency_mm": ("" if ev.engagement_latency_mm is None
                                  else round(ev.engagement_latency_mm, 1)),
        "post_clear_action_latency_mm": (
            "" if ev.post_clear_action_latency_mm is None
            else round(ev.post_clear_action_latency_mm, 1)),
        "boundary_band_entries": ev.boundary_band_entries,
        "corrective_response_present": (
            "" if ev.corrective_response_present is None
            else ev.corrective_response_present),
        "behavioral_transition_count": ev.behavioral_transition_count,
        "behavioral_seams": "|".join(
            f"{st}:{kind}" for st, kind in ev.behavioral_seams),
        "code_max_arm_alternations": (
            code.max_arm_alternations if code else ""),
        "code_coordination_relations": (
            code.construct_coordination_relations if code else ""),
        "code_wait_release_total": (
            sum(code.wait_release_counts.values()) if code else ""),
        "code_state_terminated_motion_fraction": (
            "" if code is None
            or code.state_terminated_motion_fraction is None
            else round(code.state_terminated_motion_fraction, 3)),
        "task_state_triggered_transition_count":
            ev.task_state_triggered_transition_count,
        "task_phase_return_count": ev.task_phase_return_count,
        "completion_triggered_transition": (
            "" if ev.completion_triggered_transition is None
            else ev.completion_triggered_transition),
        "reengagement_after_resolution": ev.reengagement_after_resolution,
        "correction_reassessment_cycles": ev.correction_reassessment_cycles,
        "code_exercised_loops_fixed": code.exercised_loops_fixed if code else "",
        "code_exercised_loops_state": code.exercised_loops_state if code else "",
        "code_exercised_conditionals": (
            code.exercised_conditional_count if code else ""),
        "code_max_nesting_depth": code.max_nesting_depth if code else "",
        "code_state_gated_drivetrain": (
            code.state_gated_drivetrain_count if code else ""),
        "code_computed_motion_params": (
            code.computed_motion_param_count if code else ""),
        "code_procedure_calls": (
            code.procedure_metrics.get("calls", 0) if code else ""),
        "code_variable_sets": (
            code.variable_metrics.get("sets", 0) if code else ""),
        "code_duplicated_sequences": (
            code.duplicated_sequence_count if code else ""),
        "scenario_exit_step": ("" if ev.scenario_exit_step is None
                               else ev.scenario_exit_step),
    }


def sweep(out_path: str, playground: str = "castle_crashers",
          limit: int | None = None) -> dict:
    runs = load_ccp_runs()
    if limit:
        runs = runs[:limit]
    config_version = load_configs(playground).config_version
    rollup_card = load_rollup_card(playground)
    # Rubric router (reviewer-ruled 2026-09-03, built 2026-09-05): the
    # OPTIONAL second gate. Ambiguity read from stage2_code_evidence.csv
    # when present (pipeline-faithful order: stage 2 regenerates first);
    # absent rows route structurally with the check recorded unavailable.
    from pathlib import Path as _RP
    import yaml as _yaml
    # Port layout: cards ship inside the package (importlib resources), not at
    # a repo-root ../../../configs. Resolve the router card via the shared
    # config root so this works from a wheel too.
    from .config import _DEFAULT_CONFIGS_DIR
    router_path = (_RP(str(_DEFAULT_CONFIGS_DIR))
                   / "testcases" / playground / "_router.yaml")
    router = {}
    if router_path.exists():
        router = (_yaml.safe_load(router_path.read_text()) or {}).get(
            "rubric_gate") or {}
    rubric_gate_on = bool(router.get("enabled"))
    rubric_families = set(router.get("families") or [])
    prod_alt: dict = {}
    if rubric_gate_on:
        import csv as _csv
        # code-evidence lands beside the sweep outputs (same data dir as --out),
        # written by rung_sweep as stage2_code_evidence.csv.
        ce_path = _RP(out_path).with_name("stage2_code_evidence.csv")
        if ce_path.exists():
            for row in _csv.DictReader(open(ce_path)):
                try:
                    prod_alt[row["run_id"]] = int(
                        row.get("max_arm_alternations") or 0)
                except ValueError:
                    pass
    last_tel = {}
    for r in runs:
        if r.playground_params:
            last_tel[r.derived_session_id] = r.run_id
    validation = set(last_tel.values())

    n = eligible_n = 0
    with open(out_path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=HEADER)
        w.writeheader()
        from pathlib import Path as _Path
        _op = _Path(out_path)
        ev_path = _op.with_name(_op.stem + "_evidence.csv")
        ev_fh = open(ev_path, "w", newline="")
        ew = csv.DictWriter(ev_fh, fieldnames=EV_HEADER)
        ew.writeheader()
        from goal_strategy.detector.parsing.parse_blocks import parse_workspace
        from .battery_evidence import scenario_evidence, ScenarioEvidence
        from .testcases import load_scenarios
        cards = {c["scenario_id"]: c for c in load_scenarios(playground)}
        for r in runs:
            ident = {
                "run_id": r.run_id, "cohort": r.cohort,
                "session": r.derived_session_id, "run_seq": r.run_seq,
                "validation_307": r.run_id in validation,
                "dev_corpus_overlap": r.dev_corpus_overlap,
                "config_version": config_version,
            }
            # OI-28 two-budget guard, D4(a) semantics (2026-09-04): a band
            # that moves between budgets keeps the PRIMARY budget's value
            # with certainty demoted (budget_sensitive) — never U. The
            # per-check rows below are the PRIMARY budget's.
            reports = [run_battery(r.workspace_xml or "", r.run_id,
                                   playground=playground, budget_key=k,
                                   collect_sims=(k == "time_budget_s"))
                       for k in ("time_budget_s", "invariance_budget_s")]
            report = reports[0]
            if not report.eligible:
                routed = False
                if rubric_gate_on:
                    from goal_strategy.detector.parsing.parse_blocks import (
                        parse_workspace as _pw)
                    from .testcases import downeye_only_sensing
                    try:
                        prog0 = _pw(r.workspace_xml or "", r.run_id)
                    except Exception:
                        prog0 = None
                    ambiguous = prod_alt.get(r.run_id, 0) == 0
                    if prog0 is not None and ambiguous                             and downeye_only_sensing(prog0):
                        routed = True
                if routed:
                    # RUBRIC-ONLY channel: boundary family, primary budget,
                    # rows never feed the goal rollup or calibration
                    # (eligible stays False; channel marks the lane).
                    rreport = run_battery(
                        r.workspace_xml or "", r.run_id,
                        playground=playground, collect_sims=True,
                        families=rubric_families, rubric_channel=True)
                    rident = {**ident, "channel": "rubric_only"}
                    for sres in rreport.scenarios:
                        for c in sres.checks:
                            w.writerow({
                                **rident, "eligible": False,
                                "scenario": sres.scenario_id,
                                "family": sres.family,
                                "construct": sres.construct,
                                "goal": c.goal or sres.goal, "check": c.name,
                                "facet": c.facet, "status": c.status,
                                "value": "" if c.value is None else c.value,
                                "capped": c.capped,
                                "abstain_reason": c.abstain_reason or "",
                                "annotation": c.annotation or "",
                                "detail": c.detail or "",
                            })
                    rprog = _pw(r.workspace_xml or "", r.run_id)
                    rarts = {(a.scenario_id, a.construct): a
                             for a in rreport.artifacts}
                    for res in rreport.scenarios:
                        art = rarts.get((res.scenario_id, res.construct))
                        if art is None:
                            rev = ScenarioEvidence(
                                scenario_id=res.scenario_id,
                                family=res.family, construct=res.construct,
                                abstained=True,
                                abstain_reason=(res.checks[0].abstain_reason
                                                if res.checks
                                                and res.checks[0].abstained
                                                else None))
                        else:
                            rev = scenario_evidence(
                                rprog, res, art,
                                cards.get(res.scenario_id, {}))
                        ew.writerow(_evidence_row(rident, rev))
                else:
                    w.writerow({**ident, "eligible": False,
                                "scenario": "__ineligible__"})
            else:
                eligible_n += 1
                for s in report.scenarios:
                    for c in s.checks:
                        w.writerow({
                            **ident, "channel": "goal", "eligible": True,
                            "scenario": s.scenario_id, "family": s.family,
                            "construct": s.construct,
                            "goal": c.goal or s.goal, "check": c.name,
                            "facet": c.facet, "status": c.status,
                            "value": "" if c.value is None else c.value,
                            "capped": c.capped,
                            "abstain_reason": c.abstain_reason or "",
                            "annotation": c.annotation or "",
                            "detail": c.detail or "",
                        })
                program = parse_workspace(r.workspace_xml or "", r.run_id)
                arts = {(a.scenario_id, a.construct): a
                        for a in report.artifacts}
                for res in report.scenarios:
                    art = arts.get((res.scenario_id, res.construct))
                    if art is None:
                        ev = ScenarioEvidence(
                            scenario_id=res.scenario_id, family=res.family,
                            construct=res.construct, abstained=True,
                            abstain_reason=(res.checks[0].abstain_reason
                                            if res.checks
                                            and res.checks[0].abstained
                                            else None))
                    else:
                        ev = scenario_evidence(
                            program, res, art,
                            cards.get(res.scenario_id, {}))
                    ew.writerow(_evidence_row(ident, ev))
                for goal, gb in banded_invariant(reports, rollup_card).items():
                    w.writerow({
                        **ident, "channel": "goal", "eligible": True,
                        "scenario": "__goal_band__", "goal": goal,
                        "check": gb.indicator or "goal_band",
                        "status": gb.label,
                        "value": "" if gb.score is None else round(gb.score, 4),
                        "abstain_reason": gb.abstain_subtag,
                        "annotation": (gb.certainty if gb.certainty == "full"
                                       else "reduced:" +
                                       "+".join(gb.certainty_reasons)),
                        "detail": (f"valid={gb.n_valid} abst={gb.n_abstained}"
                                   + (f" P={gb.probability:.3f}"
                                      if gb.probability is not None else "")
                                   + ("".join(" FLAG:" + f for f in gb.flags))),
                    })
            n += 1
            if n % 200 == 0:
                print(f"  {n}/{len(runs)}")
                fh.flush()
                ev_fh.flush()
        ev_fh.close()
    return {"runs": n, "eligible": eligible_n,
            "validation_307": len(validation)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--playground", default="castle_crashers")
    parser.add_argument("--limit", type=int, default=None,
                        help="first N runs only (smoke runs)")
    args = parser.parse_args(argv)
    print("DONE", sweep(args.out, args.playground, args.limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
