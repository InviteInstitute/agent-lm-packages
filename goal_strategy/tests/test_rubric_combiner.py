"""Combiner unit tests (the D-a..D-e rulings as invariants)."""
from __future__ import annotations

from goal_strategy.rubric_combiner import (
    combine_run, load_claims, _holds,
)


def _claims():
    return load_claims("castle_crashers")


def _row(**kw):
    base = {"abstained": "False"}
    base.update({k: str(v) for k, v in kw.items()})
    return base


def test_claims_card_loads_with_inference_labels():
    c = _claims()
    assert c["claims_id"] == "castle_crashers_claims_v1"
    for dim, spec in c["dimensions"].items():
        for lvl, ls in spec["levels"].items():
            for fl in ls.get("floors") or []:
                assert "inference" in fl, (dim, lvl)   # the D-d principle
                assert fl.get("weight", "primary") in ("primary", "supporting",
                                                       "constraint")


def test_yaml_true_op_fires():
    assert _holds({"x": True}, {"evidence": "x", "op": True})
    assert _holds({"x": "True"}, {"evidence": "x", "op": "true"})
    assert not _holds({"x": False}, {"evidence": "x", "op": True})


def test_tsr2_requires_the_conjunction():
    """The ruled TSR-2: transitions replicated across tests AND the
    phase-return present — either alone is insufficient."""
    c = _claims()
    rows = [_row(task_state_triggered_transition_count=3,
                 task_phase_return_count=0),
            _row(task_state_triggered_transition_count=3,
                 task_phase_return_count=0)]
    des = {d.dimension: d for d in combine_run("r", rows, None, None, c)}
    assert des["task_state_regulation"].level == 1     # no return -> capped at 1
    rows[0] = _row(task_state_triggered_transition_count=3,
                   task_phase_return_count=1)
    des = {d.dimension: d for d in combine_run("r", rows, None, None, c)}
    assert des["task_state_regulation"].level == 2
    # and the REVERSE: return alone (no replicated transitions) is
    # equally insufficient — the conjunction binds both ways
    only_return = [_row(task_state_triggered_transition_count=1,
                        task_phase_return_count=1)]
    des = {d.dimension: d
           for d in combine_run("r", only_return, None, None, c)}
    assert des["task_state_regulation"].level == 1


def test_negative_scores_zero_with_evidence_never_U():
    """D-e spirit under the R2 restructure (2026-09-11): the
    never-corrective program still reads 0 WITH evidence — now as a
    VERIFIED zero through the opportunity gate (>=2 demonstrated
    deviations, no recovery loop), never U."""
    c = _claims()
    rows = [_row(corrective_response_present=False),
            _row(corrective_response_present=False)]
    des = {d.dimension: d for d in combine_run("r", rows, None, None, c)}
    rec = des["recovery"]
    assert rec.level == 0 and not rec.u_reason
    assert rec.fired[0][0] == "gate.recovery_opportunity"


def test_ceiling_zero_assigns_level_zero():
    """The economy rule ASSIGNS at ceiling 0 — census-decided, not U."""
    c = _claims()
    des = {d.dimension: d
           for d in combine_run("r", [_row()], {"run_id": "r"},
                                {"control_structure": 0}, c)}
    cs = des["control_structure"]
    assert cs.level == 0
    assert cs.fired and cs.fired[0][0] == "census.ceiling_zero"


def test_ceiling_caps_awarded_level():
    c = _claims()
    rows = [_row(code_max_arm_alternations=5)]
    des = {d.dimension: d
           for d in combine_run("r", rows, None,
                                {"environmental_feedback": 1}, c)}
    assert des["environmental_feedback"].level == 1    # capped below 2


def test_no_evidence_is_U():
    c = _claims()
    des = {d.dimension: d for d in combine_run("r", [], None, None, c)}
    assert all(d.level is None for d in des.values())


# ---- SMC gated ordinal lower scale (reviewer-ruled 2026-09-09) ----

def _smc(des):
    return {d.dimension: d for d in des}["spatial_motion"]


def test_smc_gate_no_fixed_motion_is_not_evaluable():
    """No motion literals and no state evidence: U with the DECLARED
    reason — never no_informative_variable."""
    c = _claims()
    prod = {"run_id": "r", "motion_literal_count": "0"}
    d = _smc(combine_run("r", [_row()], prod, None, c))
    assert d.level is None and d.u_reason == "not_evaluable"


def test_smc_verified_zero_assigns_with_gate_evidence():
    """Evaluable + neither route demonstrated: VERIFIED zero, fired
    shows the gate — absence of calibration IS the L0 evidence."""
    c = _claims()
    prod = {"run_id": "r", "motion_literal_count": "3",
            "calibrated_param_matches": "0", "fixed_motion_specificity": "0"}
    d = _smc(combine_run("r", [_row()], prod, None, c))
    assert d.level == 0 and not d.u_reason
    assert d.fired and d.fired[0][0] == "gate.smc_evaluable"


def test_smc_either_route_awards_l1_with_strength():
    c = _claims()
    direct = {"run_id": "r", "motion_literal_count": "2",
              "calibrated_param_matches": "1",
              "fixed_motion_specificity": "0"}
    d = _smc(combine_run("r", [_row()], direct, None, c))
    assert d.level == 1
    assert [s for e, l, w, s in d.fired] == ["direct"]
    indirect = {"run_id": "r", "motion_literal_count": "4",
                "calibrated_param_matches": "0",
                "fixed_motion_specificity": "1"}
    d = _smc(combine_run("r", [_row()], indirect, None, c))
    assert d.level == 1
    assert [s for e, l, w, s in d.fired] == ["indirect"]


def test_smc_l2_overrides_gate_and_palette():
    """State-derived motion wins regardless of the fixed-motion
    vocabulary — even with ZERO literals (gate would fail) the state
    evidence awards L2 (the ruled precedence)."""
    c = _claims()
    prod = {"run_id": "r", "motion_literal_count": "0",
            "state_gated_drivetrain": "2",
            "state_gated_drivetrain_executed": "2"}
    d = _smc(combine_run("r", [_row()], prod, None, c))
    assert d.level == 2


def test_smc_l2_requires_executed_gating():
    """OI-33 ruling ("attempts are flawed"): an evaluated conditional
    whose motion arm never RAN is an attempt — the architecture count
    alone never awards L2; the run scores by the gated lower rules."""
    c = _claims()
    prod = {"run_id": "r", "motion_literal_count": "3",
            "state_gated_drivetrain": "2",
            "state_gated_drivetrain_executed": "0",
            "calibrated_param_matches": "0",
            "fixed_motion_specificity": "0"}
    d = _smc(combine_run("r", [_row()], prod, None, c))
    assert d.level == 0                      # verified zero, not L2
    assert d.fired[0][0] == "gate.smc_evaluable"


def test_smc_computed_params_no_longer_score():
    """The WREN-C008 regression: a computed motion param alone neither
    lifts to L1 nor fakes an informative zero via supporting — the run
    scores by the gated rules (here: evaluable coarse -> verified 0)."""
    c = _claims()
    prod = {"run_id": "r", "motion_literal_count": "2",
            "computed_motion_params": "1",
            "calibrated_param_matches": "0", "fixed_motion_specificity": "0"}
    d = _smc(combine_run("r", [_row()], prod, None, c))
    assert d.level == 0
    assert d.fired[0][0] == "gate.smc_evaluable"


def test_explain_run_agrees_with_combine_run():
    """explain_run (the audit tool's provenance source) must tell the
    same story combine_run scores: same final label per dimension, and
    every claim row carries its inference label."""
    from goal_strategy.rubric_combiner import explain_run
    c = _claims()
    cases = [
        ([], None, None),                                    # no evidence
        ([_row(code_max_arm_alternations=3)], None, None),   # EF award
        ([_row()], {"run_id": "r", "motion_literal_count": "3",
                    "fixed_motion_specificity": "0"}, None), # verified 0
        ([_row(corrective_response_present=False),
          _row(corrective_response_present=False)], None, None),  # negative
        ([_row()], {"run_id": "r"}, {"control_structure": 0}),    # census 0
    ]
    for rows, prod, ceil in cases:
        des = {d.dimension: d.label
               for d in combine_run("r", rows, prod, ceil, c)}
        exp = explain_run("r", rows, prod, ceil, c)
        for dim, label in des.items():
            assert exp[dim]["final"] == label, (dim, label)
            for lv in exp[dim]["levels"]:
                for claim in lv["claims"]:
                    assert claim["inference"], (dim, lv["level"])


# ---- Recovery R2 restructure (reviewer-ruled 2026-09-11) ----

def _rec(des):
    return {d.dimension: d for d in des}["recovery"]


def test_r2_reflex_only_is_nonrecovering_zero():
    """A corrective EVENT without the loop (retreat is the terminal
    seam) is L0 non-recovering — the demoted reflex class."""
    c = _claims()
    rows = [_row(corrective_response_present=True,
                 correction_reassessment_cycles=0),
            _row(corrective_response_present=False)]
    d = _rec(combine_run("r", rows, None, None, c))
    assert d.level == 0
    assert d.fired[0][0] == "gate.recovery_opportunity"


def test_r2_loop_once_with_failures_is_level_one():
    """The riser class: the loop demonstrated once, failures elsewhere
    permitted at L1 (condition-dependent recovery)."""
    c = _claims()
    rows = [_row(corrective_response_present=True,
                 correction_reassessment_cycles=1),
            _row(corrective_response_present=False),
            _row(corrective_response_present=False)]
    d = _rec(combine_run("r", rows, None, None, c))
    assert d.level == 1


def test_family_grain_l2_needs_two_families_and_robustness():
    """The family-grain ruling (2026-09-11): L2 = the closed loop in
    >=2 condition FAMILIES, with at most ONE family containing an
    UNSURVIVED deviation (a fall-off). One-family cycling stays L1;
    two failure families block L2; arrested-survived encounters are
    answered deviations and never count."""
    c = _claims()

    def rows(fams_cyc, fams_all):
        out = []
        for i, fam in enumerate(fams_all):
            out.append(_row(corrective_response_present=True,
                            correction_reassessment_cycles=(
                                1 if fam in fams_cyc else 0),
                            family=fam, scenario=f"s_{fam}_{i}"))
        return out

    one_fam = rows({"t1"}, ["t1", "t2"])
    d = _rec(combine_run("r", one_fam, None, None, c))
    assert d.level == 1                     # loop in ONE family only

    two_fam = rows({"t1", "t5"}, ["t1", "t5", "t2"])
    stays_ok = {f"s_t2_2": 1.0}             # arrested + survived = answered
    d = _rec(combine_run("r", two_fam, None, None, c,
                         stays=stays_ok))
    assert d.level == 2                     # cross-family loop, robust

    stays_bad = {"s_t1_0": 0.5, "s_t2_2": 0.0}   # two failure families
    d = _rec(combine_run("r", two_fam, None, None, c,
                         stays=stays_bad))
    assert d.level == 1                     # robustness constraint blocks

    stays_one = {"s_t2_2": 0.0}             # one failure family tolerated
    d = _rec(combine_run("r", two_fam, None, None, c,
                         stays=stays_one))
    assert d.level == 2


def test_r2_single_opportunity_is_U():
    """One demonstrated deviation cannot verify a zero (D-e
    replication): the gate holds it at U with the declared reason."""
    c = _claims()
    rows = [_row(corrective_response_present=False)]
    d = _rec(combine_run("r", rows, None, None, c))
    assert d.level is None
    assert d.u_reason == "insufficient_deviation_opportunity"


def test_r2_constraint_alone_never_informative():
    """A holding constraint (corrective_false <= 1 is trivially true
    with no rows) must not fake an informative zero — a run with no
    deviation evidence stays U."""
    c = _claims()
    rows = [_row(code_max_arm_alternations=0)]   # a row, no recovery info
    d = _rec(combine_run("r", rows, None, None, c))
    assert d.level is None


def test_census_ceiling_outranks_recovery_gate():
    """Economy-rule precedence (2026-09-11): a no-sensing program's
    recovery zero is census-VERIFIED — ceiling 0 assigns even though
    the opportunity gate (battery-only evidence) cannot pass."""
    c = _claims()
    des = {d.dimension: d
           for d in combine_run("r", [], {"run_id": "r"},
                                {"recovery": 0,
                                 "task_state_regulation": 0}, c)}
    rec = des["recovery"]
    assert rec.level == 0
    assert rec.fired[0][0] == "census.ceiling_zero"
    assert des["task_state_regulation"].level == 0
