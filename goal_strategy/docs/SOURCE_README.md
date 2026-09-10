# vex_goal_profiles

A small, fast goal-recognition pipeline for VEX VR playgrounds. One student
program in, one **goal profile** out: for each goal declared for the
playground, the evidence that the student *pursued* it (intent) and *attained*
it (attainment), across three channels — authored **code**, **simulation** of
that code, and the real-run **outcome** params.

```python
from vex_goal_profiles import profile

prof = profile(workspace_xml, program_id,
               playground_params={"weight_cleared": 1525, ...},   # optional
               playground="castle_crashers")
```

Pure and stateless; configs load once at first call; median ~5ms per program;
no pandas in the core package. Never raises on malformed input — indicators
**abstain with a named reason** instead of defaulting, and everything the
simulator cannot model degrades with a **named flag**, never silently.

## State of play (2026-08-26)

- **Validation campaign** (`VALIDATION_PLAN.md`): Stages 0–2 **complete** over
  the full Spring26 sample — 7,984 runs / 205 students / 317 sessions. Zero
  crashes; endpoint fidelity 76.6% agree with 99%+ of disagreements
  mechanism-attributed and **3 unexplained runs**; every rung ladder
  reviewer-ruled. Stage 3 (longitudinal analysis prep) is next.
- **Execution model**: the simulator runs the **VR-Seq cooperative
  scheduler** by default — a transliteration of VEX's shipped
  `@vexcode/scratch-vm` fork (confirmed at source), with measured supersession
  semantics. Byte-identical to sequential execution for single-stack programs
  (96% of the sample). History: `docs/archive/`.
- **Sensor models**: all measured or probe-verified — front-eye cone (fov 13°,
  range 124mm), distance sensor (range 2,000mm measured, banded cone), bumper
  radii, down-eye color zones, magnet near-contact attachment (blade 75mm /
  hitch 40mm). Two docs-derived figures fell to probes (eye 1000→124mm,
  distance 3000→2000mm); nothing in the registry now stands unprobed.
- **Suite**: 252 tests, including byte-identity pins on the frozen path
  fixture, corpus regression pins, scheduler identity gates, and per-sensor
  tripwires. A behavior-changing simulator edit breaks pins BY DESIGN —
  follow the §6 protocol (attribute → reviewer sign-off → regenerate).

## The goals (Castle Crashers, v1)

| Goal | Intent | Attainment |
|---|---|---|
| `playground_engagement` | robot movement is acheived | displacement from spawn ≥100mm (outcome; sim fallback flagged) |
| `engage_plow` | magnet state authored (code) + min distance to plow, edges 190/380/570mm from the card tolerance (sim) | magnet-armed attachment clearance vs measured gaps (sim; `not_armed` is a real rung) |
| `clear_debris_zone` | debris-zone coverage, edges .05/.10/.20 (sim) | `weight_cleared`, goal-anchored bands [0.001, 701, 2501, 4000] → none/initial/med/high/advanced (outcome) |
| `remain_on_island` | robot remains within playground boundries (i.e. on the island) | `on_island_observed` (final GPS vs the island polygon) + `on_island_sim` (§6a rule) — observation authoritative, simulation fills abstentions at marked-lower certainty |

`boundary_exceeded` is a critical-failure flag, not a goal; simulation-channel
indicators score the path truncated at the first boundary exit (§6a), with a
card-ruled outcome-override lane for dead-reckoning drift. A fourth
evidence channel — "test", fed by battery scenarios where simulation
evidence is U-gated — joins code/simulation/outcome when Phase B-1 lands
(SENSOR_TESTBATTERY.md §6.0).

## Documentation map

**Living documents:**
- `FINDINGS.md` — the measurement ledger: every probe, ruling, attribution,
  and §6 change, chronological. The evidentiary record.
- `OPEN_ISSUES.md` — the researcher's decision queue. Live issues only;
  resolved ones are one-line ledger entries pointing into FINDINGS.
- `VALIDATION_PLAN.md` — the validation campaign stages and their status.
- `SENSOR_TESTBATTERY.md` — the OI-20 working surface: capability stocktake
  with full-sample coverage, and the test-battery build plan (Phase A
  complete; Phase B = scenario card families, next).
- `PIPELINE_DATAFLOW.md` — **the online implementation sketch** (start here
  if you are building the online path). Stage-by-stage, with 2026-08-26
  currency notes mapping each stage to its working offline analogue.
- `RUBRIC_SCORING.md` — design stub for execution-characteristic levels
  (the battery's second reader; filled at Phase B-2).

**Archive (`docs/archive/`)** — completed process documents kept as the
record behind shipped decisions (the scheduler investigation, build spec,
and probe protocols). See its README.

## Layout

- `src/vex_goal_profiles/` — the package: `profile.py` (the product),
  `indicators.py` (registry), `config.py` (card loading), `timeline.py`
  (rung-transition events), `testcases.py` (sensor test battery harness),
  `ccp_runs.py` (validation-sample loader), and the three sweeps
  (`dryrun.py`, `fidelity_sweep.py`, `rung_sweep.py`) that generate the
  canonical CSVs under `data/ccp_run_dataset/`.
- `vendor/goal_strategy_detector/` — vendored parser + simulator.
  `simulation/simulate_path.py` carries this project's execution model (the
  cooperative scheduler, measured sensor models, hat semantics); its module
  docstring and FINDINGS carry the change history.
- `configs/` — **all entities and thresholds live here, never in Python**:
  playground card, goals card (with per-ladder `provenance` notes), shared
  robot card (measured sensors), capability registry, test-scenario cards.
- `viz/` — two Streamlit apps: `app.py` (dev-corpus review) and
  `longitudinal.py` (the population tool: per-run review + the rung-review
  page). `python3 -m streamlit run viz/longitudinal.py`.
- `data/` — dev corpus (112 sessions) + frozen fixtures + the ccp_run_dataset
  (canonical parquet + the three generated CSVs) + probe screenshots.

## How to extend — YAML only

Adding a playground, goal, rung, or scenario must not touch `src/`:
playground card (geometry, objects, regions, block families, fidelity
thresholds, `simulation:` settings), goals card (indicators, rungs with
`provenance`, flag rules), robot card (measured sensors, block
availability), capability registry, and test-scenario cards. See
`configs/goals/castle_crashers.yaml` for every pattern and
`tests/test_config_driven.py` for the acceptance test that drives the full
pipeline from synthetic YAML alone. Rung edits bump `config_version`
automatically (hashed from the cards).

## Data — never in this repository

**`data/` is confidential student data and is git-ignored in its entirety**,
along with every file derived from it (`profiles.csv`, the generated
CSVs, frozen fixtures, probe screenshots). Collaborators receive the data
through a secure channel, never through git. All identifiers in code,
docs, and data use the anonymized bird-name scheme (CROW/WREN/DOVE/LARK);
no original institution acronyms appear anywhere in the repository.
Consequence for a fresh clone: the corpus-fixture tests (path identity,
regression pins, sweeps) require `data/` locally and will not run without
it; the config/engine/scheduler unit tests run standalone.

## Working protocol

Changes follow the **§6 discipline**: one change → attribution report
(named runs, mechanisms) → reviewer sign-off → regenerate pins/fixtures.
Open modelling questions go to `OPEN_ISSUES.md` (flag-and-queue), never
decided ad hoc. Simulation shortfalls degrade with named flags; the
`high-certainty` masks in the analysis layer key off flags-empty, so flags
are load-bearing — never repurpose one (give new uncertainty its own name).

## Tests & batch tools

```
python -m pytest                                   # 252 tests
python -m vex_goal_profiles.cli --out profiles.csv # dev-corpus review CSV
python -m vex_goal_profiles.dryrun --out ...       # population robustness sweep
python -m vex_goal_profiles.fidelity_sweep --out ...  # endpoint-fidelity taxonomy
python -m vex_goal_profiles.rung_sweep --out ...   # per-run indicator/rung table
```
