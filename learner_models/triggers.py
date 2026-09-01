"""All five intervention triggers in one place.

Four of them are "momentary": they read straight off the per-run edit_distance
sequence and are pure functions with no state and no DB, so they can be re-run any
time and produce the same answer.

  wheel_spin : >= WHEEL_SPIN_ZERO_RUNS zero-edit runs in a row (the student keeps
               running the same code), goes quiet until a real edit re-arms it.
  resilience : a real edit right after >= RESILIENCE_ZERO_RUNS zeros (they got unstuck).
  explorer   : one run with edit_distance >= EXPLORER_EDIT_DISTANCE (a big rewrite).
  iterative  : ITERATIVE_DEFAULT_THRESHOLD runs with edit_distance > 0 (steady editing).

The fifth, inactive, is the odd one out: it's about time, not edit distance, and it's
stateful (fire, re-alert, resolve over time). The decision is kept pure and its two
database touch-points are left to the caller. See the "inactive" section near the bottom
and the README for the full seam.
"""
from datetime import datetime, timezone

from .constants import (
    WHEEL_SPIN_ZERO_RUNS, RESILIENCE_ZERO_RUNS, EXPLORER_EDIT_DISTANCE,
    ITERATIVE_EDIT_MIN, ITERATIVE_DEFAULT_THRESHOLD, ITERATIVE_THRESHOLDS,
    INACTIVE_TRIGGER_SECONDS, RE_ALERT_SECONDS,
    TRIGGER_LABELS as LABELS,
)


# ---------------------------------------------------------------------------
# The four momentary triggers (pure, read off the edit_distance sequence)
# ---------------------------------------------------------------------------
def detect_run_triggers(edit_distances, iterative_threshold=ITERATIVE_DEFAULT_THRESHOLD):
    """One pass over the edit_distance sequence (its first element is None). Returns
    a (trigger_type, run_index, detail) tuple for each fire. It's deterministic,
    so callers can re-run it and dedupe on run_index instead of worrying about
    firing the same thing twice.

      wheel_spin : a run of zeros hits WHEEL_SPIN_ZERO_RUNS, then it stays quiet until
                   a non-zero edit re-arms it, so it doesn't fire every extra rerun.
      resilience : a non-zero edit right after >= RESILIENCE_ZERO_RUNS zeros.
      explorer   : one run with edit_distance >= EXPLORER_EDIT_DISTANCE.
      iterative  : the running count of edits (> ITERATIVE_EDIT_MIN) hits the
                    threshold. A zero-edit run resets the count.
    """
    out = []
    zero_streak = 0
    wheel_armed = True
    iter_count = 0
    iter_armed = True
    for i, ed in enumerate(edit_distances):
        if ed is None:
            continue
        if ed > 0 and zero_streak >= RESILIENCE_ZERO_RUNS:
            out.append(("resilience", i, {"label": LABELS["resilience"],
                                          "value": f"recovered after {zero_streak} reruns"}))
        if ed == 0:
            zero_streak += 1
            if zero_streak >= WHEEL_SPIN_ZERO_RUNS and wheel_armed:
                out.append(("wheel_spin", i, {"label": LABELS["wheel_spin"],
                                              "value": f"{zero_streak} identical reruns"}))
                wheel_armed = False
        else:
            zero_streak = 0
            wheel_armed = True
        if ed >= EXPLORER_EDIT_DISTANCE:
            out.append(("explorer", i, {"label": LABELS["explorer"], "value": f"changed {ed}"}))
        if ed > ITERATIVE_EDIT_MIN:
            iter_count += 1
            if iter_count >= iterative_threshold and iter_armed:
                out.append(("iterative", i, {"label": LABELS["iterative"],
                                             "value": f"{iter_count} steady edits"}))
                iter_armed = False
        if ed == 0:
            iter_count = 0
            iter_armed = True
    return out


def detect_run_triggers_by_playground(runs):
    """The primary entry point. Breaks `runs` into runs of the same
    playground and runs detect_run_triggers on each stretch on its own, using that
    playground's iterative threshold (ITERATIVE_THRESHOLDS, falling back to the
    default). `runs` is what compute_run_edit_distances returned. Returns
    [(trigger_type, global_run_index, detail)].

    Doing it per stretch means all the counters reset when a student jumps to a new
    challenge, which is the desired behavior. The stretch offset is added back so
    run indices stay global."""
    out = []
    i, n = 0, len(runs)
    while i < n:
        pg = runs[i].get("playground")
        j = i
        while j < n and runs[j].get("playground") == pg:
            j += 1
        edit_distances = [r["edit_distance"] for r in runs[i:j]]
        threshold = ITERATIVE_THRESHOLDS.get(pg, ITERATIVE_DEFAULT_THRESHOLD)
        for ttype, local_idx, detail in detect_run_triggers(
            edit_distances, iterative_threshold=threshold
        ):
            out.append((ttype, i + local_idx, detail))
        i = j
    return out


# ---------------------------------------------------------------------------
# The fifth trigger: inactive (time-based, stateful, DB left to the caller)
# ---------------------------------------------------------------------------
# The two spots where inactive would normally hit a database (reading the last event
# time and the last time it fired, then writing the new fire) are pulled out into
# arguments and the return value, so no DB is imported here. Whoever integrates
# this wires those two spots up. There's a full write-up in the README's "inactive DB
# seam" section.

# Sentinel run_index for the first inactive fire (each re-alert decrements it).
INACTIVE_RUN_INDEX = -1


def is_inactive(last_event_ts, now):
    """True if the last event is older than the idle threshold. If last_event_ts is
    None (no events yet), never considered inactive."""
    if last_event_ts is None:
        return False
    return (now - last_event_ts).total_seconds() >= INACTIVE_TRIGGER_SECONDS


def detect_inactive_trigger(last_event_ts, now=None, last_inactive_fire=None):
    """Determine whether an inactive fire is due right now. Pure, no DB.

    Args:
      last_event_ts:      when the session's most recent event happened (aware UTC),
                          or None. Read this from wherever events are stored.
      now:                current time (aware UTC), defaults to utcnow.
      last_inactive_fire: the last inactive fire for this session as
                          (run_index, fired_at), or None if it's never fired. Read
                          this from wherever triggers are stored.

    Returns a (trigger_type, run_index, detail) tuple when something's due, otherwise
    None. When it fires, persist it (dedupe on run_index). When it comes back None
    because the student is active again, that's the cue to close out any open inactive
    row so the next idle streak starts clean.

    How it behaves: it fires once a session has been idle longer than
    INACTIVE_TRIGGER_SECONDS. The first fire gets INACTIVE_RUN_INDEX (-1). If the student
    is STILL idle RE_ALERT_SECONDS later, it fires again with the next index down, so a
    UNIQUE (student, session, type, run_index) constraint dedupes fires while still
    letting the re-alerts through. That way a student who never comes back keeps
    resurfacing instead of getting flagged once and forgotten.
    """
    now = now or datetime.now(timezone.utc)
    if not is_inactive(last_event_ts, now):
        return None  # active, so nothing to fire (closing the old row is on the caller)

    if last_inactive_fire is None:
        run_index = INACTIVE_RUN_INDEX  # first fire
    else:
        last_run_index, last_fired_at = last_inactive_fire
        if (now - last_fired_at).total_seconds() < RE_ALERT_SECONDS:
            return None  # already fired recently, not time to re-alert yet
        run_index = last_run_index - 1  # step the index down for this re-alert

    idle_minutes = int((now - last_event_ts).total_seconds() // 60)
    return ("inactive", run_index,
            {"label": LABELS["inactive"], "value": f"idle {idle_minutes}m"})
