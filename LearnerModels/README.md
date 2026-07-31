# LearnerModels

Behavioral signals off a student's VEX event stream: how much their code changes per
run, the five intervention triggers, and the session broken into episodes. All pure, no
DB and no framework.

Needs `apted` (`pip install -r requirements.txt`); everything else is stdlib.

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
- `segment_session` looks at only `event_type` + `ts` (it ignores `content`), and hands
  back a `(episodes, pauses)` tuple, both lists of dicts.

## The five triggers

All read off each run's integer `edit_distance`, except `inactive`, which is time-based.

| trigger | rule | kind |
|---|---|---|
| `wheel_spin` | 6+ zero-edit runs in a row (re-running identical code) | momentary |
| `resilience` | a real edit right after 4+ zeros (got unstuck) | momentary |
| `explorer` | one run with edit_distance 13+ (big rewrite) | momentary |
| `iterative` | 6+ runs with edit_distance 1+ (steady editing) | momentary |
| `inactive` | no event for 240s+ | sustained |

The four momentary ones are pure functions of the edit-distance sequence
(`detect_run_triggers` / `detect_run_triggers_by_playground`). Thresholds live in
`constants.py`. Each fire is `(trigger_type, run_index, detail)`; dedupe on `run_index`.

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

So you provide exactly two things: a **read** (the last event time and the last inactive
fire) and a **write** (persist the fire, or resolve the open row on recovery). No table
shape is forced on you here.

The first fire uses `run_index = INACTIVE_RUN_INDEX` (-1), and each re-alert steps it
down (-2, -3, ...), so a UNIQUE(student, session, type, run_index) constraint dedupes
fires while still letting a student who never comes back resurface every
`RE_ALERT_SECONDS`.

## Modules

| module | public | notes |
|---|---|---|
| `run_sequence.py` | `compute_run_edit_distances` | runProject to workspace XML to AST to per-run distance |
| `distance.py` | `cached_edit_distance`, `compute_edit_distance` | APTED tree-edit distance, Blockly cost model, XML-pair memo |
| `ast_builder.py` | `xml_to_block_ast`, `extract_workspace_xml` | Blockly XML into an AST dict |
| `triggers.py` | `detect_run_triggers[_by_playground]`, `is_inactive`, `detect_inactive_trigger` | all 5 triggers (4 momentary + the inactive DB seam above) |
| `episodes.py` | `segment_session`, `segment_episodes` | session into episodes + pauses |
| `humanize.py` | `humanize_text` | workspace XML into readable pseudo-code |
| `constants.py` | thresholds + APTED costs | one place for all the tunable numbers |
