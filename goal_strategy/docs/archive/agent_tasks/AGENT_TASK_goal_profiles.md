# Agent task — build `vex_goal_profiles`, a lightweight goal-recognition pipeline

**Date:** 2026-08-17 · **For:** coding agent · **Reviewer:** Chris

---

## 1. What this is

A small, fast pipeline that takes **one student program** and returns a **goal profile**: for each
goal declared for the playground, what evidence there is that the student *pursued* it and what
evidence there is that they *attained* it.

**One function is the product:**

```python
profile(workspace_xml: str, program_id: str,
        playground_params: dict | None = None,
        playground: str = "castle_crashers") -> GoalProfile
```

Pure, stateless, no batch assumptions, no filesystem access at call time (configs load once at
import). Built and validated on final code states; **designed to run online per run episode**, so it
must be fast (target < 50ms) and must not require a corpus.

## 2. What this is NOT — do not build these

Explicitly out of scope. Do not add them, do not port them, do not leave hooks for them.

- **No segmentation / partitioning.** No spans, no boundaries, no chunks, no phases. Goals are **not
  mutually exclusive**; a program may pursue several, and each is reported independently.
- **No strategy classes.** No `serpentine` / `cyclic` / `direct` / `axis_aligned`. No facets.
- **No HSMM, Viterbi, transitions, durations, or emission tables.**
- **No elicitation or likelihood grids.** v1 is deterministic and rule-based.
- **No `none` class.** Absence of pursuit is read off the goal profile, not modelled as a category.
- **Do not inherit** the design-commitment, open-items, or carry-forward apparatus from either
  source project. Playground and goal *specifications* are inherited — see §5 — the surrounding
  documentation is not.

## 3. Inheritance manifest — exact

Two source projects, both siblings of the new folder. **Nothing in either is modified.**

### Copy verbatim, do not edit

From `VEX_model_tracing/src/goal_strategy_detector/`:

| File | Why |
|---|---|
| `simulation/simulate_path.py` | The simulator. Carries the heading-convention fix, origin recording, unroll caps, and BUG-8…BUG-13. You need `simulate_path`, `slice_sim_result`, `PathStep`, `SimulationResult`, `PlaygroundContext`, `ObjectRef`, `RegionBounds`. **Do not call the traversal-metrics functions** (`compute_region_traversal_metrics`, `compute_axis_progress_metrics`, `compute_path_leg_structure`, `compute_path_straightness`) — and **do not delete them**, deleting breaks byte-identity with the frozen fixture |
| `parsing/parse_blocks.py` | `parse_workspace`, `linearize` |
| `parsing/block_program.py` | `BlockProgram`, `BlockNode` |
| `parsing/block_registry.py` | Block classification |
| `data/blocks.csv` | Per-block-type simulation status. Load-bearing: this marks sensors `ignored` |

From `VEX_model_tracing/`: `tests/test_path_identity.py` and `data/frozen_paths.parquet` (the
tripwire and its fixture), and `playgrounds/castle_crashers.yaml` (see §5).

### Write fresh — small

- **Code-fact extraction** (~50 lines): `magnet_block_present`, `magnet_state`, `drive_count`,
  `turn_count`, `has_movement_block`. **Do not port `code_features.py`** — 20KB and carries open
  defect BUG-13.
- **Config loading** — playground and goal cards → runtime objects. Do not port `load_cards.py`.

### Explicitly leave behind

`code_features.py`, `movement_sequence.py`, `outcome_features.py` (**stale constants** — `_PLOW_Y =
1348` against the spec's `1169`), `structure_analyzer.py`, `load_cards.py`, `load_inputs.py`, all
scorers, all goal/strategy detection, all declarations and evidence cards.

### On the inherited defects — not in scope

**BUG-10 and F-2 do not affect this pipeline.** Both concern *external metric functions* being handed
the wrong origin (spawn instead of slice start). We call none of those functions. The simulator's own
`region_coverage` is swept-path based and computed from the actual previous position inside the
movement loop, so it is origin-correct by construction. **BUG-13** lives in `code_features.py`, which
we are not porting. Do not attempt to fix any of them.

**One real consequence to handle.** `PathStep` is recorded only *after* a block runs, so the spawn
position is not in `path`. `SimulationResult` carries `origin_x` / `origin_y` / `origin_heading`.
**Any scan over the path — boundary checks, minimum distances, the event timeline — must seed from
the origin**, or the state before the first block is invisible.

## 4. Layout

```
vex_goal_profiles/
  README.md
  configs/
    playgrounds/castle_crashers.yaml     # geometry, objects, regions, spawn (copied spec)
    goals/castle_crashers.yaml           # goal cards: indicators, bindings, rung edges
  src/vex_goal_profiles/
    __init__.py
    config.py            # load + validate playground and goal cards
    indicators.py        # the GENERIC indicator registry (§6)
    codefacts.py         # the ~5 code facts
    profile.py           # profile() — the public API
    cli.py               # batch over a parquet, for validation only
  vendor/goal_strategy_detector/         # verbatim copies, never edited
  tests/
  data/frozen_paths.parquet
```

## 5. Extensibility is a hard requirement

**Adding a new playground, or new playground-specific goals, must require YAML only — no changes to
`src/`.** This is the primary architectural constraint; violating it fails the task.

Two card types:

**`configs/playgrounds/<id>.yaml`** — geometry, objects (with `tolerance` / affordance radii),
regions, spawn. Carried from the existing spec, **plus one addition**: a `block_families` map so no
block type is named in Python.

```yaml
block_families:
  magnet:   [pg_magnet_set_magnet_state]
  movement: [pg_drivetrain_drive_for, pg_drivetrain_turn_for, pg_drivetrain_turn_to_heading]
```

**`configs/goals/<id>.yaml`** — which goals exist for that playground, which indicators evidence
them, what entity each is bound to, and every rung edge:

```yaml
playground: castle_crashers
version: 1
goals:
  - id: engage_plow
    label: Engage the plow
    intent:
      - name: magnet_activation_intent
        indicator: code_state_authored
        binding: {block_family: magnet}
        rungs: {labels: [absent, present_not_boost, boost]}
      - name: plow_approach_intent                 # a SECOND intent indicator, other channel
        indicator: min_distance_to_object          # from the registry, §6
        binding: {object: plow}
        rungs:
          direction: lower_is_better               # REQUIRED — see rule 6
          reference: object.tolerance              # resolves to 190 from the playground card
          edges_as_multiples: [1.0, 2.0, 3.0]
          labels: [reached, near, approached, never_close]
    attainment:
      - name: plow_proximity_execution
        indicator: state_active_within_radius
        binding: {object: plow, state: magnet_active}

  - id: clear_debris_zone
    intent:
      - name: debris_zone_coverage
        indicator: region_coverage
        binding: {region: debris_zone}
        rungs:
          direction: higher_is_better
          edges: [0.05, 0.10, 0.20]
          labels: [negligible, some, meaningful, systematic]
    attainment:
      - name: weight_cleared
        indicator: outcome_field
        binding: {field: weight_cleared}
        rungs: {edges: [0.001, 810], labels: [none, some, substantial]}
```

**Rules this imposes.**

1. **No numeric threshold appears in Python.** Every edge is in a goal card.
2. **Indicators are generic and parameterised by binding** — `min_distance_to_object(object=plow)`,
   never `min_distance_to_plow()`. No playground entity name may appear in `src/`.
3. **Prefer `reference` + `edges_as_multiples`** over absolute edges, so a ladder derived from an
   affordance radius ports to a new playground without re-deriving numbers.
4. Adding a genuinely new *kind* of measurement means one new registry function plus a registry
   entry — that is the only case where `src/` changes.
5. `config_version` on every profile is a hash of both cards. Edges change → stored profiles invalidate.
6. **`direction` is required on every rung spec** (`lower_is_better` | `higher_is_better`). Labels are
   listed best-first. Without it, a distance ladder and a coverage ladder are indistinguishable from
   the card. Validation must reject a rung spec missing it.
7. **Block types are named only in `block_families`**, never in Python.

**Known boundary of the abstraction — document, do not try to fix.** `state_active_within_radius`
binds to a *simulator state* (`magnet_active`), which is computed inside `simulate_path.py`. A new
playground can declare new objects, regions, goals, rungs and block families in YAML alone, but
**cannot declare a new simulator state** without simulator work. v1 supports the states the simulator
already exposes. Record this in the README as the one place §5 does not hold.

## 6. Indicator registry — generic, 8 functions

| Registry name | Binding | Returns |
|---|---|---|
| `min_distance_to_object` | `object` | min mm over path (origin-seeded) |
| `region_coverage` | `region` | coverage fraction from `SimulationResult` |
| `state_active_within_radius` | `object`, `state` | bool + min mm while the state is active |
| `code_state_authored` | `block_family` | categorical (e.g. `absent` / `present_not_boost` / `boost`) |
| `code_movement_authored` | — | count of movement blocks |
| `displacement_from_spawn` | `source: outcome\|simulation` | mm |
| `outcome_field` | `field` | numeric from `playground_params` |
| `boundary_exceeded` | — | bool |

These eight cover all of §8. Anything expressible as a combination of them belongs in a goal card,
not in code.

### 6a. Scoring scope — pre-failure truncation. **Applies to every simulation-channel indicator.**

The path is **truncated at, and including, the first step that falls outside
`field_boundary.polygon_mm`.** Everything after the robot leaves the island is simulation fiction —
the attempt is the evidence; what a physics engine does with an off-field robot is not.

- Compute the exit index over the **origin-seeded** path (§3).
- Use `slice_sim_result(full_result, 0, exit_index + 1, context=ctx)` to get a truncated
  `SimulationResult`. **Pass `context`** — without it, per-object distances fall back to whole-run
  minima and bleed across the boundary.
- If no exit occurs, the truncated result is the full result.
- Record the exit step on `GoalProfile` as `boundary_exit_step: int | None` alongside
  `boundary_exceeded`.

**This affects 68 of 119 programs** and is deliberate: 4 programs arm the magnet only *after* leaving
the island, and under this rule they correctly score `not_armed` rather than being credited.

Code-channel and outcome-channel indicators are unaffected — the code is what it is, and the outcome
is from the real run.

## 7. Output contract

```python
@dataclass
class Indicator:
    name: str
    channel: str            # "code" | "simulation" | "outcome"
    value: float | bool | str | None   # CONTINUOUS where one exists — always populated
    rung: str | None
    rung_edges: list                   # echoed for auditability
    abstained: bool
    abstain_reason: str | None
    flags: list[str]

@dataclass
class GoalEvidence:
    goal: str
    intent: list[Indicator]
    attainment: list[Indicator]        # may be EMPTY — a modelling statement, not a gap

@dataclass
class GoalProfile:
    program_id: str
    playground: str
    goals: list[GoalEvidence]
    boundary_exceeded: bool            # critical failure — NOT a goal
    outcome_available: bool
    config_version: str
```

**Intent and attainment — the rule that generates §8.**

- **Intent** may come from any channel: authored code, or simulated behaviour showing the student was
  trying.
- **Attainment** comes from whichever channel can evidence it. The **outcome** channel is the most
  certain. **Simulation is a legitimate attainment channel** where no outcome measure exists — some
  attainment is only observable in simulation — and every simulated attainment indicator carries
  `flags: ["simulated_attainment"]` plus any specific uncertainty flags.
- A goal may declare an **empty** attainment list, and the contract must support it — but only when an
  attainment indicator would **restate its intent measurement**. **No v1 goal uses this**; every goal
  in §8 has both. Keep the capability, do not exercise it.
- Never omit attainment merely because no outcome field exists, and never promote a simulated proxy
  into an attainment slot when it is measuring intent.
- A goal may carry **several intent indicators on different channels** — `engage_plow` has two. They
  are reported side by side and never combined into a score.

**Other contract rules.**

- `value` is populated whenever computable, even when `rung` is None.
- An indicator that cannot be computed **abstains with a reason** — never substitute a default.
- **Every goal in the card is always present in `goals`**, even when every one of its indicators
  abstained. A goal is never dropped from the output.
- When a goal card names an outcome field absent from `playground_params`, abstain with
  `outcome_field_absent`. This is the generic mechanism that handles the 7 wrong-playground sessions
  — **do not special-case them**.
- `GoalProfile` also carries `boundary_exit_step: int | None` (§6a).
- **The core package must not import pandas.** It is needed only by `cli.py`. `profile()` has to stay
  viable in an online request path.

## 8. Goals — v1, Castle Crashers

Anchors from the playground card. **Plow anchor is (163, 1169); engagement radius 190mm.**

### G1 · `playground_engagement`

| | Indicator | Registry fn | Channel | Continuous | Rung |
|---|---|---|---|---|---|
| intent | `movement_authored` | `code_movement_authored` | code | block count | `none` / `authored` |
| attainment | `robot_moved` | `displacement_from_spawn` (source: outcome) | outcome | mm | `stationary` (<100) / `moved` |

Uses `playground_params.gps_x_position` / `gps_y_position` — the real run. Falls back to simulated net
displacement when params are absent; set `flags: ["simulated_fallback", "simulated_attainment"]`.

### G2 · `engage_plow`

Navigation to the plow is folded in here as a **second intent indicator**, not a separate goal.

| | Indicator | Registry fn | Channel | Continuous | Rung |
|---|---|---|---|---|---|
| intent | `magnet_activation_intent` | `code_state_authored` | code | — | `absent` / `present_not_boost` / `boost` |
| intent | `plow_approach_intent` | `min_distance_to_object` | simulation | min mm | `reached` (≤1×) / `near` (≤2×) / `approached` (≤3×) / `never_close` |
| attainment | `plow_proximity_execution` | `state_active_within_radius` | simulation | min mm while armed | `not_armed` / `armed_never_close` / `armed_within_radius` |

**Why folded, not separate** (measured on the corpus, recorded so it is not relitigated): at the
`reached` rung min-distance is near-redundant with the magnet flag — 43 of 46 who reached the plow
authored a magnet, P(reached\|magnet)=0.61 vs P(reached\|no magnet)=0.06. At the middle rungs it
measures sweeping rather than navigation: the 15 no-magnet programs that came within 570mm have
median debris coverage **0.183** against a corpus median of 0.108, i.e. they are sweepers passing
nearby, which the playground card's `approach_path_caveat` predicts. Gated by magnet-authoring the
ladder is clean and informative — among the 70 magnet-authors: 43 reached / 12 near / 2 approached /
**13 never_close** (declared intent, no progress).

**Flag required:** when `plow_approach_intent` reaches `near` or better while
`magnet_activation_intent == absent`, set `flags: ["no_declared_intent"]` — the proximity is
uncorroborated by code and is more likely sweep spillover.

`magnet_active` is a **persistent state** set at the boost block. Attainment is
`∃ step t : armed_t ∧ dist_t ≤ 190` — a conjunction over time, **not** a property of the activation
step. Carries `simulated_attainment` always.

**Geometry flags — required.** Several steps may satisfy `armed_t ∧ dist_t ≤ 190`. Evaluate the flag
over **all** qualifying steps, with this precedence — physically, if the robot passes through a
bad position and later reaches a good one, engagement is still plausible:

1. **Any** qualifying step with `1169 ≤ y ≤ 1230` (direct attraction) **or** `y > 1320` (rotation
   assisted) → described, **no flag**.
2. Otherwise, if **all** qualifying steps have `1250 ≤ y ≤ 1320` → `flags: ["stuck_zone"]` — the card
   says the prong blocks attachment there.
3. Otherwise → `flags: ["geometry_undescribed"]` (i.e. `y < 1169`, or the undeclared gap
   `1230 < y < 1250`).

Zone bounds come from `objects.plow.plow_engagement.zones` in the playground card, **never from
code**.

**Why this matters, and why it is not pinned.** In the design analysis 19 of 43 engagements landed in
undescribed geometry — mostly *below* the plow, since spawn is south of it and approach-from-below
was never probed. That is a gap in the **playground spec**, not a property of this pipeline, and the
rule above is a provisional reading of an admittedly incomplete physics model. **Report the counts in
`FINDINGS.md`; do not assert them in a test** (§9).

### G3 · `clear_debris_zone`

| | Indicator | Registry fn | Channel | Continuous | Rung |
|---|---|---|---|---|---|
| intent | `debris_zone_coverage` | `region_coverage` | simulation | coverage fraction | `negligible` (<0.05) / `some` / `meaningful` / `systematic` (≥0.20) |
| attainment | `weight_cleared` | `outcome_field` | outcome | kg | `none` (0) / `some` (>0) / `substantial` (≥810) |

**Coverage is intent, not attainment** — a simulated behavioural measure that the student was trying
to clear the zone. `weight_cleared` is the real outcome and the only attainment claim here. Abstain
on `weight_cleared` when params are absent; **do not** promote coverage into the attainment slot.

Coverage edges are the T-3 ladder, carried as recorded.

### G4 · Not a goal — `boundary_exceeded`

A **boolean critical-failure flag** on `GoalProfile`, outside the goal list. True if any path step
(origin-seeded) falls outside `field_boundary.polygon_mm`. Fires on 68/119. Do not build a ladder or
a survival fraction for it.

## 9. Tests

| Test | Asserts |
|---|---|
| `test_path_identity.py` | Copied simulator reproduces `frozen_paths.parquet` within 1e-9mm on all 119. **Must pass before anything else is built** |
| `test_config_driven.py` | **A synthetic second playground + goal card produces a valid profile with zero changes to `src/`.** This is the acceptance test for §5 |
| `test_indicators.py` | Per registry function: each rung reachable; abstention fires with the right reason; continuous value present whenever computable; origin seeding covered |
| `test_profile_contract.py` | `engage_plow` carries **two** intent indicators on different channels; an empty `attainment` list is representable even though no v1 goal uses one; `config_version` changes when a card changes; `profile()` never raises on malformed XML; works with `playground_params=None` |
| `test_corpus_regression.py` | **Pins against verified counts over the 119** (see below) |
| Performance | `profile()` median < 50ms over the 119 |

**Regression pins.** These were computed and verified during design. They catch silent drift when
code or rungs change. If a pin fails, **stop and report** — do not adjust the pin.

| Quantity | Expected |
|---|---|
| `boundary_exceeded == True` | **68** |
| `plow_approach_intent == reached` (≤190mm), full path | **46** |
| `plow_proximity_execution == armed_within_radius`, full path | **43** |
| `magnet_activation_intent == boost` | **70** |
| sessions abstaining with `outcome_field_absent` | **7** |

**Pin only invariants, never findings.** Every quantity above is a property of the **parser, the
simulator, and the corpus** — if one moves, something drifted and you want to know. The geometry
flag counts (`geometry_undescribed`, `stuck_zone`) are **deliberately not pinned**: they are
properties of a *provisional classification rule* over zone bounds the playground card admits it does
not fully describe. If they move, that is information, not a regression. **Report them in
`FINDINGS.md` instead.**

**Note:** the first three are **full-path** figures from the design analysis. Under §6a truncation the
pipeline's numbers will be *lower*. Compute both in this test, pin the full-path values against the
table, and **record the truncated values in `FINDINGS.md`** as the new baseline — that delta is
itself a finding worth seeing.

## 10. Deliverables

1. Package, configs, tests.
2. `cli.py` producing a **flat CSV over the 119** — one row per program, one column per indicator
   value **and** one per rung. This is the review artifact; make it readable.
3. `README.md` ≤ 2 pages: what it is, the four goals, **how to add a playground**, how to change a rung.
4. `FINDINGS.md` recording without resolving: `geometry_undescribed` count, `stuck_zone` count, the
   truncated-vs-full-path deltas from §9, and any program where `profile()` abstained and why.

## 11. Out of scope for v1 — do not build

`timeline.py` — a per-step scan emitting goal intent/attainment/failure **events** with their `step`,
`block_id` and `block_type`. Planned for a later pass, gated on a green v1, and specified separately
when it happens. **Do not build it, do not stub it, and remove it from the §4 layout.** It is listed
here only so it is not mistaken for an oversight.

## 12. Constraints on you, the agent

- **Do not modify** anything in `VEX_model_tracing/` or `goal_strategy_detection/`.
- **Do not add** goals, indicators, or rungs beyond §8. Propose in `FINDINGS.md` instead.
- **No thresholds and no playground entity names in Python.**
- **Do not port** the excluded modules in §3, or attempt to fix BUG-10 / F-2 / BUG-13.
- If an indicator can't be computed as specified, **abstain and record it** — do not substitute a proxy.
- Stop and ask if §8 is ambiguous rather than choosing.

## 13. Open items — record, do not solve

- 7 of the 119 sessions carry a **different playground's** params (`trash_collected` / `coral_damaged`).
  Detect and abstain on the outcome channel; do not drop the row.
- Rung edges throughout are inherited or first-pass; `config_version` exists so revising them is cheap.
