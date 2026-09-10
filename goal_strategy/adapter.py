"""As-run event adapters. Outcomes must already belong to the supplied run."""
from __future__ import annotations

import copy
import json
import math

from .config import configs_root, load_configs
from .execution import prepare_execution
from .profile import _profile
from .serialize import PIPELINE_VERSION, SCHEMA_VERSION, profile_to_dict, to_dict


def _object(value, label, diagnostics):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except (ValueError, RecursionError):
            diagnostics.append(f'invalid_{label}')
            return {}
    if not isinstance(value, dict):
        diagnostics.append(f'invalid_{label}')
        return {}
    return copy.deepcopy(value)


def _canonical_playground(name):
    if not isinstance(name, str):
        return None
    # Aliases are derived from each card, so new playgrounds can be added in YAML.
    root = configs_root().joinpath('playgrounds')
    for path in sorted(root.iterdir(), key=lambda p: p.name):
        if path.name.endswith('.yaml'):
            canonical = path.name[:-5]
            cfg = load_configs(canonical)
            aliases = set(cfg.card.get('aliases') or [])
            aliases.update([canonical, cfg.card.get('playground_name'), cfg.card.get('vex_playground_key'),
                            (cfg.card.get('corpus_filter') or {}).get('playground_self_id')])
            if name in aliases:
                return canonical
    return None


def _params(value, canonical, end_status, diagnostics):
    params = None
    if value is not None:
        obj = _object(value, 'playground_data', diagnostics)
        identity = obj.get('playground')
        if identity is not None and _canonical_playground(identity) != canonical:
            diagnostics.append('conflicting_telemetry_playground')
        elif 'parameters' in obj:
            params = _object(obj['parameters'], 'parameters', diagnostics)
        else:
            params = obj
    if end_status is not None:
        if end_status not in ('completed', 'stopped_by_user', 'timeout', 'error'):
            diagnostics.append('invalid_end_status')
        elif end_status != 'completed':
            params = dict(params or {})
            params['project_stopped_by_user'] = True
    return params


def _result(xml, program_id, playground, params, diagnostics, include_timeline, include_battery):
    canonical = _canonical_playground(playground)
    result = dict(schema_version=SCHEMA_VERSION, pipeline_version=PIPELINE_VERSION,
                  program_id=program_id, index=None, event_index=None, ts=None,
                  playground=playground if isinstance(playground, str) else None,
                  status='unsupported_playground', reason='unsupported_playground',
                  profile=None, timeline=None, battery=None, diagnostics=diagnostics)
    if canonical is None:
        return result
    execution = prepare_execution(xml, program_id, params, canonical)
    prof = _profile(xml, program_id, params, canonical, _execution=execution)
    if execution.program is None:
        diagnostics.append('invalid_xml')
    for goal in prof.goals:
        for indicator in goal.intent + goal.attainment:
            if indicator.abstain_reason and 'invalid' in indicator.abstain_reason:
                diagnostics.append(indicator.abstain_reason)
    diagnostics[:] = sorted(set(diagnostics))
    invalid = [d for d in diagnostics if d.startswith('invalid_') or d.endswith('_invalid') or d == 'conflicting_telemetry_playground']
    result.update(status='invalid_input' if invalid else 'profiled',
                  reason=invalid[0] if invalid else None, profile=profile_to_dict(prof))
    if include_timeline:
        from .timeline import timeline_result
        result['timeline'] = to_dict(timeline_result(xml, program_id, params, canonical, _execution=execution))
    if include_battery:
        from .testcases import run_battery
        result['battery'] = to_dict(run_battery(xml, program_id, canonical, _execution=execution))
    return result


def goal_profile(workspace_xml, program_id, playground_params=None,
                 playground='castle_crashers', *, include_timeline=False, include_battery=False):
    diagnostics = []
    params = _params(playground_params, _canonical_playground(playground), None, diagnostics)
    return _result(workspace_xml, program_id, playground, params, diagnostics, include_timeline, include_battery)


def goal_profile_from_content(content, *, program_id, playground=None, playground_data=None,
                              end_status=None, include_timeline=False, include_battery=False):
    diagnostics = []
    obj = _object(content, 'content', diagnostics)
    effective = obj.get('playground') if obj.get('playground') is not None else playground
    project = _object(obj.get('project'), 'project', diagnostics)
    xml = project.get('workspace')
    params = _params(playground_data, _canonical_playground(effective), end_status, diagnostics)
    return _result(xml, program_id, effective, params, diagnostics, include_timeline, include_battery)


def _timestamp(event, result):
    ts = event.get('ts')
    try:
        valid = ts is None or isinstance(ts, (int, float)) and not isinstance(ts, bool) and math.isfinite(ts)
    except OverflowError:
        valid = False
    if valid:
        result['ts'] = ts
    else:
        result['diagnostics'].append('invalid_timestamp')


def goal_profile_from_run_event(event, *, program_id, playground_data=None, end_status=None,
                                include_timeline=False, include_battery=False):
    if not isinstance(event, dict) or event.get('event_type') != 'runProject':
        raise ValueError('Expected a runProject event')
    result = goal_profile_from_content(event.get('content'), program_id=program_id,
             playground_data=playground_data, end_status=end_status,
             include_timeline=include_timeline, include_battery=include_battery)
    _timestamp(event, result)
    return result


def goal_profiles_from_events(events, *, session_id, outcomes_by_run_index=None,
                              include_timeline=False, include_battery=False):
    if not isinstance(session_id, str) or not session_id:
        raise ValueError('A nonempty session_id is required')
    if outcomes_by_run_index is not None and not isinstance(outcomes_by_run_index, dict):
        raise TypeError('outcomes_by_run_index must be a mapping keyed by global integer run index')
    outcomes = outcomes_by_run_index or {}
    if any(type(k) is not int or k < 0 for k in outcomes):
        raise ValueError('Outcome keys must be nonnegative integer run indices')
    runs, diagnostics = [], []
    previous_playground = None
    for event_index, event in enumerate(events):
        if not isinstance(event, dict):
            diagnostics.append(dict(event_index=event_index, reason='invalid_event'))
            continue
        if event.get('event_type') != 'runProject':
            if event.get('event_type') == 'playgroundData':
                diagnostics.append(dict(event_index=event_index, reason='unassociated_outcome'))
            continue
        content_diagnostics = []
        content = _object(event.get('content'), 'content', content_diagnostics)
        inherited = content.get('playground') is None
        effective = previous_playground if inherited else content['playground']
        index = len(runs)
        associated = outcomes.get(index, {})
        if not isinstance(associated, dict):
            raise ValueError(f'Outcome entry {index} must be a dict')
        program_id = associated.get('program_id') or json.dumps([session_id, index], separators=(',', ':'))
        if not isinstance(program_id, str):
            raise ValueError('Associated program_id must be a string')
        result = goal_profile_from_content(content, program_id=program_id, playground=effective,
            playground_data=associated.get('playground_data'), end_status=associated.get('end_status'),
            include_timeline=include_timeline, include_battery=include_battery)
        result.update(index=index, event_index=event_index)
        result['diagnostics'].extend(content_diagnostics)
        if inherited and effective is not None:
            result['diagnostics'].append('inherited_playground')
        _timestamp(event, result)
        result['diagnostics'] = sorted(set(result['diagnostics']))
        runs.append(result)
        previous_playground = effective
    for index in outcomes:
        if index >= len(runs):
            diagnostics.append(dict(index=index, reason='outcome_without_run'))
    return dict(runs=runs, diagnostics=diagnostics)
