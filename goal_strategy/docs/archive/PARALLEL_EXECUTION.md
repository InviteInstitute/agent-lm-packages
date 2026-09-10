# PARALLEL_EXECUTION — simulator review against the VEX VR parallel-execution investigation

Response (2026-08-25) to the reviewer's "VEX VR Parallel Execution: Known
Behavior, Hypotheses, and Open Questions" (design_instructions). Compares
each area of that document against the simulator's current architecture:
where we already match, where we differ, and what our data can already
adjudicate. Ends with the empirical result that reshapes OI-7 and a
recommendation.

## 0 · The headline empirical result (our data speaks to §7/§12)

We ran the arbitration adjudication the investigation makes possible: for
every live telemetry run where ≥2 `when_started` stacks drive, simulate
under four policies and score off-island agreement against the real GPS.

| policy | tier 1: ≥2 stacks drive UNCONDITIONALLY (n=9) | tier 2: ≥2 stacks with any drivetrain, monitors included (n=62) |
|---|---|---|
| sequential sum (current sim) | **8/9 (89%)** | **52/62 (84%)** |
| first-stack-wins lockout | 3/9 (33%) | 17/62 (27%) |
| last-doc-stack-wins lockout | 6/9 (67%) | 26/62 (42%) |
| newest-created-wins (gated map only) | 6/7 | 12/13 |

**Every exclusive-ownership policy loses badly to the sequential-sum
approximation.** This is evidence FOR the investigation's model: if threads
interleave and drivetrain commands replace each other (§7), then over a run
MULTIPLE stacks genuinely contribute motion — and summing stack
contributions (what sequential execution effectively does) tracks reality
far better than granting any single stack outright ownership. It
retroactively explains both prior findings: the ungated newest-wins lockout
regressed 25 agreeing runs (monitor-winners), and even the gated version
merely broke even. Exclusive static ownership is the wrong general model.

**Consequence: A1's lockout application is PAUSED** (sweeps pass no
precedence; the machinery — snapshots adapter, creation-order recovery,
`stack_precedence` sim input, tests — all stays, reusable for whatever
arbitration the probes establish). The `concurrent_stacks_unverified` flag
stays on all 287 multi-stack runs — honest, since the semantics are now
known to be scheduler-shaped, not ownership-shaped.

## 1 · Areas compared, section by section

Notation: **MATCHES** (behavior corresponds) · **DIFFERS** (known
divergence) · **APPROXIMATES** (deliberate stand-in, flagged) ·
**CAN HOST** (existing machinery that could support the real semantics).

### §1 Program initialization
- Each stack is a separate parsed unit (`event_handler_stacks`) — MATCHES
  the separate-function compilation.
- Execution is strictly sequential in DOCUMENT order, one program counter,
  no per-stack execution state beyond a per-stack forever flag and gate
  signal — DIFFERS from `vr_thread` concurrency.
- `vr_thread(...)` launch order is not modeled; note the investigation's
  example launches `when_started2` BEFORE `when_started1` — if generated
  launch order is reverse-document or creation-ordered, our document-order
  assumption is wrong even as a first approximation. Probe 1 settles this
  cheaply.

### §2 Shared robot and device state
- **MATCHES**: one shared robot/world per simulation — pose, drivetrain
  state, magnet, sensors, pieces, regions, pen are all singletons on the
  `_Simulator`; variables are a shared dict; no per-thread device
  ownership anywhere. One stack's motion is visible to another stack's
  sensor reads (this is exactly how deferred detection hats fire off the
  main stack's movement).
- The doc's thread-state vs world-state split exists implicitly: program
  state lives in Python call frames during `execute_stack`, world state on
  the simulator object. A scheduler would need to REIFY the thread state
  (explicit program counters / continuations) — that is the single biggest
  architectural lift.

### §3 Scheduling and interleaving
- No scheduler: a stack runs to completion (or its wait_until gate) before
  the next starts — DIFFERS.
- **CAN HOST**: two pieces of existing machinery are already event-driven
  scheduling in miniature:
  1. **Deferred sensor hats** — registered before any stack runs, checked
     BETWEEN BLOCKS and latched mid-move, firing inline with restart
     semantics. Between-blocks checks are exactly the "runtime boundary"
     the investigation hypothesizes; the check sites are natural yield
     points for a cooperative scheduler.
  2. **The when_timer clock** — threads (hats) becoming runnable when
     simulated time crosses a threshold.

### §4 Thread start order
- We assume document order; unverified. Probe 1 (print A/B) settles it.

### §5 Blocking movement commands (`drive_for`, `turn_for`)
- Modeled as time-consuming motion (segment-sampled, advances `sim_time_s`
  at calibrated velocities) — MATCHES "movement over a period of time".
- But motion executes ATOMICALLY: nothing else runs during it — DIFFERS
  from "other threads may execute while the caller waits".
- **CAN HOST**: mid-move interruption already exists — detection hats
  latch mid-move and the restart machinery TRUNCATES an in-flight move at
  the detection point. That is precisely the "INTERRUPTED" outcome of §8,
  implemented today for hats; a scheduler could reuse the same truncation
  for cross-thread command replacement.

### §6 Non-blocking drivetrain commands (`drive`, `turn`, `stop`)
- **MATCHES STRONGLY**: our pending-motion model is exactly the doc's
  reading — `drive(FORWARD)` arms persistent drivetrain state and returns;
  a later `wait` converts it to velocity×time motion; any subsequent
  drivetrain command REPLACES it; still armed at program end → indefinite
  runoff. The investigation's "set state and return" is our reviewer-ruled
  continuous-motion semantics, ratified against ground truth (OI-3,
  WREN-C048).

### §7 Competing drivetrain commands
- WITHIN one stack: replacement is modeled (previous paragraph) — MATCHES
  the shared-resource single-active-command model.
- ACROSS stacks: no interleaving, so no cross-thread replacement — DIFFERS.
  The §0 adjudication shows the sequential sum nevertheless approximates
  the multi-contributor outcome well at the endpoint level (84–89%).
  Trajectory SHAPE under interleaving would differ even where endpoints
  agree — relevant for rubric evidence, not just fidelity.

### §8 Interrupted blocking commands — their top unresolved area
- Not modeled cross-thread. Our hat-restart truncation implements
  Possibility A (interruption abandons the remainder) for the hat case;
  which possibility VEX implements for threads is exactly Probe 7/8.
  Whatever the probes find, `COMPLETED / INTERRUPTED / STOPPED` outcomes
  map cleanly onto our existing move-truncation representation.

### §9 Sensor reads
- Instantaneous, no time cost, no yield — one of the doc's candidate
  interpretations. Between-blocks hat evaluation happens at the same
  boundaries where sensor-read yields would occur, so if Probe 3 finds
  sensor reads yield, our check sites are already in the right places.

### §10 Infinite loops and implicit yielding
- Our mechanism is loop caps (20 unrolls/level) + the 50k execution
  budget — an **APPROXIMATION**, documented as such (never claimed as VEX
  behavior). It prevents starvation of the SIMULATION, not of sibling
  threads (there is no interleaving to starve). If probes establish
  per-iteration yields, loop iterations become scheduler boundaries and
  the cap question decouples from fairness.

### §11 Program time vs physical time
- Partially distinguished today: `sim_time_s` advances with motion, waits,
  and wait_until marches; pure computation is free (cost only in
  `blocks_executed`). Physics updates per motion segment (50mm sampling),
  sensors evaluated between blocks and mid-move — the doc's
  execute → command → physics → sensors → eligibility loop exists in
  degenerate single-thread form.

### §12 The example program
Under our current model: the reactive stack and the fixed-path stack
execute one after the other (document order), so the fixed path runs
unopposed and the reactive loop unrolls against the post-hoc world. Under
VEX semantics both policies compete continuously. Endpoint-wise the §0
adjudication says our approximation usually lands right; the INTERLEAVED
trajectory (and any rubric claim about "feedback-regulated" behavior
DURING the drive) is not currently reproducible. This matters for the
test battery's Environmental-Feedback levels more than for fidelity.

### §13 Assumptions audit (their checklist, answered for our sim)
| assumption | our sim |
|---|---|
| one program counter per program | YES (sequential) |
| all top-level stacks execute sequentially | YES, document order |
| drive_for changes position atomically | NO — segment-sampled over time; but atomically w.r.t. OTHER STACKS |
| a blocking command pauses all program execution | YES (the divergence §5 names) |
| drivetrain commands belong to the issuing thread | NO — shared state, no ownership (matches VR) |
| one block execution = one physics timestep | NO — blocks are free; motion advances physics/time |

### §14 Execution tracing
We already record: per-step path with block ids, `sensor_hats_fired`
(fire/restart steps), `blocks_executed`, `sim_time_s`, contacts,
loop-cap sites. There are no thread events because there are no threads.
If a scheduler is built, the doc's event vocabulary (THREAD_*,
DRIVE_INTERRUPT, COMMAND_COMPLETE) maps directly onto our step records —
and the A2 "structures exercised" extract (build plan §6.1) should adopt
it so battery evidence and scheduler traces share one format.

## 2 · What our instruments say about the nine probes

None of the probes can be answered without the real runtime — they are
VEX-side experiments. What we add:
- **Population stakes** (which probes matter most for THIS sample):
  multi-stack programs = 287 runs / 20 students; ≥2 unconditional drivers
  (where §7/§8 arbitration bites hardest) = 11 telemetry runs; monitors +
  driver (where §9/§10 scheduling bites) = the dominant shape (~51 of 62
  tier-2 runs). So **Probes 2/3/9 (loop yields, sensor yields, reactive
  replacement) affect more of our population than Probes 6–8** — slightly
  reordering the investigation's priority list for our purposes, while
  agreeing that interrupted-`drive_for` fate is the deepest semantic
  unknown.
- **Predictions to test against Probe 6/8/9 outcomes**: our pending-motion
  model predicts a non-blocking command issued later simply replaces the
  active motion (no queue, no resume). If probes confirm across threads,
  the §6/§7 model generalizes with command replacement at yield points
  and Possibility A for interrupted callers — the smallest coherent
  scheduler consistent with everything observed so far.
- **Probe harness**: probe programs can be pre-run through the sim (as
  dev-corpus probes were in the OI-5/OI-21 series) so each VR observation
  lands against a stated simulator prediction — the falsification
  discipline that has worked all session.

## 3 · Recommendation

1. **Hold A1's lockout application paused** (done — sweeps pass no
   precedence; canonical CSVs unchanged; 235 tests green). The recovery
   machinery, census, and `stack_precedence` input remain — they are the
   ingest layer for ANY arbitration semantics the probes establish.
2. **Run the probes VR-side in the reviewer's priority order amended per
   §2 above**: 1 (start order — cheap), 2/3/4 (yield boundaries), 7/8
   (interrupted blocking), 6/9 (replacement dynamics).
3. **If probes support the working model**, the build target is a
   cooperative round-robin scheduler at block boundaries with shared
   drivetrain replacement and Possibility-A interruption — reusing the
   pending-motion model, mid-move truncation, and between-blocks check
   sites named above. That is a §6 change with the largest blast radius
   since the sensing build; it should come with a dual-run mode
   (sequential vs scheduled) so the fidelity sweep can attribute every
   divergence, and the sequential model stays as the fallback for
   single-stack programs (7,697 runs — 96% of the sample — are entirely
   unaffected by all of this).
4. **Rubric linkage** (SENSOR_TESTBATTERY §4/§6): multi-stack students are
   U-gated on behavioral dimensions until the scheduler exists; the
   monitor+driver idiom — the very pattern that falsified the lockout —
   is itself execution-characteristic evidence (concurrent policy
   composition) once we can simulate it faithfully.

## 4 · Probe protocol — authorable scripts, predictions, and what each result means

Practical notes before authoring:
- **Playground**: use an open-field playground (e.g. Grid Map) so no
  debris/wall contact confounds motion. None of these probes need Castle
  Crashers; keep drives ≤600mm.
- **Repetition**: run every probe **3×** — determinism is itself a finding
  (the investigation's Q5). Report the console output verbatim and the
  final pose (position + heading from the dashboard) each time.
- **Stack identity**: author stack A FIRST and place it LEFT/TOP in the
  workspace; author B second. Where a probe asks for a "creation variant",
  delete and re-create the named stack so creation order and document
  position disagree — that variant separates document-order from
  creation-order from launch-order accounts.
- "print" = the VR print-to-console block; "timer" = the built-in timer
  reporter (print it to timestamp events).

Recommended run order: P1 → P0 → P5 → P2 → P3/P4 → P7 → P8 → P6 → P9.
(P1/P0 are cheap anchors; P7/P8 are the deepest unknowns — their §8.)

---

**P1 · Start order** *(their Probe 1)*
```
when started (A):            when started (B):
  print "A"                    print "B"
```
Record: console order, 3×. Then the creation variant (delete/re-create A
so B is older but A sits first in the workspace) and run again.
- Sim today: A then B (document order), always.
- Discriminates: document order vs creation order vs generated
  `vr_thread` order (their example suggests launch order may be REVERSED);
  deterministic vs not.

**P0 · Drivetrain-only ordering** *(the reviewer's own observation, made
geometric — endpoints separate the hypotheses)*
```
when started (A):            when started (B):
  drive forward for 400mm      turn right for 90°
  turn left for 90°            drive forward for 200mm
  drive forward for 300mm
```
Record: trajectory sketch + final pose, 3×; then the creation variant.
- Sequential A→B predicts: N-ish 400, W 300, then turn right and 200 more.
- Sequential B→A predicts a completely different endpoint (turn first).
- Interleaved-with-replacement predicts truncated/blended segments — a
  pose matching NEITHER sequential endpoint.
- Sim today: A→B endpoint exactly.

**P5 · Does blocking movement release the thread?** *(their Probe 5 —
run early: it decides whether ANY interleaving exists)*
```
when started (A):            when started (B):
  print "A-before"             print "B"
  drive forward for 600mm
  print "A-after"
```
Record: console order (is "B" between A-before and A-after?), 3×.
- Sim today: A-before, A-after, B — B strictly after A completes.
- If "B" lands between: threads interleave at blocking calls
  (the investigation's working model confirmed at its base).

**P2 · Tight-loop fairness** *(their Probe 2)*
```
when started (A):            when started (B):
  forever:                     print "B started"
    change [a] by 1
```
Record: does "B started" ever print? Approximately when (timer print in B
helps)? Variants: replace `change a` with (v1) a sensor reporter read in
an if, (v2) `drive forward` (non-blocking).
- Sim today: A's forever is capped at 20 unrolls, then B runs — an
  approximation artifact, not a scheduling claim.
- Discriminates their §10 candidate yield mechanisms: pure computation vs
  sensor reads vs drivetrain calls as boundaries.

**P3 · Sensor-read yield** *(their Probe 3 — v1 of P2, kept separate for
a clean single-variable comparison)*
```
when started (A):            when started (B):
  forever:                     print "B started"
    if front eye near object:
      (empty)
```
Record: does B start? Compare directly with P2's pure-computation loop.

**P4 · Non-blocking drivetrain yield** *(their Probe 4 — v2 of P2)*
```
when started (A):            when started (B):
  forever:                     print "B started"
    drive forward
```
Record: does B start? Does the robot move while looping?

**P7 · Fate of an interrupted drive_for** *(their Probe 7 — top unknown)*
```
when started (A):            when started (B):
  print "A-before"             wait 0.5 seconds
  drive forward for 600mm      stop driving
  print "A-after"              print "B-stopped"
  turn right for 90°
```
Record: console order + timestamps (add `print timer` after each print),
final pose (did the 90° turn happen?), how far the robot actually drove.
- Possibility A (interrupt wakes caller): "A-after" prints ~0.5s, turn
  executes.
- Possibility B (caller keeps waiting): "A-after" never prints (or prints
  at the un-interrupted completion time), no turn.
- Possibility C (drive resumes): robot completes ~600mm total after a
  pause.
- Sim today: no interleaving — A completes fully, then B's stop is a
  no-op on an idle drivetrain.

**P8 · Competing blocking commands** *(their Probe 8)*
```
when started (A):            when started (B):
  drive forward for 600mm      wait 0.5 seconds
  print "A-done"               turn right for 90°
                               print "B-done"
```
Record: trajectory (straight-then-turn? turn mid-drive?), both prints +
timestamps, final pose. Together with P7 this decides replacement vs
queueing for `*_for` commands and who resumes.

**P6 · Non-blocking replacement of a blocking command** *(their Probe 6)*
```
when started (A):            when started (B):
  drive forward for 600mm      wait 0.5 seconds
                               turn right        (non-blocking)
```
Record: does forward motion stop at ~0.5s? Does the robot spin
indefinitely (armed turn, nothing replaces it)? Final pose.
- Our pending-motion model, generalized across threads, predicts: drive
  truncated at ~0.5s (~300mm at default velocity), then continuous right
  spin until program end.

**P9 · Reactive loop vs fixed sequence** *(their Probe 9 — the
monitor+driver idiom distilled; CROW-C094's shape)*
```
when started (A):            when started (B):
  drive forward for 600mm      forever:
  print "A-finished"             turn right    (non-blocking)
```
Record: does "A-finished" ever print? Trajectory (any forward progress at
all, or immediate continuous spin?), 3×.
- This is the sharpest single test of how a reactive stack starves or
  coexists with a dead-reckoning stack — the configuration behind the 25
  falsified lockout runs.

---

**Reporting template per probe** (what the sim comparison needs):
```
probe id / variant · run 1..3
console output (verbatim, with timer values where printed)
final pose: x, y, heading
trajectory notes (segments, pauses, spins)
determinism: identical across runs? what varied?
```
Each report lands against the stated sim prediction above; divergences
route into the scheduler design (§3), agreements retire their open
question. P1+P5 alone settle whether any scheduler is needed; P7+P8 fix
its interruption semantics; P2–P4 fix its yield boundaries; P0/P9 are
end-to-end checks the fidelity data can then be re-read against.
