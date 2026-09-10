# Agent task 2 — goal event timeline + review viz

**Date:** 2026-08-17 · **For:** coding agent · **Reviewer:** Chris
**Gate: CLEARED. Tasks 1 and 3 are complete, the suite is green (2026-08-18), and
`frozen_paths.parquet` was regenerated after Part A sign-off. Start here.**

**Read `OPEN_ISSUES.md` first.** It is the researcher's decision queue — nine entries — and this viz
exists to make those decisions inspectable. **§B4 maps each one to what it must show.** Where §B4 and
the generic view specs disagree, §B4 wins.

Two deliverables, in order. **A must be finished and tested before B begins** — B renders A's output.

---

## A · `timeline.py` — goal events with code and path positions

### A1. What it is

A per-step scan of the simulated path that emits the **moments** at which each goal's evidence
changes, each stamped with the block that caused it.

```python
timeline(workspace_xml: str, program_id: str,
         playground_params: dict | None = None,
         playground: str = "castle_crashers") -> list[GoalEvent]
```

**This is not segmentation.** There are no spans, no intervals, no exclusivity, and nothing decides
what happens *between* events. Two goals may fire on the same step. It is an ordered event list and
nothing more. Do not add span, phase, or partition concepts.

### A2. The generating principle — an event is a rung transition

Do not hand-write event conditions per goal. **Every event is a rung change on an indicator already
declared in the goal card.** This means the timeline needs no new configuration and stays correct
automatically when rungs are edited.

```python
@dataclass
class GoalEvent:
    step: int                  # path step index (origin-seeded, see profile §3)
    block_id: str | None       # None only for the origin pseudo-step
    block_type: str | None
    goal: str
    indicator: str
    kind: str                  # "intent" | "attainment" | "failure"
    from_rung: str | None
    to_rung: str
    value: float | bool | str  # the indicator's value at this step
    flags: list[str]
```

`kind` is `intent` or `attainment` according to which list the indicator sits in on the goal card.
`failure` is reserved for the boundary exit (§A4).

### A3. Computing it efficiently — do not brute-force

Naïve per-step re-evaluation of `region_coverage` means one `slice_sim_result` call per step. The
longest program in the corpus is 641 steps; that is unacceptable for an online path.

**Exploit monotonicity.** Almost every indicator here is monotone in path prefix length:

| Indicator | Monotone? | How to find crossings |
|---|---|---|
| `min_distance_to_object` | yes — running minimum, only improves | single forward pass, O(n) |
| `region_coverage` | yes — cells only accumulate | **binary-search** the first step crossing each rung edge: ~log₂(n) slices per edge, ≈15 slices total |
| `state_active_within_radius` | yes — latches once true | single forward pass, O(n) |
| code-channel indicators | constant | one event at step 0 if the rung is not the lowest |
| outcome-channel indicators | constant | one event at the final step |

Assert monotonicity in a test. If a future indicator is non-monotone, it must declare so and fall
back to the per-step scan.

**Target: `timeline()` median < 100ms over the 119.**

### A4. Truncation and failure

Honour §6a of task 1 — the scored path is truncated at and including the first boundary exit.

- Emit a `failure` event at the exit step: `goal: "__boundary__"`, `indicator: "boundary_exceeded"`,
  `to_rung: "exceeded"`.
- **Also compute the timeline over the untruncated path** and return it separately as
  `post_exit_events: list[GoalEvent]`. Do not merge the two lists. This is what lets a reviewer see
  that a program "engaged the plow" only in post-exit fiction — the four magnet-after-exit programs
  are the case in point.

### A5. Tests

- Each rung transition of each indicator reachable by a hand-built program.
- Events are ordered by `step`, then by goal-card order for ties.
- Every event carries a `block_id` except the origin pseudo-step.
- Monotonicity assertion (§A3).
- Binary-search coverage crossings agree with a brute-force per-step scan on 10 programs.
- Regression: `WREN-C094` produces a boundary `failure` event, and its magnet-armed event precedes its
  plow-reached event (arm-then-approach); `WREN-C050` has the reverse order (approach-then-arm).

---

## B · The review viz

### B1. What already exists — copy it, do not rebuild it

**Most of the hard work is done, in `VEX_model_tracing/src/vex_model_tracing/viz/`.**

| File | What it gives you | Disposition |
|---|---|---|
| `blockly.py` + `vex_blocks.js` (17KB) | **Renders real VEX blocks from `workspace_xml`** via the Blockly CDN. `vex_blocks.js` defines the `pg_*` block types; `stubUnknownBlocks` renders unrecognised types as generic labelled blocks rather than crashing | **Copy.** This is the single most valuable asset here — do not attempt to rebuild block rendering |
| `plots.py` → `path_figure()` | Plotly playground plot: field boundary polygon, region rectangles, object markers with tolerance circles, spawn star, path with per-step hover carrying `step`/`block_type`/`block_id` | **Copy and adapt** — it is already ~90% of the high-level path view |
| `plots.py` → `band_strip()` | A value positioned against its rung edges | **Copy** — reuse for continuous indicator values |
| `plots.py` → `cohort_figure()` | Strip plot of a value across the cohort with edges as cut lines | **Copy** for the cohort view |
| `app.py` | Streamlit multi-page shell, `st.cache_data` patterns, layout idioms | **Reference, do not copy wholesale** — it is built around the old node/declaration API which no longer exists |

Do not copy `decode_views.py` — it is decode/partition machinery, which is out of scope.

### B2. Two code representations — decoupled on purpose

`blockly.py` renders read-only with **no highlight mechanism**, and highlighting inside a Blockly
canvas is where the effort would go. **Do not fight this.** Split the two jobs:

| | Purpose | Highlighting |
|---|---|---|
| **Blockly canvas** | Visual context — what the student's program *looks like* | None required. Rendered once, never re-rendered |
| **Block-tree list** | The steppable, highlightable representation | **This is where highlighting and event markers live** |

**Block-tree list spec.** One row per authored block, in program order:

- Derived from `linearize()` plus a small recursive depth walk over `BlockNode.children` / `.next`
  (~20 lines). **Do not port `structure_analyzer.py`** — you need depth, nothing more.
- Indented by nesting depth.

**Stacks must never be flattened into one list.** A Blockly workspace can hold several independent
stacks, and that structure is obvious on the canvas but invisible in a flat list. **Group the rows by
stack, with an explicit header per group:**

```
▸ Stack 1 · when started            (executed 1st)
▸ Stack 2 · when started            (executed 2nd)
▸ Unattached blocks · never executed        ← from BlockProgram.orphan_stacks
```

Read the groups from `BlockProgram.event_handler_stacks` and `BlockProgram.orphan_stacks` — both are
already on the parsed program. Mark orphan groups clearly as never-run.

**Execution ordinals changed in task 3 — do not label receiver stacks with a top-level ordinal.**
`pg_events_when_broadcasted` stacks are now **excluded from the top-level loop** and execute *inline
at their broadcast site*. A receiver is not "executed 3rd"; it runs **inside** another stack, at a
specific step. Show the relationship:

```
▸ Stack 1 · when started                              (executed 1st)
    …
    broadcast "Chash"  ──┐
▸ Stack 2 · when I receive "Chash"   ←────────────────┘  runs inline here
▸ Stack 3 · when bumper pressed        FORCED · trigger_unsimulated
▸ Unattached blocks · never executed
```

**Stack headers carry their trust flags**, read from the profile: `trigger_unfaithful` (eye hats, 7
programs), `trigger_unsimulated` (bumper hats, 2), `concurrent_stacks_unverified` (WREN-C008),
`broadcast_concurrency_approximated`, `broadcast_recursion_suppressed`. A reviewer must be able to
see *which stack* is untrusted, not just that the program is.

**This is not an edge case.** Measured on the 119: **44 programs (37%) have more than one top-level
stack** (21 with two, 14 with three, 6 with four, 3 with five); **42 have orphan blocks**; and **10
have more than one *event handler* stack** — 7 with two, 2 with three, 1 with four. Flattening would
silently misrepresent more than a third of the corpus.
- Each row shows a human label plus **key fields as set**, read from `BlockNode.fields`:
  `drive forward 500 mm` · `turn right 90°` · `repeat 3` · `set magnet boost`.
- A gutter column for event markers, and the current step's `block_id` highlighted.
- **Show every authored block**, dimming any that produced no path step. This is a feature, not
  noise: it surfaces orphaned and never-executed blocks directly — 35% of programs have them, at a
  median 27% of the program.

**Many-to-one, and say so in the UI.** The list is the *authored* sequence; the path is the
*executed* sequence. A loop-body row highlights repeatedly across iterations. When the current block
has executed more than once, show an iteration counter (`iteration 3 of 10`).

**Still build the walkthrough as a single self-contained HTML component.** Serialise into one page:
`workspace_xml`, the block-tree rows, the path as `[{step, x, y, block_id, block_type}]`, the event
list, playground geometry, and the goal profile. All stepping is client-side, so there is no
Streamlit rerun per step and the Blockly canvas renders exactly once. The payload is small — the
longest program is 641 steps.

Highlighting the list is plain HTML you control. Since Blockly is in the same page, you *may* also
call `ws.highlightBlock(block_id)` — treat it as **best-effort; drop it if it proves finicky.** The
list is the contract.

### B3. Three views

**View 1 · Walkthrough** *(code, path, goals side by side)*

```
┌───────────────┬──────────────────┬──────────────┐
│ block tree    │  path (SVG)      │  goals       │
│ • indented    │  full path grey  │  rung chips  │
│ • fields set  │  prefix coloured │  live values │
│ • HIGHLIGHTED │  marker at step  │  flags       │
│ • event gutter│  event markers   │              │
├───────────────┴──────────────────┴──────────────┤
│  ▸ Blockly canvas (collapsible, static context)  │
├──────────────────────────────────────────────────┤
│  event strip — click an event to jump             │
│  scrubber ◀ ▶ ────────●────────────  step 23      │
└──────────────────────────────────────────────────┘
```

Three columns by default; **the Blockly canvas sits in a collapsible panel below** rather than
competing for width. It is context, not the working surface — but it is **not optional**, and it must
stay reachable for every program.

**Default it to expanded whenever the program has more than one top-level stack** (44 of 119). Spatial
stack layout is exactly what the canvas shows better than any list, and those are the programs where
a reviewer most needs to see it. Show the stack count in the panel header so it is obvious when
collapsed: `▸ Blockly workspace — 3 stacks (1 handler, 2 unattached)`.

- **Show the untruncated path.** Steps after the boundary exit are **greyed** on the path, the block
  tree and the event strip, and post-exit events are visually distinct (§A4). A goal "attained" only
  in post-exit fiction must be obvious at a glance — this is a requirement, not a nicety.
- **Mark fabricated steps distinctly** (`SimulationResult.fabricated_steps`, new in task 3) — the
  200mm continuous-drive fallback, the 90° turn fallback, the 50mm `wait_until` probes. 26 programs
  have them and one program has 500 of them. A reviewer watching the robot travel on an invented
  constant must be able to see that it is invented. Serves **OI-3**.
- **Plot the real final GPS position** as its own marker alongside the simulated final position, with
  a connecting line when they differ. Field names come from the playground card
  (`outcome_metrics.final_gps_position`). Serves **OI-2** — 36 programs disagree on whether the robot
  ended off the island, and this makes each one legible in one glance.
- **Draw the plow engagement zones** from `objects.plow.plow_engagement.zones` as banded overlays —
  `direct_attraction`, `stuck_zone`, `rotation_assisted`, **and the undeclared 1230–1250 gap and
  below-plow region as a distinctly-styled "undescribed" band**. Mark every qualifying step (armed ∧
  within tolerance). Card-driven, no hardcoding. Serves **OI-4**.
- Clicking an event jumps to its step and highlights its block-tree row. That is the code-to-goal
  mapping.
- Prev/next controls for **both** step and event.

**View 2 · Program summary** *(high-level, no stepping)*

`path_figure()` with event markers annotated, the goal profile as a table (indicator · channel ·
value · rung · flags), the event list, and the boundary-exit step. One screen, no interaction — for
scanning programs quickly.

**Program selection, shared by Views 1 and 2.** A selector with **substring search over program id**
(carry the pattern from the old `app.py`), plus filters on rung values and flags so a program found
in View 3 can be reached directly.

**View 3 · Cohort — two distinct jobs, build both, label them separately**

**(a) Program finder.** A filterable table: one row per program, one column per indicator rung, plus
flags and `boundary_exceeded`. Every row **links into View 1** at that program. Include the
**near-cut-point list** from the old `app.py` — programs whose continuous value sits within ±δ of a
rung edge. That list is the fastest route to the programs where a rung decision actually bites.

**(b) Rung calibration.** Per indicator: the continuous value distribution with **rung edges drawn as
cut lines** (reuse `cohort_figure()`), plus counts per rung. This is the view for judging whether an
edge sits in the right place — a rung with two programs in it, or one holding 80% of the corpus, is
visible immediately. Also show the distribution of **event steps** (when in a program are goals
attained?) and flag counts (`geometry_undescribed`, `stuck_zone`, `no_declared_intent`,
`outcome_field_absent`).

Since rung edges live in the goal cards, (b) is the instrument for revising them — make the current
edges and the `config_version` visible on the page. Serves **OI-9**.

**(c) Off-island disagreement queue — a named third section, prefiltered.** The 36 programs where the
simulated and real final positions disagree about being off the island (31 under-detections, 5 over).
One row each: sim final, real GPS final, which side each says, and the defect flags present
(`fabricated_motion`, `boundary_exit_fabricated`, `loop_was_capped`, `trigger_*`). Sorted with
under-detections first. Every row links into View 1.

This is the highest-value screen in the tool: **OI-2 asks for each disagreement to end up attributed
to a named defect**, and this queue is how that triage happens. Show the running count of
attributed-vs-unattributed.

### B4. What each OPEN_ISSUE needs to see — the acceptance criteria that matter

The viz is being built *now*, ahead of other work, because these decisions are blocked on looking at
data. Each row names what must be reachable in the tool.

| Issue | What the viz must make inspectable | Where |
|---|---|---|
| **OI-1** sub-rung conditional-hat sensitivity | A **treatment selector (B1 / B2)** on View 1, re-rendering path, timeline and indicator values. `WREN-C040`'s `debris_zone_coverage` is 0.0351 vs 0.0 across the two — that difference must be *visible*, not inferred | View 1 |
| **OI-2** 36 off-island disagreements | The disagreement queue (View 3c) plus the real-GPS marker on the path | Views 1, 3c |
| **OI-3** 200mm fallback too small | Fabricated steps marked on path and block tree; the 6 `boundary_exit_fabricated` programs reachable in one click | View 1, 3c |
| **OI-4** undescribed plow geometry | Engagement zone bands incl. the undescribed regions, with qualifying steps marked. The 8 programs at y=1249 should look like a cluster | View 1 |
| **OI-5 / OI-6** untrusted triggers | `trigger_unfaithful` / `trigger_unsimulated` on the **stack header**, not just the program | View 1 |
| **OI-8** WREN-C082, zero steps | Must render without breaking, and must show *why* there are no steps — the unevaluable `while` guard, from `unknown_reporter_blocks` | View 1 |
| **OI-9** first-pass rung edges | Value distributions against edges, with near-cut-point list | View 3b |

**Treatment selector (OI-1) — specifics.** The profile already accepts a treatment via `_profile`
parameter / `--conditional-hats` / `VEX_GOAL_PROFILES_CONDITIONAL_HATS`. Surface it as a control on
View 1, default **B1**, and show the selected treatment in the header. It only differs on the 9
conditional-hat programs; grey the control elsewhere rather than hiding it.

**Flag rendering.** There are now ~12 flag types across three registers. Do not render them as one
undifferentiated list — group them: **trust** (`trigger_unfaithful`, `trigger_unsimulated`,
`concurrent_stacks_unverified`, `broadcast_*`), **fabrication** (`fabricated_motion`,
`boundary_exit_fabricated`), **evidence scope** (`simulated_attainment`, `geometry_undescribed`,
`stuck_zone`, `no_declared_intent`, `outcome_field_absent`, `simulated_fallback`). A reviewer needs
to tell "we may be wrong about this" from "this is a fact about the student".

### B5. Constraints

- The viz **reads** `profile()` and `timeline()`. It must not reimplement any indicator, rung
  assignment, or threshold. If a value is needed and not exposed, extend the output contract — do not
  compute it in the view layer.
- **No thresholds or playground entity names in viz code**, same rule as task 1.
- Viz dependencies (`streamlit`, `plotly`) stay out of the core package.
- Everything must render for a program with **zero path steps** (WREN-C082) and for one that fails to
  parse.
- **`gps_final_error_mm` is two-tier and must be displayed as such**: it exists only where sim and
  real agree the robot stayed on the island (n=42, median 145mm). Elsewhere it is `null` with reason
  `off_island_position_not_comparable` — render the reason, never a number. Off-island agreement is
  the primary fidelity signal; the coordinate error is secondary.

---

## C · Why this order

The timeline is the validation instrument for the profile, and the viz is the validation instrument
for the timeline. Right now a reviewer reading `engage_plow: armed_within_radius` has to trust it.
After A they can see *step 23, this drive block, y=1150*. After B they can watch it happen next to
the code that caused it.

It also changes what hand-labelling costs. Instead of reading a CSV, a labeller scrubs a program and
confirms or corrects the goal readings — which makes the n≈10 validation set cheap to produce and
makes disagreements specific to a step rather than to a whole program.

---

## C2 · Amendment — **IMPLEMENTED IN TASK 3, DO NOT REBUILD**

> **Status 2026-08-18: everything in this section is done.** The flags exist, the broadcast fix
> shipped, fabricated motion is instrumented. Retained below only as background for the viz
> requirements it generates (§B4). **Implement nothing from this section.**

`simulate_path` executes **every** handler stack, sequentially, in XML document order:

```python
for root in program.event_handler_stacks:
    sim.execute_stack(root)
```

Document order is roughly where the student placed the stack on the canvas. It carries no execution
semantics. There are **six hat types**, not one, and this loop treats them all identically.

### Corpus census — 133 handler stacks over 119 programs

| Hat type | stacks |
|---|---|
| `pg_events_when_started` | 120 |
| `pg_events_optical_detect_object` ("when eye") | 7 |
| `pg_events_when_broadcasted` ("when I receive") | 3 |
| `pg_events_when_bumper` | 3 |

### Three distinct defects — three distinct flags

| Flag | Programs | Defect |
|---|---|---|
| `concurrent_stacks_unverified` | **1** (WREN-C008) | More than one `when_started`. blocks.csv's own description: *"Multiple when started blocks can run multiple stacks at once."* The simulator runs them sequentially |
| `broadcast_flow_unmodelled` | **2** (WREN-C008, WREN-C012) | The program contains a broadcast block and/or a `when I receive` stack |
| `conditional_hat_forced` | **8** | A sensor- or timer-triggered hat (`when eye`, `when bumper`, `when timer`) whose stack is executed **unconditionally** |

**Required in task 1:** add all three as booleans on `GoalProfile`; every **simulation-channel**
indicator on an affected program carries the corresponding flag; counts recorded in `FINDINGS.md`.
Code- and outcome-channel indicators are unaffected. **Do not fix the simulator in task 1.**

### Why `broadcast_flow_unmodelled` is the one that matters

These are **not parallel programs — they are one unified control flow**, and the simulator gets the
*order* wrong. Its own comment says so:

```python
if bt in ("pg_events_broadcast", "pg_events_broadcast_and_wait"):
    # Broadcasted stacks are already executed at the top level by simulate_path();
    # inline triggering requires expression evaluator infrastructure (Tier 2).
    return
```

`broadcast` is a no-op and the receiving stack runs at top level in document order. For
`when started: [drive A, broadcast, drive C]` + `when I receive: [drive B]`, the true order is
A→B→C under `broadcast and wait`; the simulation produces A→C→B.

The fix is tractable and does **not** need an expression evaluator: on `pg_events_broadcast_and_wait`,
execute the matching `when I receive` stacks inline (matched on the event name in the block's fields),
and exclude those stacks from the top-level loop. Plain `pg_events_broadcast` is fire-and-forget, so
inline execution is an approximation — but a far better one than document order.

**This is a path-changing simulator change.** It would deliberately break `test_path_identity`, which
is exactly what the change taxonomy exists for: one change, its own attribution, fixture regenerated.
**A decision for Chris, not the agent** — n=2 today, but broadcast use grows once students learn it.

### Correction to the old project's records

The frozen project recorded the sensor bias as **"0/119 affected — no program contains any sensor
block."** That census counted sensor *reporter* blocks and missed sensor *hats*.
`pg_events_when_bumper` and `pg_events_optical_detect_object` are classified `event` / `handled`, and
their stacks execute whether or not the sensor would ever have fired.

**The sensor bias is 8 programs, not 0.** Same failure shape — a wrong answer rather than an
abstention — reached by a different route. Record this in `FINDINGS.md`.

### Consequence for the viz

The block-tree stack headers (§B2) must show **which hat** each group carries, not just "when
started", and mark unconditionally-forced stacks:

```
▸ Stack 1 · when started                     (executed 1st)
▸ Stack 2 · when I receive "go"              (executed 2nd — TRIGGER ORDER NOT MODELLED)
▸ Stack 3 · when bumper pressed              (executed 3rd — FORCED, condition not evaluated)
▸ Unattached blocks · never executed
```

## D · Decisions taken — do not reopen

1. **Untruncated path is shown**, greyed after the boundary exit, with post-exit events visually
   distinct. Requirement, not an option (§B3 View 1).
2. **View 3 does both jobs**, built and labelled as two separate sections: program finder with
   links into View 1, and rung calibration against the current edges (§B3 View 3).
3. **Block highlighting is decoupled from Blockly.** The block-tree list is the steppable,
   highlightable representation; the Blockly canvas is static visual context in a collapsible panel.
   `ws.highlightBlock` is best-effort only (§B2).
4. **One program at a time. No comparison view.** Two browser tabs cover it.
5. **The Blockly canvas stays**, reachable for every program and default-expanded on multi-stack
   programs. Stack structure is never flattened in the block-tree list (§B2, §B3).

## E · Remaining small calls — agent may propose, Chris signs

- **Near-cut-point δ.** The old `app.py` used 5% of the observed value range. Carry that default and
  make it adjustable in the view.
- **Block label vocabulary.** The block-tree list needs human labels for `pg_*` types
  (`pg_drivetrain_drive_for` → `drive forward`). Propose a mapping; it belongs in the **playground
  card** alongside `block_families`, not in viz code.
