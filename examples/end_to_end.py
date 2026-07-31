"""
End-to-end walkthrough: one VEX student event stream -> everything the packages produce.

Run it (needs `apted`, which LearnerModels requires):

    pip install apted
    python examples/end_to_end.py

It builds a small synthetic session and shows, in order:
  1. LogParserDeltaEngine, the current workspace as a compact LLM-ready prompt
  2. LogParserDeltaEngine.generate_readable_text, the workspace as readable pseudo-code
  3. LearnerModels.compute_run_edit_distances, per-run code-change magnitude
  4. LearnerModels.detect_run_triggers_by_playground, the 4 momentary triggers
  5. LearnerModels.segment_session, the session split into episodes + pauses
  6. LearnerModels.detect_inactive_trigger, the 5th (sustained) trigger, DB-free

Everything below is plain data in, plain data out, no DB, no framework.
"""
import json
from datetime import datetime, timedelta, timezone

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from LogParserDeltaEngine import (
    generate_compact_prompt_from_project, generate_readable_text,
)
from LearnerModels import (
    compute_run_edit_distances, detect_run_triggers_by_playground,
    segment_session, detect_inactive_trigger,
)

# A tiny "program": a hat block driving forward. This is the VEX workspace XML
# that a VEX log carries inside content.project.workspace.
WORKSPACE = (
    '<xml>'
    '  <block type="pg_events_when_started" id="hat">'
    '    <next><block type="pg_drivetrain_drive_for" id="drive">'
    '      <field name="DIRECTION">fwd</field><field name="UNITS">mm</field>'
    '      <value name="AMOUNT"><shadow type="math_number"><field name="NUM">200</field></shadow></value>'
    '    </block></next>'
    '  </block>'
    '</xml>'
)


def make_run(ts, workspace=WORKSPACE, playground="RoverRescue"):
    """One runProject event in the shape both LearnerModels entry points read."""
    return {
        "event_type": "runProject",
        "ts": ts,
        "content": {"eventType": "runProject", "playground": playground,
                    "project": {"workspace": workspace}},
    }


# A session: the student runs the SAME code 7 times (wheel-spinning), with a short
# pause before the last run. Timestamps are epoch seconds, one minute apart.
t0 = 1_690_000_000.0
events = [make_run(t0 + i * 60) for i in range(6)]
events.append(make_run(t0 + 6 * 60 + 400))   # +400s gap -> an INACTIVE_PAUSE episode

BAR = "=" * 72


def main():
    # 1. Current workspace as an LLM prompt (from the latest run's project field).
    latest_project = json.dumps(events[-1]["content"]["project"])
    print(BAR)
    print("1. LogParserDeltaEngine, current workspace prompt")
    print(BAR)
    print(generate_compact_prompt_from_project(latest_project))

    # 2. Same workspace, humanized to pseudo-code.
    print("\n" + BAR)
    print("2. generate_readable_text, readable pseudo-code")
    print(BAR)
    print(generate_readable_text(WORKSPACE))

    # 3. Per-run edit distances. Identical reruns -> 0, first run has no predecessor.
    print("\n" + BAR)
    print("3. compute_run_edit_distances, magnitude per run")
    print(BAR)
    runs = compute_run_edit_distances(events)["runs"]
    for r in runs:
        print(f"  run {r['index']}: edit_distance={r['edit_distance']}  playground={r['playground']}")

    # 4. Momentary triggers. Six identical reruns cross WHEEL_SPIN_ZERO_RUNS (=6).
    print("\n" + BAR)
    print("4. detect_run_triggers_by_playground, momentary triggers")
    print(BAR)
    fires = detect_run_triggers_by_playground(runs)
    if fires:
        for ttype, idx, detail in fires:
            print(f"  {ttype:12} @ run {idx}: {detail['label']}, {detail['value']}")
    else:
        print("  (none fired)")

    # 5. Episodes + pauses. segment_session reads only event_type + ts.
    print("\n" + BAR)
    print("5. segment_session, episodes + pauses")
    print(BAR)
    episodes, pauses = segment_session(events)
    pause_summary = [(p.get("episode_type"), round(p.get("duration", 0))) for p in pauses]
    print(f"  {len(episodes)} episodes: {[e.get('episode_type') for e in episodes]}")
    print(f"  {len(pauses)} pauses:   {pause_summary}   (episode_type, duration_s)")

    # 6. The sustained inactive trigger, pure: YOU pass in the two facts it needs.
    print("\n" + BAR)
    print("6. detect_inactive_trigger, the 5th trigger (DB-free)")
    print(BAR)
    now = datetime.now(timezone.utc)
    last_event = now - timedelta(minutes=10)      # student idle 10 min
    fire = detect_inactive_trigger(last_event, now=now, last_inactive_fire=None)
    print(f"  first fire: {fire}")
    print(f"  just fired again? {detect_inactive_trigger(last_event, now=now, last_inactive_fire=(-1, now))}"
          "  (None, not due for re-alert yet)")

    print("\n" + BAR)
    assert any(t == "wheel_spin" for t, _i, _d in fires), "expected wheel_spin to fire"
    assert fire and fire[0] == "inactive"
    print("end-to-end OK")


if __name__ == "__main__":
    main()
