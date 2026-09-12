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
