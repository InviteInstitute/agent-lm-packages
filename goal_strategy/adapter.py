"""As-run event adapters. Outcomes must already belong to the supplied run."""
from __future__ import annotations

import copy
import functools
import hashlib
import json
import math
import os
import threading
from collections import OrderedDict

from .config import ConfigError, configs_root, load_configs, register_config_cache_clearer
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


def _card_aliases(cfg, canonical):
    aliases = set(cfg.card.get('aliases') or [])
    aliases.update([canonical, cfg.card.get('playground_name'), cfg.card.get('vex_playground_key'),
                    (cfg.card.get('corpus_filter') or {}).get('playground_self_id')])
    return aliases


@functools.lru_cache(maxsize=8)
def _alias_to_canonical(root):
    """Whole-directory form of the per-card alias scan: every alias -> its
    canonical playground, the first YAML in sorted order winning a shared alias.
    Keyed on the resolved configs root and dropped by load_configs.cache_clear(),
    so it costs one directory read per config source instead of one per run."""
    mapping = {}
    for path in sorted(root.joinpath('playgrounds').iterdir(), key=lambda p: p.name):
        if not path.name.endswith('.yaml'):
            continue
        canonical = path.name[:-5]
        for alias in _card_aliases(load_configs(canonical), canonical):
            if isinstance(alias, str):
                mapping.setdefault(alias, canonical)
    return mapping


register_config_cache_clearer(_alias_to_canonical.cache_clear)


def _canonical_playground(name):
    if not isinstance(name, str):
        return None
    # Aliases are derived from each card, so new playgrounds can be added in YAML.
    root = configs_root()
    try:
        return _alias_to_canonical(root).get(name)
    except ConfigError:
        # A malformed card in the directory: fall back to the original lazy scan,
        # which raises or resolves depending on where `name` falls in sort order.
        return _canonical_playground_scan(name, root)


def _canonical_playground_scan(name, root):
    for path in sorted(root.joinpath('playgrounds').iterdir(), key=lambda p: p.name):
        if path.name.endswith('.yaml'):
            canonical = path.name[:-5]
            if name in _card_aliases(load_configs(canonical), canonical):
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


# Content-addressed result cache. program_id is a pure label (it flows only into
# output fields, never into parsing/simulation/scoring), so the profile is a
# deterministic function of everything BELOW keyed here; identical re-runs
# (wheel-spinning) hit, and program_id is re-stamped per call. The key omits
# program_id and includes the config source + conditional-hat treatment, and the
# cache is dropped by load_configs.cache_clear() so in-place card edits stay honest.
_RESULT_CACHE: "OrderedDict[tuple, dict]" = OrderedDict()
_RESULT_CACHE_MAX = 256
# The other caches use functools.lru_cache (internally locked); this manual LRU
# needs its own lock so concurrent hosts can't race get/evict into a KeyError.
_RESULT_CACHE_LOCK = threading.Lock()


def _result_cache_clear():
    with _RESULT_CACHE_LOCK:
        _RESULT_CACHE.clear()


register_config_cache_clearer(_result_cache_clear)


def _restamp_program_id(obj, program_id):
    """Overwrite every 'program_id' field in a cached result copy with this
    call's id. Robust to nesting (profile, battery, timeline all embed it)."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key == 'program_id':
                obj[key] = program_id
            else:
                _restamp_program_id(value, program_id)
    elif isinstance(obj, list):
        for value in obj:
            _restamp_program_id(value, program_id)


def _result_cache_key(xml, playground, params, diagnostics, include_timeline,
                      include_battery, include_rubric, include_rollup):
    treatment = (os.environ.get("GOAL_STRATEGY_CONDITIONAL_HATS")
                 or os.environ.get("VEX_GOAL_PROFILES_CONDITIONAL_HATS")
                 or "execute").lower()
    try:
        params_key = json.dumps(params, sort_keys=True, default=str)
    except TypeError:
        # Non-string / heterogeneous param keys can't be sorted by json; coerce
        # keys to str. Safe for the cache key - unrecognized keys don't affect
        # the profile, so grouping them together never returns a stale result.
        params_key = json.dumps({str(k): v for k, v in params.items()},
                                sort_keys=True, default=str)
    return (
        hashlib.sha256((xml or "").encode("utf-8", "surrogatepass")).hexdigest(),
        playground if isinstance(playground, str) else repr(playground),
        params_key,
        bool(include_timeline), bool(include_battery), bool(include_rubric),
        bool(include_rollup),
        tuple(sorted(set(diagnostics))),
        str(configs_root()), treatment,
        PIPELINE_VERSION, SCHEMA_VERSION,
    )


def _result(xml, program_id, playground, params, diagnostics, include_timeline,
            include_battery, include_rubric=False, include_rollup=False):
    key = _result_cache_key(xml, playground, params, diagnostics, include_timeline,
                            include_battery, include_rubric, include_rollup)
    with _RESULT_CACHE_LOCK:
        cached = _RESULT_CACHE.get(key)
        if cached is not None:
            _RESULT_CACHE.move_to_end(key)
    if cached is not None:
        # Copy outside the lock; the cached master is never mutated in place.
        result = copy.deepcopy(cached)
        _restamp_program_id(result, program_id)
        return result
    # Compute outside the lock so a slow simulation never serializes all callers;
    # a concurrent duplicate miss just recomputes the same value (last write wins).
    result = _compute_result(xml, program_id, playground, params, diagnostics,
                             include_timeline, include_battery, include_rubric,
                             include_rollup)
    stored = copy.deepcopy(result)
    with _RESULT_CACHE_LOCK:
        _RESULT_CACHE[key] = stored
        if len(_RESULT_CACHE) > _RESULT_CACHE_MAX:
            _RESULT_CACHE.popitem(last=False)
    return result


def _compute_result(xml, program_id, playground, params, diagnostics,
                    include_timeline, include_battery, include_rubric=False,
                    include_rollup=False):
    canonical = _canonical_playground(playground)
    result = dict(schema_version=SCHEMA_VERSION, pipeline_version=PIPELINE_VERSION,
                  program_id=program_id, index=None, event_index=None, ts=None,
                  playground=playground if isinstance(playground, str) else None,
                  status='unsupported_playground', reason='unsupported_playground',
                  profile=None, timeline=None, battery=None, rubric=None,
                  rollup=None, diagnostics=diagnostics)
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
    # Battery-once: the battery runs its own designed worlds (separate
    # simulations, by design). When any battery-fed channel is requested it
    # runs a SINGLE time with collect_sims=True, and that one report is shared
    # by the battery, rubric and rollup channels.
    report = None
    if include_battery or include_rubric or include_rollup:
        from .testcases import run_battery
        report = run_battery(xml, program_id, canonical, collect_sims=True)
    if include_battery:
        # Strip the collected artifacts so the battery output is identical to a
        # plain collect_sims=False run (they are internal sim data, never part
        # of the battery channel).
        import dataclasses
        result['battery'] = to_dict(dataclasses.replace(report, artifacts=()))
    if include_rubric:
        # PROVISIONAL purpose-2 (rubric_status = provisional_stage2E). Reuses
        # the shared execution's parsed program and simulation for the code
        # channel and the shared battery report for the scenario channel.
        from .rubric_online import rubric_dimensions, rubric_to_dict
        dims = rubric_dimensions(execution.program, execution.context.full_sim,
                                 program_id, prof.config_version, canonical,
                                 report=report)
        result['rubric'] = rubric_to_dict(dims)
    if include_rollup:
        # Purpose-1 rolled-up goal claims (the agent-facing meta view): banded
        # from the shared battery report, enriched from the computed profile.
        from .rollup_online import goal_rollup
        result['rollup'] = goal_rollup(prof, report, canonical)
    return result


def goal_profile(workspace_xml, program_id, playground_params=None,
                 playground='castle_crashers', *, include_timeline=False,
                 include_battery=False, include_rubric=False, include_rollup=False):
    diagnostics = []
    params = _params(playground_params, _canonical_playground(playground), None, diagnostics)
    return _result(workspace_xml, program_id, playground, params, diagnostics,
                   include_timeline, include_battery, include_rubric, include_rollup)


def goal_profile_from_content(content, *, program_id, playground=None, playground_data=None,
                              end_status=None, include_timeline=False,
                              include_battery=False, include_rubric=False,
                              include_rollup=False):
    diagnostics = []
    obj = _object(content, 'content', diagnostics)
    return _profile_obj(obj, diagnostics, program_id=program_id, playground=playground,
                        playground_data=playground_data, end_status=end_status,
                        include_timeline=include_timeline, include_battery=include_battery,
                        include_rubric=include_rubric, include_rollup=include_rollup)


def _profile_obj(obj, diagnostics, *, program_id, playground=None, playground_data=None,
                 end_status=None, include_timeline=False, include_battery=False,
                 include_rubric=False, include_rollup=False):
    """Profile an already-parsed, caller-owned content dict. Lets the streaming
    path reuse the copy it made for inheritance/replay instead of _object-ing the
    content a second time. `diagnostics` is seeded and extended in place."""
    effective = obj.get('playground') if obj.get('playground') is not None else playground
    project = _object(obj.get('project'), 'project', diagnostics)
    xml = project.get('workspace')
    params = _params(playground_data, _canonical_playground(effective), end_status, diagnostics)
    return _result(xml, program_id, effective, params, diagnostics,
                   include_timeline, include_battery, include_rubric, include_rollup)


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
                                include_timeline=False, include_battery=False,
                                include_rubric=False, include_rollup=False):
    if not isinstance(event, dict) or event.get('event_type') != 'runProject':
        raise ValueError('Expected a runProject event')
    result = goal_profile_from_content(event.get('content'), program_id=program_id,
             playground_data=playground_data, end_status=end_status,
             include_timeline=include_timeline, include_battery=include_battery,
             include_rubric=include_rubric, include_rollup=include_rollup)
    _timestamp(event, result)
    return result


def goal_profiles_from_events(events, *, session_id, outcomes_by_run_index=None,
                              include_timeline=False, include_battery=False,
                              include_rubric=False, include_rollup=False):
    # Whole-session convenience over the online GoalProfileStream: one shared
    # per-run core means the batch and streaming paths cannot drift, and a
    # session prefix profiles identically either way.
    from .streaming import GoalProfileStream
    stream = GoalProfileStream(session_id, include_timeline=include_timeline,
                               include_battery=include_battery,
                               include_rubric=include_rubric,
                               include_rollup=include_rollup)
    if outcomes_by_run_index is not None and not isinstance(outcomes_by_run_index, dict):
        raise TypeError('outcomes_by_run_index must be a mapping keyed by global integer run index')
    outcomes = outcomes_by_run_index or {}
    if any(type(k) is not int or k < 0 for k in outcomes):
        raise ValueError('Outcome keys must be nonnegative integer run indices')
    for event in events:
        stream.push(event, outcome=outcomes.get(len(stream.runs)))
    diagnostics = list(stream.diagnostics)
    for index in outcomes:
        if index >= len(stream.runs):
            diagnostics.append(dict(index=index, reason='outcome_without_run'))
    return dict(runs=stream.runs, diagnostics=diagnostics)
