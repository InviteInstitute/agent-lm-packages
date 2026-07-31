# agent-lm-packages

Three small, **pure** Python packages that take a VEX (VEXcode VR) student's block
event stream and turn it into things an agent can act on: the current workspace,
behavioral triggers, and (later) a goal/strategy layer. No database, no web framework.
Each package takes plain data in and hands plain data back, so any host (reflecks, the
agent server, a notebook) can drive them.

Each folder is an independent, `pip`-installable package with its own README.

## The three packages

| Folder | What it does | Deps | Status |
|---|---|---|---|
| [`LogParserDeltaEngine/`](LogParserDeltaEngine/) | Replay a log stream (or one project XML) into the current Blockly workspace and render it as LLM-ready pseudo-code. | stdlib | populated |
| [`LearnerModels/`](LearnerModels/) | Per-run edit distances (APTED), the 5 behavioral triggers, and session episodes. | `apted` | populated |
| [`GoalStrategy/`](GoalStrategy/) | The pedagogy layer (goal + feedback strategy). | none yet | empty placeholder |

## How they fit together

```
 VEX event stream (runProject, blockMoved, loadProject, ...)
        |
        |-- LogParserDeltaEngine --> current workspace --> LLM prompt   ("what is the code now?")
        |
        |-- LearnerModels --> edit distance per run --> triggers (5) --> episodes  ("what is the student doing?")
                                                            |
                                                            +--> GoalStrategy (future): pick feedback/goal
```

## Data contract (what you feed in)

Both live packages read the parsed VEX log content, the same shape it already gets
stored in. One event shape drives the whole `LearnerModels` pipeline:

```python
{"event_type": "runProject",       # str,  the VEX eventType
 "content": {...parsed VEX log...}, # dict, carries project.workspace + playground
 "ts": 1690000000.0}               # float epoch seconds (or None)
```

- `LearnerModels.compute_run_edit_distances(events)` reads `runProject` events and their
  `content`. Returns `{"runs": [{"index", "edit_distance", "ts", "playground"}]}`.
- `LearnerModels.segment_session(events)` reads only `event_type` + `ts`. Returns a
  `(episodes, pauses)` tuple.
- `LogParserDeltaEngine.generate_llm_prompt_from_project(project_json_str)` takes the
  `project` field of a single VEX log. Returns the pseudo-code prompt, or `None`.

The host supplies these (an adapter from wherever you keep events). Nothing in here
touches a DB. The one stateful trigger, `inactive`, leaves its two DB touch-points to
the caller, see [`LearnerModels/README.md`](LearnerModels/README.md).

There's a runnable walkthrough in [`examples/end_to_end.py`](examples/end_to_end.py)
that feeds one event stream through both packages.

## Install / test

Each folder is self-contained (relative imports). From this directory:

```bash
pip install apted                       # only LearnerModels needs it
python test_smoke.py                    # fast assertions across the cores
python examples/end_to_end.py           # narrated walkthrough with real output
```
