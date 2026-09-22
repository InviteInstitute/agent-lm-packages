"""Real-time driver for the event -> goal-profile pipeline.

`goal_profiles_from_events` needs the whole session at once. A live host (an
agent watching a student code, a websocket consumer, a queue worker) has the
events one at a time and wants a profile the moment a run finishes. This module
is that online path: push one VEX event as it arrives, get the run's profile
back, and associate an outcome later when the playground telemetry shows up.

No server, no threads, no wall clock. Plain data in, plain data out, so any host
loop can drive it - the same contract as the rest of the package.

The stream is the single source of truth for per-run semantics (global run
index, playground inheritance, stable ``program_id``, diagnostics); the batch
``goal_profiles_from_events`` drives one of these, so the two cannot diverge.
Feeding a prefix of a session's events yields exactly the runs the batch call
produces for that same prefix - that prefix identity is what makes the online
path safe to trust mid-session.
"""
from __future__ import annotations

import json

from .adapter import _object, _profile_obj, _timestamp


class GoalProfileStream:
    """Stateful, incremental view over one student's one session.

    Construct with the session id, then ``push`` events in arrival order. Each
    ``runProject`` appends one profiled run and returns its result dict; every
    other event returns ``None`` (recording a stream-level diagnostic for
    ``playgroundData`` and non-dict events, mirroring the batch adapter).
    ``associate_outcome`` re-profiles an earlier run once its outcome is known.
    """

    def __init__(self, session_id, *, include_timeline=False, include_battery=False,
                 include_rubric=False, include_rollup=False):
        if not isinstance(session_id, str) or not session_id:
            raise ValueError('A nonempty session_id is required')
        self.session_id = session_id
        self._include_timeline = include_timeline
        self._include_battery = include_battery
        self._include_rubric = include_rubric
        self._include_rollup = include_rollup
        self._previous_playground = None
        self._event_index = 0
        self.runs = []          # profiled runs; runs[i]['index'] == i
        self.diagnostics = []    # stream-level (non-run) diagnostics, in arrival order
        self._records = []       # per-run inputs, kept so a late outcome can re-profile

    def push(self, event, *, outcome=None):
        """Consume one event. Returns the run's result dict for a ``runProject``
        (a new run is appended), otherwise ``None``. ``outcome`` associates that
        run's outcome at profile time, exactly as ``outcomes_by_run_index[index]``
        does in the batch call; a later outcome uses ``associate_outcome``."""
        event_index = self._event_index
        self._event_index += 1
        if not isinstance(event, dict):
            self.diagnostics.append(dict(event_index=event_index, reason='invalid_event'))
            return None
        if event.get('event_type') != 'runProject':
            if event.get('event_type') == 'playgroundData':
                self.diagnostics.append(dict(event_index=event_index, reason='unassociated_outcome'))
            return None
        content_diagnostics = []
        content = _object(event.get('content'), 'content', content_diagnostics)
        inherited = content.get('playground') is None
        effective = self._previous_playground if inherited else content['playground']
        index = len(self.runs)
        if outcome is not None and not isinstance(outcome, dict):
            raise ValueError(f'Outcome entry {index} must be a dict')
        result = self._profile_run(content, effective, inherited, outcome or {},
                                   index, event_index, event.get('ts'), content_diagnostics)
        self.runs.append(result)
        # Keep only what re-profiling needs: the owned content copy, the resolved
        # playground/inheritance, the pristine content diagnostics, and the ts.
        # Not the whole event (it re-holds the content) - see review #2.
        self._records.append(dict(content=content, effective=effective, inherited=inherited,
                                  ts=event.get('ts'), event_index=event_index,
                                  content_diagnostics=content_diagnostics))
        self._previous_playground = effective
        return result

    def associate_outcome(self, index, outcome):
        """Attach an outcome to an already-profiled run and recompute it. Returns
        the refreshed result, or ``None`` (with an ``outcome_without_run``
        diagnostic) if the run has not been seen yet. Recomputing - rather than
        patching - guarantees a late outcome never leaves stale evidence, and
        yields the same run the batch call produces with the outcome supplied up
        front."""
        if type(index) is not int or index < 0:
            raise ValueError('Outcome index must be a nonnegative integer run index')
        if not isinstance(outcome, dict):
            raise ValueError(f'Outcome entry {index} must be a dict')
        if index >= len(self.runs):
            self.diagnostics.append(dict(index=index, reason='outcome_without_run'))
            return None
        rec = self._records[index]
        result = self._profile_run(rec['content'], rec['effective'], rec['inherited'], outcome,
                                   index, rec['event_index'], rec['ts'],
                                   rec['content_diagnostics'])
        self.runs[index] = result
        return result

    def _profile_run(self, content, effective, inherited, associated, index, event_index,
                     ts, content_diagnostics):
        program_id = associated.get('program_id') or json.dumps(
            [self.session_id, index], separators=(',', ':'))
        if not isinstance(program_id, str):
            raise ValueError('Associated program_id must be a string')
        # Reuse the already-owned content copy; seed diagnostics with the content
        # parse (a copy - _profile_obj extends it in place, the stored one stays
        # pristine for re-profiling).
        result = _profile_obj(
            content, list(content_diagnostics), program_id=program_id, playground=effective,
            playground_data=associated.get('playground_data'),
            end_status=associated.get('end_status'),
            include_timeline=self._include_timeline, include_battery=self._include_battery,
            include_rubric=self._include_rubric, include_rollup=self._include_rollup)
        result.update(index=index, event_index=event_index)
        if inherited and effective is not None:
            result['diagnostics'].append('inherited_playground')
        _timestamp({'ts': ts}, result)
        result['diagnostics'] = sorted(set(result['diagnostics']))
        return result
