"""Purpose-2 combination — the D-a…D-e rulings as code (2026-09-09).

Turns the persisted evidence (stage3_battery_evidence.csv +
stage2_code_evidence.csv) into one DimensionEvidence per
(run, dimension), under configs/testcases/<pg>/_claims.yaml:

    ceilings cap  ->  floor claims vote (primary 1.0 / supporting 0.5;
    validation-role variables GATE, never vote)  ->  opportunity-verified
    negatives subtract  ->  level = highest floor with net support >=
    support_min and no surviving negative  ->  U when nothing
    informative reached the dimension.

Every threshold lives in the claims card with its D-d inference label —
nothing numeric here. Borderline claims (|net - support_min| <=
borderline_margin) are flagged: the D-b validation oversample for C3.
Consumes CSVs only — running this NEVER re-simulates.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path

from .config import _DEFAULT_CONFIGS_DIR, _load_yaml

_W = {"primary": 1.0, "supporting": 0.5,
      # R2 Recovery ruling (2026-09-11): a CONSTRAINT claim contributes
      # no support and never makes a dimension informative — it only
      # gates (pair with conjunct: true). Used for consistency bounds
      # like corrective_false_tests <= 1 at Recovery-2.
      "constraint": 0.0}


@dataclass(frozen=True)
class DimensionEvidence:
    run_id: str
    dimension: str
    level: int | None              # None = U
    ceiling: int | None            # census cap (None = uncapped)
    fired: tuple = ()              # (evidence name, level, weight, strength)
                                   # strength: direct|indirect|census|gate|""
    negatives: tuple = ()          # negatives that survived
    borderline: bool = False       # near support_min — the C3 oversample
    u_reason: str = ""             # when level is None

    @property
    def label(self) -> str:
        return f"U/{self.u_reason or 'no_evidence'}" if self.level is None \
            else str(self.level)


def load_claims(playground: str = "castle_crashers",
                configs_dir: str | None = None) -> dict:
    path = (Path(configs_dir or _DEFAULT_CONFIGS_DIR) / "testcases"
            / playground / "_claims.yaml")
    return _load_yaml(path) if path.exists() else {}


def _run_features(batt_rows: list, prod: dict | None,
                  stays: dict | None = None) -> dict:
    """The per-run feature dictionary the claims card's `evidence:` names
    resolve against. batt_rows = this run's scored (non-abstained)
    goal+rubric evidence rows; prod = its stage2_code_evidence row;
    stays = {scenario: stays_on_island proportion} from the checks
    table (the Recovery family-grain ruling, 2026-09-11 — survival is
    the outcome record the failure features read)."""
    f: dict = {}
    n = lambda r, k: int(r.get(k) or 0)
    x = lambda r, k: float(r[k]) if r.get(k) not in ("", None) else None
    f["battery.code_max_arm_alternations"] = max(
        (n(r, "code_max_arm_alternations") for r in batt_rows), default=0)
    f["battery.response_latency_mm"] = any(
        r.get("response_latency_mm") not in ("", None) for r in batt_rows)
    f["battery.boundary_band_entries"] = max(
        (n(r, "boundary_band_entries") for r in batt_rows), default=0)
    f["battery.task_state_triggered_transition_count"] = max(
        (n(r, "task_state_triggered_transition_count") for r in batt_rows),
        default=0)
    f["battery.task_transitions_ge2_tests"] = sum(
        1 for r in batt_rows
        if n(r, "task_state_triggered_transition_count") >= 2)
    f["battery.task_phase_return_any"] = any(
        n(r, "task_phase_return_count") >= 1 for r in batt_rows)
    f["battery.completion_triggered_transition"] = any(
        r.get("completion_triggered_transition") == "True"
        for r in batt_rows)
    f["battery.clear_without_post_change"] = sum(
        1 for r in batt_rows
        if r.get("completion_triggered_transition") == "False")
    f["battery.corrective_true_any"] = any(
        r.get("corrective_response_present") == "True" for r in batt_rows)
    f["battery.corrective_false_tests"] = sum(
        1 for r in batt_rows
        if r.get("corrective_response_present") == "False")
    # R2 Recovery (2026-09-11): tests where a deviation opportunity was
    # DEMONSTRATED (corrective evaluated either way) — the evaluability
    # gate's evidence (>=2 = a zero can be verified, per D-e replication)
    f["battery.corrective_evaluated_tests"] = sum(
        1 for r in batt_rows
        if r.get("corrective_response_present") in ("True", "False"))
    f["battery.reassessment_cycles_max"] = max(
        (n(r, "correction_reassessment_cycles") for r in batt_rows),
        default=0)
    # Recovery family-grain ruling (2026-09-11). A CLOSED loop
    # (cycles >= 1) is already the re-armed loop — the counter closes
    # a correction only when reassessment follows, and trailing
    # corrections never close (the C114_020 finding: two answered
    # rounds read as one closed loop). The L2 floor therefore asks for
    # the closed loop in >= 2 condition FAMILIES, and the robustness
    # constraint counts families containing an UNSURVIVED deviation
    # (an arrested, survived encounter is an ANSWERED deviation —
    # never a failure; the failure condition is the counter-evidence).
    f["battery.reassessment_cycle_families"] = len(
        {r.get("family") for r in batt_rows
         if n(r, "correction_reassessment_cycles") >= 1})
    f["battery.unsurvived_deviation_families"] = len(
        {r.get("family") for r in batt_rows
         if (stays or {}).get(r.get("scenario"), 1.0) < 1.0})
    # state-termination EVENT count is not emitted per se; the ruled
    # replication proxy is >=2 scenario rows with a non-zero fraction
    f["battery.state_termination_events"] = sum(
        1 for r in batt_rows
        if (x(r, "code_state_terminated_motion_fraction") or 0) > 0)
    # detects-fail with the encounter reached is a stage3 check fact;
    # supplied by the caller when available (else 0 — no negative).
    f.setdefault("battery.detects_fail_with_encounter", 0)
    if prod:
        p = lambda k: int(prod.get(k) or 0)
        f["production.max_arm_alternations"] = p("max_arm_alternations")
        f["production.coordination_relations"] = p("coordination_relations")
        f["production.exercised_loops_any"] = (
            p("exercised_loops_fixed") + p("exercised_loops_state")
            + p("exercised_loops_forever"))
        f["production.state_controlled_termination"] = \
            prod.get("state_controlled_termination") == "True"
        f["production.state_gated_drivetrain"] = p("state_gated_drivetrain")
        f["production.state_gated_drivetrain_executed"] = p(
            "state_gated_drivetrain_executed")   # OI-33 scoring variant
        f["production.computed_motion_params"] = p("computed_motion_params")
        f["production.structures_exercised"] = (
            f["production.exercised_loops_any"] > 0
            or p("procedure_calls") > 0 or p("variable_sets") > 0)
        f["production.procedure_reused_or_parameterized"] = \
            p("procedure_reused") > 0
        f["production.calibrated_param_matches"] = p(
            "calibrated_param_matches")   # SMC-1 audit column (may be absent)
        f["production.motion_literal_count"] = p("motion_literal_count")
        # SMC specificity (2026-09-09): ordinal 0/1, blank = None
        # (insufficient fixed motion) — a missing column never fires.
        sv = prod.get("fixed_motion_specificity")
        f["production.fixed_motion_specificity"] = (
            int(sv) if sv not in ("", None) else None)
    return f


def _holds(f: dict, spec: dict) -> bool:
    v = f.get(spec["evidence"])
    op = spec.get("op")
    if op is True or op == "true":     # YAML parses bare `true` as bool
        return v is True or v == "True"
    if op == "present":
        return bool(v)
    if op == "known":
        # fires when the variable was DETERMINED, whatever its value —
        # the evaluability op (a determined 0 is evaluable; None is not)
        return v is not None
    if op == "ge":
        try:
            return (v or 0) >= spec["value"]
        except TypeError:
            return False
    if op == "le":
        try:
            return (v or 0) <= spec["value"]
        except TypeError:
            return False
    return False


def combine_run(run_id: str, batt_rows: list, prod: dict | None,
                ceilings: dict | None, claims: dict,
                stays: dict | None = None) -> list:
    """[DimensionEvidence] for one run under the claims card."""
    smin = float(claims.get("support_min") or 1.0)
    margin = float(claims.get("borderline_margin") or 0.0)
    feats = _run_features(batt_rows, prod, stays)
    out = []
    for dim, spec in (claims.get("dimensions") or {}).items():
        cap = (ceilings or {}).get(dim)
        if not batt_rows and not prod:
            out.append(DimensionEvidence(run_id, dim, None, cap,
                                         u_reason="no_evidence"))
            continue
        # Evaluability gate (gated ordinal, reviewer-ruled 2026-09-09):
        # when declared and failed, the lower scale is NOT EVALUABLE —
        # only an awarded higher level survives; U carries the declared
        # reason, never "no_informative_variable".
        gate = spec.get("evaluability")
        gate_ok = _holds(feats, gate) if gate else None
        level, fired_all, neg_all, borderline = 0, [], [], False
        informative = False
        all_fires = []   # every fired claim, any level — so a voted
                         # 0-with-evidence row shows WHAT was informative
        for lvl in sorted((spec.get("levels") or {}), key=int):
            lspec = spec["levels"][lvl]
            floors = lspec.get("floors") or []
            support = 0.0
            fired = []
            conjunct_ok = True
            for c in floors:
                if _holds(feats, c):
                    w = _W.get(c.get("weight", "primary"), 1.0)
                    support += w
                    fired.append((c["evidence"], int(lvl), w,
                                  c.get("strength", "")))
                    if w > 0:
                        # constraints (w=0) gate; they are never
                        # themselves evidence that the dimension spoke
                        informative = True
                elif c.get("conjunct"):
                    conjunct_ok = False
            all_fires.extend(fired)
            negs = [nspec for nspec in (lspec.get("negatives") or [])
                    if _holds(feats, nspec)]
            neg_w = float(len(negs))
            net = support - neg_w
            # BORDERLINE (D-b): a CONTESTED or NEAR-MISS decision, never
            # the normal single-primary-claim award — (a) the level was
            # awarded with negatives fired and only margin to spare, or
            # (b) support existed but net just missed the threshold.
            if fired and negs and net >= smin and net - smin <= margin:
                borderline = True
            if fired and smin - margin < net < smin:
                borderline = True
            if conjunct_ok and net >= smin \
                    and (cap is None or int(lvl) <= cap):
                level = int(lvl)
                fired_all = fired
                neg_all = [(n_["evidence"], int(lvl)) for n_ in negs]
            elif negs:
                informative = True   # a surviving negative IS evidence
        if gate is not None and not gate_ok and level == 0 and cap != 0:
            # not evaluable and nothing higher earned: U with the
            # declared reason (sub-threshold fires don't rescue an
            # unevaluable dimension). A census ceiling of 0 OUTRANKS
            # the gate (economy-rule precedence, 2026-09-11): the
            # dimension is structurally closed by code, so the zero is
            # census-verified and needs no battery opportunity — it
            # falls through to the ceiling-0 assignment below.
            out.append(DimensionEvidence(
                run_id, dim, None, cap,
                u_reason=gate.get("u_reason", "not_evaluable")))
            continue
        if not informative:
            if cap == 0:
                # the economy rule ASSIGNS here, it doesn't just cap: a
                # 0-ceiling is census-decided (no sensing / no structures
                # / no conditionals) — level 0 with the ceiling as the
                # fired evidence, never U.
                out.append(DimensionEvidence(
                    run_id, dim, 0, cap,
                    fired=(("census.ceiling_zero", 0, 1.0, "census"),)))
                continue
            if spec.get("verified_zero") and gate_ok:
                # VERIFIED ZERO (reviewer-ruled 2026-09-09): the run was
                # evaluable, fitting was sought on every route and not
                # demonstrated — absence IS the L0 evidence; no positive
                # coarse indicator required.
                out.append(DimensionEvidence(
                    run_id, dim, 0, cap,
                    fired=((f"gate.{gate.get('name', 'evaluable')}",
                            0, 1.0, "gate"),)))
                continue
            out.append(DimensionEvidence(run_id, dim, None, cap,
                                         u_reason="no_informative_variable"))
        else:
            fired_out = fired_all if level > 0 else all_fires
            out.append(DimensionEvidence(
                run_id, dim, level, cap, fired=tuple(fired_out),
                negatives=tuple(neg_all), borderline=borderline))
    return out


def explain_run(run_id: str, batt_rows: list, prod: dict | None,
                ceilings: dict | None, claims: dict,
                stays: dict | None = None) -> dict:
    """The combiner's own account of one run (validation audit MVP 2):
    for each dimension, every claim evaluated with its observed
    feature value, threshold, weight/strength and the claims card's
    D-d inference label — so a UI can DISPLAY scoring logic without
    recreating it. Additive: combine_run is untouched; a test pins
    agreement between the two on the final level."""
    smin = float(claims.get("support_min") or 1.0)
    margin = float(claims.get("borderline_margin") or 0.0)
    rows = [r for r in batt_rows if r.get("abstained") != "True"]
    feats = _run_features(rows, prod, stays)
    final = {d.dimension: d for d in
             combine_run(run_id, batt_rows, prod, ceilings, claims,
                         stays=stays)}
    out = {}
    for dim, spec in (claims.get("dimensions") or {}).items():
        cap = (ceilings or {}).get(dim)
        gate = spec.get("evaluability")
        entry = {
            "final": final[dim].label,
            "borderline": final[dim].borderline,
            "u_reason": final[dim].u_reason,
            "ceiling": cap,
            "support_min": smin, "borderline_margin": margin,
            "gate": None, "levels": [],
        }
        if gate:
            entry["gate"] = {"evidence": gate.get("evidence"),
                             "op": str(gate.get("op")),
                             "observed": feats.get(gate.get("evidence")),
                             "holds": _holds(feats, gate),
                             "u_reason": gate.get("u_reason", "")}
        for lvl in sorted((spec.get("levels") or {}), key=int):
            lspec = spec["levels"][lvl]
            lclaims, support = [], 0.0
            for c in (lspec.get("floors") or []):
                holds = _holds(feats, c)
                w = _W.get(c.get("weight", "primary"), 1.0)
                if holds:
                    support += w
                lclaims.append({
                    "evidence": c["evidence"],
                    "op": str(c.get("op")),
                    "threshold": c.get("value"),
                    "observed": feats.get(c["evidence"]),
                    "holds": holds,
                    "weight": c.get("weight", "primary"),
                    "strength": c.get("strength", ""),
                    "conjunct": bool(c.get("conjunct")),
                    "inference": c.get("inference", ""),
                })
            negs = []
            for nspec in (lspec.get("negatives") or []):
                negs.append({
                    "evidence": nspec["evidence"],
                    "op": str(nspec.get("op")),
                    "threshold": nspec.get("value"),
                    "observed": feats.get(nspec["evidence"]),
                    "holds": _holds(feats, nspec),
                    "inference": nspec.get("inference", ""),
                })
            net = support - float(sum(1 for n in negs if n["holds"]))
            entry["levels"].append({
                "level": int(lvl), "claims": lclaims, "negatives": negs,
                "support": support, "net": net,
                "conjunct_ok": all(c["holds"] for c in lclaims
                                   if c["conjunct"]),
                "meets": net >= smin,
                "capped": cap is not None and int(lvl) > cap,
            })
        out[dim] = entry
    return out


def sweep_combiner(evidence_csv: str, code_csv: str, out_csv: str,
                   playground: str = "castle_crashers",
                   checks_csv: str | None = None) -> dict:
    """Batch: DimensionEvidence rows for EVERY scorable run — the
    battery population (goal AND rubric_only channels) plus the
    census-only remainder of the corpus (reviewer-ruled 2026-09-11:
    the economy rule's population — dead reckoners are decidable from
    code + the production run, and the census-decided pathway must be
    auditable). Census-only runs combine with batt_rows=[]: ceilings
    assign, production floors vote, battery-only dimensions read U or
    census zeros as ruled. CSV-only; never re-simulates."""
    claims = load_claims(playground)
    prod = {r["run_id"]: r for r in csv.DictReader(open(code_csv))} \
        if Path(code_csv).exists() else {}
    # stays_on_island per (run, scenario) — the Recovery family-grain
    # ruling's survival record (2026-09-11); defaults to the checks
    # file beside the evidence table
    if checks_csv is None:
        cand = Path(evidence_csv).with_name("stage3_battery.csv")
        checks_csv = str(cand) if cand.exists() else None
    stays_by_run: dict = {}
    if checks_csv and Path(checks_csv).exists():
        for r in csv.DictReader(open(checks_csv)):
            if r.get("check") == "stays_on_island" \
                    and r.get("status") == "measured":
                try:
                    stays_by_run.setdefault(r["run_id"], {})[
                        r["scenario"]] = float(r["value"] or 0)
                except ValueError:
                    pass
    by_run: dict = {}
    for r in csv.DictReader(open(evidence_csv)):
        if r.get("abstained") == "True":
            continue
        by_run.setdefault(r["run_id"], []).append(r)
    for rid in sorted(prod):
        by_run.setdefault(rid, [])
    ceilings_by_run = {}
    for rid, p in prod.items():
        c = {}
        for part in (p.get("ceilings") or "").split(";"):
            if ":" in part:
                k, v = part.split(":", 1)
                c[k] = int(v)
        ceilings_by_run[rid] = c
    n = 0
    with open(out_csv, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["run_id", "dimension", "level", "ceiling",
                    "borderline", "u_reason", "fired", "negatives"])
        for rid, rows in by_run.items():
            for de in combine_run(rid, rows, prod.get(rid),
                                  ceilings_by_run.get(rid), claims,
                                  stays=stays_by_run.get(rid)):
                w.writerow([de.run_id, de.dimension, de.label,
                            "" if de.ceiling is None else de.ceiling,
                            de.borderline, de.u_reason,
                            "|".join(f"{e}@{l}" + (f"~{s}" if s else "")
                                     for e, l, _, s in de.fired),
                            "|".join(e for e, _ in de.negatives)])
                n += 1
    return {"runs": len(by_run), "rows": n}
