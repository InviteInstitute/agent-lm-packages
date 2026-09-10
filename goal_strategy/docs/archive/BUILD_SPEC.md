# BUILD_SPEC — VR-Seq cooperative scheduler for `simulate_path`

**Audience:** the coding agent. **Companion to** `SCHEDULING_MODEL.md` (why this
approach; the evidence; §10 is the authoritative evidence record). This document
is the implementation contract: what to build, what must not change, and what
counts as done.

**Status of the underlying semantics:** read from VEX's shipped source
(`@vexcode/scratch-vm`, confirmed 2026-08-25). This is transliteration, not
modelling, except where §7 names an open parameter.

---

## 0 · One-paragraph summary

`simulate_path` executes top-level stacks strictly sequentially, one after
another, in document order. VEX VR runs each `when started` stack as a
**scratch-vm thread**, stepped round-robin, yielding at loop back-edges and
parking on blocking motion. This build reifies per-stack execution state using
**Python generators**, adds a **Sequencer** that drives them round-robin over a
shared, last-write-wins drivetrain cell, and gates the whole thing behind a
`scheduler` argument whose default reproduces today's behaviour byte-for-byte.
Roughly 96% of the corpus (7,697 single-stack runs of 7,984) must be unaffected.

---

## 1 · Do not change

These are ruled, validated, or deliberately deferred. Touching them invalidates
the attribution report and the regression pins.

| area | rule |
|---|---|
| **Layer 2 physics/sensing** | Drive/turn velocity calibration (9.88 mm/s·%, 4.16 °/s·%), front-eye cone (fov 13°, range 124 mm), bumper radii, magnet near-contact model (blade 75 mm / hitch 40 mm), colour zones, distance cone. Measured. Untouched. |
| **Loop caps** | `_FOREVER_UNROLL` / `forever_unroll` (20), `max_unroll`, `execution_budget` (50k), and the faithful-nesting `_forever_completed` rule. Keep exactly. The real-time replacement is a separate ruling (§8). |
| **Timer / wall-clock model** | `sim_time_s` and `timer_s` advance only from motion and explicit waits. Do **not** add per-loop-iteration time in this build (§8). |
| **`stack_precedence` / lockout** | `lockout_losers`, `stack_lockout_winner`, `creation_order.py` — falsified and PAUSED. Leave the machinery in place and inert. Do not delete, do not re-enable. |
| **Continuous-motion semantics** | `drive`/`turn` arm pending motion; `wait` commits velocity×time and **leaves the motion armed** (WREN-C048); any drivetrain command clears it; terminal runoff at 4× field radius. Ratified against ground truth. The scheduler must reproduce these, not replace them. |
| **`wait_until` gate semantics** | OI-3: no self-motion; pending motion marches to the condition; unmet gates the stack (`_GateSignal`, `wait_until_unmet`). |
| **Flag vocabulary** | Existing flags keep their meanings. Add new ones (§6); do not repurpose. |
| **Conditional-hat treatment** | B1 (`conditional_hats="execute"`) stays the default. |

---

## 2 · Target semantics

### 2.1 Thread model

- One thread per top-level `pg_events_when_started` stack.
- Threads are created **in document order — MEASURED** (`SCHEDULING_MODEL.md`
  §11.2: two print-only stacks, `A` prints before `B`; under reverse launch
  order the first thread stepped would print first). This matches scratch-vm's
  `startHats`, which pushes in the target's top-block order. P-A is closed.
  The Code Viewer's reverse `vr_thread(...)` emission is a **Python**-path
  artifact and does not describe the blocks runtime; the corpus is 7,983 Blocks
  / 1 Switch / 0 Python, so it is irrelevant here regardless.
  Keep `thread_start_order` (`document` | `reverse_document`) as a config with
  `document` as the measured default — cheap, and it makes the assumption
  visible — but the tier-2 sensitivity sweep is now optional, not a gate.
- Broadcast receivers (`pg_events_when_broadcasted`) keep today's **inline**
  execution at the broadcast site. Do not convert them to threads in this build.
- Deferred sensor hats keep today's inline execution (§2.5). **Phase 2.**

### 2.2 Stepping rule

Event-driven cooperative round-robin. There is exactly **one active drivetrain
motion** at any time (shared device, last write wins), which makes the event
calendar small and deterministic.

```
run():
  threads = [Thread(stack) for stack in when_started_stacks]   # document order
  while any(t.alive for t in threads):
      # 1 · advance every RUNNABLE thread to its next yield point,
      #     round-robin in creation order, until none are runnable
      progressed = True
      while progressed:
          progressed = False
          for t in threads:
              if t.status is RUNNABLE:
                  t.step()            # generator .send(None) -> next yield
                  progressed = True
      # 2 · nothing runnable: advance the clock to the next event
      if no parked threads and no active motion: break
      dt = min(next_wake_time, active_motion_completion_time) - now
      commit_motion_slice(dt)         # physics for this slice only
      now += dt
      wake threads whose wake_time <= now
      if active motion completed: unpark its owner (status RUNNABLE)
```

Thread statuses, mirroring scratch-vm: `RUNNABLE`, `PARKED_MOTION` (awaiting a
blocking `*_for` completion — scratch's `STATUS_PROMISE_WAIT`), `PARKED_TIME`
(explicit `wait`), `PARKED_COND` (`wait_until`), `GATED` (unmet gate — dead but
not an error), `DONE`.

**Loop yielding.** Every loop-body iteration ends in a yield (scratch-vm's
`isLoop` back-edge rule). With `loop_iteration_time_s = 0.0` (the phase-1
default) a yield costs no simulated time; the existing unroll caps remain the
termination guarantee.

### 2.3 Yield contract — per block

For every `handled` block in `data/blocks.csv`. "yield" = give up the pass and
return to the sequencer; "park" = suspend until an external event.

| block(s) | behaviour |
|---|---|
| `pg_drivetrain_drive_for`, `pg_drivetrain_turn_for`, `turn_to_heading`, `turn_to_rotation` | **park (`PARKED_MOTION`)** — write the drivetrain cell with a completion target, then suspend. Unparked on completion, or per `superseded_motion` if another thread overwrites the cell. |
| `pg_drivetrain_drive`, `pg_drivetrain_turn` | write the cell (continuous), **no yield, no park** — returns immediately. Preserves the pending-motion model. |
| `pg_drivetrain_stop`, `stop_driving` | clear the cell, **no yield**. If another thread was `PARKED_MOTION` on the cleared motion, apply `superseded_motion`. |
| `set_drive_velocity`, `set_turn_velocity`, `set_heading`, `set_drive_heading`, `set_drive_rotation` | state only, **no yield**. Note the existing rule: velocity setters do **not** clear pending motion; heading setters **do** (`_clear_pending_motion`). Preserve both exactly. |
| `pg_control_wait` | **park (`PARKED_TIME`)** until `now + N`. Armed motion continues during the wait (WREN-C048) — this now falls out of the slice mechanism rather than being special-cased. |
| `pg_control_wait_until` | **park (`PARKED_COND`)**; re-evaluate the condition at every slice boundary. Keep `_march_drive_until` / `_march_turn_until` as the "when does this become true under the active motion" solver; keep the unmet → `_GateSignal` + `wait_until_unmet` path. |
| `pg_control_forever`, `pg_control_repeat`, `pg_control_repeat_until`, `pg_control_while` (and the `forever` / `repeat` / `while` / `repeat_until` / `controls_*` aliases) | **yield at the end of every iteration.** Caps unchanged. |
| `pg_control_if*`, `if_then*`, `controls_if` | no yield. Branch bodies run inline in the same thread. |
| `pg_control_break`, `pg_control_stop_project` | no yield. `stop_project` must now stop **all** threads, not just the caller — see §5 hazards. |
| `pg_events_broadcast` | receivers inline (unchanged), no yield. Keep `broadcast_concurrency_approximated`. |
| `pg_events_broadcast_and_wait` | receivers inline (unchanged), no yield. Semantically correct already for the single-receiver case. |
| `procedures_call` | inline expansion, no yield (a yield inside the body propagates through `yield from` naturally). |
| `pg_magnet_*` | no yield. |
| `pg_looks_*` (pen/print) | no yield. Faithful no-ops. |
| `pg_sensing_reset_timer` | no yield. |
| all `pg_sensing_*` reporters, all `pg_operator_*`, all `pg_variables_*` reads | **no yield** — evaluated inline inside the enclosing block, exactly as scratch-vm evaluates reporters within `execute()`. `_eval_expression` stays a plain function; do **not** make it a generator. |
| `pg_variables_set_*`, `change_variable`, `variables_set/change`, `math_change` | no yield. |

### 2.4 Shared drivetrain cell

Replace the four loose fields (`pending_drive_dir`, `pending_turn_dir`,
`pending_drive_block`, `pending_turn_block`) with one object; keep the existing
field names as properties if that reduces churn.

```python
@dataclass
class DrivetrainCell:
    mode: str | None          # None | "drive" | "turn"
    sign: float               # +1 fwd / -1 rev ; +1 CCW / -1 CW
    block: BlockNode | None   # arming block, for step attribution
    target: float | None      # remaining mm or deg; None = continuous
    owner: int | None         # thread index parked on completion; None if non-blocking
```

Rules:

1. **Last write wins.** Any drivetrain command overwrites the cell outright.
   No queue, no lock, no ownership. (Confirmed at the firmware level for V5 and
   structurally certain for VR — `SCHEDULING_MODEL.md` §4.1, §10.8.)
2. **On overwrite with a live `owner`:** apply `superseded_motion` (§7).
   Default `truncate_and_resume` — commit the distance travelled so far, then
   set the owner `RUNNABLE`.
3. **Slice commitment.** `commit_motion_slice(dt)` moves the robot by
   `velocity × dt` along the current mode, reusing the existing `_move` sampling
   (50 mm coverage steps, region sampling, `_latch_sensor_hats_along`). Decrement
   `target`; when it reaches zero the motion completes.
4. **Continuous motion** (`target is None`) never completes; it ends only on
   overwrite, on `stop`, or at program end via `finish_pending_motion()`.
5. **Terminal runoff** is unchanged: when all threads are `DONE`/`GATED` and the
   cell still holds continuous motion, run `finish_pending_motion()` once.

### 2.5 Sensor-hat integration — phase 1 keeps it inline

**Do not convert deferred sensor hats to threads in this build.** Reason: the
byte-identity gate (§4) is what makes this change safe, and converting hats
would change behaviour for the 300 single-stack runs that pair `when started`
with a detection hat — mixing two changes into one attribution report.

Phase 1 therefore keeps, unchanged:

- `fire_ready_sensor_hats()` called at the top of `execute_block` (this already
  sits exactly where scratch-vm's between-blocks boundary is);
- `_latch_sensor_hats_along` mid-move latching;
- the `_HatRestartSignal` restart loop with `hat_restart_capped`;
- `_in_sensor_hat` reentrancy guard and the `_active_hat` move pre-scan.

Two adjustments are required for correctness under multiple threads:

- `fire_ready_sensor_hats()` must run in the context of **whichever thread hit
  the block boundary**, and the hat's inline stack must not be able to observe
  another thread's half-finished generator state. Since hats execute
  synchronously inside `execute_block`, this holds automatically — but assert it
  with the `_in_sensor_hat` guard, and make the guard **global to the
  simulator**, not per-thread.
- `_forever_completed` is currently per-top-level-stack, saved/restored around
  hat firing. It must become **per-thread state** (§5).

Phase 2 (separate PR, separate attribution): hats become real threads created by
a per-slice `startHats` equivalent with `restartExistingThreads: true`. Note for
that build: the restart-and-truncate behaviour the reviewer probed on 2026-08-24
is exactly scratch-vm's `_restartThread`, so it should survive the conversion.

### 2.6 Time model

- `sim_time_s` and `timer_s` advance **only** in `commit_motion_slice(dt)` and in
  `pg_control_wait`. Same total as today for a single thread.
- `loop_iteration_time_s` config exists but defaults to `0.0` (§8).
- The scheduler's `now` is `sim_time_s`. There is no second clock.

---

## 3 · Implementation

Target file: `vendor/goal_strategy_detector/simulation/simulate_path.py`
(3,309 lines; interpreter core is ~1747–2660).

### 3.1 Generator conversion

Mechanical, and bounded:

- `execute_stack(node)` → generator. Body becomes
  `while current: yield from self.execute_block(current); current = current.next`.
- `execute_block(block)` → generator. Every existing `return` stays a `return`
  (legal in a generator). Every `self.execute_stack(x)` becomes
  `yield from self.execute_stack(x)`.
- Loop branches: insert `yield` at the end of each iteration body, after the
  `_BreakSignal` handling and before the `_forever_completed` check.
- Blocking motion branches (`drive_for`, `turn_for`, `turn_to_*`): write the
  cell, then `yield PARK_MOTION` instead of calling `_move` inline.
- `_eval_expression`, `_get_numeric`, `_hat_detects`, `_bumper_pressed`,
  `_eye_near_object`, and every geometry helper stay **plain functions**.
- `fire_ready_sensor_hats` stays a plain function in phase 1 (it drives its own
  inline `execute_stack`, which is now a generator — drain it with a
  `for _ in gen: pass` loop, since hats do not park in phase 1).

**Exception propagation is unaffected.** `_BreakSignal`, `_StopSignal`,
`_BudgetSignal`, `_HatRestartSignal`, `_GateSignal` all propagate through
`yield from` normally. Do not restructure them.

### 3.2 The Sequencer

New class in the same module, ~150 lines, implementing §2.2. It owns:
`threads`, `now`, the `DrivetrainCell`, the wake calendar, and
`commit_motion_slice`.

`simulate_path` gains a branch: `scheduler="sequential"` runs today's loop
(drain each stack's generator to completion in order); `scheduler="cooperative"`
constructs the Sequencer.

### 3.3 Signal semantics under threads

| signal | scope |
|---|---|
| `_BreakSignal` | thread-local, unchanged (caught by the enclosing loop). |
| `_GateSignal` | **thread-local** — gates that thread only, sets it `GATED`. Matches today's per-stack `continue`. |
| `_StopSignal` / `_BudgetSignal` | **global** — `stop project` halts every thread and suppresses runoff. See §5. |
| `_HatRestartSignal` | scoped to the inline hat execution, unchanged. |

### 3.4 Config surface

`simulate_path(program, context, conditional_hats="execute",
stack_precedence=None, scheduler="sequential", superseded_motion="truncate_and_resume",
thread_start_order="document", loop_iteration_time_s=0.0)`

Card-overridable under `simulation:` in the playground YAML, following the
existing `execution_budget_blocks` pattern:

```yaml
simulation:
  scheduler: sequential          # sequential | cooperative
  superseded_motion: truncate_and_resume
  thread_start_order: document   # document | reverse_document (P-A, see SCHEDULING_MODEL §11.1)
  loop_iteration_time_s: 0.0
```

Bump `config_version` when any of these change from their defaults in a card.

---

## 4 · Acceptance criteria

In order. Do not proceed past a failing gate.

1. **G1 — refactor identity.** With `scheduler="sequential"`, the full corpus
   reproduces `data/frozen_paths.parquet` byte-for-byte.
   `tests/test_path_identity.py` and `tests/test_corpus_regression.py` green.
2. **G2 — all tests.** All 235 tests green, no new skips.
3. **G3 — single-stack identity under the scheduler.** With
   `scheduler="cooperative"`, every run with **exactly one** `when_started`
   stack (7,697 of 7,984) must be byte-identical to G1 output. This is the
   central safety property: one thread makes round-robin degenerate to
   sequential and every yield point unobservable. Add
   `tests/test_scheduler_identity.py` pinning it over the dev corpus.
4. **G4 — the falsification test.** On the 62 tier-2 telemetry runs (≥2 stacks
   with any drivetrain command), cooperative scheduling must **meet or beat**
   sequential-sum's 52/62 off-island endpoint agreement, and must beat every
   ownership policy (best was 26/62). Report the 2×2 against
   `stage2_fidelity.csv`. **If cooperative scores below 52/62, stop and report
   — do not tune.** That result would falsify the model and is worth more than
   a passing build.
5. **G5 — §6 attribution report.** For the 287 multi-stack runs: every changed
   fidelity verdict named and mechanism-attributed, per the project's standing
   one-change → attribution → sign-off protocol. Regenerate pins only after
   sign-off.

---

## 5 · Hazards specific to this codebase

Read these before writing code; each has bitten a similar refactor.

1. **`self.step` is a single monotonic path index.** Under interleaving,
   `PathStep`s from different threads land in one sequence. Downstream consumers
   (`indicators.py`, `timeline.py`, `slice_sim_result`, the viz walkthrough)
   assume path order is execution order. Add an **additive** `thread_id: int |
   None = None` to `PathStep`, set only under cooperative mode, and verify
   nothing compares `PathStep` instances by whole-dataclass equality (that would
   break G1/G3).
2. **`_forever_completed` must become per-thread.** It is currently a simulator
   attribute reset per top-level stack and saved/restored around hat firing.
   Under threads it is thread-local state. Getting this wrong silently changes
   nested-loop semantics (OI-24 ruling 1).
3. **`_current_root_id`** is used only by the paused lockout gate. Under threads
   it must track the *executing thread's* root, or the lockout gate could
   suppress the wrong stack's drivetrain commands if it is ever re-enabled.
4. **`stop project` is global.** Today `_StopSignal` escapes the whole
   `for root in executable` loop and suppresses runoff. Under threads it must
   kill all threads and still suppress runoff. A thread-local catch here silently
   changes 1,171 `fabricated_motion` runs.
5. **`_eval_expression` reads live world state.** Under interleaving a condition
   can now observe another thread's motion. That is correct and is much of the
   point — but it means conditions that were stable become order-sensitive.
   Expect G4 movement here, and attribute it.
6. **`_maybe_activate_pieces()` and `fire_ready_sensor_hats()` run at the top of
   every `execute_block`.** Under the scheduler they now run at each thread's
   block boundaries, interleaved. Preserve the call order exactly; do not hoist
   them into the sequencer loop.
7. **Velocity is global, not per-thread.** `drive_velocity_mm_per_s` is shared
   robot state — correct, keep it shared. One thread's `set drive velocity`
   changes another thread's in-flight motion. That is real VEX behaviour.
8. **`_clear_pending_motion` is called by heading setters but not velocity
   setters.** Preserve this asymmetry exactly when migrating to the cell.
9. **`slice_sim_result` and the rung/timeline anchors** assume a contiguous
   single-threaded path. Check them against a cooperative run before G5.

---

## 6 · New flags

| flag | meaning |
|---|---|
| `scheduler_cooperative` | run simulated under the cooperative scheduler (provenance marker, always set in that mode). |
| `motion_superseded` | a blocking `*_for` motion was truncated by another thread's drivetrain command, and its thread resumed. Diagnostic/provenance only — the policy is measured (§7), so this is no longer a conditional-evidence marker. |
| `drivetrain_contention` | two threads wrote the cell within one scheduling event. Diagnostic; the real system silently does the same. |

`concurrent_stacks_unverified` is retired **only** for runs the scheduler
actually resolves. Where the model still cannot decide, it stays and the rubric
U-gate applies. The fix shrinks the U population; it never fakes it.

---

## 7 · RESOLVED parameter: `superseded_motion` = `truncate_and_resume`

**Measured 2026-08-25 (probe P7/P8, 3 runs + 1 variant, fully deterministic).**
This was the last open parameter; it is now evidence, not a default.

Probe (Grid-style open field, drive velocity 50%):
```
when started (A):                 when started (B):
  set drive velocity 50%            wait 1 second
  print "A1"; print timer           stop driving          <-- variant: turn right for 90 deg
  drive forward for 1000 mm         print "B1"; print timer
  print "A2"; print timer
  print position X
  turn right for 90 degrees
  print "A3"; print timer
```

Observed, identical on every run and on the variant:
```
A1 t=0
A2 t=1          <-- 1000mm at 494 mm/s would complete at t~2.02
position X = -900
B1 t=1
A3 t=2          <-- A's own turn executed AFTER the interruption
```

Readings:

1. **`truncate_and_resume` confirmed.** A's blocking `drive_for` returned early,
   at the moment B issued its command, and A's stack continued (`A2`, then the
   turn, then `A3`). The parked thread is not killed.
2. **Any competing drivetrain command truncates — not just `stop`.** The
   `turn right for 90` variant produced byte-identical console output. This is
   direct evidence for the last-write-wins shared cell of §2.4; do not
   special-case `stop`.
3. **Threads genuinely interleave.** B's `wait 1 second` elapsed while A was
   mid-drive (P5 confirmed behaviourally).
4. **Deterministic.** Identical across 3 runs and the variant.

Implementation consequence: **ship `truncate_and_resume` as the measured
default.** Keep `truncate_and_park` and `resume_after` implemented behind the
config as falsification alternatives — running the tier-2 comparison across all
three is still worthwhile as a consistency check (a policy that fits the corpus
*better* than the measured one would indicate a problem elsewhere in the model,
not a reason to switch).

Two residual observations, neither affecting the above, both Layer 2 rather than
scheduler questions:

- Position X = -900 is uncalibrated (start position was not printed). Consistent
  with ~500 mm travelled if spawn X was -1400; the t=1 timestamp already rules
  out a full 1000 mm.
- `A3` lands ~1 s after `A2`, where a 90 deg turn at 50% turn velocity should
  take ~0.43 s (4.16 deg/s per %). Likely integer print precision or an unset
  turn velocity; worth a precision rerun if turn timing ever becomes
  load-bearing.

## 8 · Explicitly deferred: the wall clock

The bundle shows VEX modified scratch-vm's loop blocks to add a **5 ms stack
timer plus `requestRedraw()` per iteration**, which rate-limits loops to roughly
one iteration per 60 Hz tick (`SCHEDULING_MODEL.md` §10.2). That gives a
principled real-time replacement for the 20-unroll cap and would make idle/timer
programs simulable (`timer_hat_unfired`).

**Not in this build.** It changes single-stack behaviour and would break the G3
identity gate that makes everything else safe. `loop_iteration_time_s` is wired
through and defaults to `0.0` so the change is a one-line experiment later,
under its own ruling and its own attribution report.

---

## 9 · Suggested PR sequence

| PR | content | gate |
|---|---|---|
| 1 | Generator conversion only; `scheduler="sequential"` is the sole path. No behaviour change. | G1, G2 |
| 2 | `DrivetrainCell` + `Sequencer` + `scheduler="cooperative"`; hats still inline. | G3, G4, G5 |
| 3 | Sensor hats as threads (`restartExistingThreads`). | own identity + attribution report |
| 4 | Wall clock (`loop_iteration_time_s`), only after a ruling. | own attribution report |

PR 1 is the risky-looking one and the safe one: large diff, zero behaviour
change, fully pinned by G1. PR 2 is the small diff that carries all the meaning.

---

## 10 · Changelog

### 2026-08-25 · post-probe revision (P7/P8 + precision rerun)

Deltas against the pre-probe version of this spec. Only item 2 changes code.

1. **§7 `superseded_motion` — RESOLVED.** Was an open parameter shipped on a
   default; now **measured** as `truncate_and_resume`. `truncate_and_park` and
   `resume_after` remain implemented as falsification alternatives only.
   Knock-on: the `motion_superseded` flag (§6) is downgraded from a
   conditional-evidence marker to provenance/diagnostic — evidence on those
   runs is full-tier.

2. **NEW REQUIREMENT — truncation is symmetric and re-entrant.** The precision
   rerun caught **mutual truncation** in one run: B truncated A's `drive_for`;
   A resumed, issued its own `turn_for`, which truncated B's `turn_for`; B
   resumed too (`SCHEDULING_MODEL.md` §11.1). The `DrivetrainCell` must
   therefore have **no owner precedence and no priority** — no "interrupter
   wins" rule. A thread resumed after truncation must be able to truncate its
   own interrupter within the same scheduling event, and resume must not be
   one-shot or latched: any number of truncate/resume cycles per thread.
   **Add a regression test:** A truncates B truncates A, both stacks complete.
   This is the sharpest single test of the shared-cell model, and the most
   likely thing to get wrong — an implementation shaped as "interrupter takes
   over, victim resumes" passes a single-truncation test and fails this one.

3. **§2.1 `thread_start_order` — config added, default MEASURED.** Briefly
   re-opened on the Code Viewer's reverse `vr_thread(...)` emission, then
   settled by probe: **document order** (`SCHEDULING_MODEL.md` §11.2). Keep the
   config with `document` as the default; the tier-2 sensitivity sweep is
   optional, not a gate. The reverse emission is a Python-path artifact and the
   corpus is 7,983 Blocks / 1 Switch / 0 Python.

4. **DO NOT model per-command latency.** The rerun shows ~0.12 s round-trip per
   blocking command to the Unity playground. It shifts absolute durations but
   not event ordering, it would break G1/G3, and the OI-16 two-duration
   calibration cancels it by construction. Deferred with the §8 wall-clock work.
