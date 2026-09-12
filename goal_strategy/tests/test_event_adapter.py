"""Public integration contracts using the target's real event conventions."""
import copy
import json
import os
import subprocess
import sys

import pytest

from goal_strategy import goal_profile, goal_profile_from_content, goal_profiles_from_events
from goal_strategy.config import load_configs
from goal_strategy.tests.test_hat_execution import drive_for, workspace
from goal_strategy.tests.test_scheduler import started

XML = workspace(started('A', drive_for(200))).replace(' xmlns="https://developers.google.com/blockly/xml"', '')


def event(playground='CastleCrasherPlus', xml=XML):
    return {'event_type': 'runProject', 'ts': None,
            'content': {'playground': playground, 'project': {'workspace': xml}}}


@pytest.mark.parametrize('content_json', [False, True])
@pytest.mark.parametrize('project_json', [False, True])
def test_dict_and_json_layers(content_json, project_json):
    content = event()['content']
    if project_json:
        content['project'] = json.dumps(content['project'])
    if content_json:
        content = json.dumps(content)
    output = goal_profile_from_content(content, program_id='shape', include_timeline=True, include_battery=True)
    assert output['status'] == 'profiled'
    assert output['profile']['playground'] == 'castle_crashers'
    assert output['timeline'] is not None and output['battery'] is not None
    json.dumps(output, allow_nan=False)


def test_run_index_matches_learner_models_and_inputs_are_unchanged():
    from learner_models import compute_run_edit_distances
    events = [event(), event('RoverRescue'), event(None), event('CastleCrasherPlus', '<bad'), event(None)]
    events.insert(2, {'event_type': 'playgroundData', 'ts': 1, 'content': {'weight_cleared': 500}})
    before = copy.deepcopy(events)
    outcomes = {4: {'playground_data': {'playground': 'CasteCrasherPlus', 'parameters': {'weight_cleared': 700}}, 'end_status': 'completed'}}
    output = goal_profiles_from_events(events, session_id='student/session', outcomes_by_run_index=outcomes)
    expected = compute_run_edit_distances(events)['runs']
    assert [(r['index'], r['playground']) for r in output['runs']] == [(r['index'], r['playground']) for r in expected]
    assert [r['status'] for r in output['runs']] == ['profiled', 'unsupported_playground', 'unsupported_playground', 'invalid_input', 'profiled']
    assert output['diagnostics'] == [{'event_index': 2, 'reason': 'unassociated_outcome'}]
    assert output['runs'][4]['profile']['outcome_available']
    assert not output['runs'][0]['profile']['outcome_available']
    assert events == before
    prefix = goal_profiles_from_events(events[:2], session_id='student/session')
    assert [r['program_id'] for r in prefix['runs']] == [r['program_id'] for r in output['runs'][:2]]


def test_conflicting_telemetry_is_rejected_and_bad_xml_retains_outcomes():
    output = goal_profile_from_content(event()['content'], program_id='conflict',
        playground_data={'playground': 'RoverRescue', 'parameters': {'weight_cleared': 9000}})
    assert output['status'] == 'invalid_input'
    assert not output['profile']['outcome_available']
    output = goal_profile_from_content(event(xml='<broken')['content'], program_id='broken',
        playground_data={'weight_cleared': 700})
    assert output['status'] == 'invalid_input' and output['profile']['outcome_available']
    output = goal_profiles_from_events([event(None)], session_id='missing')
    assert output['runs'][0]['status'] == 'unsupported_playground'


@pytest.mark.parametrize('bad', ['{', '[]', None, 5])
def test_bad_content_is_explicit(bad):
    output = goal_profile_from_content(bad, program_id='bad', playground='castle_crashers')
    assert output['status'] == 'invalid_input'
    json.dumps(output, allow_nan=False)


def test_cards_are_isolated_and_config_source_is_resolved_each_call(tmp_path, monkeypatch):
    from shutil import copytree
    from goal_strategy.config import configs_root
    first = load_configs('castle_crashers')
    first.card['playground_name'] = 'mutated'
    assert load_configs('castle_crashers').card['playground_name'] != 'mutated'
    copytree(configs_root(), tmp_path/'cards')
    card = tmp_path/'cards/playgrounds/castle_crashers.yaml'
    card.write_text(card.read_text().replace('Castle Crashers Plus', 'Alternate'))
    monkeypatch.setenv('GOAL_STRATEGY_CONFIG_DIR', str(tmp_path/'cards'))
    assert load_configs('castle_crashers').card['playground_name'] == 'Alternate'
    assert load_configs('castle_crashers').config_version != first.config_version


def test_alias_resolution_is_cached_and_cleared_with_configs(tmp_path, monkeypatch):
    # The cached alias->canonical map must honor the same cache_clear() contract
    # as the cards it is derived from: a new alias appears only after clearing.
    from shutil import copytree
    from goal_strategy.adapter import _canonical_playground
    from goal_strategy.config import configs_root, load_configs
    copytree(configs_root(), tmp_path/'cards')
    monkeypatch.setenv('GOAL_STRATEGY_CONFIG_DIR', str(tmp_path/'cards'))
    load_configs.cache_clear()                          # isolate from other tests' caches
    assert _canonical_playground('CastleCrasherPlus') == 'castle_crashers'
    assert _canonical_playground('BrandNewAlias') is None

    card = tmp_path/'cards/playgrounds/castle_crashers.yaml'
    card.write_text(card.read_text() + '\naliases:\n  - BrandNewAlias\n')
    assert _canonical_playground('BrandNewAlias') is None   # still the cached map
    load_configs.cache_clear()
    assert _canonical_playground('BrandNewAlias') == 'castle_crashers'
    monkeypatch.undo()
    load_configs.cache_clear()                          # don't leak the temp dir's map


def test_plain_output_reproducible_without_optional_imports():
    code = 'import sys,json; sys.modules.update({x:None for x in ["pandas","pyarrow","streamlit","plotly","apted"]}); from goal_strategy import goal_profile; print(json.dumps(goal_profile(' + repr(XML) + ',"stable"),sort_keys=True,allow_nan=False))'
    outputs = [subprocess.check_output([sys.executable, '-c', code], env=dict(os.environ, PYTHONHASHSEED=str(seed))) for seed in [1, 2, 42]]
    assert len(set(outputs)) == 1


def test_extreme_timestamp_is_metadata_diagnostic():
    events = [event()]
    events[0]['ts'] = 10**400
    result = goal_profiles_from_events(events, session_id='extreme')['runs'][0]
    assert result['ts'] is None
    assert 'invalid_timestamp' in result['diagnostics']
    json.dumps(result, allow_nan=False)


def test_finite_inputs_whose_derived_distance_overflows_abstain():
    output = goal_profile(XML, 'overflow', {'weight_cleared': 700,
        'gps_x_position': 1.79e308, 'gps_y_position': 1.79e308}, include_timeline=True)
    assert output['status'] == 'invalid_input'
    assert any(i['abstained'] and i['abstain_reason'] == 'outcome_field_invalid'
               for g in output['profile']['goals'] for i in g['attainment'])
    json.dumps(output, allow_nan=False)
