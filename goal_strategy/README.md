# Goal recognition

This package holds the headless core of the `vex-goal-profiles` project:

- Goal profiles
- The Blockly parser and simulator
- Timelines and the sensor battery
- Purpose-2 rubric scoring and purpose-1 goal rollup
- Batch analysis
- The cards, tests and research documents

The package is agent-facing by design: one student program in, one JSON result out. The human-facing Streamlit review and validation apps and the research maintenance scripts are intentionally NOT part of this package. The core requires Python 3.10+ and PyYAML. pandas and pyarrow are optional, and only the batch and analysis tools use them.

## Install

From the repository root:

```bash
python -m pip install .
python -m pip install '.[goal-strategy-analysis]'  # parquet/batch tools
```

The distribution also installs the existing log parser and learner-model packages. The import of `goal_strategy` does not import those packages or their APTED dependency.

## Profile one program

```python
from goal_strategy import goal_profile

result = goal_profile(
    workspace_xml,
    program_id="student/session/run",
    playground_params={"weight_cleared": 700},
    include_timeline=True,
    include_battery=True,
)
```

`result` is a strict JSON-compatible dictionary with these keys: `schema_version`, `pipeline_version`, `program_id`, source `playground`, `status`, `reason`, the full `profile`, optional `timeline` and `battery`, and `diagnostics`. Direct calls have `index=None`. Stream calls have a global zero-based run index. The typed APIs remain available:

```python
from goal_strategy.profile import profile
from goal_strategy.timeline import timeline_result
from goal_strategy.testcases import run_battery
from goal_strategy import profile_to_dict
```

XML may have the Blockly namespace or no namespace. Empty or malformed XML abstains on code and simulation, and the valid outcome fields stay. Non-finite numeric outcomes abstain before scoring. Missing configuration is a deployment error and raises `ConfigError`.

The parser rejects DTD and entity declarations, and XML larger than 2,000,000 characters, as named invalid-XML evidence. These bounds protect parsing. The statement and simulated-time budgets of the simulator are not CPU deadlines.

## Join event evidence

```python
from goal_strategy import goal_profiles_from_events
from learner_models import compute_run_edit_distances

output = goal_profiles_from_events(
    events,
    session_id="student/session",
    outcomes_by_run_index={
        0: {
            "playground_data": {
                "playground": "CasteCrasherPlus",
                "parameters": {"weight_cleared": 700},
            },
            "end_status": "completed",
        }
    },
)
distances = compute_run_edit_distances(events)["runs"]
joined = [{"goal": goal, "distance": distance}
          for goal, distance in zip(output["runs"], distances)]
```

The caller supplies the ordered events of **one session of one student**. Every `runProject` gets a row, including invalid XML and unsupported playgrounds. The index matches `learner_models`. Equal or missing timestamps do not reorder runs. Missing playground names inherit the playground of the preceding run. Session ID plus index gives a stable run ID for complete-session prefix replays. The package does not support independently renumbered chunks.

Both `content` and its `project` field accept dictionaries or JSON strings. `goal_profile_from_content(content, *, program_id, ...)` and `goal_profile_from_run_event(event, *, program_id, ...)` support single-run integration. Associated outcomes accept flat dictionaries or nested `{playground, parameters}` payloads, including JSON strings. `end_status` accepts `completed`, `stopped_by_user`, `timeout` or `error`.

Only Castle Crashers currently has cards. Its canonical name, VEX key `CastleCrasherPlus` and telemetry spelling `CasteCrasherPlus` all resolve through the card. Unsupported playgrounds return `status="unsupported_playground"` and `profile=None`. The package rejects conflicting telemetry identity. A missing first playground is unsupported. Only the direct XML API defaults to Castle Crashers.

Outcomes must already belong to the supplied run. Raw `playgroundData` events remain unassociated collection diagnostics. The package infers no "next telemetry event" pairing. Repeated calls recompute outcome-dependent evidence, so late associated outcomes cannot return stale cached profiles.

## Stream events in real time

`goal_profiles_from_events` needs the whole session at once. If a host watches a student code and wants a profile the moment each run finishes, use `GoalProfileStream`. It is the same pipeline, online:

```python
from goal_strategy import GoalProfileStream

stream = GoalProfileStream(session_id="student/session")
for event in live_event_source:            # one VEX event at a time, in arrival order
    result = stream.push(event)            # a runProject returns its profiled run
    if result is not None:
        act_on(result)                     # else None (playgroundData / non-run events)

# The playground telemetry for run 1 usually lands after run 1 was profiled:
stream.associate_outcome(1, {"playground_data": {"parameters": {"weight_cleared": 700}},
                             "end_status": "completed"})   # returns the refreshed run
```

`push` assigns the same global run index, playground inheritance, stable `program_id` and diagnostics as the batch call. `goal_profiles_from_events` is a thin driver over one stream, so the two cannot diverge. This guarantee makes mid-session profiling trustworthy: the runs that a stream emits after *k* events are identical to `goal_profiles_from_events` over those same *k* events.

`associate_outcome` recomputes a prior run and never patches it. A late outcome thus gives exactly the run that the batch call produces with the outcome supplied at the start. A late outcome never leaves stale evidence. `GoalProfileStream(..., include_timeline=True, include_battery=True)` also streams those channels.

This package has no server or thread. Any host loop (a websocket, a queue worker, a notebook) can drive the stream. [`examples/realtime.py`](../examples/realtime.py) is a runnable walkthrough. `GOAL_REALTIME_DELAY=0.6` sets its pace to feel live.

A long-lived host that stores each run can call `stream.release(index)` after it stores the run. The stream then does not hold the result and inputs of every run for the whole session. `runs[index]` becomes `None`, and indices stay stable. A later `associate_outcome` for a released run records an `outcome_run_released` diagnostic and does not profile the run again.

## Execution and confidence

The profile, timeline and review plots share one nominal execution and scoring scope. This scope includes the cooperative scheduler of the card, program rejection, boundary truncation and corroborated outcome override. Distinct battery and scatter worlds remain separate simulations.

Execution flags show capped loops, unknown reporters and statements, invalid expressions, and conditional model behavior. Explicit zero velocity keeps the previous fallback and carries `zero_velocity_assumed` pending a VEX measurement. Reachable procedure definitions contribute code and sensing evidence. Uncalled definitions remain excluded. Cooperative absolute turns use drivetrain arbitration. Each thread has its own procedure recursion tracking.

Early stops waive endpoint-error matching and annotate outcome evidence with `early_stop_outcome`. `fidelity_verdict` records the shared offline interpretation. Unexplained divergence adds `sim_unverified` and does not change numerical estimates. Concurrent scatter-world disagreement adds `debris_bracket_divergent`. These annotations are descriptive. They are not calibrated probabilities or measured goal accuracy.

The full 19-scenario, 7-family test battery ships with the package. You can call it through `run_battery` and `include_battery`.

Purpose-2 rubric scoring (the six execution-characteristic dimensions) is also implemented and tested. The opt-in `include_rubric` flag exposes it online. It is PROVISIONAL (`rubric_status = provisional_stage2E`, under active human validation in the source Stage 2E). It is thus off by default. Read its levels as provisional, never as settled per-run feedback.

These items remain future work:

- Automatic fourth-channel composition into the goal rollup
- Feedback selection
- Automatic raw-event outcome association

See [PORT_COMPARISON.md](docs/PORT_COMPARISON.md) for the exact implemented-versus-wired status.

```python
result = goal_profile(workspace_xml, program_id="student/session/run", include_rubric=True)
# result['rubric'] = {'provisional': True, 'status': 'provisional_stage2E',
#                     'dimensions': {'control_structure': {'level': '2', ...}, ...}}
```

## Resources and private data

Bundled cards, detector CSV and local Blockly JavaScript ship in the wheel. The configuration precedence is:

1. Explicit `configs_dir` on typed or internal tools
2. `GOAL_STRATEGY_CONFIG_DIR`
3. Legacy `VEX_GOAL_PROFILES_CONFIG_DIR`
4. Bundled cards

Conditional hats accept `GOAL_STRATEGY_CONDITIONAL_HATS` and its legacy `VEX_GOAL_PROFILES_CONDITIONAL_HATS` alias. Each request gets its own copy of the cached configuration, for isolation. The cache also holds the playground alias resolution, and `load_configs.cache_clear()` drops both. Call that function, or restart, after you edit external cards.

Core profiling needs no dataset. Offline tools use explicit file paths or `GOAL_STRATEGY_DATA_DIR`. For a checkout, the convenience path is `data/goal_strategy/`, relative to the working directory. If an input is missing, the tool explains how to configure a data directory. Keep the existing structure:

```text
<GOAL_STRATEGY_DATA_DIR>/
  final_code_states.parquet
  frozen_paths.parquet
  ccp_run_dataset/
    ccp_runs.parquet
    stage1_dryrun.csv
    stage2_fidelity.csv
    stage2_rungs.csv
```

Distributions and Git exclude private inputs, generated results and screenshots. Do not regenerate or edit frozen research fixtures merely to match changed behavior.

## Batch and review workflows

```bash
export GOAL_STRATEGY_DATA_DIR=/path/to/private/data
python -m goal_strategy.cli --out "$GOAL_STRATEGY_DATA_DIR/profiles.csv"
python -m goal_strategy.dryrun --out "$GOAL_STRATEGY_DATA_DIR/ccp_run_dataset/stage1_dryrun.csv"
python -m goal_strategy.fidelity_sweep --out "$GOAL_STRATEGY_DATA_DIR/ccp_run_dataset/stage2_fidelity.csv"
python -m goal_strategy.rung_sweep --out "$GOAL_STRATEGY_DATA_DIR/ccp_run_dataset/stage2_rungs.csv"
python -m goal_strategy.testcases --out "$GOAL_STRATEGY_DATA_DIR/testcases_report.csv"
```

Use `--help` for playground, config, scheduler and input options. Each sweep restores the dry-run Unix alarm when the sweep ends. The alarm is for the main thread of the CLI. It is not a server request timeout API.

## Validation and research history

```bash
python -m pip install '.[dev]'
python test_smoke.py
python examples/end_to_end.py
python examples/realtime.py
python -m pytest -q -m 'not corpus'
python -m build
# With every confidential input and generated validation table present:
python -m pytest -q -m corpus --require-goal-data
```

Ordinary test runs skip private-data cases when inputs are absent. The strict flag fails if any required private validation input is missing. Public synthetic fixtures test the five batch commands independently.

[EVIDENCE_MODEL.md](docs/EVIDENCE_MODEL.md), the live ECD reference, gives the evidentiary argument end to end: constructs, evidence sources, indicators, thresholds and combination.

These items are deliberately NOT part of this agent-facing package. They are in the source `vex-goal-profiles` project:

- The human-facing Streamlit review and validation apps
- The human-review corpus
- The research maintenance scripts
- The frozen-fixture producer `tools/dump_frozen_paths.py`

Further reading:

- [MIGRATION_MAP.md](docs/MIGRATION_MAP.md): ownership and path changes.
- [PORT_COMPARISON.md](docs/PORT_COMPARISON.md): the implemented-versus-wired status against current source.
- [PORT_VALIDATION.md](docs/PORT_VALIDATION.md): validation results and remaining qualifications.
- [SOURCE_README.md](docs/SOURCE_README.md), the living research notes and archived specifications: the original research history. Their historical status claims are not a substitute for the validation report of the port.
