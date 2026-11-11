# learner_models

This package reads behavioral signals from the VEX event stream of a student:

- How much the code of the student changes per run
- The five intervention triggers
- The session, divided into episodes

The package is pure, with no DB and no framework.

The package needs `apted`. `pip install .` from the repository root installs `apted` automatically.
Everything else is stdlib.

Workspace rendering (compact and readable) is in `log_parser_delta_engine`.

## Pipeline

```python
from learner_models import (
    compute_run_edit_distances, detect_run_triggers_by_playground, segment_session,
)

runs             = compute_run_edit_distances(events)["runs"]  # APTED edit distance per run
fires            = detect_run_triggers_by_playground(runs)     # [(type, run_index, detail), ...]
episodes, pauses = segment_session(events)                     # CODE/RUN/RESET episodes + pauses
```

`events` is one time-ordered list of dicts. Both entry points read the same list:

```python
{"event_type": "runProject",      # str,  the VEX eventType
 "content": {...parsed VEX log...},# dict, carries project.workspace + playground
 "ts": 1690000000.0}              # float epoch seconds (or None)
```

- `compute_run_edit_distances` reads only `runProject` events. It needs their `content`
  (`project.workspace`, `playground`).
- `segment_session` reads only `event_type` and `ts`. It ignores `content`.

### Live hosts: the incremental forms

A host that sees events one at a time should not run the batch calls again over the whole session
on every event. Both batch calls have an incremental twin. The twin gives exactly the same output
for the same events, at a constant cost per event:

```python
from learner_models import RunDistanceStream, SessionSegmenter

runs, segmenter = RunDistanceStream(), SessionSegmenter()
for ev in live_events:
    runs.push(ev)                                # returns the new run dict, or None
    segmenter.push(ev["event_type"], ev["ts"])
runs.runs                                        # == compute_run_edit_distances(events)["runs"]
segmenter.result()                               # == segment_session(events)
segmenter.forget_before(index)                   # optional: keep only a recent window
```

`RunDistanceStream` keeps only the workspace of the previous run. It parses a workspace into an AST
only when it actually computes a distance, so identical re-runs and cached pairs cost a hash.

### Size limits

- The package walks programs without recursion, so a long straight-line program never hits the
  Python recursion limit. (Blockly nests each next block inside the previous block.) APTED itself
  recurses once per tree level, so the package raises the interpreter limit to fit before APTED
  runs.
- APTED is roughly cubic. The package does not compare a pair if either program has more than
  `MAX_DIFF_BLOCKS` (600) blocks. The `edit_distance` of that pair is `None`, like the first run
  after a playground switch. Real runs reach a maximum near 180 blocks.
- Run scoring keeps typed-in values. The value in a shadow (a number, some text, a
  dropdown default) is copied onto the block that owns the slot, so changing drive
  distance 100 to 150 scores 1. A shadow hidden behind a connected block is skipped,
  and an edit to a real literal block still costs 1, not 2.
- Run scoring counts only live code, using the same rules as the renderers
  (`log_parser_delta_engine/liveness.py`). That is every stack under an enabled hat
  (when started, when broadcasted, bumper, timer, optical) plus every My Block
  definition live code calls. Detached blocks, uncalled definitions and disabled hat
  stacks do not affect the distance or the 600-block limit. No live stack means an
  empty scoring tree.
- The general `xml_to_block_ast` parser is unchanged. The batch and live run APIs
  both use `scoring_ast`. Trigger thresholds are unchanged.
- Existing computed scores and downstream triggers must be recomputed to adopt
  this policy. Historical alerts are not rewritten.
- Two runs with identical scored trees return 0 without APTED.
- The distance cache is an LRU of the most recent 50,000 XML pairs.

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

All triggers read the integer `edit_distance` of each run, except `inactive`, which is time-based.

| trigger | rule | kind | constant |
|---|---|---|---|
| `wheel_spin` | 6+ zero-edit runs in a row (re-running identical code) | momentary | `WHEEL_SPIN_ZERO_RUNS` |
| `resilience` | a real edit right after 4+ zeros (got unstuck) | momentary | `RESILIENCE_ZERO_RUNS` |
| `explorer` | one run with edit_distance 13+ (big rewrite) | momentary | `EXPLORER_EDIT_DISTANCE` |
| `iterative` | 6+ runs with edit_distance 1+ (steady editing) | momentary | `ITERATIVE_DEFAULT_THRESHOLD` (per-playground overrides in `ITERATIVE_THRESHOLDS`) |
| `inactive` | no event for 240s+ | sustained | `INACTIVE_TRIGGER_SECONDS` |

The four momentary triggers are pure functions of the edit-distance sequence
(`detect_run_triggers` / `detect_run_triggers_by_playground`). The thresholds are in
`constants.py`. Each fire is `(trigger_type, run_index, detail)`. Dedupe on `run_index`.

`detect_run_triggers_by_playground` divides `runs` into same-playground stretches and runs the
detection on each stretch. The counters reset on a playground switch. Each playground uses its own
`iterative` threshold. The returned `run_index` values stay global.

## The `inactive` DB seam

`inactive` is stateful, because it fires, re-alerts, then resolves over time. It thus cannot be
fully pure like the other triggers. This package keeps the *decision* pure and leaves the two
storage touch-points to the caller:

```python
from learner_models import detect_inactive_trigger

fire = detect_inactive_trigger(
    last_event_ts,            # read from session events: most recent event timestamp
    now=None,                 # defaults to utcnow
    last_inactive_fire=None,  # read from stored triggers: (run_index, fired_at) of last inactive fire, or None
)
if fire:
    ...        # persist it (dedupe on run_index)
else:
    ...        # if the student is active again, close out any open inactive row
```

The caller provides exactly two things:

- A **read**: the last event time and the last inactive fire.
- A **write**: persist the fire, or resolve the open row on recovery.

The package forces no table shape on the caller.

The first fire uses `run_index = INACTIVE_RUN_INDEX` (-1). Each re-alert steps it down (-2, -3, ...)
after `RE_ALERT_SECONDS` (600s). A `UNIQUE(student, session, type, run_index)` constraint thus
dedupes fires, and a student who never comes back still appears again periodically.

## Modules

| module | public | notes |
|---|---|---|
| `run_sequence.py` | `compute_run_edit_distances`, `RunDistanceStream` | runProject to workspace XML to AST to per-run distance (batch and incremental) |
| `distance.py` | `cached_edit_distance`, `compute_edit_distance` | APTED tree-edit distance, VEX cost model, bounded XML-pair memo |
| `ast_builder.py` | `xml_to_block_ast`, `extract_workspace_xml` | VEX XML into an AST dict |
| `triggers.py` | `detect_run_triggers[_by_playground]`, `is_inactive`, `detect_inactive_trigger` | all 5 triggers (4 momentary + the inactive DB seam above) |
| `episodes.py` | `segment_session`, `segment_episodes`, `SessionSegmenter`, `boundary_kind` | session into episodes + pauses (batch and incremental) |
| `switches.py` | `detect_switches` | identity switches (handle re-casing, class-code change) from the live stream |
| `constants.py` | thresholds + APTED costs | one place for all the tunable numbers |
