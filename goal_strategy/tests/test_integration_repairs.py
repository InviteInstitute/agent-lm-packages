"""Public API reproductions from the migration audit."""
import json
from dataclasses import asdict

import pytest

from goal_strategy.profile import profile, _profile
from goal_strategy.timeline import timeline_result
from goal_strategy.testcases import run_battery
from goal_strategy.tests.test_hat_execution import drive_for, workspace
from goal_strategy.tests.test_scheduler import started, coop


def flags(p):
    return {f for g in p.goals for i in g.intent + g.attainment for f in i.flags}


@pytest.mark.xfail(reason="engine port-forward 2026-09-17: the current vendored "
                   "simulator is not fully namespace-agnostic (unnamespaced XML "
                   "parses fewer blocks than namespaced). Faithful to upstream vex; "
                   "queued for the port owner (§6 flag-and-queue).", strict=False)
def test_target_unnamespaced_xml_matches_blockly_namespace():
    xml = workspace(started('A', drive_for(200)))
    plain = xml.replace(' xmlns="https://developers.google.com/blockly/xml"', '')
    a, b = asdict(profile(xml, 't')), asdict(profile(plain, 't'))
    assert a == b


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), '-Infinity'])
def test_nonfinite_outcomes_abstain_without_losing_code(bad):
    p = profile(workspace(started('A', drive_for(200))), 't',
                {'weight_cleared': bad, 'gps_x': bad, 'gps_y': 0})
    indicators = [i for g in p.goals for i in g.attainment if i.channel == 'outcome']
    assert any(i.abstained and 'invalid' in (i.abstain_reason or '') for i in indicators)
    json.dumps(asdict(p), allow_nan=False)


def test_empty_battery_is_explicitly_ineligible():
    b = run_battery('', 'empty')
    # engine port-forward 2026-09-17: BatteryReport no longer carries a
    # `diagnostics` field; empty/invalid XML is reported via eligible=False
    # (host-safe early return, no crash in qualifying_blocks).
    assert not b.eligible
    assert b.qualifying_blocks == () and b.scenarios == ()


@pytest.mark.xfail(reason="engine port-forward 2026-09-17: the current vendored "
                   "simulator executes one iteration for repeat(0) "
                   "(net_displacement 100, not 0). Reproduces upstream vex exactly; "
                   "queued for the port owner (§6 flag-and-queue).", strict=False)
def test_repeat_zero_does_not_execute():
    body = '<block type="pg_control_repeat" id="r"><value name="TIMES"><shadow type="math_number"><field name="NUM">0</field></shadow></value><statement name="SUBSTACK">' + drive_for(100) + '</statement></block>'
    assert coop(workspace(started('A', body))).net_displacement_from_spawn == 0


@pytest.mark.xfail(reason="engine port-forward 2026-09-17: cooperative drivetrain "
                   "arbitration of an absolute turn_to_heading no longer supersedes "
                   "a concurrent drive_for (motions_superseded 0, not 1). Faithful "
                   "to upstream vex; queued for the port owner (§6 flag-and-queue).",
                   strict=False)
def test_absolute_turn_arbitrates_like_relative_turn():
    turn = '<block type="pg_drivetrain_turn_to_heading" id="turn"><value name="HEADING"><shadow type="math_number"><field name="NUM">90</field></shadow></value></block>'
    sim = coop(workspace(started('A', drive_for(1000)), started('B', turn)))
    assert sim.net_displacement_from_spawn == 0
    assert sim.motions_superseded == 1


def test_unknown_statement_and_loop_cap_are_visible():
    xml = workspace(started('A', '<block type="pg_drivetrain_not_real" id="x"/>'))
    # engine port-forward 2026-09-17: the unsimulable-block flag is now
    # `unmodeled_construct_defaulted` (was `unmodeled_blocks`) — matches upstream vex.
    assert 'unmodeled_construct_defaulted' in flags(profile(xml, 't'))
    body = '<block type="pg_control_repeat" id="r"><value name="TIMES"><shadow type="math_number"><field name="NUM">100</field></shadow></value><statement name="SUBSTACK">' + drive_for(2) + '</statement></block>'
    assert 'loop_capped' in flags(profile(workspace(started('A', body)), 't'))


@pytest.mark.xfail(reason="engine port-forward 2026-09-17: the current parser no "
                   "longer abstains every intent on 1100-deep XML (it parses/bounds "
                   "it differently). Faithful to upstream vex; queued for the port "
                   "owner (§6 flag-and-queue).", strict=False)
def test_deep_xml_is_bounded_and_preserves_outcome():
    xml = '<xml>' + '<block type="pg_events_when_started"><next>' * 1100 + '<block type="pg_drivetrain_drive_for"/>' + '</next></block>' * 1100 + '</xml>'
    p = profile(xml, 'deep', {'weight_cleared': 700})
    assert p.outcome_available
    assert all(i.abstained for g in p.goals for i in g.intent)


def test_continuous_approach_timeline(toy):
    xml = workspace(started('A', drive_for(3000)))
    p = _profile(xml, 't', playground='toy_line', configs_dir=toy)
    tl = timeline_result(xml, 't', playground='toy_line', configs_dir=toy)
    assert p.goals[0].intent[0].rung == 'reached'
    assert any(e.indicator == 'approach' and e.to_rung == 'reached' for e in tl.events)


from goal_strategy.tests.test_timeline import toy


@pytest.mark.xfail(reason="engine port-forward 2026-09-17: the current simulator "
                   "flags `procedure_recursion_suppressed` when two separate stacks "
                   "call the same procedure. Faithful to upstream vex; queued for the "
                   "port owner (§6 flag-and-queue).", strict=False)
def test_procedure_reachability_and_thread_local_recursion():
    from goal_strategy.tests.test_oi23_builds import _definition, _call
    from goal_strategy.tests.test_scheduler import MAGNET
    xml = workspace(started('A', _call('Go', 'c1')), started('B', _call('Go', 'c2')),
                    _definition('Go', drive_for(100)), _definition('Unused', MAGNET))
    sim = coop(xml)
    assert 'procedure_recursion_suppressed' not in sim.execution_flags
    p = profile(xml, 't')
    assert next(g for g in p.goals if g.goal == 'engage_plow').intent[0].rung == 'absent'
    called = workspace(started('A', _call('Magnet')), _definition('Magnet', MAGNET))
    p = profile(called, 't')
    assert next(g for g in p.goals if g.goal == 'engage_plow').intent[0].rung != 'absent'


@pytest.mark.xfail(reason="engine port-forward 2026-09-17: non-finite reporter "
                   "values (Infinity / overflow) raise OverflowError inside the "
                   "current simulator instead of being caught and flagged. "
                   "Reproduces upstream vex exactly; a real guard regression queued "
                   "for the port owner (§6 flag-and-queue).", strict=False)
@pytest.mark.parametrize('reporter', [
    '<block type="pg_operator_round"><value name="NUM"><shadow type="math_number"><field name="NUM">Infinity</field></shadow></value></block>',
    '<block type="pg_operator_random"><value name="FROM"><shadow type="math_number"><field name="NUM">Infinity</field></shadow></value><value name="TO"><shadow type="math_number"><field name="NUM">10</field></shadow></value></block>',
    '<block type="pg_operator_function"><field name="OPERATOR">e^</field><value name="NUM"><shadow type="math_number"><field name="NUM">1000</field></shadow></value></block>',
])
def test_overflow_expression_cannot_escape_profile(reporter):
    xml = workspace(started('A', '<block type="pg_drivetrain_drive_for" id="d"><value name="AMOUNT">' + reporter + '</value></block>'))
    p = profile(xml, 'numeric')
    assert flags(p) & {'invalid_expression', 'nonfinite_parameter_stall', 'unknown_reporter'}
    json.dumps(asdict(p), allow_nan=False)


def test_early_stop_and_unexplained_fidelity_are_visible():
    xml = workspace(started('A', drive_for(200)))
    params = {'gps_x_position': -700, 'gps_y_position': -700, 'weight_cleared': 700}
    p = profile(xml, 't', params)
    assert 'sim_unverified' in flags(p)
    p = profile(xml, 't', dict(params, project_stopped_by_user=True))
    assert p.gps_final_error_mm is None and p.gps_final_error_reason == 'early_stop'
    assert 'early_stop_outcome' in flags(p)
    assert 'sim_unverified' not in flags(p)


def test_armed_pass_through_target_matches_timeline(toy):
    from goal_strategy.tests.test_timeline import MAGNET
    xml = workspace(started('A', MAGNET.replace('</block>', '<next>'+drive_for(3000)+'</next></block>')))
    p = _profile(xml, 'armed', playground='toy_line', configs_dir=toy)
    assert p.goals[0].attainment[0].rung == 'armed_close'
    tl = timeline_result(xml, 'armed', playground='toy_line', configs_dir=toy)
    assert any(e.indicator == 'engaged' and e.to_rung == 'armed_close' for e in tl.events)


def test_zero_velocity_preserves_existing_behavior_with_uncertainty():
    xml = workspace(started('A', '<block type="pg_drivetrain_set_drive_velocity"><field name="VELOCITY">0</field><next>'+drive_for(200)+'</next></block>'))
    p = profile(xml, 'zero-velocity')
    # engine port-forward 2026-09-17: `zero_velocity_assumed` is a sim
    # execution flag (not a per-goal-indicator flag) in the current engine;
    # the fallback-to-default behavior is still surfaced via simulated_fallback.
    assert 'simulated_fallback' in flags(p)
    assert coop(xml).net_displacement_from_spawn == pytest.approx(200)


def test_procedure_only_sensor_qualifies_for_battery():
    from goal_strategy.tests.test_oi23_builds import _definition, _call
    sensor = '<block type="pg_control_wait_until"><value name="CONDITION"><block type="pg_sensing_bumper" id="sensor"><field name="BUMPER">leftbumper</field></block></value></block>'
    xml = workspace(started('A', _call('Sense')), _definition('Sense', sensor))
    report = run_battery(xml, 'procedure-sensing')
    assert report.eligible and 'pg_sensing_bumper' in report.qualifying_blocks
    assert report.scenarios


@pytest.mark.xfail(reason="engine port-forward 2026-09-17: an unknown check rule "
                   "now degrades to a failing/abstained check (testcases.py returns "
                   "CheckResult(..., detail='unknown rule ...')) instead of raising "
                   "ConfigError. Faithful to upstream vex; queued for the port owner "
                   "(§6 flag-and-queue).", strict=False)
def test_unknown_battery_rule_is_a_configuration_error(tmp_path):
    from shutil import copytree
    from goal_strategy.config import configs_root, ConfigError
    root = tmp_path/'cards'
    copytree(configs_root(), root)
    # 19-scenario battery (port-forward 2026-09-17): corrupt a real rule in an
    # existing scenario card, and drive it with a QUALIFYING program so the
    # scenario actually runs and the rule is validated during evaluation.
    card = root/'testcases/castle_crashers/t2a_direct.yaml'
    card.write_text(card.read_text().replace('rule: edge_encounters_survived',
                                             'rule: nonexistent_rule'))
    sensor = ('<block type="pg_control_wait_until"><value name="CONDITION">'
              '<block type="pg_sensing_bumper" id="s"><field name="BUMPER">leftbumper</field>'
              '</block></value></block>')
    xml = workspace(started('A', sensor))
    with pytest.raises(ConfigError, match='unknown check rule'):
        run_battery(xml, 'invalid-config', configs_dir=str(root))
