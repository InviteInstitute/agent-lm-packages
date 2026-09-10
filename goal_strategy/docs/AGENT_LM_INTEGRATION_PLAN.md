# Port the complete goal-recognition project into `agent-lm-packages/goal_strategy`

Implementation status, 2026-09-10: the complete project is now ported into this folder. This document preserves the implementation specification and original observations. See [PORT_VALIDATION.md](PORT_VALIDATION.md) for completed checks, semantic changes and pending private-corpus qualification.

**Destination:** `/var/www/agent-lm-packages/goal_strategy/`.

**Scope:** move the complete maintained project into that folder: profiler, parser, simulator, timeline, sensor battery, offline tools, review apps and assets, configuration, tests, and research/design documentation. Keep confidential datasets and generated results outside version control. Optional dependencies keep the runtime lightweight without excluding analysis tools from the port.

This replaces the earlier online-only plan. The earlier claims that config relocation was the only substantive change, that all inputs were crash-safe, and that a block budget guaranteed sub-50-ms latency are not supported by the inspected implementation.

## 1. Verified starting point

| Item | Observed state |
|---|---|
| Source checkout | `/home/maharsh/working/vex-goal-profiles`, commit `2ad1770b3d1c6606fa456a015d505ff091810f7f` |
| Target checkout | `/var/www/agent-lm-packages`, commit `c341a2a225aafe0a96eb538556fd9f63b2301d26` |
| Destination folder | `goal_strategy/README.md` only; still says “Need to get it from Caitlin!” |
| Installed target packages | `log_parser_delta_engine` and `learner_models`; `goal_strategy` is not listed in packaging metadata |
| Target Python declaration | `>=3.9`; source declaration is `>=3.10` |
| Target dependencies | `apted>=1.0` as a base dependency; extras `log-parser` and `learner-models` |
| Target tests | 40 functions in root `test_smoke.py`; direct runner and pytest-compatible functions |
| Target verification in this review | `test_smoke.py`: 40 passed; `examples/end_to_end.py`: completed successfully in the temporary review environment |
| Source inventory | 13 package Python modules, 9 YAML cards, 27 test modules, 8 visualization Python modules, vendored engine and UI assets |
| Source verification from the deep dive | 206 passed, 2 skipped, 45 dependent on absent private corpus/fixtures; 253 total tests collected |

The source audit and reproductions are in [REPOSITORY_DEEP_DIVE.md](REPOSITORY_DEEP_DIVE.md). The documented full-population fidelity statistics were not independently rerun because private data is absent.

### Actual target contracts

- `learner_models/run_sequence.py` enumerates **every** `runProject` in input order and returns a zero-based global `index`. Triggers refer to that index. Filtering unsupported goal playgrounds before indexing would attach evidence to the wrong runs.
- That code accepts `content` as a dict or JSON string. `project` can independently be a dict or JSON string. Missing playground names inherit the previous effective playground within the supplied stream.
- `learner_models/ast_builder.py` and the workspace renderers accept XML without a namespace. Their ASTs serve edit-distance and presentation purposes, not simulation.
- `log_parser_delta_engine.smart_delta_engine.process_log()` currently expects JSON strings for `content` and `blockEventData`, despite broader wording in its README. A dict-content load was ignored in a diagnostic check; the JSON-string equivalent loaded two blocks. Profile the run snapshot, not a reconstruction obtained by assuming this replay API accepts the same envelope as every other function.
- `playgroundData` is listed as a soft performance event in `learner_models/constants.py`. Neither target package provides a run/outcome pairing function, a required run-ID field, or realistic telemetry fixtures. Episode segmentation is not an outcome-association algorithm. It treats `playgroundReset` as soft, while resets still matter to telemetry association.
- `examples/end_to_end.py` uses an unnamespaced workspace and defaults to `RoverRescue`. The source currently has a goal card only for Castle Crashers.

**New integration reproduction:** the target example's 200-mm-drive XML parses as zero blocks in the source and yields `stationary`, without abstention. Adding the Blockly namespace yields three parsed blocks and 200 mm of movement. Namespace compatibility is a required port fix, not just documentation work.

## 2. Decisions for this port

1. **One destination package:** use `goal_strategy`, with the vendored engine under `goal_strategy.detector`. All goal-related code and project documentation live under this folder. Maintain one simulator implementation in the target.
2. **Full project ownership:** move all implemented features, including battery and offline/review tools. Importing `goal_strategy` must not import pandas, pyarrow, Streamlit, Plotly, or APTED.
3. **Preserve sibling behavior:** keep the other packages' public exports, distance AST, trigger thresholds, run indices, and original smoke tests. Join evidence at the run index; the profiler does not decide when an intervention fires.
4. **Retain the goal simulation IR:** the target's distance AST drops shadow inputs by default and cannot replace named value/statement slots and procedure metadata. Adopt input conventions without conflating these representations.
5. **Separate relocation from semantic changes:** establish a relocatable baseline, then repair defects in attributable changes. Temporary parity with a known defect is a migration checkpoint, not release acceptance.
6. **Propose Python `>=3.10` as the common floor**, matching the source declaration. Record this target compatibility change and check downstream interpreter versions before release. If an actual consumer needs 3.9, explicitly backport and test before declaring 3.9 support; a successful 3.12 run is insufficient.
7. **Port implemented features and preserve future plans:** the current battery and five scenario cards move now. Unbuilt B-1 scenario families, automatic fourth-channel composition, and B-2 rubric scoring remain labeled future research work. A complete port does not require inventing those results.
8. **Target becomes authoritative after acceptance:** retain the source checkout/baseline for comparison and rollback. Do not delete its Git history or maintain two ongoing implementations.

## 3. Complete source-to-destination map

| Source | Destination | Work |
|---|---|---|
| `src/vex_goal_profiles/__init__.py` | `goal_strategy/__init__.py` | Define documented integration exports; avoid heavy imports |
| `profile.py`, `indicators.py`, `config.py`, `codefacts.py`, `timeline.py` | Same filenames under `goal_strategy/` | Rewrite imports; share execution/scoring; fix contract defects |
| `testcases.py` | `goal_strategy/testcases.py` | Port complete battery and CLI; align execution and input handling |
| `ccp_runs.py`, `creation_order.py` | Same filenames under `goal_strategy/` | Retain loaders and historical ordering analysis; parameterize data paths |
| `cli.py`, `dryrun.py`, `fidelity_sweep.py`, `rung_sweep.py` | Same filenames under `goal_strategy/` | Preserve batch entry points under new module prefix |
| `vendor/goal_strategy_detector/**` | `goal_strategy/detector/**` | Include parser, simulator, helpers, `data/blocks.csv`, provenance and notices |
| `configs/**` | `goal_strategy/configs/**` | Include all nine cards |
| `viz/**` | `goal_strategy/viz/**` | Include all eight Python modules, VEX definitions/corrections, local Blockly runtime and dependency notes |
| `tests/**` | `goal_strategy/tests/**` | Include all 27 test modules and helpers; distinguish standalone/private-data cases |
| Root living documents | `goal_strategy/docs/` | FINDINGS, OPEN_ISSUES, VALIDATION_PLAN, PIPELINE_DATAFLOW, SENSOR_TESTBATTERY, RUBRIC_SCORING |
| `docs/archive/**` | `goal_strategy/docs/archive/**` | Preserve historical specifications and agent briefs |
| `design_instructions/**` | `goal_strategy/design_instructions/**` | Preserve both design workbooks as repository assets |
| Source `README.md` | `goal_strategy/docs/SOURCE_README.md` | Preserve source overview; write current package README separately |
| This plan and `REPOSITORY_DEEP_DIVE.md` | `goal_strategy/docs/` | Include explicitly; both are currently untracked source documents |
| Source metadata/ignore rules | Target root `pyproject.toml`, `.gitignore`, distribution manifest | Merge relevant rules; do not overwrite target files wholesale |
| Confidential `data/`, generated CSVs, path fixtures, screenshots | External data root, optionally target `data/goal_strategy/` locally | Exclude from Git, wheel and source distribution; do not fabricate absent inputs |

Do not copy `.git/`, caches, environments, build output, or egg-info. Preserve historical text as history; update current instructions and add `goal_strategy/docs/MIGRATION_MAP.md` for old paths and commands. Do not manually alter files marked generated or any CHANGELOG.

Proposed layout:

```text
agent-lm-packages/
  pyproject.toml
  .gitignore
  MANIFEST.in
  README.md
  test_smoke.py
  conftest.py                      # register the optional corpus validation flag
  examples/end_to_end.py
  goal_strategy/
    __init__.py
    README.md
    requirements.txt
    profile.py
    indicators.py
    config.py
    codefacts.py
    timeline.py
    testcases.py
    ccp_runs.py
    creation_order.py
    cli.py
    dryrun.py
    fidelity_sweep.py
    rung_sweep.py
    execution.py                   # small shared execution/scoring implementation
    adapter.py                     # normalization and integration APIs
    serialize.py                   # plain-data output and canonicalization
    detector/
      __init__.py
      parsing/
      simulation/
      data/blocks.csv
    configs/
      capabilities.yaml
      playgrounds/
      goals/
      robot/
      testcases/castle_crashers/
    viz/
      __init__.py
      app.py
      longitudinal.py
      data.py
      plots.py
      rung_review.py
      walkthrough.py
      workspace.py
      blockly.py
      requirements.txt
      vex_blocks.js
      vex_blocks_corrections.js
      vendor/blockly_local.js
    tests/
      __init__.py
      conftest.py
      helpers.py
      test_*.py
    docs/
      MIGRATION_MAP.md
      SOURCE_README.md
      AGENT_LM_INTEGRATION_PLAN.md
      REPOSITORY_DEEP_DIVE.md
      ...living documents...
      archive/
    design_instructions/
  data/goal_strategy/               # optional local location, Git-ignored
```

## 4. Package and dependency changes

Keep offline module names at package root to minimize avoidable import churn. Their optional imports stay inside the tools, not in `goal_strategy.__init__`. Replace `goal_strategy_detector` imports with `goal_strategy.detector` or appropriate relative imports.

Extend the target's explicit package list and preserve the existing extras:

```toml
[project]
requires-python = ">=3.10"
dependencies = ["apted>=1.0", "pyyaml"]

[project.optional-dependencies]
log-parser = []
learner-models = ["apted>=1.0"]
goal-strategy = ["pyyaml"]
goal-strategy-analysis = ["pandas", "pyarrow"]
goal-strategy-viz = ["pandas", "pyarrow", "streamlit>=1.50", "plotly>=6"]
dev = ["pytest", "build", "pandas", "pyarrow", "streamlit>=1.50", "plotly>=6"]

[tool.setuptools]
packages = [
  "log_parser_delta_engine",
  "learner_models",
  "goal_strategy",
  "goal_strategy.detector",
  "goal_strategy.detector.parsing",
  "goal_strategy.detector.simulation",
  "goal_strategy.viz",
]

[tool.setuptools.package-data]
log_parser_delta_engine = ["vex_blocks.json"]
goal_strategy = [
  "README.md",
  "configs/*.yaml",
  "configs/playgrounds/*.yaml",
  "configs/goals/*.yaml",
  "configs/robot/*.yaml",
  "configs/testcases/*/*.yaml",
]
"goal_strategy.detector" = ["data/*.csv"]
"goal_strategy.viz" = ["*.js", "vendor/*.js"]
```

This is a metadata fragment, not a replacement for the full project section. Keep the name and existing metadata; select/document a release version when accepted. Repeating PyYAML in the goal extra follows the target's existing learner-models convention. `pip install .` installs all three core packages. `goal_strategy/requirements.txt` lists PyYAML; root metadata remains the installation authority.

Tests, workbooks, and research docs belong in the repository and source distribution, not the runtime wheel. Include them explicitly in `MANIFEST.in` while excluding private data and generated outputs. Verify the built wheel/sdist contents; directory copying and editable installation are insufficient.

A wheel must contain all nine YAML cards, detector CSV, VEX JS assets/local Blockly runtime, and both apps' Python code. A clean base-only interpreter must profile synthetic XML without importing optional analysis/UI libraries or importing the sibling packages.

## 5. One execution and scoring path

Introduce a small internal artifact containing the parsed program, resolved config/options, executable reachability, code facts, full simulation or rejection reason, and execution diagnostics. Outcome-dependent scoring derives the scoring scope, including boundary truncation and corroborated override.

Reuse these artifacts across profile indicators, timeline, visualization, and offline exports. Battery scenarios intentionally run different worlds: reuse safe immutable inputs but isolate mutable scenario state. Resolve scheduler and other execution settings once and consistently, including scenario baselines.

Place shared logic in `execution.py` or existing modules where natural. Retain plain functions and dataclasses. This concrete consistency problem justifies shared execution, not a new framework, plugin system, service, or persistent cache.

### Required repairs and acceptance cases

Start each repair with its end-user/API reproduction. Audit numbers refer to [REPOSITORY_DEEP_DIVE.md](REPOSITORY_DEEP_DIVE.md).

| Work item | Required result |
|---|---|
| Namespace compatibility, new target finding | Unnamespaced and equivalent Blockly-namespaced 200-mm programs both yield 200 mm; preserve mutation attributes and connected-block-over-shadow semantics |
| Shared execution, audit 1 | Concurrent 1000/400 drives give consistent 400-mm profile, timeline and plot; rejected Switch code cannot acquire simulated events elsewhere |
| Finite telemetry, audit 2 | NaN/infinite weight or GPS abstains with a named invalid-input reason; no highest-rung fallthrough; strict JSON succeeds |
| Expression/input robustness, audit 3 | Random/round infinity, exponential overflow, malformed or over-deep/large XML yield named partial evidence rather than crashes or silently invented zero |
| Absolute-turn scheduling, audit 4 | Relative and absolute turns use the same measured drivetrain arbitration/timing rules |
| Procedure semantics, audit 5 | Reachable procedure bodies count in code facts, capability scans and battery eligibility; uncalled definitions do not become intent; recursion tracking is per call chain/thread |
| Installed resources, audit 6 | Non-editable wheel works outside both checkouts, including cards, CSV and JS assets |
| Uncertainty propagation, audit 7 | Loop caps, unknown reporters and unsupported blocks remain visible publicly; broad family matches cannot silently certify unknown implementations |
| Explicit zero, audit 8 | Repeat zero executes zero iterations; separately establish zero-velocity semantics before changing that behavior |
| Continuous timeline geometry, audit 9 | Passing through a target mid-drive gives the same reached rung in profile and timeline, attributed to the containing command |
| Battery contracts, audit 10 | Empty XML returns an explicit ineligible/invalid report; unknown check definitions fail config validation; scenario results retain execution uncertainty |
| Canonical output, audit 11 | Flag/diagnostic order is stable across hash seeds; preserve meaningful goal, rung and event ordering |
| UI provenance, audit 12 | Modeled/deferred hats are described from actual execution metadata rather than forced/unfaithful type-based labels |

Configuration defects remain explicit developer/deployment errors. Missing package cards must not become evidence that a student failed. Malformed code preserves valid outcome evidence; one bad telemetry field does not discard other channels.

Fix namespace compatibility in the goal parser, not by changing target examples to hide the mismatch. Do not mutate caller-owned content or XML.

### Confidence beyond mechanical parity

The offline fidelity sweep has interpretation not fully exposed by `profile()`. Factor and test the already ruled policies from `PIPELINE_DATAFLOW.md`: early-stop handling, unexplained-fidelity degradation and applicable debris bracketing. Document exactly which ship; do not advertise an uncomputed confidence tier.

Preserve each existing flag's meaning, including `simulated_attainment`; give new uncertainty distinct names/scopes. Use card thresholds in shared fidelity logic, replacing the sweep's hardcoded 71.2-mm comparison with its existing card entry. Version fidelity/rung exports so the UI cannot silently join stale CSVs against current cards.

The B-1 fourth-channel composition and B-2 rubric remain separate research extensions. The complete current battery moves and is explicitly callable; migration does not transform it into a newly validated achievement score.

## 6. Public APIs and target integration

### Typed modules and plain-data entry points

Preserve typed source APIs at their new module paths:

```python
from goal_strategy.profile import profile           # GoalProfile dataclass
from goal_strategy.timeline import timeline_result
from goal_strategy.testcases import run_battery
```

Expose plain-data convenience functions at package root. Proposed signatures:

```python
goal_profile(workspace_xml, program_id, playground_params=None,
             playground="castle_crashers", *,
             include_timeline=False, include_battery=False)

goal_profile_from_content(content, *, program_id, playground=None,
                          playground_data=None, end_status=None,
                          include_timeline=False, include_battery=False)

goal_profile_from_run_event(event, *, program_id, playground_data=None,
                            end_status=None, include_timeline=False,
                            include_battery=False)

goal_profiles_from_events(events, *, session_id,
                          outcomes_by_run_index=None,
                          include_timeline=False, include_battery=False)
```

These return serializable dicts. Expose `profile_to_dict()` for typed callers. Timeline/battery computation is opt-in on aggregate calls, but the corresponding modules always ship. Offline callers can use typed APIs directly.

The adapter needs lightweight dict/JSON/project extraction, with compatibility tests against the siblings' accepted valid shapes. Implement this small normalization locally rather than importing `learner_models` just for its extractor or depending on the log parser's private helper. Avoid APTED imports and a global helper refactor as prerequisites.

### Output envelope

Define and test one envelope for the root APIs:

```python
{
    "schema_version": 1,
    "pipeline_version": "<released implementation version>",
    "program_id": "<caller-supplied or session-scoped run id>",
    "index": 0,                  # global run index for stream calls; None otherwise
    "event_index": 3,            # original event-list position, or None
    "ts": 1690000000.0,          # run-start timestamp, or None
    "playground": "CastleCrasherPlus",  # effective source name when available
    "status": "profiled",       # profiled | invalid_input | unsupported_playground
    "reason": None,
    "profile": {                # complete serialized GoalProfile
        "program_id": "<same id>",
        "playground": "castle_crashers",
        "config_version": "<card hash>",
        "goals": [],            # illustrative; supported profiles contain every card goal
        # ...all remaining GoalProfile fields, not a lossy subset...
    },
    "timeline": None,           # requested: events, post_exit_events, boundary metadata
    "battery": None,            # requested: eligibility, scenarios, checks, diagnostics
    "diagnostics": [],          # e.g. inferred playground or rejected telemetry
}
```

Supported playground plus invalid XML returns `invalid_input` with a partial profile: code/simulation abstain and valid outcomes remain usable. Unsupported playgrounds return an explicit envelope with `profile=None`, not a dropped stream row. Missing telemetry alone is normal, not invalid input.

Retain all current boundary, override, orphan, fabricated-motion, channel, rung-edge, flag, abstention and fidelity fields. Validate numeric evidence before scoring; replacing a final NaN with null must not conceal an invalid achievement rung. Verify `json.dumps(result, allow_nan=False)` and fresh-process reproducibility.

`schema_version` describes structure, `pipeline_version` released semantics, and `config_version` cards. Preserve the current card hash for pure relocation. Battery results also need a version/hash covering selected scenario cards and options. Paths/import names must not enter semantic hashes.

### Run identity and playground routing

The stream API consumes one student's one session's ordered events. Enumerate every `runProject`, including invalid/unsupported runs, and return `{"runs": [...], "diagnostics": [...]}` with the same indices as `compute_run_edit_distances(events)["runs"]`. Collection diagnostics identify unassociated events by their original event index without assigning them to a run. Preserve input order with equal/missing timestamps; do not re-sort or deduplicate identical code.

Construct an unambiguous ID from caller-supplied session ID plus global index, or accept a verified host ID through associated metadata. Keep event index separate. Replaying a complete session prefix preserves IDs; independently renumbered chunks are not the input contract.

Match missing-playground inheritance to the target and annotate inference. Map `CastleCrasherPlus`, telemetry self-ID `CasteCrasherPlus`, and canonical `castle_crashers` through card/config aliases. Do not default `RoverRescue`, `CoralReefRescue`, or an unidentified first run to Castle Crashers. Reject conflicting telemetry playground identity before using that outcome.

The direct typed XML API may retain its existing Castle Crashers default. The stream adapter resolves actual event identity. Document those different contracts explicitly.

### Outcome association: explicit inputs, no invented event ownership

The direct APIs accept **already associated** `playground_data` and `end_status`. The stream API accepts an optional mapping by its global run index:

```python
outcomes_by_run_index = {
    0: {
        "playground_data": {
            "playground": "CasteCrasherPlus",
            "parameters": {"weight_cleared": 700},
        },
        "end_status": "completed",
        # Optional verified host program_id and outcome timestamp/provenance.
    }
}
```

This is a new proposed adapter argument, not an existing target raw-event schema. It provides a direct integration path without inventing timing semantics. With no mapping, deliver code/simulation evidence and outcome abstentions. Report unassociated performance events as metadata rather than guessing ownership.

Accept associated dict/JSON payloads, either flat parameters or nested `{playground, parameters}`. `ccp_runs.unwrap_params()` currently accepts only strings and can raise on invalid JSON: retain its normalization intent, not its implementation unchanged. Neither repo establishes `content.playgroundData` as a complete live envelope contract.

Automatic association from raw events is a follow-on capability once representative host fixtures establish identity/lifecycle rules. Cover multiple updates, `projectEnd` followed by telemetry, `playgroundReset`, load/new project, next run, playground changes, equal timestamps and missing IDs. Never attach an unkeyed late outcome across a reset/new-run boundary solely because it is the next performance event.

This does not omit an existing feature: the source loader consumes a pre-paired run dataset. Port that loader and support explicit host association. Automatic raw-event pairing was an unverified addition in the earlier plan.

### Joining the three packages

Extend `examples/end_to_end.py` with a Castle Crashers stream using the same unnamespaced XML style, an associated outcome, a missing-outcome run and an unsupported-playground run. Join distances, triggers and goal envelopes by `index` in the example.

Keep the existing Rover example working, showing unsupported goal recognition until a Rover card exists. Use standalone compact/readable renderers on as-run XML. The migration adds no LLM calls, feedback-selection rules, DB, queue or service endpoint.

## 7. Configuration, data paths and cache behavior

### Packaged resources

Read bundled YAML through `importlib.resources.files("goal_strategy")`; use corresponding resources for detector CSV and JS. Read text through the resource interface rather than assuming a persistent filesystem directory. If a consumer requires a path, keep materialization alive for the entire operation.

Configuration precedence: explicit `configs_dir`, then `GOAL_STRATEGY_CONFIG_DIR`, then legacy `VEX_GOAL_PROFILES_CONFIG_DIR`, then packaged cards. Retain the existing conditional-hat environment setting as a compatibility alias and resolve execution settings once. Timeline, battery, UI and tools must agree.

Cache configuration by the resolved source, not just playground while reading environment settings inside a cached function. Do not expose mutable cached state that scenarios alter. External card updates need explicit invalidation or restart; a version hash is not file watching. Document this.

### Private data and generated output

Use explicit file/data-root arguments first, then `GOAL_STRATEGY_DATA_DIR`. The documented checkout convenience is `<target>/data/goal_strategy/`; do not infer it by walking `__file__.parents`. If no data root is supplied to a corpus tool, explain how to provide one. Core profiling never requires private data.

Keep current relative structure under that root: `final_code_states.parquet`, `frozen_paths.parquet`, `ccp_run_dataset/ccp_runs.parquet`, generated sweep CSVs and review annotations. Accept explicit output paths or write under the external data root, never `site-packages`.

Merge ignores for `/data/`, generated root CSVs/reports, local screenshots and build output. Root-anchor `/data/` so the public detector CSV stays tracked. Allowlist source-distribution contents instead of recursively packaging every CSV/image.

All source tests move. Some frozen-fixture tests reference `tools/dump_frozen_paths.py`, which is absent from this checkout. Obtain or reconstruct that operational dependency before promising fixture regeneration; do not manually edit generated pins to make tests pass.

### Result caching

Do not add a global result cache in the initial port. If measurements justify caching later, separate simulation from outcome-dependent scoring. Simulation keys include XML, playground/cards, released implementation, resolved execution options and scenario settings. Whole-profile keys also include outcomes, stop metadata and requested features.

Identical code can have different outcomes. A run-ID/code-only cache must not return stale evidence after telemetry arrives. The random reporter already uses a deterministic midpoint; global RNG seeding is not needed. Cross-process flag order does need canonicalization.

## 8. Offline tools and review apps

Preserve these module entry points:

```bash
python -m goal_strategy.cli --parquet /path/to/data/final_code_states.parquet --out /path/to/data/profiles.csv
python -m goal_strategy.dryrun --out /path/to/data/ccp_run_dataset/stage1_dryrun.csv
python -m goal_strategy.fidelity_sweep --out /path/to/data/ccp_run_dataset/stage2_fidelity.csv
python -m goal_strategy.rung_sweep --out /path/to/data/ccp_run_dataset/stage2_rungs.csv
python -m goal_strategy.testcases --parquet /path/to/data/final_code_states.parquet --out /path/to/data/testcases_report.csv
```

Data-root-dependent commands assume `GOAL_STRATEGY_DATA_DIR` is set. Preserve current controls and document explicit data-root inputs. Forward playground/configuration settings through loaders and profilers; the source CLI/rung sweep currently misses some forwarding. Keep Unix signal timeout behavior documented within the dry-run CLI and restore handlers afterward; it is not an online request timeout API.

For both review apps:

- Replace bare `import data`, `import workspace`, etc. with package-qualified imports. Remove `sys.path` injection and generic module-name collisions.
- Put Streamlit execution behind `main()` and a script guard. Importing helpers must not launch an app or load a corpus; source `longitudinal.py` currently calls `main()` at import time.
- Use shared runtime data/configuration resolution and execution artifacts. Preserve the dev-corpus, longitudinal, fidelity-queue and rung-review workflows.
- Use the local Blockly runtime throughout. `workspace.py` is local; `walkthrough.py` and `blockly.py` still reference a CDN. Include all definitions, corrections and unknown-block rendering.
- Preserve diff overlays and XML/JSON escaping; render student-authored strings as text or escape HTML interpolation. Display unknown diagnostic flags instead of silently filtering them through a fixed presentation list.
- Inspect plot/summary agreement, scrubbing, procedures, sensor-hat labels, missing-data messaging and narrow/wide layouts in a browser with synthetic data, then private examples when available.

From the target checkout, after installing the visualization extra:

```bash
python -m streamlit run goal_strategy/viz/app.py
python -m streamlit run goal_strategy/viz/longitudinal.py
```

Also test the scripts by their installed package paths outside the checkout and document how to locate them. No separate web deployment is required for the port.

## 9. Implementation phases and validation gates

### Phase 0: inventory and baseline

Record commits, file inventory, untracked plan/audit docs and the target's 40 passing tests. Preserve the source baseline. Capture synthetic profiles, paths, timelines and battery outputs with explicit settings, including known inconsistencies. Start repairs with the API reproductions in section 5.

Record missing private fixtures and producer scripts. Their absence limits corpus qualification, not progress on relocation, packaging or standalone checks.

**Exit:** inventory and baseline are reviewable; existing target behavior is pinned.

### Phase 1: complete relocation and packaging

Populate the entire tree in section 3, including battery, tools, assets, tests and docs. Rewrite imports, merge metadata, package resources and parameterize private paths. Preserve card content/hash and explicit execution modes.

Compare source/target in separate processes so imports cannot contaminate parity checks. No hidden dependency or symlink back to the source. Build/inspect wheel and sdist and run installed code outside either checkout. Keep distinct source defaults as baseline observations before unifying them in Phase 2.

**Exit:** every asset has a destination and the complete project has a usable target home. Mechanical differences are explained; this is not the correctness release.

### Phase 2: consistency and reviewed repairs

Implement shared execution/scoring and section 5's required fixes. Prefer one attributed semantic change at a time. Run affected synthetic end-to-end tests, then private path/rung/corpus comparisons when available. Do not regenerate fixtures merely because they changed.

Follow the source's attribution and reviewer sign-off discipline before accepting changed research baselines. Continue independent port work while private-data runs or modeling rulings are pending.

**Exit:** no known contradictory profile/timeline/UI execution; robustness and uncertainty tests pass; every behavior change has an explicit validation status.

### Phase 3: adapters and sibling integration

Implement APIs/envelope, namespace handling, aliases, run-index preservation and associated-outcome input. Cover dict/JSON shapes, missing/invalid code, missing/invalid/conflicting telemetry, inherited/unsupported playgrounds, null/equal timestamps, repeated runs and updated outcomes.

Test index joins including unsupported runs between supported runs. Extend examples and READMEs while preserving the smoke runner and all 40 original tests.

**Exit:** target-format events yield plain-data goal evidence without changing learner-model signals or guessing telemetry ownership.

### Phase 4: batch and UI qualification

Exercise all five CLI modules with synthetic parquet/outcome data and temporary output directories. Verify playground and version consistency from loader through CSV to UI; reject or visibly identify stale/mixed artifacts.

Run both apps in a browser, inspect UI and network requests, then exercise private review workflows when available. Fix encountered UI defects and test failures. Keep battery computation opt-in while its resources, reports, CLI and tests remain fully available.

**Exit:** destination analysis/review workflows work without the source checkout or runtime CDN dependencies.

### Phase 5: release and ownership

Complete standalone tests, smoke/example, wheel/resource checks and supported-Python checks at the declared minimum and deployment interpreter. This inspection ran Python 3.12 only.

Complete private-corpus attribution before claiming population equivalence or accepting changed fixtures. If inputs remain absent, distinguish complete transfer from pending corpus qualification; do not call it fully validated. Record measured latency, research limitations, versions, commands and Python-floor impact. Make the target authoritative and retain the baseline for rollback.

**Exit:** implemented workflows and assets are present, validation status is explicit and consumers have documented migration contracts.

### Test organization

Keep root `test_smoke.py` in discovery; do not replace it with goal-only `testpaths`. Use package-relative helper imports or importlib collection, not source/vendor/viz `sys.path` injection.

Register a `corpus` marker in root pytest configuration and a strict opt-in `--require-goal-data` option in root `conftest.py`, so pytest recognizes the option before descending into goal tests. Keep corpus fixtures and input checks under `goal_strategy/tests/`. Missing private files can skip marked cases in a normal checkout, but explicit full-data validation must fail if required inputs are absent. Preserve all assertions and numerical tolerances. Synthetic engine, adapter, batch and UI-helper checks must not depend on confidential files.

Planned commands after implementation:

```bash
python -m pip install '.[dev]'
python test_smoke.py
python examples/end_to_end.py
python -m pytest -q -m 'not corpus'
python -m build
```

In a separate clean environment, install the built wheel and check import origins, resources, profiling and strict JSON from a temporary directory. Repeat visualization resource checks with the UI extra. Editable-install tests do not replace installed-wheel tests.

With `GOAL_STRATEGY_DATA_DIR` pointing at the private dataset:

```bash
python -m pytest -q -m corpus --require-goal-data
```

The marker and option are proposed work, not existing source features. Use the current fixture protocol for tiny cross-platform floating-point differences. Track semantic changes separately from deliberate canonical ordering.

## 10. Performance targets and operational limits

The source review observed approximately 3.1, 30.8 and 537.5 ms for one, two and three nested repeat-20 loops around a 50-mm drive. These are individual synthetic timings, not population percentiles. The older approximately 5-ms median is a documented source-corpus result, not a new-package benchmark.

The 50,000-statement budget limits statements, not elapsed CPU time. Reporter traversal, geometry sampling, sensor marching, parser depth and scenario multiplication add work. `time_budget_s` models program duration, not request timeout.

For fixed cards and ordinary expressions, work is broadly proportional to execution and sampled geometry. General cost also depends on XML/reporter size, objects/sensors, travel sampling and scenarios. Do not claim `O(L)` alone for arbitrary input or universally bound path points by statements under concurrent motion slicing. Timeline coverage searches can repeat prefix scans.

Benchmark cold/warm execution separately, then profile-only, profile-plus-timeline and batteries. Report median, p95, p99, maximum, input sizes and versions on realistic fixtures. Bound parser input and recursion/work explicitly. Choose host concurrency and actual CPU deadlines from measurements; a median test does not establish a tail SLA.

First remove duplicate simulation through shared execution. Use the host's existing worker/request facilities if cancellation or background processing is needed. The port does not add a queue, scheduler service or cache service.

## 11. Completion checklist

- [ ] Every source module, current scenario, review asset, test and maintained document has a destination under `goal_strategy`; private data remains external.
- [ ] No runtime dependency on the source checkout or old top-level package/engine names.
- [ ] Target's existing 40 smoke tests and original example behavior remain intact.
- [ ] Target-format unnamespaced XML works, including shadow inputs and procedures.
- [ ] Profile, timeline, UI, exports and scenarios use consistent policies and preserve uncertainty.
- [ ] All required reproductions have fixes/tests or explicit unresolved qualifications; known correctness gaps prevent a fully validated release claim.
- [ ] Plain-data output is strict JSON and reproducible, with stable global run indices and explicit unsupported playgrounds.
- [ ] Outcome association is explicit; no undocumented raw-event contract is assumed.
- [ ] Wheel has all cards/CSV/JS; wheel and sdist exclude private data and generated results.
- [ ] Both review apps and every batch tool work with external paths in the destination.
- [ ] Standalone and private-corpus results are reported separately; fixture changes follow attribution/sign-off.
- [ ] Python and latency claims match actual tests.
- [ ] Documentation accurately describes goal recognition and tools; unbuilt rubric/feedback selection remains future work.

## 12. Inputs still needed for release qualification

These do not block this plan or the mechanical port:

- Private corpus, frozen fixtures and missing regeneration tools for population attribution and research acceptance.
- Actual downstream interpreter versions for the proposed `>=3.10` floor.
- Representative host lifecycle fixtures if automatic raw-telemetry association is requested. Explicit associated-outcome APIs do not depend on that future capability.
- Reviewer rulings for modeling changes whose true VEX behavior is not established, such as zero velocity; preserve named uncertainty until measured.

Naming and scope are resolved here: the destination is `goal_strategy`, the detector is nested, and the full existing project moves. The work remaining is implementation and evidence-based qualification.
