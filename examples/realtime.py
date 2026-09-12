"""
Real-time walkthrough: profile a VEX session as it happens, one event at a time.

Run it (from the repo root, after `pip install .`):

    python examples/realtime.py            # instant
    GOAL_REALTIME_DELAY=0.6 python examples/realtime.py   # paced, feels live

The batch `goal_profiles_from_events` needs the whole session up front. A live
host has events trickling in while a student codes and wants a profile the
moment each run finishes. `GoalProfileStream` is that online path: push one
event as it arrives, get the run's profile back, and attach the playground
outcome later when the telemetry shows up.

The last block asserts the streamed runs equal the batch call over the same
events - real time and after-the-fact agree exactly.
"""
import os
import time

from goal_strategy import GoalProfileStream, goal_profiles_from_events


def workspace(drive_mm, with_magnet=False):
    """A tiny Castle Crashers program: drive forward, optionally lower the plow."""
    magnet = ('<next><block type="pg_magnet_set_magnet_state" id="m">'
              '<field name="STATE">boost</field></block></next>') if with_magnet else ''
    return (
        '<xml>'
        '<block type="pg_events_when_started" id="hat"><next>'
        '<block type="pg_drivetrain_drive_for" id="drive">'
        '<field name="DIRECTION">fwd</field><field name="UNITS">mm</field>'
        f'<value name="AMOUNT"><shadow type="math_number"><field name="NUM">{drive_mm}</field></shadow></value>'
        f'{magnet}</block></next></block>'
        '</xml>'
    )


def run(ts, xml, playground='CastleCrasherPlus'):
    return {'event_type': 'runProject', 'ts': ts,
            'content': {'playground': playground, 'project': {'workspace': xml}}}


# One student's session as it unfolds: run a short drive, run it again, then a
# playgroundData telemetry event lands for run 1, then they add the plow and
# drive farther. The outcome for run 1 arrives *after* run 1 was profiled.
T0 = 1_690_000_000.0
EVENTS = [
    run(T0 + 0,   workspace(150)),                       # run 0
    run(T0 + 45,  workspace(300)),                       # run 1
    {'event_type': 'playgroundData', 'ts': T0 + 70,      # telemetry, not a run
     'content': {'playground': 'CasteCrasherPlus', 'parameters': {'weight_cleared': 700}}},
    run(T0 + 90,  workspace(300, with_magnet=True)),     # run 2
    run(T0 + 140, workspace(600, with_magnet=True)),     # run 3
]
# The host pairs that telemetry with the run it belongs to (run 1).
RUN1_OUTCOME = {'playground_data': {'playground': 'CasteCrasherPlus',
                                    'parameters': {'weight_cleared': 700}},
                'end_status': 'completed'}

BAR = '=' * 72
DELAY = float(os.environ.get('GOAL_REALTIME_DELAY', '0'))


def rung(result, goal_name, indicator_name):
    """Pull one indicator's rung out of a run result for a compact live line."""
    prof = result.get('profile')
    if not prof:
        return result['status']
    for goal in prof['goals']:
        if goal['goal'] == goal_name:
            for ind in goal['intent'] + goal['attainment']:
                if ind['name'] == indicator_name:
                    return ind['rung'] if not ind['abstained'] else f"abstain:{ind['abstain_reason']}"
    return '?'


def show(result):
    moved = rung(result, 'playground_engagement', 'robot_moved')
    cleared = rung(result, 'clear_debris_zone', 'weight_cleared')
    outcome = 'outcome' if (result.get('profile') or {}).get('outcome_available') else 'no-outcome'
    print(f"  run {result['index']}: {result['status']:<12} moved={moved:<10} "
          f"weight_cleared={cleared:<16} [{outcome}]  {result['program_id']}")


def main():
    print(BAR)
    print("Live session: pushing events into GoalProfileStream as they arrive")
    print(BAR)

    stream = GoalProfileStream('demo/student/session')
    for event in EVENTS:
        if DELAY:
            time.sleep(DELAY)
        result = stream.push(event)
        if result is None:
            kind = event.get('event_type') if isinstance(event, dict) else 'malformed'
            print(f"  .... {kind} (no run profiled)")
            # This telemetry belongs to run 1 - associate it now that we know.
            if isinstance(event, dict) and event.get('event_type') == 'playgroundData':
                print("       -> associating outcome with run 1 (arrived after the run):")
                show(stream.associate_outcome(1, RUN1_OUTCOME))
            continue
        show(result)

    print("\n" + BAR)
    print("Real-time result == batch result over the same session")
    print(BAR)
    batch = goal_profiles_from_events(
        EVENTS, session_id='demo/student/session',
        outcomes_by_run_index={1: RUN1_OUTCOME})
    assert stream.runs == batch['runs'], "streamed runs diverged from batch!"
    print(f"  {len(stream.runs)} runs, identical to goal_profiles_from_events. OK")

    # Run 1 carried a real outcome once its telemetry was associated.
    assert stream.runs[1]['profile']['outcome_available']
    assert not stream.runs[0]['profile']['outcome_available']
    print("realtime OK")


if __name__ == '__main__':
    main()
