# Goal recognition

The complete `vex-goal-profiles` project now lives here: goal profiles, Blockly parser and simulator, timelines, sensor battery, batch analysis, review apps, cards, tests, and research documents. The core requires Python 3.10+ and PyYAML. pandas, pyarrow, Streamlit and Plotly are optional.

## Install

From the repository root:

```bash
python -m pip install .
python -m pip install '.[goal-strategy-analysis]'  # parquet tools
python -m pip install '.[goal-strategy-viz]'       # review apps
```

The distribution also installs the existing log parser and learner-model packages. Importing `goal_strategy` does not import those packages or their APTED dependency.

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

`result` is a strict JSON-compatible dictionary with `schema_version`, `pipeline_version`, `program_id`, source `playground`, `status`, `reason`, the full `profile`, optional `timeline` and `battery`, and `diagnostics`. Direct calls have `index=None`; stream calls have a global zero-based run index. Typed APIs remain available:

```python
from goal_strategy.profile import profile
from goal_strategy.timeline import timeline_result
from goal_strategy.testcases import run_battery
from goal_strategy import profile_to_dict
```

XML may have the Blockly namespace or no namespace. Empty/malformed XML abstains on code and simulation while preserving valid outcome fields. Non-finite numeric outcomes abstain before scoring. Missing configuration is a deployment error and raises `ConfigError`.

The parser rejects DTD/entity declarations, XML larger than 2,000,000 characters, more than 20,000 XML elements, or depth above 200. Rejection returns named invalid-XML evidence. These bounds protect parsing; the simulator's statement and simulated-time budgets are not CPU deadlines.

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

The caller supplies **one student's one session's ordered events**. Every `runProject` gets a row, including invalid XML and unsupported playgrounds. The index matches `learner_models`; equal/missing timestamps do not reorder runs. Missing playground names inherit the preceding run's playground. Session ID plus index produces a stable run ID for complete-session prefix replays. Independently renumbered chunks are not supported.

Both `content` and its `project` field accept dictionaries or JSON strings. `goal_profile_from_content(content, *, program_id, ...)` and `goal_profile_from_run_event(event, *, program_id, ...)` support single-run integration. Associated outcomes accept flat dictionaries or nested `{playground, parameters}` payloads, including JSON strings. `end_status` accepts `completed`, `stopped_by_user`, `timeout`, or `error`.

Only Castle Crashers currently has cards. Its canonical name, VEX key `CastleCrasherPlus`, and telemetry spelling `CasteCrasherPlus` resolve through the card. Unsupported playgrounds return `status="unsupported_playground"` and `profile=None`. Conflicting telemetry identity is rejected. A missing first playground is unsupported; only the direct XML API defaults to Castle Crashers.

Outcomes must already belong to the supplied run. Raw `playgroundData` events remain unassociated collection diagnostics. There is no inferred "next telemetry event" pairing. Repeated calls recompute outcome-dependent evidence, so late associated outcomes cannot return stale cached profiles.

## Stream events in real time

`goal_profiles_from_events` needs the whole session at once. When a host watches a student code and wants a profile the moment each run finishes, drive `GoalProfileStream` instead - the same pipeline, online:

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

`push` assigns the same global run index, playground inheritance, stable `program_id` and diagnostics as the batch call - `goal_profiles_from_events` is a thin driver over one stream, so the two cannot diverge. The guarantee that makes mid-session profiling trustworthy: the runs a stream has emitted after *k* events are identical to `goal_profiles_from_events` over those same *k* events. `associate_outcome` recomputes a prior run (never patches it), so a late outcome yields exactly the run the batch call produces with the outcome supplied up front, and never leaves stale evidence. `GoalProfileStream(..., include_timeline=True, include_battery=True)` streams those channels too. There is no server or thread here; any host loop (a websocket, a queue worker, a notebook) drives it. A runnable walkthrough is in [`examples/realtime.py`](../examples/realtime.py) (`GOAL_REALTIME_DELAY=0.6` paces it to feel live).

## Execution and confidence

The profile, timeline and review plots share one nominal execution and scoring scope, including the card's cooperative scheduler, program rejection, boundary truncation and corroborated outcome override. Distinct battery/scatter worlds remain separate simulations.

Execution flags expose capped loops, unknown reporters/statements, invalid expressions, and conditional model behavior. Explicit zero velocity retains the previous fallback and carries `zero_velocity_assumed` pending a VEX measurement. Reachable procedure definitions contribute code and sensing evidence; uncalled definitions remain excluded. Cooperative absolute turns use drivetrain arbitration and procedure recursion tracking belongs to each thread.

Early stops waive endpoint-error matching and annotate outcome evidence with `early_stop_outcome`. `fidelity_verdict` records the shared offline interpretation; unexplained divergence adds `sim_unverified` without changing numerical estimates. Concurrent scatter-world disagreement adds `debris_bracket_divergent`. These are descriptive annotations, not calibrated probabilities or measured goal accuracy.

The implemented five-scenario battery ships and is callable. New B-1 scenario families, automatic fourth-channel composition, B-2 rubric scoring, feedback selection, and automatic raw-event outcome association remain future work.

## Resources and private data

Bundled cards, detector CSV and local Blockly JavaScript ship in the wheel. Configuration precedence is explicit `configs_dir` on typed/internal tools, then `GOAL_STRATEGY_CONFIG_DIR`, legacy `VEX_GOAL_PROFILES_CONFIG_DIR`, then bundled cards. Conditional hats accept `GOAL_STRATEGY_CONDITIONAL_HATS` and its legacy `VEX_GOAL_PROFILES_CONDITIONAL_HATS` alias. Cached configuration is copied per request for isolation; playground alias resolution is cached alongside it, and `load_configs.cache_clear()` drops both. Call it, or restart, after editing external cards.

Core profiling needs no dataset. Offline tools use explicit file paths or `GOAL_STRATEGY_DATA_DIR`. The checkout convenience is `data/goal_strategy/` relative to the working directory. Missing inputs explain how to configure a data directory. Keep the existing structure:

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

Private inputs, generated results and screenshots are excluded from distributions and Git. Do not regenerate or edit frozen research fixtures merely to match changed behavior.

## Batch and review workflows

```bash
export GOAL_STRATEGY_DATA_DIR=/path/to/private/data
python -m goal_strategy.cli --out "$GOAL_STRATEGY_DATA_DIR/profiles.csv"
python -m goal_strategy.dryrun --out "$GOAL_STRATEGY_DATA_DIR/ccp_run_dataset/stage1_dryrun.csv"
python -m goal_strategy.fidelity_sweep --out "$GOAL_STRATEGY_DATA_DIR/ccp_run_dataset/stage2_fidelity.csv"
python -m goal_strategy.rung_sweep --out "$GOAL_STRATEGY_DATA_DIR/ccp_run_dataset/stage2_rungs.csv"
python -m goal_strategy.testcases --out "$GOAL_STRATEGY_DATA_DIR/testcases_report.csv"
python -m streamlit run goal_strategy/viz/app.py
python -m streamlit run goal_strategy/viz/longitudinal.py
```

Use `--help` for playground, config, scheduler and input options. The dry-run Unix alarm is restored after each sweep and is intended for the CLI's main thread. It is not a server request timeout API.

Outside a checkout, locate an installed app before launching:

```bash
python -c 'from importlib.resources import files; print(files("goal_strategy.viz").joinpath("app.py"))'
python -m streamlit run /printed/path/to/app.py
```

Both apps use bundled Blockly assets. Review tables reject stale/missing pipeline or card versions before joining results. Restart the app or clear Streamlit caches after replacing input files.

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

Ordinary test runs skip private-data cases when inputs are absent. The strict flag fails if any required private validation input is missing. Public synthetic fixtures exercise the five batch commands independently.

See [MIGRATION_MAP.md](docs/MIGRATION_MAP.md) for ownership and path changes and [PORT_VALIDATION.md](docs/PORT_VALIDATION.md) for validation results and remaining qualifications. [SOURCE_README.md](docs/SOURCE_README.md), the living research notes, and archived specifications preserve the original research history. Their historical status claims are not a substitute for the port's validation report.
