# LearnerModels

Behavioral signals off a student's VEX event stream: how much their code changes per run,
the five intervention triggers, and the session broken into episodes. All pure, no DB and
no framework.

Needs `apted` (`pip install -r requirements.txt`). Everything else is stdlib.

Workspace rendering (compact + readable) lives in `LogParserDeltaEngine`.

## Pipeline

```python
from LearnerModels import (
    compute_run_edit_distances, detect_run_triggers_by_playground, segment_session,
)

runs             = compute_run_edit_distances(events)["runs"]  # APTED edit distance per run
fires            = detect_run_triggers_by_playground(runs)     # [(type, run_index, detail), ...]
episodes, pauses = segment_session(events)                     # CODE/RUN/RESET episodes + pauses
```

`events` is one time-ordered list of dicts, and both entry points read the same list:

```python
{"event_type": "runProject",      # str,  the VEX eventType
 "content": {...parsed VEX log...},# dict, carries project.workspace + playground
 "ts": 1690000000.0}              # float epoch seconds (or None)
```

- `compute_run_edit_distances` looks at `runProject` events only, and needs their
  `content` (`project.workspace`, `playground`).
- `segment_session` looks at only `event_type` + `ts` (it ignores `content`).

## Output shapes

**`runs`** is a list of dicts, one per `runProject` event:

```python
{"index": int,              # 0-based position among runs
 "edit_distance": int|None, # APTED distance vs previous run (None for first run per playground)
 "ts": float|None,          # the event's timestamp
 "playground": str|None}    # the VEX playground name
```

**`fires`** is a list of `(trigger_type, run_index, detail)` tuples:

```python
("wheel_spin", 6, {"label": "Wheel-spinning", "value": "6 identical reruns"})
#  trigger_type: str   run_index: int (global)   detail: {"label": str, "value": str}
```

**`episodes`** is a list of dicts:

```python
{"episode_type": "CODE"|"RUN"|"RESET",  # kind of episode
 "boundary":     "hard"|"soft",          # hard boundaries block merging
 "start_idx":    int,                    # inclusive index into events
 "end_idx":      int,                    # exclusive index into events
 "start_ts":     float|None,
 "end_ts":       float|None,
 "event_count":  int,
 "soft_indices": [int]}                  # UI events absorbed into this episode
```

**`pauses`** is a list of dicts, sorted by `after_idx`:

```python
{"after_idx":     int,                    # the event index before the gap
 "duration":      float,                  # seconds
 "episode_type":  "INACTIVE_PAUSE"|"POST_RUN_PAUSE",
 "boundary":      "hard"}
```

## The five triggers

All read off each run's integer `edit_distance`, except `inactive`, which is time-based.

| trigger | rule | kind | constant |
|---|---|---|---|
| `wheel_spin` | 6+ zero-edit runs in a row (re-running identical code) | momentary | `WHEEL_SPIN_ZERO_RUNS` |
| `resilience` | a real edit right after 4+ zeros (got unstuck) | momentary | `RESILIENCE_ZERO_RUNS` |
| `explorer` | one run with edit_distance 13+ (big rewrite) | momentary | `EXPLORER_EDIT_DISTANCE` |
| `iterative` | 6+ runs with edit_distance 1+ (steady editing) | momentary | `ITERATIVE_DEFAULT_THRESHOLD` (per-playground overrides in `ITERATIVE_THRESHOLDS`) |
| `inactive` | no event for 240s+ | sustained | `INACTIVE_TRIGGER_SECONDS` |

The four momentary ones are pure functions of the edit-distance sequence
(`detect_run_triggers` / `detect_run_triggers_by_playground`). Thresholds live in
`constants.py`. Each fire is `(trigger_type, run_index, detail)`. Dedupe on `run_index`.

`detect_run_triggers_by_playground` breaks `runs` into same-playground stretches and runs
the detection per stretch (counters reset on a playground switch), using each playground's
own `iterative` threshold. Returned `run_index` values stay global.

## The `inactive` DB seam

`inactive` is stateful (it fires, re-alerts, then resolves over time), so it can't be
fully pure like the others. This package keeps the *decision* pure and leaves the two
storage touch-points to you:

```python
from LearnerModels import detect_inactive_trigger

fire = detect_inactive_trigger(
    last_event_ts,            # you read: when the session's most recent event happened
    now=None,                 # defaults to utcnow
    last_inactive_fire=None,  # you read: (run_index, fired_at) of the last inactive fire, or None
)
if fire:
    ...        # you persist it (dedupe on run_index)
else:
    ...        # if the student is active again, you close out any open inactive row
```

You provide exactly two things: a **read** (the last event time and the last inactive
fire) and a **write** (persist the fire, or resolve the open row on recovery). No table
shape is forced on you.

The first fire uses `run_index = INACTIVE_RUN_INDEX` (-1), and each re-alert steps it down
(-2, -3, ...) after `RE_ALERT_SECONDS` (600s), so a `UNIQUE(student, session, type,
run_index)` constraint dedupes fires while still letting a student who never comes back
resurface periodically.

## Modules

| module | public | notes |
|---|---|---|
| `run_sequence.py` | `compute_run_edit_distances` | runProject to workspace XML to AST to per-run distance |
| `distance.py` | `cached_edit_distance`, `compute_edit_distance` | APTED tree-edit distance, Blockly cost model, XML-pair memo |
| `ast_builder.py` | `xml_to_block_ast`, `extract_workspace_xml` | Blockly XML into an AST dict |
| `triggers.py` | `detect_run_triggers[_by_playground]`, `is_inactive`, `detect_inactive_trigger` | all 5 triggers (4 momentary + the inactive DB seam above) |
| `episodes.py` | `segment_session`, `segment_episodes` | session into episodes + pauses |
| `constants.py` | thresholds + APTED costs | one place for all the tunable numbers |
