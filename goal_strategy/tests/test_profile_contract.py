"""Output-contract tests (spec §7): channels, abstention, goal completeness,
robustness to malformed input."""
from goal_strategy import GoalEvidence, profile
from goal_strategy.config import load_configs


def test_engage_plow_has_two_intent_indicators_on_different_channels():
    cfg = load_configs("castle_crashers")
    goal = next(g for g in cfg.goals if g.id == "engage_plow")
    assert len(goal.intent) == 2
    prof = profile("", "contract_test")
    evidence = next(g for g in prof.goals if g.goal == "engage_plow")
    assert {ind.channel for ind in evidence.intent} == {"code", "simulation"}


def test_profile_never_raises_on_malformed_xml_and_none_params():
    for xml in ("", "   ", "<not xml", "<xml>truncated", None):
        prof = profile(xml, "broken", playground_params=None)
        assert prof.program_id == "broken"
        assert not prof.outcome_available
        # Every card goal is always present, even when everything abstained.
        assert [g.goal for g in prof.goals] == \
            ["playground_engagement", "engage_plow", "clear_debris_zone",
             "remain_on_island"]
        for goal in prof.goals:
            for ind in goal.intent + goal.attainment:
                assert ind.abstained
                assert ind.abstain_reason in ("no_code", "no_simulation", "invalid_xml",
                                              "outcome_field_absent",
                                              "gps_unavailable")


def test_boundary_is_a_profile_flag_not_a_goal():
    prof = profile("", "flag_test")
    assert "boundary_exceeded" not in [g.goal for g in prof.goals]
    assert prof.boundary_exceeded is False
    assert prof.boundary_exit_step is None


def test_empty_attainment_list_is_representable():
    evidence = GoalEvidence(goal="modelling_statement", intent=[], attainment=[])
    assert evidence.attainment == []


def test_rung_edges_echoed_for_auditability():
    prof = profile("", "audit_test")
    plow = next(g for g in prof.goals if g.goal == "engage_plow")
    approach = next(i for i in plow.intent if i.name == "plow_approach_intent")
    assert approach.rung_edges == [190.0, 380.0, 570.0]   # 1x/2x/3x object.tolerance
    magnet = next(i for i in plow.intent if i.name == "magnet_activation_intent")
    assert magnet.rung_edges == []                        # categorical


def test_config_version_is_stable_within_a_config():
    a = profile("", "v1").config_version
    b = profile("", "v2").config_version
    assert a == b and len(a) == 12
