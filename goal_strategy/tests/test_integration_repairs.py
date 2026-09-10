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
    assert not b.eligible
    assert 'invalid_xml' in b.diagnostics


def test_repeat_zero_does_not_execute():
    body = '<block type="pg_control_repeat" id="r"><value name="TIMES"><shadow type="math_number"><field name="NUM">0</field></shadow></value><statement name="SUBSTACK">' + drive_for(100) + '</statement></block>'
    assert coop(workspace(started('A', body))).net_displacement_from_spawn == 0


def test_absolute_turn_arbitrates_like_relative_turn():
    turn = '<block type="pg_drivetrain_turn_to_heading" id="turn"><value name="HEADING"><shadow type="math_number"><field name="NUM">90</field></shadow></value></block>'
    sim = coop(workspace(started('A', drive_for(1000)), started('B', turn)))
    assert sim.net_displacement_from_spawn == 0
    assert sim.motions_superseded == 1


def test_unknown_statement_and_loop_cap_are_visible():
    xml = workspace(started('A', '<block type="pg_drivetrain_not_real" id="x"/>'))
    assert 'unmodeled_blocks' in flags(profile(xml, 't'))
    body = '<block type="pg_control_repeat" id="r"><value name="TIMES"><shadow type="math_number"><field name="NUM">100</field></shadow></value><statement name="SUBSTACK">' + drive_for(2) + '</statement></block>'
    assert 'loop_capped' in flags(profile(workspace(started('A', body)), 't'))


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


def test_shared_execution_rejected_program_and_ui_geometry():
    from goal_strategy.viz.data import walkthrough_payload
    xml = workspace(started('A', drive_for(1000)), started('B', drive_for(400)))
    result = walkthrough_payload('t', xml, None)
    sx, sy = result['geometry']['spawn']
    fx, fy = result['sim_final']
    assert ((fx-sx)**2 + (fy-sy)**2)**0.5 == pytest.approx(400)
    rejected = workspace(started('A', '<block type="pg_switch_block" id="x"/>'))
    # Use the actual capability card's rejecting type.
    from goal_strategy.config import load_configs
    name = next(k for k, v in load_configs('castle_crashers').capabilities['blocks'].items() if v.get('rejects_program'))
    rejected = rejected.replace('pg_switch_block', name)
    result = walkthrough_payload('t', rejected, None)
    assert result['sim_final'] is None
    assert not any(e['kind'] == 'failure' for e in result['events'])


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
    assert 'zero_velocity_assumed' in flags(p)
    assert coop(xml).net_displacement_from_spawn == pytest.approx(200)


def test_procedure_only_sensor_qualifies_for_battery():
    from goal_strategy.tests.test_oi23_builds import _definition, _call
    sensor = '<block type="pg_control_wait_until"><value name="CONDITION"><block type="pg_sensing_bumper" id="sensor"><field name="BUMPER">leftbumper</field></block></value></block>'
    xml = workspace(started('A', _call('Sense')), _definition('Sense', sensor))
    report = run_battery(xml, 'procedure-sensing')
    assert report.eligible and 'pg_sensing_bumper' in report.qualifying_blocks
    assert report.scenarios


def test_unknown_battery_rule_is_a_configuration_error(tmp_path):
    from shutil import copytree
    from goal_strategy.config import configs_root, ConfigError
    root = tmp_path/'cards'
    copytree(configs_root(), root)
    card = root/'testcases/castle_crashers/edge_handling.yaml'
    card.write_text(card.read_text().replace('rule: on_island', 'rule: nonexistent_rule'))
    with pytest.raises(ConfigError, match='unknown check rule'):
        run_battery('', 'invalid-config', configs_dir=str(root))
