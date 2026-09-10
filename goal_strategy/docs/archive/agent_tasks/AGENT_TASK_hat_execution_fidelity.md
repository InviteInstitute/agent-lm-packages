# Agent task 3 — hat-stack execution fidelity

**Date:** 2026-08-17 · **For:** coding agent · **Reviewer:** Chris
**Gate: task 1 (`AGENT_TASK_goal_profiles.md`) must be complete and green first.**
**Recommended order: task 1 → task 3 → task 2 (timeline + viz).** See §1.

This is a **path-changing simulator change**. It will deliberately break `test_path_identity`. That is
the point of the change taxonomy, not a failure — but it means the discipline in §6 is mandatory.

---

## 1. Why this comes before the viz

Task 2 builds a timeline and a walkthrough **on top of simulated paths**. Changing those paths
afterwards means re-validating every screen. Task 3 is small and touches one file; doing it first
gives task 2 a stable substrate.

The counter-argument, worth knowing: the viz would be a *good instrument for reviewing* this change —
watching the broadcast program execute in the right order is more convincing than a diff. If you
would rather have that, run task 2 first and accept re-validation. **Default is task 3 first.**

## 2. The three defects

`simulate_path` executes every handler stack sequentially in XML document order:

```python
for root in program.event_handler_stacks:
    sim.execute_stack(root)
```

There are six hat types and this loop treats them identically.

| Defect | Programs | Status in this task |
|---|---|---|
| **A · Broadcast flow not modelled** | 2 | **Fix** |
| **B · Conditional hats forced** | 8 | **Measure both treatments, do not choose** |
| **C · Concurrent `when_started`** | 1 | **Flag only; record what would resolve it** |
| **D · Fabricated motion from capped indefinite blocks** (§7) | **28** | **Flag only — additive, no path change** |

**Do A, B, C and D in that order, as separate diffs.** Only A changes paths.

### The two affected programs, in full

**`WREN-C012`** — the pattern Chris described. A sensor-triggered interrupt:

```
Stack 0  when started            : drive/turn sequence, ending in forever{drive, turn}
Stack 1  when eye DETECTS object : broadcast "ObjectDetected"
Stack 2  when I receive "ObjectDetected" : forever{ turn_to_rotation }
```

**`WREN-C008`** — two concurrent `when_started` stacks plus two receivers:

```
Stack 0  when started            : drives, magnet boost, drives, broadcast "Chash"
Stack 1  when started            : forever{ if{ broadcast_and_wait "my_event"; drive rev;
                                    turn right; wait_until }; broadcast "Chash" }
Stack 2  when I receive "my_event": stop_driving
Stack 3  when I receive "Chash"   : drive fwd        ← continuous, no distance
```

**The match key is `BROADCAST_OPTION`**, present as a field on `pg_events_broadcast`,
`pg_events_broadcast_and_wait` and `pg_events_when_broadcasted`. Confirmed on both programs.

### Defects A and B are entangled — read this before designing

In `WREN-C012` the broadcast **originates from a sensor hat**. So:

- If conditional hats are executed (today's behaviour), the eye hat fires, broadcasts, and the
  receiver's `forever{turn}` runs — **fabricating both the hat's blocks and its downstream receiver.**
- If conditional hats are **not** executed, the broadcast is never sent and the receiver correctly
  never runs.

**Not executing conditional hats propagates correctly through broadcast chains; executing them
fabricates a cascade.** That is a real argument for treatment B2 in §4, and it must be visible in the
measurement.

## 3. Part A — inline broadcast execution (the fix)

The simulator's own comment overstates the difficulty:

```python
# inline triggering requires expression evaluator infrastructure (Tier 2).
```

An expression evaluator is needed for *conditions*, not for broadcast. Broadcast matching is a string
compare on `BROADCAST_OPTION`.

**Implement:**

1. Build `receivers: dict[str, list[BlockNode]]` from every `pg_events_when_broadcasted` stack, keyed
   on its `BROADCAST_OPTION`.
2. **Exclude those stacks from the top-level loop** — otherwise they execute twice.
3. On `pg_events_broadcast_and_wait`: execute all matching receiver stacks inline, then continue.
   This is exact per the block's documented semantics ("pauses execution … until all triggered … have
   completed").
4. On `pg_events_broadcast`: execute matching receivers inline as well. **This is an approximation** —
   the real block is fire-and-forget and continues immediately. Inline is not correct, but it is far
   closer than document order. Every program where a plain `broadcast` fires keeps
   `flags: ["broadcast_concurrency_approximated"]`.
5. **Recursion guard, mandatory.** A receiver that broadcasts the same event loops forever. Track an
   active-event set; a broadcast for an already-active event is a no-op and sets
   `flags: ["broadcast_recursion_suppressed"]`. `WREN-C008` broadcasts `"Chash"` from two places, so
   this will be exercised.
6. No matching receiver → no-op, as today.
7. Multiple receivers for one event → execute all, in document order, and flag
   `broadcast_multiple_receivers`.

## 3b. The objective criterion — real GPS final position

**Use this to judge every change in this task.** `playground_params` carries
`gps_x_position` / `gps_y_position` from the **real run**. It is in the **same coordinate frame** as
the simulator, and it is an independent ground truth that has not been used until now.

Define `gps_final_error_mm = hypot(sim_final − gps_final)`. Measured on the current build:

| Subset | n | median error |
|---|---|---|
| **clean** — no boundary exit, no loop cap, no fabricated motion, no multi-hat | **26** | **24 mm** |
| exits island | 68 | 1006 mm |
| multi hat stacks | 10 | 1933 mm |
| loop capped | 22 | 2001 mm |
| fabricated motion | 28 | **2555 mm** |

Two things follow. **The simulator is faithful when none of the known defects apply** — 24mm median,
6.9mm at the 25th percentile. And **every defect this task addresses degrades agreement with reality
in the expected direction**, fabricated motion worst.

**Required:** add `gps_final_error_mm` to the review CSV, and report the median for each affected
subset **before and after** every change in this task. A change that does not reduce it has not
improved fidelity, whatever else it does.

**Caveats to carry.** The clean base is only 26 programs and its own 75th percentile is 1081mm, so
there are unmodelled effects beyond A–D. `WREN-C082_WREN-C082_S001` produces **zero simulated path
steps** while its real GPS sits **59 metres** from spawn — the simulator reproduced nothing at all
there; inspect it. And this metric compares one run's outcome against the final workspace; the fact
that clean programs agree to 24mm is itself evidence those correspond.

## 4. Part B — conditional hats: measure, do not decide

`when eye` (7 stacks), `when bumper` (3), `when timer` (0 in corpus) currently execute
unconditionally. Deciding correctly needs sensor simulation, which is out of scope.

### The principle this sits under

**Evidence comes only from blocks with a real pathway to execution** — but there are two tiers, and
collapsing them produces a wrong answer instead of an admission of ignorance:

| Tier | Example | Treatment |
|---|---|---|
| **No pathway** — structurally cannot execute | orphaned (detached) blocks | **Exclude.** Already correct: `code_state_authored` reads active blocks only |
| **Pathway exists but is unevaluable** | `when bumper` / `when eye` stacks; broadcast receivers under unmodelled ordering | **Abstain** — not silently included, not silently excluded |

An orphan *cannot* run. A `when bumper` stack *might have*; we cannot tell. B1 and B2 below are both
**guesses** about the second case. B3 is the option consistent with this project's own rule —
*an indicator that cannot be computed abstains with a reason; never substitute a default.*

**Note on orphans (settled, do not revisit):** detaching blocks is normal Blockly editing practice —
it is how students disable code — so an orphaned block is not evidence of thwarted intent and must
not be read as intent. Report `orphan_block_count` in the review CSV as a descriptive field only: no
flags, no indicator effect, no failure signal. (Corpus: 42 programs have orphaned blocks, median 27%
of the program; 34 have orphaned *movement* blocks.)

**Deliverable is a comparison, not a choice.** Produce all three and report the delta:

| Treatment | Behaviour |
|---|---|
| **B1** — status quo | Execute conditional-hat stacks unconditionally |
| **B2** — suppress | Do not execute them; the stack contributes no path steps |
| **B3** — abstain | Execute per B2, **and** the simulation channel abstains for those programs with reason `conditional_hat_unevaluable`. Code and outcome channels still report |

**Two separate questions — do not tangle them:**

1. **Which path is closer to reality?** Empirical. `gps_final_error_mm` (§3b) answers it for B1 vs B2.
2. **Should simulation indicators be reported on a path we cannot verify?** Policy. B3 is the answer
   consistent with the abstention discipline used everywhere else in this project.

For each of the 8 affected programs, report under both treatments: path length, `boundary_exceeded`,
every indicator value and rung, the goal profile diff, and — decisively — **`gps_final_error_mm`
(§3b)**. Put it in `FINDINGS.md` as a table.

**The treatment whose median `gps_final_error_mm` is lower on those 8 programs is the one whose
*path* better matches reality.** That settles question 1 by measurement rather than taste. Report the
number; if it is close or contradictory, say so rather than picking. B3 shares B2's path, so it
scores identically on this metric — it differs only in whether indicators are reported.

Implement B2 and B3 behind a config flag defaulting to **B1** (status quo) so nothing changes
silently. **Chris chooses after seeing the numbers.**

## 5. Part C — concurrent `when_started`: flag only

**1 program** (`WREN-C008`). `blocks.csv` says *"Multiple when started blocks can run multiple stacks
at once"*, so sequential execution is wrong in principle. Do not attempt to fix — concurrency needs a
scheduler, and one drivetrain cannot serve two stacks anyway.

Keep `concurrent_stacks_unverified`. Record in `FINDINGS.md` what would resolve it: **VEX may only run
one `when_started` stack per test, in which case `PlaygroundRun` data should identify which stack was
actually tested.** Confirm when that data is available.

## 6. Change protocol — mandatory, one change at a time

1. **Baseline.** Task 1 green; regression pins recorded; `test_path_identity` passing.
2. **One change only.** Part A. Do not bundle B or C into the same diff.
3. **Attribution report** before touching any fixture: which programs' paths changed, how many steps,
   the first divergent step per program, and the before/after on all five task-1 pins. Expect changes
   confined to `WREN-C008` and `WREN-C012` — **if any other program's path moves, stop and report.**
4. **Do not regenerate `frozen_paths.parquet` until Chris signs the attribution report.** After
   sign-off, regenerate, update the pins, and record the change with its date and reason.
5. Part B ships behind a default-off flag and changes no path.

## 7. Part D — fabricated motion: flag it, do not fix it

Indefinite-duration blocks are all capped, but by **four different constants, only one of which is
flagged.** This affects more programs than defects A–C combined and it contaminates a regression pin.

| Block | Treatment | Constant | Flagged today |
|---|---|---|---|
| `forever` / `repeat until` | 20 iterations | `_FOREVER_UNROLL = 20` | ✅ `loop_was_capped`, `loop_cap_steps` |
| `repeat(N)`, N > 20 | 20 iterations | `_MAX_UNROLL_ITERATIONS = 20` | ✅ |
| continuous drive **+ `wait`** | velocity × time — **correct** | — | n/a |
| continuous drive **alone** | **nominal 200mm** | hardcoded | ❌ |
| continuous turn **+ `wait`** | velocity × time — **correct** | — | n/a |
| continuous turn **alone** | **nominal 90°** | hardcoded | ❌ |
| `wait_until` unsatisfied | 50 iterations × 50mm = **2500mm** | `_MAX_WAIT_ITERS = 50` | ❌ |

**Corpus:** 34 drive-fallbacks over 23 programs (25 correctly paired with `wait`); 19 turn-fallbacks
over 10 programs (7 paired); 2 `wait_until`. **28 programs (24%) contain ≥1 fabricated element**,
~11,800mm of invented travel.

**It contaminates `boundary_exceeded`.** Five programs exit the island *on a fabricated block*:
`WREN-C019`, `WREN-C015`, `WREN-C026`, `WREN-C065` (continuous-drive fallback) and `WREN-C027`
(`wait_until`). Under §6a the path is truncated at first exit — so for these five, **the truncation
point and everything downstream of it are artifacts of an invented distance**, and
`boundary_exceeded` is one of the task-1 regression pins.

**Required — additive only, no path changes:**

1. Record per fabricated step: the block type and which fallback fired. Expose on
   `SimulationResult` as `fabricated_steps: list[int]`, mirroring `loop_cap_steps`.
2. `GoalProfile` gains `fabricated_motion: bool` and `boundary_exit_fabricated: bool` — the latter
   true when the first out-of-bounds step is itself a fabricated step.
3. Simulation-channel indicators on affected programs carry `flags: ["fabricated_motion"]`.
4. `FINDINGS.md`: the table above with this run's counts, and the list of programs where
   `boundary_exit_fabricated` is true.

**Do not change any constant and do not alter execution.** Every value here is a modelling choice
that needs a real-playground probe (§8) before anyone touches it. Severity for the eventual fix is
`wait_until` first (2500mm exceeds the field's ~1700mm playable radius), then turn fallbacks (an
invented heading propagates into every later position), then drive fallbacks.

**The 200mm drive fallback is probably too small, not too large.** Chris reports a real, observed
misconception — students misuse continuous drive blocks and drive off the island. The GPS check
(§3b) is consistent with that: for the 23 drive-fallback programs, median **real** displacement from
spawn is **2621mm** against **1304mm** simulated, while non-fallback programs match closely (2280 vs
2007). Per-program the gap is noisy (median +148mm, 12 of 23 above), so this is **suggestive, not
conclusive** — the probe in §8 settles it. Record it; do not act on it.

## 8. Real-playground probes — Chris, not the agent

Several questions here can only be settled by running the actual playground. Each is a few minutes:

| Probe | Settles |
|---|---|
| Two `when started` stacks, each driving a different direction | Does VEX run both, pick one, or error? Defect C |
| `when started: [drive, broadcast X]` + `when I receive X: [drive]` | Does the receiver run concurrently or after? Part A's approximation |
| A `when bumper` stack that drives, never touching the bumper | Does it fire? Defect B |
| Engage the plow from below (`y < 1169`) | The undescribed engagement geometry — 19 of 43 engagements, still open |
| `when started: [drive forward]` — continuous drive, no `wait`, nothing after | How far does the robot actually travel? The simulator invents **200mm**. Affects 23 programs (Part D) |
| `when started: [drive forward, wait until <never true>]` | What does an unsatisfiable `wait_until` do? The simulator drives **2500mm** — more than the field's playable radius |
| `when started: [turn right]` — continuous turn, no `wait` | The simulator invents **90°**. A wrong heading propagates into every later position |

## 9. Constraints

- Change **only** `vendor/goal_strategy_detector/simulation/simulate_path.py`, and record that it is
  no longer byte-identical to the source project — update any `VERBATIM` manifest accordingly.
- Do not touch the parser, `blocks.csv`, or the goal cards.
- Do not implement sensor simulation, an expression evaluator, or a scheduler.
- Do not build any part of task 2.
- If Part A's attribution report shows a path change outside `WREN-C008` / `WREN-C012`, **stop.**
