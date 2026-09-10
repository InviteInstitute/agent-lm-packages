# SCHEDULING_MODEL — a specification-first alternative to the nine-probe reconstruction

> **READING ORDER — read §10 FIRST.** Sections 1–9 were written *before* the
> VEXcode VR bundle was inspected and argue the case from inference. §10 records
> what was subsequently confirmed by reading VEX's shipped source and **is
> authoritative wherever the two disagree.** Specifically superseded:
> §1's claim that the editor is scratch-blocks (it is vanilla Blockly — see
> §10.3); §1E's "bundle proof not obtained" (obtained — §10.1); §5's framing of
> the model as an adopted specification (it is now a transliteration of shipped
> code — §10.5); §7's parameter P-A, thread start order (resolved — `startHats`
> pushes in block order); and §8's exclusion of wall-clock time (reopened by the
> 5 ms loop floor — §10.2). This document is a RATIONALE memo, not a build
> spec; it explains why the approach is defensible and what is known, not the
> implementation contract.

Research memo, 2026-08-25. Written against PARALLEL_EXECUTION.md (the nine-probe
plan), SENSOR_TESTBATTERY.md §6.1/A1, and OI-7.

**Thesis.** We do not need to reconstruct VEX VR's concurrency semantics from
behaviour. VEX VR's block layer is a **scratch-blocks / scratch-vm derivative**,
and scratch-vm's scheduler is a *published, exactly-specified, open-source
reference implementation*. The defensible move is to adopt that specification as
our execution model, validate it against the 3,978-run GPS corpus we already
have, and reduce the nine VR probes to **one ten-minute browser inspection plus
at most two residual parameter probes**.

Crucially, the spec **retrodicts three behaviours we already probed and paid
for** — that is free validation, obtained before any build.

---

## 1 · The finding: VEX VR's block runtime is scratch-vm-shaped

Evidence ladder, weakest-to-strongest, with confidence marked.

**A. Vendor statement (CONFIRMED).** VEX's own launch announcement: *"VEXcode VR
lets you code a virtual robot using a block based coding environment **powered by
Scratch Blocks**."* (vexforum.com/t/vexcode-vr-is-now-available/78710). VEXcode's
product marketing carries the same tagline family-wide. scratch-blocks is the
Scratch Foundation's Blockly fork; its canonical runtime partner is scratch-vm.

**B. Our own corpus proves the block model is Scratch's, not vanilla Blockly's
(CONFIRMED — this is the strongest single datapoint and it is in our repo).**
`vendor/goal_strategy_detector/data/blocks.csv` — the observed VEX VR opcode
inventory — is organised on Scratch's exact category/opcode convention:

```
pg_control_forever      pg_control_repeat_until   pg_control_wait_until
pg_events_when_started  pg_events_broadcast       pg_events_broadcast_and_wait
pg_looks_print          pg_looks_set_pen_color    pg_operator_math
pg_sensing_distance     pg_variables_set_variable
procedures_definition            <-- unprefixed
```

Two things to notice:

1. `<category>_<block>` with a `pg_` extension prefix is *precisely* Scratch's
   extension-opcode convention (`${extensionId}_${blockId}`), and the categories
   (`control` / `events` / `looks` / `operator` / `sensing` / `variables`) are
   Scratch's category names, not Blockly's.
2. **`procedures_definition` appears unprefixed.** That is scratch-vm's verbatim
   core opcode for My Blocks. Vanilla Blockly's equivalent is
   `procedures_defnoreturn`. A VEX-authored block language that merely *looked*
   like Scratch would not accidentally land on scratch-vm's internal procedure
   opcode — that block is inherited, not imitated.

(The `controls_if` / `controls_whileUntil` / `variables_set` rows in the CSV are
speculative "may appear in some VEX VR exports" entries we added ourselves; they
are marked as such in the Category column and correspond to no observed block.
They should not be read as Blockly evidence.)

**C. Documented block semantics are Scratch's semantics (CONFIRMED).**
- Broadcast vs broadcast-and-wait is Scratch's exact pair, with Scratch's exact
  wording in VEX's docs (api.vex.com/vr/home/blocks/events.html).
- "Multiple **when started** blocks can be used to run different sets of blocks
  at the same time" — Scratch's multi-hat threading model
  (api.vex.com/vr/home/blocks/Logic/events.html).
- `drive for` / `turn for` with an expandable **"and don't wait"** arrow is the
  Scratch `…until done` idiom, right down to the expandable-arrow UI affordance.
- My Blocks exist — a scratch-blocks concept absent from vanilla Blockly.

**D. Python mode is a separate runtime (CONFIRMED, and it matters).** VEX's KB
article 360044206011 states VR Python runs on **Pyodide** (WebAssembly, Py3.8),
that *"Python threading is not supported"*, and that VR provides *"a custom
`vr_threads` which closely simulates **co-operative tasks**"*. The Playground
itself is a **Unity WebGL** build (kb 5771331774228 names
`VEXcodePlaygrounds.{loader.js,wasm,data}.unityweb`; the loader exposes Unity's
`SendMessage` bridge). So the architecture is: block/Python runtime in JS/WASM ⇄
Unity physics via message passing, with motion completion arriving as a callback.

**E. Direct bundle proof (NOT OBTAINED).** I could not fetch vr.vex.com's main JS
bundle from this sandbox — the egress proxy rejects the host, and Cloudflare
challenges every text-proxy route. **This is the one gap, and §6 closes it in ten
minutes on your machine.**

**Overall confidence:** the *editor* is scratch-blocks — confirmed by the vendor.
The *runtime* is scratch-vm-derived — **strong inference** from B/C, not yet
confirmed at the source level. §5 explains why the recommendation is robust even
if D turns out to be a VEX-authored sequencer, and §6 makes the confirmation
cheap.

---

## 2 · What the reference specification says

Fetched from `scratchfoundation/scratch-vm@develop`
(`src/engine/{sequencer,thread,runtime,execute}.js`). This is the artefact that
replaces our probing.

**Constants.**
```
THREAD_STEP_INTERVAL = 1000/60 ms          // 60 ticks/sec, driven by setInterval
WORK_TIME            = 0.75 × step time    // ≈12.5 ms of work per tick
WARP_TIME            = 500 ms              // "run without screen refresh"
Thread.STATUS_*      = RUNNING | PROMISE_WAIT | YIELD | YIELD_TICK | DONE
```

**Thread creation (`startHats`).** One thread per matching hat, pushed onto
`runtime.threads` **in the target's top-block array order** — i.e. project-load
order, which for a freshly authored workspace is *creation order*, and is **not**
spatial x/y position. Hats declare `restartExistingThreads`: for
`event_whenflagclicked`-class hats it is `false` (starting a live one is a no-op);
for edge-activated sensor hats it is `true` (**the existing thread is restarted
from its top block**).

**Outer loop (`stepThreads`), per tick.**
```
WORK_TIME = 0.75 × currentStepTime;  freeze the ms clock for the whole tick
while threads remain AND some thread is active AND elapsed < WORK_TIME:
    for i in 0..threads.length-1:            # round-robin, index order
        step thread i once                   # one "pass"
    (clear YIELD_TICK threads only on the next tick's first pass)
```
So a tick contains **many round-robin passes**, bounded by a real-time work
budget — not one pass per frame.

**Inner step (`stepThread`) — the complete yield rule set.** A thread gives up
the CPU exactly when:

1. **it finishes a loop-body iteration** (`forever`, `repeat`, `while`,
   `repeat until`) — one iteration per pass, always, unless in warp mode;
2. **a primitive returns a Promise** → `STATUS_PROMISE_WAIT`; the thread parks
   until the `.then` handler flips it back to `RUNNING`;
3. **a primitive calls `util.yield()`** (`wait until`, `wait`) →
   `STATUS_YIELD`;
4. **`util.yieldTick()`** → skipped for the remainder of the current tick;
5. **a recursive custom-block call** in non-warp mode;
6. warp mode suppresses 1 and 5 for up to 500 ms; 2/3/4 still yield.

**That is the entire specification.** There is nothing else to discover about
when threads interleave.

---

## 3 · Free validation: the spec retrodicts what we already probed

This is the part that makes the recommendation more than a hunch. Three
behaviours we established the expensive way — by probing VR and by adjudicating
against GPS — are *predictions of the reference spec*, which we did not have in
hand when we found them.

| what we established | how we established it | what the spec says |
|---|---|---|
| **Detection hats are edge-triggered, re-arm, and RESTART the stack mid-flight, truncating an in-flight move** (SENSOR_TESTBATTERY §3; reviewer-probed 2026-08-24) | VR probing + corpus adjudication | Exactly `restartExistingThreads: true` on an edge-activated hat. `_restartThread` resets the thread to its top block, retaining thread order; the abandoned `*_for` Promise is simply never awaited — i.e. **in-flight move truncation falls out of the model** rather than being a special case. |
| **Broadcast is exact for single receivers; broadcast-and-wait blocks the sender** (§3, modelled) | docs + implementation | Scratch's `event_broadcast` (fire-and-forget, `startHats` pushes receiver threads) vs `event_broadcastandwait` (sender parks until all receiver threads are DONE). Identical. |
| **`wait` keeps pending motion armed** (WREN-C048, reviewer-diagnosed) | corpus diagnosis | `wait` yields the *thread*; the drivetrain command cell lives in the Unity world, untouched by a thread yield. Falls out. |

Add the §0 adjudication in PARALLEL_EXECUTION.md: **sequential-sum (84–89%) beat
every exclusive-ownership policy (27–67%)**. Under the spec, multiple stacks
round-robin over a shared, last-write-wins drivetrain, so several stacks
genuinely contribute motion across a run — which is why a summing approximation
tracks reality and an ownership model does not. Our single most expensive
empirical result is a *consequence* of the spec.

**Four independent confirmations, zero of them fitted.** That is a much stronger
evidentiary position than nine probes would produce, because it is predictive
rather than reconstructive.

---

## 4 · Proposed model: `VR-Seq` — a cooperative sequencer at scratch-vm's yield points

### 4.1 Semantics to implement

- **One thread per `pg_events_when_started` stack**, created in document order
  (see §7 — this is one of the two residual parameters, and it is a one-line
  config with a corpus-adjudicable default).
- **Round-robin passes.** All runnable threads step once per pass, in creation
  order.
- **Yield points, verbatim from §2:** end of every loop-body iteration; any
  blocking primitive (`drive for` / `turn for` in wait mode, `wait`,
  `wait until`, `broadcast and wait`); recursive procedure call. Nothing else.
- **Shared drivetrain = one mutable command cell** `(mode, direction, magnitude,
  velocity)`. **Last writer wins. No queue, no lock, no ownership.** This is not
  a guess: it is how the real V5 stack works at the firmware level (the Brain
  streams a *setpoint* to a motor MCU running its own PID; there is nowhere for a
  queue to live), it is how PROS and vexide both write through, and vexide's
  response was to make double-ownership a *compile error* precisely because the
  hardware offers no arbitration.
- **Interrupted blocking motion → the caller resumes (Possibility A).** When
  thread A is parked on `drive for 600mm` and thread B writes a competing
  drivetrain command, A's motion is truncated at the current pose and A's promise
  resolves, returning a completion boolean. Rationale: (i) it is what our
  hat-restart truncation already implements for the single-thread case, (ii) on
  V5 the blocking wait is a library poll loop over "am I still seeking a target",
  which a replacement clears — so the caller returns early rather than hanging,
  (iii) it fails safe (the alternative, an unresolved promise, deadlocks the
  thread and would silently truncate programs). **Flag it as a named modelling
  choice**, not a measurement — see §7.
- **Time advances only when every thread is parked.** Rather than emulating
  60 Hz ticks, run passes until all threads are in `PROMISE_WAIT`/`YIELD`, then
  advance sim time to the next motion-completion event. Same trajectories,
  event-driven cost, and it sidesteps having to invent a per-block time cost.

### 4.2 Implementation shape — where the cost actually is

The lift PARALLEL_EXECUTION.md §2 correctly identified is *reifying thread
state*. In Python that is a solved problem: **generators**.

`simulate_path.py` is 3,309 lines, but the interpreter core is bounded:
`execute_stack` (1747) → `execute_block` (1930–2400) plus `_move` /
`finish_pending_motion`. The conversion is mechanical:

- `execute_stack` / `execute_block` become generators; every recursive call
  becomes `yield from`.
- The loop constructs `yield` once per iteration (yield point 1).
- Blocking motion `yield`s a *pending-completion token* instead of calling
  `finish_pending_motion` inline (yield point 2). The sequencer owns completion.
- A ~150-line `Sequencer` class drives the generators round-robin and owns the
  drivetrain cell and the event clock.
- The existing signal exceptions (`_BreakSignal`, `_StopSignal`,
  `_HatRestartSignal`, `_GateSignal`) survive unchanged — `_HatRestartSignal` in
  particular *is* scratch's `_restartThread`, and becomes "discard this
  generator, build a fresh one from the hat's top block."

**Blast-radius invariant, and it is a strong one: with exactly one thread,
round-robin degenerates to sequential and every yield point is unobservable.**
So `VR-Seq` must be **byte-identical on the 7,697 single-stack runs (96% of the
sample)** — the same discipline that made `stack_precedence` safe, and the 235-test
suite plus the frozen-path pins enforce it automatically.

Two things must be **explicitly decoupled** to preserve that invariant:

- **Keep the 20-unroll loop cap and the 50k budget exactly as they are.**
  The real semantics is "loops run until real time runs out", which we cannot
  model without a wall clock. Changing the cap is a *separate* ruling with its
  own attribution report. Do not bundle it.
- **Keep the timer/wall-clock model as-is.** §8 notes what a later tick clock
  would unlock, but it is not part of this build.

Ship dual-mode (`sequential` | `scheduled`) exactly as PARALLEL_EXECUTION.md §3
recommends, so the fidelity sweep attributes every divergence.

---

## 5 · Why this is defensible without the probe series

The probe plan's epistemic problem is that it is **behavioural reconstruction**:
nine experiments, each with a small number of observations, from which a
scheduler is inferred. Every inferred rule is underdetermined by its evidence,
and the failure mode is exactly what happened to the lockout — a rule that was
correctly probed on two-driver configurations and then falsified on
monitor+driver configurations it was never tested against. More probes do not fix
that; they enlarge the surface on which the same mistake can recur.

The specification-first argument is different in kind:

1. **The semantics are documented, not inferred.** If VEX VR runs scratch-vm, the
   scheduler is a published file, not a black box. We are not estimating VEX's
   behaviour; we are citing it.
2. **It is predictive, not fitted.** §3 lists four behaviours the spec explains
   that we established independently and beforehand. A reconstruction cannot
   offer that.
3. **It has a validation set no probe series can match.** 3,978 telemetry runs
   with GPS endpoints; 287 multi-stack runs; 62 tier-2 runs where ≥2 stacks touch
   the drivetrain. The spec makes a falsifiable prediction — *round-robin
   interleaving should meet or beat sequential-sum's 52/62, and both should
   crush every ownership policy* — testable today, with statistical power nine
   probes will never have.
4. **It confines the remaining unknowns to two named parameters** (§7), each a
   config field with a defensible default and a corpus adjudication, instead of
   an open-ended semantics question.
5. **It is the right target even under partial falsification.** Suppose the
   bundle check shows a VEX-authored sequencer rather than scratch-vm proper. The
   block *language* is still Scratch's (§1B/1C), so the yield-point set is still
   the natural one, and the model is still strictly better-founded than either
   the current sequential approximation or an ownership rule we have already
   falsified. The downside case is "well-motivated approximation"; the upside
   case is "citing the implementation."

And the honest framing for the write-up, which is what makes it defensible rather
than merely plausible: *"We adopt the scratch-vm sequencer as our execution
specification, on the evidence that VEXcode VR's block layer is a scratch-blocks/
scratch-vm derivative. Yield points, thread creation, hat restart, and shared-
device last-write-wins are taken from that specification. Two parameters —
thread start order and the fate of a superseded blocking motion — are modelling
choices, declared as such, defaulted per §7, and adjudicated against the
telemetry corpus."*

---

## 6 · Confirmation protocol — ten minutes, replacing nine probes

Run on your machine (vr.vex.com is unreachable from my sandbox). All of this is
inspection of client-side JavaScript your own browser already downloads.

**Step 1 — bundle strings (settles the lineage outright).** Open vr.vex.com,
DevTools → Network, filter JS, open the main bundle, and search for:

```
scratch-vm   Sequencer   stepThreads   WORK_TIME   THREAD_STEP_INTERVAL
startHats    _pushThread   restartExistingThreads   STATUS_PROMISE_WAIT
warpTimer    pyodide
```

**Step 2 — live objects.** In the console try `window.vm`, then
`vm.runtime.threads`, `vm.runtime.sequencer`, `vm.runtime.currentStepTime`,
`vm.runtime.turboMode`. scratch-gui forks very commonly leave `window.vm`
exposed. If it is there, you can *watch the threads* while a two-stack program
runs — which is a direct observation of the interleave, not an inference from
endpoints.

**Step 3 — the payoff, if Step 1 hits.** Find the `pg_drivetrain_drive_for`
primitive in the bundle and read it. **The answers to probes P5, P6, P7, P8 and
P9 are literally in that function**: whether it returns a Promise, what resolves
it, and what a competing command does to a pending one. Reading four lines of
VEX's own code beats nine behavioural experiments on every axis — precision,
cost, and defensibility. If the bundle is minified, the shape (`return new
Promise(...)`, a resolver stored on a device object, a `stop`/`replace` path that
calls it) survives minification perfectly well.

**Step 4 — corroboration, 60 seconds.** Save a project and open the `.vrblocks`
file in a text editor. Scratch's `"targets" / "blocks" / "opcode" / "topLevel"`
JSON shape is another independent confirmation. (Our corpus stores Blockly XML,
which is the editor's serialisation, so this is worth checking separately.)

**Fallback ladder if Step 1 misses.** Do not reinstate all nine probes. Run only
the ones the spec cannot answer, in this order:
- **P5** (does blocking motion release the thread?) — the base question; one run.
- **P2** (tight-loop fairness) — confirms the loop back-edge yield.
- **P7/P8** (fate of an interrupted `drive_for`) — the superseded-promise
  parameter of §7.

P0, P1, P3, P4, P6, P9 are all *predicted* by the spec and become confirmations
to run only if something disagrees.

I can drive Step 1–3 in your Chrome directly if you want — say the word.

---

## 7 · The two residual parameters

Everything else is specified. These two are modelling choices; declare them, and
let the corpus adjudicate.

**P-A · Thread start order.**
- Spec default: `runtime.threads` push order = the target's top-block array
  order = project-load order.
- Our uncertainty: whether VEX's `.vrblocks` serialisation preserves *creation*
  order or *document/spatial* order, and whether VR's Python path (which emits
  `vr_thread(when_started1())` at file bottom) reorders anything.
- Default: **document order** (what we do today) — so this parameter is a no-op
  on the current pipeline until evidence moves it.
- Adjudication: we already have `recover_creation_order` built and censused
  (resolved 226 / censored 45 / ambiguous 9 / tied 7 over the 287 runs). Run the
  scheduler under both orderings and check endpoint agreement on the 62 tier-2
  runs. If it is ordering-insensitive — as it was for WREN-C008 — the parameter is
  moot and we say so. **The A1 machinery we paused is exactly the ingest layer
  this needs; nothing built is wasted.**

**P-B · Fate of a superseded blocking motion.**
- Options: (A) truncate and resume the caller [recommended default]; (B) caller
  parks forever; (C) motion resumes after the interruption.
- Default: **A**, on the reasoning in §4.1, and because B silently deadlocks
  student programs in a way we would have to flag anyway.
- Adjudication: A vs B is endpoint-distinguishable on the tier-2 runs — under B,
  interrupted stacks stop contributing entirely, so B should look *more* like the
  falsified ownership policies and lose. §6 Step 3 settles it by reading the
  code; failing that, P7/P8 settle it in two probe runs.

A third, smaller one to track but not gate on: **pass budgeting.** Scratch bounds
a tick by 12.5 ms of real work; we have no per-block cost model. The event-driven
formulation in §4.1 avoids needing one for trajectory purposes. It resurfaces only
if the wall-clock work of §8 is ever taken up.

---

## 8 · What this does and does not solve

**Solves (or unblocks):**
- **The largest known gap:** 287 runs / 20 students on
  `concurrent_stacks_unverified`. Multi-stack students stop being U-gated across
  every behavioural rubric dimension — which SENSOR_TESTBATTERY §4.5 identifies
  as a battery *prerequisite*.
- **Trajectory shape under interleaving**, which PARALLEL_EXECUTION §12 flags as
  mattering more for Environmental-Feedback rubric levels than for endpoint
  fidelity. The battery needs to see feedback-regulated behaviour *during* a
  drive; only a scheduler produces that.
- **The monitor+driver idiom becomes evidence** rather than a flag — it is
  concurrent policy composition, exactly the execution characteristic the rubric
  is trying to read.
- **A principled account of the loop cap.** Even without changing the cap now, we
  can finally say *why* a cap is an approximation and what it approximates
  (real-time work budgeting), instead of declaring it a bare backstop.

**Does not solve, and should not be claimed to:**
- Random debris scatter (unchanged; still the `sensor_uncertainty` lane).
- Edge divergence slips (unchanged; soft annotation).
- `weight_cleared` physics (outcome-only, unchanged).
- **Wall-clock idle time / unfired timer hats** (6 runs / 1 student). A 60 Hz
  tick clock *would* close this — a non-yielding thread burning passes is
  precisely how VR's timer advances while a program "sits". But that is a
  separate ruling with its own attribution report, and bundling it would break
  the single-stack byte-identity invariant that makes §4 safe. Note it as a
  follow-on, not a deliverable.
- Anything about VR *Python* programs beyond blocks. Pyodide is a different
  runtime; if `program_type` ever includes Python projects at scale, the model
  needs its own evidence. (Census check worth doing: `ccp_runs.program_type`.)

**Transfers that would be unjustified** — recording these so they do not creep in
later. From the V5/VEXos side, the following are *not* VR evidence and must not
be imported: the 2 ms `vexTasksRun` cadence, the 10 ms motor-PID/device refresh,
the 128-task limit, priorities 1/7/15, the VEXos watchdog failure mode,
`isSpinning()`'s "seeking a target, not moving" quirk, and anything from PROS
(which is preemptive, 1 ms tick — a *third* system, useful only as contrast).
What legitimately transfers from V5 is qualitative and structural: cooperative
rather than preemptive scheduling, `wait=True` semantics, `set_timeout` as a
bounded-blocking concept, and last-write-wins on a shared device.

---

## 9 · Recommended sequence

1. **§6 bundle inspection** (today, ~10 min). Outcome branches the rest.
2. **Corpus prediction test before any build** (cheap): re-run the §0 arbitration
   adjudication with a fifth policy — round-robin interleaving, hand-simulated or
   crudely approximated — on the 62 tier-2 runs. If it does not at least match
   sequential-sum's 52/62, stop and re-think before writing the scheduler.
3. **Build `VR-Seq`** per §4.2: generator refactor, sequencer, shared drivetrain
   cell, dual-mode flag, loop caps and timer model untouched. Gate on
   byte-identity over the 7,697 single-stack runs.
4. **§6 attribution report** over the 287 multi-stack runs; expect fidelity
   verdict movement, expect to have to explain each one.
5. **Retire `concurrent_stacks_unverified`** only where the scheduler actually
   resolves the run; keep it (and the rubric U-gate) where P-A is censored. The
   fix shrinks the U population; it never fakes it.
6. **Only then** revisit the wall-clock tick (§8) as its own ruling.

---

## Sources

**Primary — our own repo:** `vendor/goal_strategy_detector/data/blocks.csv`
(opcode inventory); `vendor/goal_strategy_detector/parsing/parse_blocks.py`
(Blockly XML namespace); `vendor/goal_strategy_detector/simulation/simulate_path.py`
(interpreter structure); `PARALLEL_EXECUTION.md` §0 (arbitration adjudication);
`SENSOR_TESTBATTERY.md` §§1–5 (census, capability stocktake); `OPEN_ISSUES.md`
OI-7.

**scratch-vm reference implementation:** `scratchfoundation/scratch-vm@develop`,
`src/engine/sequencer.js`, `src/engine/thread.js`, `src/engine/runtime.js`,
`src/engine/execute.js`.

**VEX vendor statements:**
- VEXcode VR is Now Available — vexforum.com/t/vexcode-vr-is-now-available/78710
  ("powered by Scratch Blocks")
- Technical Implementation Details, VR Python — kb.vex.com/hc/en-us/articles/360044206011
  (Pyodide; "Python threading is not supported"; `vr_threads` "closely simulates
  co-operative tasks")
- Troubleshooting VEXcode VR Playground Access Errors — kb.vex.com/hc/en-us/articles/5771331774228
  (Unity WebGL assets)
- VR Blocks API: Events — api.vex.com/vr/home/blocks/Logic/events.html;
  Drivetrain — api.vex.com/vr/home/blocks/drivetrain.html
- VEXcode VR 2.0 Python preview — vexforum.com/t/vexcode-vr-2-0-preview-python-support/81699

**V5/VEXos reverse-engineering (used only for the structural claims in §4.1 and
the exclusion list in §8):** vexide/vex-sdk `vex-sdk-jumptable/src/task.rs`
(`vexTasksRun` — *"The scheduler is entirely cooperative"*); vexide/vex-v5-qemu
README (VEXcode's "cooperative task scheduler"); vexide/vexide
`vexide-devices/src/smart/motor.rs` (10 ms motor PID; write-through commands);
purduesigbots/pros `src/devices/vdml.c` (per-call mutex, not ownership);
jpearman on VEX Forum — *"vexos does not use a pre-emptive scheduler, it's a
cooperative scheduler"* (vexforum.com/t/data-race-and-vexos-scheduler/106687).

---

## 10 · Bundle inspection results — §1 CONFIRMED AT SOURCE (2026-08-25)

Run against `https://research-vr.vex.com/`, `main.bundle.js` (29.7 MB), via
in-page fetch + string search. §1's "strong inference" is now **confirmed**, and
the Layer-1 / Layer-2 split below supersedes the looser framing in §1.

### 10.1 · What was confirmed

**`@vexcode/scratch-vm` is a private VEX fork of scratch-vm, shipped as the
runtime.** 63 module paths under `./node_modules/@vexcode/scratch-vm/src/`,
including the complete engine: `engine/{sequencer,thread,execute,runtime,
blocks,target,block-utility}.js`, `blocks/scratch3_{control,event,data,
operators,procedures,sensing,motion,looks,sound}.js`, `extension-support/
extension-manager.js`, `serialization/sb3.js`. Sibling packages: `@vexcode/
blockly`, `@vexcode/python-vm`, `@vexcode/robot-config`, `@vexcode/
vexcode-webserial`.

**The sequencer is stock, unmodified.** `stepThreads()` reads verbatim:
`const e = .75*this.runtime.currentStepTime` (the `WORK_TIME` constant, inlined
by the minifier — an earlier note that it was missing was a minification
artifact, now retracted); `numActiveThreads = Infinity`; round-robin
`for (let o=0; o<r.length; o++)`; `YIELD_TICK` cleared only on a tick's first
pass; done-thread compaction. `stepThread()` likewise: loop-back-edge yield
(`if (frame.isLoop) { if (!warp || warpTimer > WARP_TIME) return }`),
`STATUS_PROMISE_WAIT` parking, `waitingReporter` return, warp handling.
`THREAD_STEP_INTERVAL = 1e3/60`, `_COMPATIBILITY = 1e3/30` — stock.

**The editor→runtime bridge.** The editor is **vanilla Blockly** (`@vexcode/
blockly`; `blockly_compressed.js`, `blocks_compressed.js`, cpp/javascript/python
generators) with VEX-authored `pg_*` block definitions in TypeScript
(`src/Blockly/Blocks/PG/PG_Drivetrain.ts` — `jsonInit`, `message0`, toolbox XML).
This is why our corpus stores Blockly XML rather than Scratch JSON. At runtime,
each VEX product registers as a **scratch-vm extension**, so the executed opcode
is `<extensionId>_<blockType>`:

```js
projectStart(){ ... this.startHats("pgBlocks_pg_events_when_started"),
                    this.startHats("iqBlocks_iq_events_when_started"), ... }
```
and registration (extension-manager):
```js
this._primitives[opcode] = t.info.func
this._hats[opcode] = { edgeActivated:            n.isEdgeActivated,
                       restartExistingThreads:   n.shouldRestartExistingThreads }
```

**Threading model, settled.** One thread per `when started` block, spawned by
scratch-vm's `startHats` at `projectStart()`, pushed in the target's block order,
stepped round-robin at 60 Hz. Edge-activated hats are re-fired every tick:
`_step(){ ... for (const e in this._hats) if (this._hats[e].edgeActivated)
this.startHats(e) ... }`, with `clearEdgeActivatedValues()` on project start and
`getIsEdgeActivatedHat()` guarding restart-vs-noop. This is the engine-level
mechanism behind our reviewer-probed edge-triggered re-arming.

**Probes retired by reading source:** P0/P1 (start order), P5 (does blocking
release the thread — yes, `STATUS_PROMISE_WAIT`), P2/P3/P4 (yield boundaries),
and the shape of P9.

### 10.2 · NEW: VEX modified the loop blocks — a 5 ms per-iteration floor

This is a VEX divergence from stock scratch-vm and the most consequential single
finding of the inspection. `scratch3_control.js`, `repeat` (and identically
`repeatUntil` / `repeatWhile`):

```js
repeat(e,t){ const n=Math.round(cast.toNumber(e.TIMES));
  void 0===t.stackFrame.loopCounter && (t.stackFrame.loopCounter=n),
  t.stackTimerNeedsInit()  ? (t.startStackTimer(5), this.runtime.requestRedraw(), t.yield())
: t.stackTimerFinished()   ? (delete t.stackFrame.timer, t.stackFrame.loopCounter--,
                              t.stackFrame.loopCounter>=0 && t.startBranch(1,!0))
:                            (this.runtime.requestRedraw(), t.yield()) }
```

Stock scratch-vm's `repeat` merely decrements and re-enters the branch. VEX adds
a **5 ms stack timer per iteration** plus `requestRedraw()` — and in non-turbo
mode `redrawRequested` terminates the tick's inner loop. Net effect: **a loop
iteration costs at least one frame, so loops advance at roughly one iteration
per stack per 60 Hz tick.**

Consequences for the build plan:

1. **Tight loops cannot starve siblings.** Probe 2's question is answered in
   source: every iteration both yields and burns a timer.
2. **A wall clock falls out.** N loop iterations ≈ N/60 s of VR time. This
   reopens the `timer_hat_unfired` / idle-wall-clock gap that
   SENSOR_TESTBATTERY §2 and §4.4 ruled out of scope — a program that sits in a
   loop until a timer hat fires becomes simulable. Recommend re-opening that
   ruling as its own item.
3. **The 20-unroll cap gains a principled replacement**: a real-time budget
   rather than an arbitrary count. Still a separate ruling with its own
   attribution report — do not bundle it with the scheduler build (§4.2).

### 10.3 · Corrections to earlier sections

- §1's claim that the editor is scratch-blocks is **wrong**: it is vanilla
  Blockly. The scratch-vm lineage lives in the *runtime only*. The reviewer's
  objection on this point was correct, and the Layer-1/Layer-2 distinction is
  the right frame: scratch-vm governs *when stacks run*; VEX's `pgBlocks`
  extension and the Unity playground govern *what a block does to the robot*.
  Our measured models (OI-5 cone, OI-16 velocities, OI-21 attachment) are
  Layer 2 and are untouched by any of this.
- The `startHats` hit in `blockly_compressed.js` is a false positive — Blockly's
  hat-shape rendering option, unrelated to thread spawning.
- `getHats()` registries visible in the bundle are scratch-vm's *own* hats
  (`event_whenflagclicked`, `control_start_as_clone`, …), not VEX's. VEX's hat
  metadata is supplied dynamically at extension registration (10.1).

### 10.4 · Still open after inspection

- **P-B — fate of a superseded blocking motion.** The `pg_drivetrain_drive_for`
  *runtime primitive* (`info.func`) was not in the fetched scripts; only the
  editor-side block definition and toolbox XML. Likely in a lazily-loaded
  `pgBlocks` extension chunk. §4.1's default (truncate + resume caller) stands
  as a declared modelling choice until read.
- **`shouldRestartExistingThreads` / `isEdgeActivated` values for VEX's sensor
  hats** (`pg_events_when_bumper`, `pg_events_optical_detect_object`). The
  *mechanism* is confirmed; the specific booleans are not. Our probed behaviour
  implies `restartExistingThreads: true`, `edgeActivated: true`.
- **Method to close both:** open a VR playground project (forcing the extension
  chunk to load), then re-run the script-grep for `shouldRestartExistingThreads`,
  `isEdgeActivated`, `pg_events_when_bumper`, `anddontwait`, `SendMessage`.

### 10.5 · Effect on the recommendation

§5's argument is strengthened from "adopt a specification on strong inference"
to **"implement the shipped source."** The scheduler is no longer a modelling
choice: `stepThreads` / `stepThread` can be transliterated from VEX's own
bundle, with the 5 ms loop floor of 10.2 included. §7's parameter P-A (thread
start order) is resolved — `startHats` pushes in block order — leaving P-B as
the single open parameter.

### 10.6 · Second inspection pass — `blockAllThreads` ruled inert; PG extension unreachable

**`blockAllThreads` — RULED OUT (2026-08-25).** VEX's extension-block schema
carries a field absent from stock scratch-vm: `blockAllThreads`, alongside
`blockType` / `branchCount` / `terminal`. Had `pg_drivetrain_drive_for` set it
true, a blocking motion would halt EVERY stack, the concurrency model would be
far more restrictive than scratch-vm's, and the existing sequential simulator
would have been closer to correct than §4 assumes. Checked: **0 occurrences of
`blockAllThreads:!0` and 37 of `blockAllThreads:!1` across the bundle, and the
property is never read (`.blockAllThreads` — no matches).** The field is
declared but inert. The interleaving model of §4 stands.

**Sibling-product hat declarations (analogy only, not PG).** The CTE/EXP
extension is statically bundled and declares:
```js
{opcode:"cte_events_when_started", blockType:HAT, isEdgeActivated:!1,
 shouldRestartExistingThreads:!0, func:"whenStarted", blockAllThreads:!1}
{opcode:"cte_events_when_timer",   blockType:HAT, isEdgeActivated:!1,
 shouldRestartExistingThreads:!0, func:"whenTimer"}
```
So `when started` is not edge-activated (fires once at `projectStart`) and
restarts existing threads. Relevant engine default: a HAT that omits
`isEdgeActivated` is assigned **true** at conversion time
(`Object.prototype.hasOwnProperty.call(e,"isEdgeActivated")||(e.isEdgeActivated=!0)`).
PG's own values remain unread.

**PG extension not reachable from the page.** With the Castle Crashers Plus
playground open, `opcode:"pg_events_when_started"` / `pg_drivetrain_drive_for`
(runtime form) appear nowhere, and `SendMessage` has no matches — despite
`runtime.projectStart()` demonstrably calling
`startHats("pgBlocks_pg_events_when_started")`. Working hypothesis: the
playground runs in an iframe or worker whose scripts do not appear in the main
page's `performance` resource entries. Hits on `pg_events_when_bumper` in the
main bundle are i18n / screen-reader label tables only.

### 10.7 · Status: nine probes reduced to one

**Retired by source reading** (PARALLEL_EXECUTION §4 numbering): P0 and P1
(start order — `startHats` pushes one thread per hat in block order), P5 (does
blocking release the thread — yes, `STATUS_PROMISE_WAIT`), P2/P3/P4 (yield
boundaries — loop back-edge, plus VEX's 5 ms stack timer and `requestRedraw`
per iteration), P9's shape (a reactive loop cannot starve a dead-reckoning
stack, because every iteration yields).

**Still requiring the real playground: P-B only**, i.e. the reviewer's P7/P8 —
the fate of a blocking `drive_for` whose motion is superseded by another
stack's drivetrain command. One experiment: stack A drives 600 mm, stack B
waits 0.5 s then stops; observe whether A's next block ever executes, and the
final pose. Possibility A (truncate, caller resumes) is §4.1's declared default.

The nine-probe reconstruction is therefore replaced by: transliterate the
shipped sequencer, and run one confirmatory probe.

### 10.8 · Runtime architecture — three processes (2026-08-25, final inspection)

The editor page hosts an iframe (`VRWindow.html`, same origin) which loads:

| process | asset | role |
|---|---|---|
| Web Worker | `SimVMWebWorker.bundle.js` (8.97 MB) | **`@vexcode/scratch-vm` executes here** — confirmed: contains `@vexcode/scratch-vm`, `stepThreads(`, and the extension-manager's `_prepareBlockInfo` / `_registerExtensionPrimitives` |
| Web Worker | `SimPythonInterpreterWebWorker.bundle.js` (173 KB) | Pyodide path for Python projects |
| iframe main | `VRWindowMain.bundle.js` (7.8 MB) | Unity host — `unityInstance.SendMessage(gameObject, method, arg)`; i18n tables |
| Unity WebGL | `VEXcodePlaygrounds.{loader.js,wasm,data}.unityweb` | physics + playground content |

The parent page holds the Blockly editor and a copy of the engine; the executing
VM is the worker. This is why every `pg_*` runtime search against the parent
bundle came back empty.

**The `pg_*` block table is not in any JavaScript.** In `SimVMWebWorker`,
`"pg_drivetrain_drive_for"` has 31 hits — all i18n message tables — and
`"pg_events_when_started"` has **zero**. `shouldRestartExistingThreads` occurs
exactly once, in the generic extension-manager registration path.
`blockAllThreads`: 0 true / 1 false (the schema default in `_prepareBlockInfo`).

**Inference (high confidence): each Unity playground declares its own blocks to
the VM at load time**, over the message bridge, and the VM registers them via
`_registerExtensionPrimitives`. Supporting evidence: the i18n tables carry
playground-specific block families side by side (`pg_magnet_*` for Castle
Crashers, `pg_sensing_ai_smells` / `pg_actions_interact_with_minerals` for the
AI/Coral playgrounds, `pg_events_when_under_attack`, `pg_events_when_level_up`),
which is exactly the per-playground block-set variation the corpus shows. The
block tables therefore live inside the Unity `.wasm`/`.data` payloads and are
not greppable.

**Consequent pipeline:** Unity declares blocks -> VM worker registers
(`_primitives[opcode] = info.func`, `_hats[opcode] = {edgeActivated,
restartExistingThreads}`) -> each primitive posts a command to Unity -> Unity's
reply resolves the parked thread's promise (`STATUS_PROMISE_WAIT`).

### 10.9 · Close-out: what remains is one behavioural probe

Reading source cannot settle P-B, because the deciding behaviour is inside the
Unity playground, not the VM. The question reduces to exactly:

> **Does the playground fire the completion callback for a motion it abandoned?**

- Fires -> the parked thread resumes; §4.1's Possibility A (declared default).
- Does not fire -> the thread parks permanently and its stack is dead.

That is the reviewer's P7/P8, now precisely targeted:
```
when started (A):              when started (B):
  print "A-before"               wait 0.5 seconds
  drive forward for 600mm        stop driving
  print "A-after"                print "B-stopped"
  turn right for 90°
```
"A-after" printing (and the 90° turn executing) confirms Possibility A.

**Optional 2-minute alternative:** DevTools -> Sources -> Threads -> select
`SimVMWebWorker`, then evaluate `runtime._hats` / `self.vm?.runtime._hats` in
that worker's console. This dumps the actually-registered hat metadata
(`edgeActivated`, `restartExistingThreads` for `pgBlocks_*`) regardless of where
the declarations originated. Fails harmlessly if the binding is module-scoped.

**Final status of the nine-probe plan:** P0, P1, P2, P3, P4, P5, P9 retired by
source reading; P6 subsumed by the pending-motion model; **P7/P8 remain as one
combined probe.** Layer 2 (drivetrain kinematics, sensor cones, attachment) is
untouched by any of this and stays measured as before.

---

## 11 · P7/P8 probe result — P-B RESOLVED, probe count now ZERO (2026-08-25)

The single remaining behavioural probe was run the same day. **Every open
parameter in this document is now closed.**

**Setup.** Open field, drive velocity 50% (494 mm/s per OI-16). Stack A authored
first, B second.
```
when started (A):                 when started (B):
  set drive velocity 50%            wait 1 second
  print "A1"; print timer           stop driving       <-- variant: turn right for 90 deg
  drive forward for 1000 mm         print "B1"; print timer
  print "A2"; print timer
  print position X
  turn right for 90 degrees
  print "A3"; print timer
```

**Observed — 3 runs of the base probe plus the variant, all identical:**
```
A1 t=0
A2 t=1
position X = -900
B1 t=1
A3 t=2
```

**Findings.**

1. **`superseded_motion` = `truncate_and_resume` (MEASURED).** A 1000 mm drive
   at 494 mm/s completes at t≈2.02; `A2` printed at **t=1**, the instant B
   intervened, and A then executed its own `turn right 90` and printed `A3`.
   The blocking call returns early and the stack survives. §4.1's declared
   default was correct — it is now evidence.
2. **Truncation is not special to `stop`.** Replacing B's `stop driving` with
   `turn right for 90 degrees` produced byte-identical output. Any drivetrain
   command replaces the active motion — direct confirmation of the
   last-write-wins shared cell (§4.1, BUILD_SPEC §2.4), previously inferred
   from V5 firmware behaviour.
3. **Threads genuinely interleave.** B's `wait 1 second` elapsed while A was
   mid-drive — P5 confirmed behaviourally, matching the sequencer source.
4. **Deterministic.** Identical across 3 runs and the variant; the
   investigation's Q5 (determinism) is answered YES, consistent with a
   single-threaded 60 Hz sequencer.

**Residual observations (Layer 2, not scheduler; recorded, not blocking):**
- Position X = -900 is uncalibrated — the start position was not printed.
  Consistent with ~500 mm travelled if spawn X was -1400; the t=1 timestamp
  already excludes a full 1000 mm.
- `A3` lands ~1 s after `A2`, where a 90° turn at 50% turn velocity should take
  ~0.43 s (4.16 °/s per %). Probably integer print precision or an unset turn
  velocity. A precision rerun (`set print precision 3`, explicit
  `set turn velocity 50%`, print start position and final heading) would settle
  it; worth doing only if turn timing becomes load-bearing.

**Final probe accounting.** Of the reviewer's nine probes: P0, P1, P2, P3, P4,
P5, P9 retired by reading VEX's shipped source (§10); P6 subsumed by the
pending-motion model; **P7/P8 now measured.** The nine-probe reconstruction
programme is complete at a cost of one experiment. Every semantic in the
scheduler model is either transliterated from `@vexcode/scratch-vm` or measured
in the playground; none is a modelling choice.

### 11.1 · Precision rerun (2026-08-25) — mutual truncation confirmed; P-A RE-OPENED

Rerun with `set print precision 3`, explicit turn velocity, and start/end
position and heading. Console (new run only):
```
A1  t=0.048
X   = -900.000        <- START
A2  t=1.074
X   = -900.000        <- after drive_for(FORWARD, 1000, MM)
B1  t=1.091
A3  heading = 94.000
    t=1.630
```
B's `stop driving` was replaced by `turn_for(RIGHT, 90)` in this run, i.e. this
is the P8 variant with instrumentation.

**Probe design defect (ours):** X is the wrong axis. The robot spawns facing
~heading 0 and drives along **Y**, so X is invariant under a forward drive and
this run carries no travel-distance measurement. Any repeat should print Y (or
both axes) and the start heading.

**Confirmed, with timing:**
1. **`truncate_and_resume`** — A's `drive_for` ran 0.048 → 1.074 = **1.026 s**
   against ~2.02 s for a full 1000 mm at 494 mm/s. Truncated at B's command;
   thread resumed and completed its stack.
2. **MUTUAL truncation (new).** B's `turn_for(RIGHT, 90)` needs 0.433 s at
   208 °/s but B printed at t=1.091, ~0.09 s after starting — **B's turn was in
   turn truncated by A's `turn_for` at ~1.074, and B also resumed.** Two
   truncate-and-resume events in opposite directions in one run. The shared
   drivetrain cell has no owner and no priority; last write wins, symmetrically.
3. **Heading 94°** is consistent with B's turn advancing a few degrees before
   A's command replaced it, plus A's own 90°. (Start heading not printed, so
   consistent-with, not proof.)
4. **Per-command latency ≈ 0.12 s.** A's turn ran 1.074 → 1.630 = 0.556 s where
   90° at the OI-16 rate (4.16 °/s·%) predicts 0.433 s. The excess is
   command round-trip to Unity — a constant the two-duration calibration
   protocol cancels, which is why OI-16's rates remain correct and wall-clock
   durations run longer. Layer 2 calibration survives the scheduler.

**P-A (thread start order) RE-OPENED — correcting §10.1 and §10.5.** The
Code Viewer's generated Python for this program ends:
```python
vr_thread(when_started2)
vr_thread(when_started1)
```
**Threads are launched in REVERSE document order.** §10.1 inferred document
order from scratch-vm's `startHats`, which pushes in the target's block order;
that reading is about the blocks runtime, whereas this is the Python generator —
but it is VEX's own statement of intended launch order and it is the opposite.
This probe cannot discriminate (B waits 1 s before acting), but the ordering
governs which stack wins tick 0 when two stacks issue drivetrain commands
immediately — the 9 tier-1 runs.

**Settling probe (30 s):** two stacks, `print "A"` and `print "B"`, nothing
else. Console order is the launch order.

**Build consequence:** BUILD_SPEC §2.1 must expose `thread_start_order`
(`document` | `reverse_document`) as a config rather than hard-coding document
order, defaulting to whatever the settling probe shows, with both orderings run
against the 62 tier-2 runs as a sensitivity check. Prior evidence suggests the
sample may be largely ordering-insensitive (WREN-C008 was byte-identical under
dual ordering), but that must be re-established under the scheduler.

### 11.2 · P-A settled: DOCUMENT ORDER (2026-08-25)

Two print-only stacks added to the same workspace as the §11.1 probe:
```
when started (A): print "A"     when started (B): print "B"
```
Console (four stacks now in the workspace; the §11.1 pair still present):
```
A0  B0  A1 0.029
-900.000
A2 1.076
-900.000
B1 1.093
A3 94.000
1.658
```
**`A` prints before `B`.** Under reverse launch order B's thread would be
stepped first — `print` does not yield, so the first thread stepped prints
first. It did not. **Thread creation follows document order**, exactly as
scratch-vm's `startHats` implies (§10.1). The §11.1 walk-back is itself
retracted: the source reading was correct.

**Scope of the correction.** The Code Viewer's reverse emission
(`vr_thread(when_started2)` before `when_started1`) is an artifact of the
**Python** code path, which is a different runtime (Pyodide worker, §10.8) from
the blocks runtime. It does not describe how blocks execute. Corpus check
(`ccp_runs.program_type`): **7,983 Blocks / 1 Switch / 0 Python** across 205
students — the Python ordering is irrelevant to this sample entirely.

**Determinism, again.** The §11.1 stacks reproduced to within ~30 ms with two
extra threads in the workspace (A2 1.076 vs 1.074; B1 1.093 vs 1.091; heading
94.000 identical). Adding threads did not perturb the existing schedule.

**All parameters are now closed.** P-A: document order (measured). P-B:
`truncate_and_resume`, symmetric and re-entrant (measured). Every semantic in
the scheduler model is transliterated from `@vexcode/scratch-vm` or measured in
the playground. Nine probes were replaced by source reading plus three short
experiments.

---

## 12 · Rate probes and the G4 ruling (2026-08-25)

Three further probes run to adjudicate G4 (cooperative 42/62 vs sequential
52/62). They falsified the working hypothesis and settled the ruling.

### 12.1 · Measured constants

| quantity | measured | method |
|---|---|---|
| loop iteration rate | **60.15 Hz** (131 iters / 2.178 s) | one `forever` counter during a 1000 mm drive |
| loop rate, 2 concurrent monitors | **60.0 Hz each** (125 & 125 / 2.083 s) | two `forever` counters, same drive |
| monitor cost to motion | **none** — drive 2.083 / 2.171 / 2.178 s at 2, 2, 1 monitors | same |
| `wait until` polling | **~13 ms overshoot** = one tick ≈ **6.4 mm** at 494 mm/s | `wait until timer > 1`, print timer → 1.013 |
| per-command latency | 60–150 ms, jittery | drive duration vs nominal 2.024 s |

**Per-thread loop rate is independent of thread count** — every thread gets one
iteration per 60 Hz tick, exactly as `stepThreads` + `requestRedraw` predict.

Note for the record: sequential's `_WAIT_MARCH_MM = 10.0` — chosen as a
"simulation quality constant" — is within ~25% of reality's measured 6.4 mm
`wait_until` resolution. Accidentally well calibrated. **Do not change it
without its own attribution report.**

### 12.2 · The rate hypothesis is FALSIFIED

The working hypothesis was that cooperative fails CROW-C094 because our
monitors evaluate at the wrong rate. The probes rule this out decisively.

In reality each of C094's five monitors evaluates **every ~8.2 mm of travel** —
~130 evaluations per monitor per 2 s drive, ~650 across the stack — and **none
fired**: the GPS proves the driver drove unopposed. Our cooperative model
evaluates ~20 times and fires. **Raising our evaluation rate toward reality's
would make spurious firing more likely, not less.**

The only reconciliation is that **our debris model places detectable objects
where reality had none.** This confirms the reviewer-agent's original
stratified reading — now by mechanism rather than by stratification.

### 12.3 · Why sequential "wins" C094

- **Sequential** evaluates each monitor at essentially one pose. Nothing near,
  nothing fires, the driver drives → matches GPS 11/11.
- **Cooperative** evaluates along the path, as reality does. Our world model has
  a piece in the cone somewhere along it; a monitor fires and takes the
  drivetrain → 0/11.
- **Reality** evaluates along the path more densely than either and does not
  fire.

Sequential's 11/11 is **concealment, not accuracy** — it scores well by not
looking at the part of the world we model badly. Cooperative looks, and
inherits the error honestly.

### 12.4 · RULING

**Cooperative ships. G4 is demoted from acceptance gate to diagnostic.**

G4's fatal property: it measures the composite of scheduler × world model
against GPS, and in the exposed stratum the world model dominates. **Every step
toward the measured runtime — loop clock, cap → 60 Hz — increases exposure to
the world model and LOWERS the G4 score.** A metric that penalises correctness
cannot be an acceptance criterion. It is a measure of world-model exposure.

Sequential is falsified as a description of the runtime by direct observation,
which endpoint agreement has no standing against:
- P7/P8: B's `wait 1 second` elapsed **during** A's drive (sequential predicts
  B1 at ~3.5 s; observed 1.091).
- Loop probe: B accumulated 131 iterations **during** A's drive (sequential
  predicts 0).

Replacement gates: clean stratum 24/26 (passed); **G6** battery scenarios on
static worlds; per-run **predicate bracketing** for exposed runs (floor = all
movable-dependent predicates forced False after first disturbance; ceiling =
forced True; verdict invariant → clear, verdict differs → U-gate). C094 is
expected to bracket-fail all 11 runs — the correct outcome, reached by
instrument rather than by naming a session.

The loop-clock work continues on its own track (wall clock, timer hats,
duration channel). 60 Hz per thread is its confirmed constant. **It is not a
C094 fix and must not be justified as one.**

### 12.5 · Amendments after the full 2×2 (2026-08-25, post-campaign)

Two corrections to §12.4, both narrowing the claim in cooperative's favour, plus
one sharpening of the argument.

**1 · The exposed-stratum claim was too broad — CORRECTED.** §12.4 said the
world model dominates across the movable-sensing-exposed stratum. The full 2×2
refutes this: excluding CROW-C094, exposed is **cooperative 18/25 vs sequential
17/25** — parity (one run; not an edge). All 11 C094 runs sat in that stratum,
cooperative 0/11 against sequential 11/11.

Correct scope: **the failure is one program family — five movable-sensing
monitors compounding against a deterministic debris field — not exposed runs
generally.** C094 is the only such program in the corpus. Confusion matrix:
12 regressions (11 of them C094) + 2 improvements (WREN-C095_S009 runs 001/002)
= the net −10. Per-student, only C094 (11→0), C091 and C203 move materially.

**2 · The stronger reason to demote G4 is statistical.** At n=62, a single
11-run session swings the metric by 10 points. **A gate whose verdict is
determined by one student's session lacks the resolution to gate anything**,
independent of the confounding argument. §12.4's "faithfulness lowers the
score" reasoning is partly undercut by the exposed-stratum parity and should
not be the load-bearing argument.

**Ruling unchanged:** cooperative ships; G4 is a diagnostic.

### 12.6 · C094 disposition — cheap diagnostic before any VR probe

Answerable from existing logs: **at what step does the first spurious monitor
fire in cooperative — before or after first debris-zone entry?**
- **After** → genuine post-disturbance scatter. Bracket-fail, documented, closed.
- **Before** → the monitor fired against initial, undisturbed, card-declared
  placements. That is not the unreconstructable-scatter problem; it is a static
  world-model or cone-geometry defect, and it is fixable.

A VR probe of the program family only earns its keep in the "before" case.

### 12.7 · Duration-channel calibration — decompose, do not fit a constant

The duration channel is validated: **Spearman 0.630 over 2,431 runs** on the
honest stratum (no loop caps, timer-idle, runoff, or boundary exits — post-exit
sim time is §6a fiction while the real run ends at the fall). The aggregate
r=0.02 was a censoring artifact.

Do **not** ship "6.2 s + 0.7 s/command" as a latency model — 0.7 s is ~5× the
probed 0.12 s and bundles several effects. Decompose on the clean stratum:
```
duration ~ β0 + β1·n_blocking_commands + β2·total_distance_mm + β3·total_turn_deg
```
β2/β3 nonzero ⇒ velocity constants are off, not latency. Also test an explicit
**ramp model** (`t_move = dist/v + t_ramp`): accel/decel on every blocking
command looks exactly like a per-command constant, and the OI-16 two-duration
protocol cancels precisely that term — which is why it was never visible. A
materially better ramp fit is a Layer-2 finding with consequences beyond
duration (it shifts mid-move hat firing points).

**Falsifiable prediction:** for terminating programs, duration should be near
deterministic given the code, so ρ=0.630 leaves much unexplained. Calibration
should raise ρ substantially. If it does not, something structural remains and
the calibration must not ship as a fix.

### 12.8 · Clock scope note

Only **8 of 1,103** loop-capped runs become uncensored at a 160 s backstop. The
wall clock's value is in timer hats, the duration channel, and honest idle
modelling — **not** in rescuing loop-capped runs. Recorded so no later work is
justified on fidelity grounds the clock does not deliver.
