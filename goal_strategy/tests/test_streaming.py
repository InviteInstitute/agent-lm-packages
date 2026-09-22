"""GoalProfileStream: the online path must agree with the batch adapter run for
run, prefix for prefix, and must let an outcome arrive after its run."""
import copy

import pytest

from goal_strategy import GoalProfileStream, goal_profiles_from_events
from goal_strategy.tests.test_event_adapter import XML, event

SESSION = 'student/session'


def stream_runs(events, outcomes=None, **kw):
    """Drive a stream one event at a time, applying outcomes by index at push
    time - the online equivalent of outcomes_by_run_index."""
    outcomes = outcomes or {}
    s = GoalProfileStream(SESSION, **kw)
    for e in events:
        s.push(e, outcome=outcomes.get(len(s.runs)))
    return s


def test_streaming_equals_batch_run_for_run():
    events = [event(), event('RoverRescue'), event(None),
              event('CastleCrasherPlus', '<bad'), event(None)]
    events.insert(2, {'event_type': 'playgroundData', 'ts': 1, 'content': {'weight_cleared': 500}})
    outcomes = {4: {'playground_data': {'playground': 'CasteCrasherPlus',
                                        'parameters': {'weight_cleared': 700}},
                    'end_status': 'completed'}}
    batch = goal_profiles_from_events(events, session_id=SESSION, outcomes_by_run_index=outcomes)
    s = stream_runs(events, outcomes)
    assert s.runs == batch['runs']
    assert s.diagnostics == batch['diagnostics']


def test_prefix_identity_holds_after_every_event():
    # The property that makes mid-session profiling trustworthy: the runs a
    # stream has emitted after k events equal the batch call over those k events.
    events = [event(), event(None), event('RoverRescue'), event('CastleCrasherPlus', '<bad')]
    s = GoalProfileStream(SESSION)
    for i, e in enumerate(events, start=1):
        s.push(e)
        prefix = goal_profiles_from_events(events[:i], session_id=SESSION)
        assert s.runs == prefix['runs']


def test_push_returns_the_run_and_none_for_other_events():
    s = GoalProfileStream(SESSION)
    assert s.push({'event_type': 'playgroundData', 'ts': 1, 'content': {}}) is None
    assert s.push('not-a-dict') is None
    run = s.push(event())
    assert run is not None and run['index'] == 0 and run['status'] == 'profiled'
    assert run is s.runs[0]
    # non-run events still advance event_index (matches batch enumerate())
    assert run['event_index'] == 2
    assert s.diagnostics == [{'event_index': 0, 'reason': 'unassociated_outcome'},
                             {'event_index': 1, 'reason': 'invalid_event'}]


def test_late_outcome_matches_upfront_outcome():
    outcome = {'playground_data': {'playground': 'CasteCrasherPlus',
                                   'parameters': {'weight_cleared': 700}},
               'end_status': 'completed'}
    upfront = stream_runs([event()], {0: outcome}).runs[0]

    s = GoalProfileStream(SESSION)
    first = s.push(event())
    assert not first['profile']['outcome_available']
    refreshed = s.associate_outcome(0, outcome)
    assert refreshed['profile']['outcome_available']
    assert refreshed is s.runs[0]
    assert refreshed == upfront


def test_associate_before_run_is_a_diagnostic_not_an_error():
    s = GoalProfileStream(SESSION)
    assert s.associate_outcome(3, {'end_status': 'completed'}) is None
    assert {'index': 3, 'reason': 'outcome_without_run'} in s.diagnostics


def test_inputs_are_not_mutated():
    e = event()
    before = copy.deepcopy(e)
    GoalProfileStream(SESSION).push(e)
    assert e == before


def test_playground_inheritance_carries_across_pushes():
    s = GoalProfileStream(SESSION)
    s.push(event('CastleCrasherPlus'))
    inherited = s.push(event(None))
    assert inherited['playground'] == 'CastleCrasherPlus'
    assert 'inherited_playground' in inherited['diagnostics']


def test_records_are_minimal_no_event_retained():
    # Review #2: keep only ts, not the whole event (which re-holds the content).
    s = GoalProfileStream(SESSION)
    s.push(event())
    rec = s._records[0]
    assert 'event' not in rec
    assert 'ts' in rec and 'content' in rec


@pytest.mark.parametrize('bad', ['', None, 5])
def test_session_id_must_be_nonempty_string(bad):
    with pytest.raises(ValueError):
        GoalProfileStream(bad)


def test_bad_outcome_type_is_rejected():
    s = GoalProfileStream(SESSION)
    with pytest.raises(ValueError):
        s.push(event(), outcome='not-a-dict')
    with pytest.raises(ValueError):
        s.associate_outcome(0, 'not-a-dict')


from goal_strategy.tests.test_hat_execution import workspace  # noqa: E402
from goal_strategy.tests.test_scheduler import started  # noqa: E402

# Namespaced like real Blockly output, so these programs reach the simulator.
_DRIVE_XML = workspace(started('A', '<block type="pg_drivetrain_drive_for" id="d">'
    '<field name="DIRECTION">fwd</field><field name="UNITS">mm</field>'
    '<value name="AMOUNT"><shadow type="math_number"><field name="NUM">200</field>'
    '</shadow></value></block>'))
# The same drive, by round(Infinity) mm: the simulator raises on it.
_OVERFLOW_XML = _DRIVE_XML.replace(
    '<shadow type="math_number"><field name="NUM">200</field></shadow>',
    '<block type="pg_operator_round"><value name="NUM"><shadow type="math_number">'
    '<field name="NUM">Infinity</field></shadow></value></block>')


def test_engine_error_keeps_later_runs_on_their_own_index():
    # Host safety: an engine defect on one run is an explicit per-run status,
    # not an exception. If it escaped, a host that catches it would lose the
    # run and every later run's global index would land on the wrong program.
    assert _OVERFLOW_XML != _DRIVE_XML
    events = [event(xml=_DRIVE_XML), event(xml=_OVERFLOW_XML), event(xml=_DRIVE_XML)]
    s = stream_runs(events, include_battery=True, include_rubric=True, include_rollup=True)
    assert [r['index'] for r in s.runs] == [0, 1, 2]
    assert s.runs[1]['status'] == 'engine_error'
    assert 'engine_error' in s.runs[1]['diagnostics']
    assert s.runs[1]['profile'] is None
    assert s.runs[2]['status'] == 'profiled'
    # a late outcome for the errored run re-profiles it without raising either
    assert s.associate_outcome(1, {'playground_data': {'weight_cleared': 500}})['index'] == 1


def test_failed_optional_channel_keeps_the_profile(monkeypatch):
    import goal_strategy.testcases as testcases
    from goal_strategy.adapter import _result_cache_clear

    def boom(*a, **k):
        raise RuntimeError('battery defect')

    monkeypatch.setattr(testcases, 'run_battery', boom)
    _result_cache_clear()  # a cached earlier result would skip the failing battery
    r = GoalProfileStream(SESSION, include_battery=True, include_rubric=True,
                          include_rollup=True).push(event(xml=_DRIVE_XML))
    assert r['status'] == 'profiled' and r['profile'] is not None
    assert r['battery'] is None and r['rubric'] is None
    assert 'battery_failed' in r['diagnostics']
    assert r['rollup'] is not None  # derived goals still read from the profile
