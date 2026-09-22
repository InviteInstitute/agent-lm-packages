# EVIDENCE_MODEL — the evidentiary argument, end to end

Status: **LIVE REFERENCE (created 2026-09-10)**. This is the
high-level, ECD-style outline of how raw student data becomes claims
about goals (purpose 1) and execution characteristics (purpose 2):
what the constructs are, where each kind of evidence comes from, what
the specific indicators are, and how they are calculated. It
supersedes `docs/archive/SENSOR_TESTBATTERY.md` and
`docs/archive/RUBRIC_SCORING.md` as the
current reflection of the instruments — those documents are the
design history (decision trails, probe records, superseded designs)
and transition to the archive. Numeric authority never lives here or
in src/: every threshold belongs to the YAML cards named in §6.
Changes to instruments follow the §6 change protocol
(attribution report → reviewer sign-off → regenerate). Validation of
everything below is **VALIDATION_PLAN.md Stage 2E**.

---

## 0 · The chain at a glance

```
as-run program + telemetry  (ccp_runs: 7,984 runs / 205 students)
        │ parse (hat-rooted stacks only; statically-dead code excluded)
        ▼
production simulation  ──────────────► PURPOSE 1: goal evidence
  (measured-model sim of the           (banded rollup, _rollup.yaml)
   student's own run)
        │ router (two eligibility questions)
        ▼
test battery simulation  (19 scenarios / 7 families, designed worlds)
        │ per-scenario evidence extraction
        ▼
evidence tables  (stage2/stage3 CSVs; indicators + diagnostics + flags)
        │ claims card (_claims.yaml) / rollup card (_rollup.yaml)
        ▼
PURPOSE 1: goal bands per run        PURPOSE 2: DimensionEvidence per
(clear/remain/engage + certainty)    (run × 6 dimensions, stage6)
```

Two purposes, one instrument stack: **purpose 1** asks *did this
program pursue and achieve the playground's goals* (criterion:
the goals); **purpose 2** asks *what execution characteristics does
this program demonstrate* (criterion: six construct dimensions).
They share the simulator and the battery but keep separate evidence
channels, separate scoring cards, and separate claims.

---

## 1 · Source data and the simulation instrument

**Data.** One row per CastleCrasherPlus run: the AS-RUN workspace XML
(mid-edit states included, never backfilled), run timing, and the
playground telemetry blob where the platform logged one (weight
cleared, end state; missing blobs are often intentional resets —
MNAR, never conditioned on silently).

**The simulator** re-executes each program in a measured model of the
playground: probed drivetrain velocities, sensor geometries (front-eye
cone, down-eye color zones, bumper radii), magnet attachment, piece
kinematics, and the VR-Seq cooperative scheduler (document-order
threads, measured yield points, last-write-wins drivetrain). The
**loop-clock execution model** runs the measured 60Hz frame against
each run's observed wall-clock duration as the budget (session-median
imputed and flagged where unobserved) — reactive controllers execute
for real iteration counts instead of unroll caps.

**Liveness (what code counts as evidence).** Only code that could
execute: detached (orphan) stacks are excluded at parse; statically
unreachable code (post-`forever` chains) is excluded from every
parse-side count (OI-33). Variables that CLAIM execution require it
(trace/path witness); parse-only variables accept
reachable-but-unexercised code by design.

**Certainty is layered, not a single score.** (1) Per-run *fidelity
verdict* from the sim-vs-telemetry validation (agree / edge_slip /
stopped / override / capped / sensor_uncertainty / nondeterministic /
UNATTRIBUTED — the last is the standing OI-29 review queue); (2)
per-indicator `channel` / `flags` / `abstain_reason`; (3) triage for
unsimulable runs. **Abstention is never failure**: every U carries a
reason, and denominators shrink rather than zero.

---

## 2 · Purpose 1 — Goal evidence (the banded rollup)

**Constructs**: the playground's goals, claimed per run.

| goal | construct claim |
|---|---|
| `clear_debris_zone` | the program clears debris from the zone |
| `remain_on_island` | the program keeps the robot on the island under boundary encounters |
| `engage_plow` | the program acquires/uses the plow attachment |
| `playground_engagement` | gate: the program does anything at all (`robot_moved`) |

**Evidence channels and indicators.** Each goal reads up to four
channels — code, simulation (production sim of the student's run),
observed (platform telemetry), test (battery) — kept separate and
named so disagreement is visible, never averaged away:

| goal | simulation | observed | test |
|---|---|---|---|
| clear_debris_zone | `debris_zone_coverage` (path coverage of the zone) | `weight_cleared` (platform kg report) | `cleared_proportion_tests` |
| remain_on_island | `on_island_sim` | `on_island_observed` | `on_island_tests` |
| engage_plow | `magnet_activation_intent`, `plow_approach_intent`, `plow_proximity_execution` | — | **none by design** (attachment is faithfully simulated; the sim channel is never U-gated) |

**Calculation** (`_rollup.yaml`, banded v2 — the numeric authority):
- *score* = flat mean of the goal's check over VALID (non-abstained)
  battery tests — clearing-only purity for CDZ (`proportion_cleared`),
  boundary survival for ROI (`stays_on_island`).
- *band* = ruled rungs. CDZ: ≥.35 broad_systematic / ≥.10
  meaningful_multi_condition / ≥.02 narrow_inconsistent / else
  little_no_capability (the .10 step is the empirically decisive one).
  ROI: ≥.5 boundary_safe / ≥.1 condition_dependent / else
  boundary_unsafe (a ≥.9 band was tested and REJECTED).
- *U* = all contributing checks abstained → no band, dominant abstain
  reason as sub-tag.
- *certainty* = full minus demotions: `sparse_evidence` (fewer valid
  tests than the card gate) and `budget_sensitive` (band moves between
  duration budgets — primary-budget band kept, certainty drops).
- *P(remain_on_island)* = a calibrated family logistic
  (`purpose1_calibration.json`); band-vs-model disagreement is a
  surfaced flag, never a silent average.

---

## 3 · The test battery — designed evidence elicitation

**Why tests exist.** The production run evidences only what the
student's one world happened to elicit. The battery places the SAME
program in designed worlds to (a) measure goal behavior the
production sim cannot faithfully evidence, and (b) resolve
execution-characteristic ambiguity the production trace leaves open.

**The router asks two independent questions** (`_router.yaml`):
- *Goal eligibility* — does the program sense movable objects the sim
  can't faithfully model? → full battery, `channel: goal`.
- *Rubric eligibility* — is executable sensing left AMBIGUOUS by the
  production trace (the down-eye-only class, zero production
  alternations)? → boundary families only, `channel: rubric_only`;
  those rows NEVER feed the goal rollup or purpose-1 calibration.

**Seven families, 19 scenarios** — each family manipulates one thing
and holds the rest; every scenario scores the same four checks
(`detects`, `proportion_engaged`, `proportion_cleared`,
`stays_on_island`) plus per-scenario rubric evidence. **The
failure-scoped window (OI-37, ruled 2026-09-11):** responsiveness
evidence is scored only BEFORE the run's failure step (first
departure from the island beyond grace) — post-failure behavior can
never evidence responsiveness; `detects` compares the two runs'
pre-failure trajectories only (a divergence arising after either run
fails, or from failure timing itself, cannot pass), and a corrective
retreat counts only while ON the island (an outbound crossing is the
failure, not the response). Each scenario's `scenario_exit_step` is
recorded for review:

| family | design | what it isolates |
|---|---|---|
| T1 integrated | the castle-wall world, canonical spawn | the favorable-condition ANCHOR (no privileged weight) |
| T2 boundary ×3 | assured boundary encounters, approach-angle ladder (direct/angled/steep) | encounter geometry, then recurrence — sustained regulation vs one-shot |
| T3 block→boundary ×3 | a block placed against the boundary | the block↔boundary INTERACTION (clear without going over) |
| T4 clearing ×3 | debris configurations off the memorized map (favorable/jittered/dispersed) | generalization vs positional luck |
| T5 pose ×3 | T1's exact world, spawn heading rotated (330/270/180) | start-independence (a boundary test for dead-reckoners) |
| T6 re-engagement ×3 | assured detection, block on the retreat line, bearing set 180/130/230 | recovery→re-engagement (search targetedness + turn sidedness) |
| T7 managed clearing ×3 | T4's exact worlds, rule-only tightening (edge-finish clears) | boundary-MANAGED clearing; the T4↔T7 pair is the repeated-regulation source |

**Machinery**: calibrated takeover placement and truncate-and-resume
preemption produce assured encounters; world events mark
retreat/recovery; abstention tokens (`test_not_activated`,
`encounter_not_reached`, …) record when a scenario could not put the
question to the program — recorded as U-with-reason, never as failure.

---

## 4 · Purpose 2 — Rubric scoring (execution characteristics)

**Constructs**: six dimensions, each an ordinal scale answering ONE
question (construct-separability ruling: one primary home per
indicator; tests stay intact; the inferential layer does the work):

| dimension | construct question | scale |
|---|---|---|
| Environmental Feedback | does changing state causally regulate execution as it unfolds? | U / 0 predetermined / 1 state-conditioned / 2 feedback-regulated |
| Control Structure | how is execution computationally organized (repetition, selection, coordination)? | U / 0 sequential / 1 structured repetition / 2 state-dependent / 3 integrated |
| Spatial / Motion Control | is movement coarse, fitted to geometry, or derived from state? | U / 0 coarse (verified) / 1 calibrated / 2 state-derived |
| Representation & Abstraction | concrete instance-specific encoding vs reusable/generalized structure? | U / 0 concrete / 1 structured / 2 generalized |
| Task-State Regulation | does task progress information regulate phase transitions? | U / 0 preset progression / 1 state-aware / 2 state-regulated |
| Recovery / Robustness | are deviations detected, corrected, evaluated, and pursuit restored? | U / 0 single-path / 1 failure-responsive / 2 regulated recovery |

**Evidence architecture.** The registry (`_evidence.yaml`) gives every
variable a role — `indicator` (can establish a level; exactly one
primary dimension), `validation` (corroborates, never establishes),
`diagnostic` (explains why an indicator fired), `metadata`/gate
(evaluability, never scores) — and each dimension draws from up to
three sources: the production **census+trace** (parse facts +
execution witness), the **battery** per-scenario evidence, and the
**census ceilings** (the economy rule: programs that structurally
cannot express a level are decided from code alone — e.g. no live
sensing ⇒ EF/TSR/Recovery ceiling 0, SMC ≤ 1; ceiling 0 ASSIGNS an
informative zero, never U).

**How to read the dimension entries below.** Each carries its
charter, an evidence-source table, a **"Levels and the indicators
that score them"** bullet list — one bullet per level, with the
specific scoring indicators (name · threshold · channel · role ·
inference) and any negatives indented beneath it — and a short *How
the indicators are computed* note. Indicator names match the claims
card's `evidence:` fields, so each bullet maps one-to-one onto a
floor in `_claims.yaml` and onto the audit tool's claim drill-down. Tables are FAMILY-collapsed
abbreviations of the archived per-scenario tables (19 test columns in
`docs/archive/RUBRIC_SCORING.md`): **●** = primary/designed source, **○** =
supporting, blank = that source cannot speak to the level; a family
cell takes its strongest variant's mark. `code` = census +
production-trace. U is never a row — an abstaining source routes to
the dimension's U surface with its reason. Floors and thresholds live
in `_claims.yaml`, each labeled with its D-d inference.

### 4.1 · Environmental Feedback (U / 0 predetermined / 1 state-conditioned / 2 feedback-regulated)

> Whether observable properties of the robot or environment causally
> influence goal-directed execution, and whether changing state
> continues to regulate behavior as execution unfolds.
> *Pathway:* state change → evaluation → observable execution change
> → repeated regulation.

**Levels and the indicators that score them** (floors vote primary
1.0 / supporting 0.5; level = highest floor with net ≥ 1.0 and no
surviving negative):

- **U — indeterminate** — no informative EF variable reached the run
  (abstained tests route here with their reasons).
- **0 — predetermined** — informative zero: evidence sought, no floor
  cleared (e.g. supporting-only fires), or census ceiling 0 ASSIGNED
  (no live sensing in executable code).
- **1 — state-conditioned**
  - `max_arm_alternations ≥ 1` — battery (primary) · presence of one
    state-driven change
  - `max_arm_alternations ≥ 1` — production trace (primary)
  - `response_latency_mm` present — battery (supporting) · onset
    demonstrably changed the trajectory
  - *negative:* `detects_fail_with_encounter ≥ 2` — replicated
    non-response under real opportunity
- **2 — feedback-regulated**
  - `max_arm_alternations ≥ 2` — battery (primary) · regulation
    re-arms within a run
  - `max_arm_alternations ≥ 2` — production trace (primary)
  - `boundary_band_entries ≥ 2` — battery (supporting) · repeated
    boundary sampling; counts only alongside alternations
    (interpretive rule — cycles alone never define the level)

| level | code | T1 | T2 | T3 | T4 | T5 | T6 | T7 |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| 0 predetermined | ● | ○ | ○ | ○ | ○ | ○ | ○ | ○ |
| 1 state-conditioned | ○ | ● | ● | ● | ● | ● | ● | ○ |
| 2 feedback-regulated | ○ | ○ | ○ | ○ |  | ○ | ● | ● |

*How the indicators are computed:*
- `max_arm_alternations` — *count (max over the run's sensing
  conditionals)*: adjacent arm SWITCHES in a conditional's
  BRANCH_ARM trace sequence (deterministic worlds: a switch happens
  only when sensed state changed; 0 = the condition never mattered).
  Computed once on the production trace AND per battery scenario —
  the multi-channel convergence dimension.
- `response_latency_mm` — *distance in mm (None = never diverged)*:
  travel from scenario onset to the first >100mm departure from the
  scenario baseline, within the pre-failure window.
- `boundary_band_entries` — *count per scenario*: down-eye band
  entries separated by full retreats (the 124mm eye-reach ring).
  Segment-DENSIFIED since OI-36/37 (2026-09-11): a band crossed
  mid-drive_for counts; the scan ends at the failure step.

### 4.2 · Control Structure (U / 0 sequential / 1 structured repetition / 2 state-dependent / 3 integrated)

> How goal-directed execution is computationally organized through
> sequencing, repetition, conditional selection, and coordination
> among control structures.
> *Pathway:* program structure → exercised constructs → relations
> among constructs.

**Levels and the indicators that score them** (all production-channel):

- **U — indeterminate** — constructs present but never exercised and
  no census decision (tests mostly LIFT this U).
- **0 — sequential** — census ceiling 0 ASSIGNED: no loops and no
  conditionals in executable code.
- **1 — structured repetition**
  - `exercised_loops_any ≥ 1` (primary) · a loop that actually ran
    (fixed + state + forever counts)
- **2 — state-dependent control**
  - `coordination_relations ≥ 1` (primary) · an exercised
    state-dependent relation (branches need not alternate —
    alternation is EF evidence)
  - `state_controlled_termination` true (primary) · an exercised
    sensing-predicated loop/wait that provably terminated
- **3 — integrated control**
  - `coordination_relations ≥ 2` (primary) · replication — two
    distinct coordination relations

| level | code | T1 | T2 | T3 | T4 | T5 | T6 | T7 |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| 0 sequential | ● | ○ |  |  |  |  |  |  |
| 1 structured repetition | ● | ○ | ○ | ○ | ○ | ○ | ○ | ○ |
| 2 state-dependent | ● | ● | ○ | ● | ○ | ○ | ● | ○ |
| 3 integrated | ○ | ● |  | ○ |  |  | ● | ○ |

*How the indicators are computed:*
- `exercised_loops_*` — *counts (one per loop kind, per run)*:
  fixed/state/forever loops that actually ran, from the trace.
- `coordination_relations` — *count of distinct relations (per
  run)*: RELATIONS between exercised constructs, four kinds: (a) a
  sensing conditional EVALUATED inside an exercised loop, (b) a
  sensing-predicated repeat_until/while that ran with its successor
  executed, (c) a sensing wait_until releasing inside an exercised
  loop, (d) a procedure call inside an exercised construct. Nested
  same-type structures produce ZERO relations.
- `state_controlled_termination` — *boolean (per run)*: from
  relation kinds (b)/(c).
- census ceilings — *a maximum LEVEL cap (per run)*: 0 with no
  loops/conditionals; 2 with conditionals but no loops.

### 4.3 · Spatial / Motion Control (U / 0 coarse / 1 calibrated / 2 state-derived)

> Whether goal-relevant movement is specified coarsely, calibrated to
> known geometry, or derived/terminated from current spatial or
> sensed state.
> *Pathway:* motion specification → relationship to geometry/state →
> observed spatial adaptability (validation).

**Levels and the indicators that score them** (gated ordinal; the
lower scale asks: fitted to the spatial problem, or generic
vocabulary?):

- **U — not evaluable** — the evaluability gate:
  `fixed_motion_specificity` is None (insufficient drive/turn
  literals to characterize). U means *not evaluable* — never "no
  indicator fired."
- **0 — coarse/fixed (VERIFIED zero)** — gate passes and neither L1
  route nor L2 fires: fitting was sought on every route and not
  demonstrated; the gate itself is the fired evidence.
- **1 — calibrated** (either route suffices; strengths distinguished)
  - route A: `calibrated_param_matches ≥ 1` — production, ~direct ·
    a live literal within card tolerance of a card-geometry distance
    (`canonical_ambiguous_matches` annotates palette-value matches)
  - route B: `fixed_motion_specificity ≥ 1` — production, ~indirect ·
    differentiated vocabulary beyond the corpus palette
- **2 — state-derived** (either floor suffices; overrides everything
  below)
  - `state_gated_drivetrain_executed ≥ 1` — production (primary) ·
    gated motion that actually RAN (attempts never score;
    `gated_sensor_fields` flags mis-wired gates diagnostically)
  - `state_termination_events ≥ 2` — battery (primary) · replicated
    state-terminated motion across scenarios

| level | code | T1 | T2 | T3 | T4 | T5 | T6 | T7 |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| 0 coarse (verified) | ● |  |  |  | ○ | ○ |  |  |
| 1 calibrated | ● | ○ |  |  | ● | ● |  |  |
| 2 state-derived | ● |  | ○ | ○ | ○ | ○ | ○ | ○ |

*How the indicators are computed:*
- `calibrated_param_matches` — *count (per run)*: live drive_for
  literals within the card tolerance of a card-geometry distance
  (spawn→piece, spawn→zone, island half-extents).
- `fixed_motion_specificity` — *ordinal 0 / 1 / None (per run)*:
  1 (differentiated) when ≥3 distinct drive clusters (5% merge), OR
  ≥1 fine-grained non-multiple-of-5 value, OR majority non-palette
  vocabulary over ≥4 literals; 0 = coarse/default palette; None =
  too few literals to characterize (feeds the U gate). The palette
  is corpus-derived (drives 200/800/1200/2000/1000/3000, turns
  90/120/180/60/270).
- `state_gated_drivetrain_executed` — *count of motion blocks (per
  production run)*: blocks under an evaluated sensing conditional
  that also appear in the executed path.
- `state_termination_events` — *count of scenarios (across the
  run's battery tests)*: scenarios whose state-terminated-motion
  fraction is non-zero (wait-release → drive, sensing-loop exit,
  arm-change whose arm drives, sensor-hat firing that drives).
- validation texture — the T4↔T7 pair and the T2/T5 ladders
  corroborate the 1/2 boundary (never score).

### 4.4 · Representation & Abstraction (U / 0 concrete / 1 structured / 2 generalized)

> Whether goal-directed behavior is encoded as concrete
> instance-specific actions and values, or through reusable,
> parameterized, or generalized structures.
> *Pathway:* code representation → reuse/parameterization/compression
> → cases represented by common logic (primarily code-based).

**Levels and the indicators that score them** (production-channel;
census-decided for ~99% of this population):

- **U — indeterminate** — structure can't be associated with the
  goal attempt.
- **0 — concrete** — census ceiling 0 ASSIGNED: no loops, no
  procedures, no variables.
- **1 — structured representation**
  - `structures_exercised` true (primary) · exercised loops, or
    procedure calls / variable sets present
- **2 — generalized representation**
  - `procedure_reused_or_parameterized` true (primary) · a proccode
    called ≥2 or parameterized — the generalization signature

| level | code | T1 | T2 | T3 | T4 | T5 | T6 | T7 |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| 0 concrete | ● |  |  |  |  |  |  |  |
| 1 structured | ● | ○ | ○ | ○ | ○ | ○ | ○ | ○ |
| 2 generalized | ● |  | ○ |  | ○ |  | ○ | ○ |

*How the indicators are computed:*
- `structures_exercised` — *boolean (per run)*: exercised loops
  (trace), or procedure calls / variable sets present (parse).
- `procedure_reused_or_parameterized` — *boolean (per run)*: true
  when a proccode is called ≥2 times or a call is parameterized
  (from block mutations).
- `duplicated_sequence_count` — *count (per run)*: repeated
  block-type 3-grams across next-chains (duplication signals
  concrete representation; diagnostic, never scores).
- `shared_structure_across_variants` — *set of block ids (per test
  family)*: exercised-block overlap across a family's variants;
  VALIDATION-role only (the same source necessarily runs in every
  variant, so overlap alone cannot demonstrate abstraction).

### 4.5 · Task-State Regulation (U / 0 preset progression / 1 state-aware / 2 state-regulated)

> Whether observable information about task progress, intermediate
> achievement, or completion regulates transitions among
> goal-directed phases (search, engagement, clearing, recovery,
> re-engagement).
> *Pathway:* task-progress event → recognition/use → transition to an
> appropriate next phase (a generic boundary reflex does NOT count).

**Levels and the indicators that score them** (battery-only, from
the seam stream):

- **U — indeterminate** — achievement may occur but use of task
  progress is not revealed (or census ceiling from no live
  recurrent sensing).
- **0 — preset progression** — informative zero, or census ceiling 0
  ASSIGNED; includes awards killed by the surviving negative.
- **1 — state-aware transition** (either floor suffices)
  - `task_state_triggered_transition_count ≥ 1` — battery (primary) ·
    a transition at a TASK seam (never mere geometry)
  - `completion_triggered_transition` true — battery (primary) ·
    post-clear behavior change inside the card's latency bar
  - *negative:* `clear_without_post_change ≥ 2` — replicated
    completion-cue non-use under demonstrated opportunity
- **2 — state-regulated progression** (a ruled CONJUNCTION — both
  floors REQUIRED)
  - `task_transitions_ge2_tests ≥ 2` — battery (primary, ⊗conjunct) ·
    ≥2 task transitions within a test, in ≥2 tests (re-arms AND not
    world-specific)
  - `task_phase_return` — battery (primary, ⊗conjunct) ·
    engage/acquire after a boundary→retreat pair — the charter's
    re-engagement

| level | code | T1 | T2 | T3 | T4 | T5 | T6 | T7 |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| 0 preset | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ |
| 1 state-aware | ○ | ○ |  | ● | ○ | ○ | ● | ○ |
| 2 state-regulated |  | ○ |  | ● |  | ○ | ● | ● |

*How the indicators are computed:* all from **the seam stream** —
seven event-anchored seam kinds pinned to preserved sim data:
`acquire` (first true movable-target sensing), `engage` (object
contact), `clear` (piece cleared), `loss` (piece vanishing while
most-recent contact), `recovery` (T6 marker events), `boundary`
(band entry), `retreat` (full withdrawal).
- `task_state_triggered_transition_count` — *count per scenario*:
  transitions whose ARRIVING seam is a TASK event
  (acquire/engage/clear/loss/recovery; geometric boundary/retreat
  excluded — the separability line). The TSR-2 floor counts the
  NUMBER OF TESTS where this is ≥2.
- `task_phase_return_count` — *count per scenario (the floor asks
  any ≥1 across tests)*: engage/acquire seams occurring after a
  boundary→retreat pair.
- `completion_triggered_transition` — *boolean per scenario (None
  when no clear occurred)*: post-clear behavior change within the
  card's `post_clear_bar_mm` (rule-dependent availability: the cue
  exists mainly on slip-band families).
- `behavioral_transition_count` — *count per scenario*: ALL
  seam-kind changes; generic/supporting only, never TSR-primary.

### 4.6 · Recovery / Robustness (U / 0 non-recovering / 1 recovery demonstrated / 2 robust regulated recovery)

> Whether execution detects deviations from productive task pursuit,
> corrects, evaluates the correction, and reliably restores progress.
> The scale scores the recovery **process** and its robustness — an
> isolated corrective movement is not a process (R2 restructure,
> reviewer-ruled 2026-09-11).
> *Pathway:* deviation → correction → reassessment → restored
> progress → consistency across conditions.

**Levels and the indicators that score them** (battery-only; gated
ordinal — the opportunity gate is the U boundary, zeros are
verified):

- **U — indeterminate** — the opportunity gate:
  `corrective_evaluated_tests < 2` — too few demonstrated deviations
  to verify anything (one miss cannot verify a zero; D-e
  replication). Census ceilings also land here-adjacent for
  no-recurrent-sensing programs.
- **0 — non-recovering (VERIFIED zero)** — ≥2 demonstrated
  deviations and no recovery loop anywhere. Two observed forms both
  land here: *(a) unanswered failure* — deviations elicit no
  corrective action at all; *(b) unsustained correction* — an
  isolated corrective-shaped movement (moving off the boundary once)
  never followed by reassessment or re-engagement — the retreat is
  the terminal observable event, and the run typically still ends in
  failure. The gate is the fired evidence.
- **1 — recovery demonstrated, condition-dependent**
  - `reassessment_cycles_max ≥ 1` — battery (primary) · a CLOSED
    loop observed at least once: deviation → correction → EVIDENCED
    reassessment. One closed loop is already the re-armed loop (the
    counter closes only when reassessment follows; trailing
    corrections never close — the C114_020 finding). Failures in
    other conditions are permitted at this level.
- **2 — robust regulated recovery** (family-grain ruling 2026-09-11;
  both required)
  - `reassessment_cycle_families ≥ 2` — battery (primary) ·
    cross-condition replication: the closed loop appears in ≥2
    condition FAMILIES — not world-specific (the ruled TSR-2 shape)
  - `unsurvived_deviation_families ≤ 1` — battery (constraint,
    ⊗conjunct) · robustness: at most ONE condition family ever
    defeats the loop. A failure is an UNSURVIVED deviation (the
    robot left the island — from the stays episode record); an
    arrested, survived encounter is an ANSWERED deviation. Families
    without cycle motivation (empty boundary worlds) can therefore
    never penalize the absence of cycling — only falling off counts.

| level | code | T1 | T2 | T3 | T4 | T5 | T6 | T7 |
|---|:-:|:-:|:-:|:-:|:-:|:-:|:-:|:-:|
| 0 single-path | ● |  | ○ |  |  | ○ |  |  |
| 1 failure-responsive |  | ○ | ● | ○ | ● | ● | ● | ○ |
| 2 regulated recovery |  | ○ | ○ |  | ○ | ○ | ○ | ● |

*How the indicators are computed:* T6 is the L1 engine (assured
deviation — corrective evaluated for 86% of scored runs), T7 the L2
engine (repeat cycles without survivor gating).
- `corrective_response_present` — *three-valued boolean per
  scenario*: deviation onset is BAND ENTRY (within 124mm of an
  edge; densified — mid-drive crossings count) — True = an entry
  later followed by a FULL retreat (≥400mm from the edge, the card's
  `retreat_mm`) **while ON the island and before the failure step**
  (OI-37: an outbound crossing is the failure, never the response);
  False = entries but never an on-island retreat; None = no
  pre-failure deviation to evaluate. Since R2 it scores nothing
  directly: evaluated-either-way tests feed the opportunity gate,
  and the False count feeds the L2 consistency constraint.
- `corrective_evaluated_tests` — *count of tests (the gate's
  evidence)*: tests where corrective was evaluated True OR False —
  demonstrated deviation opportunities.
- `correction_reassessment_cycles` — *count of CLOSED loops per
  scenario (L1 takes the max across tests)*: a state machine over
  the seam stream — a retreat followed by another retreat, or by
  acquire/engage/clear/boundary (reassessment — a new
  interaction/state read), closes one loop. A trailing correction
  never closes, so one closed loop already evidences re-arming.
  Empirically the cycle CONTAINS the corrective event.
- `reassessment_cycle_families` — *count of condition families (per
  run)*: families with ≥1 closed loop — the L2 cross-condition
  floor.
- `unsurvived_deviation_families` — *count of condition families
  (per run)*: families containing a scenario whose stays_on_island
  episode record shows an unsurvived encounter — the L2 robustness
  constraint's failure unit. Retired from scoring:
  `corrective_false_tests` (the retreat-choreography count; kept as
  a diagnostic — its arrested-survivor artifact was 25% of Falses).
- population profile — *percentages (context only)*: 32%
  always-corrective / 11% never / 57% mixed — condition-dependence
  is the modal reading, which is exactly what the L1/L2 robustness
  axis now scores.

### 4.7 · Combination — evidence to levels

(`rubric_combiner.py`, mechanics ruled D-a…D-e):
census ceilings cap (and ceiling-0 assigns); floors vote (primary 1.0
/ supporting 0.5; validation gates); opportunity-verified negatives
subtract (D-e: demonstrated-opportunity non-response is evidence;
abstention never is); level = highest floor with net support ≥ the
card minimum, no surviving negative, conjunctions honored; verified
zeros and evaluability gates where declared; borderline (contested or
near-miss) flagged as the C3 oversample; every fired claim carries
its strength label into the output. **Governing principles:**
thresholds must map to inferences (≥1 presence, ≥2 replication, all
consistency — norm-referenced bars forbidden); attempts never score
(execution-claiming evidence must have executed); U always says why.

---

## 5 · Certainty, roles, and validity

There is deliberately **no single certainty score**: consumers read
the layer they need (fidelity verdict for the run, per-indicator
flags/channel for the variable, U-reasons for the gap, diagnostics
for the why). Instrument validation — the blind reliability sample,
weight calibration, and the named review classes (borderline TSR,
indirect-only and canonical-ambiguous SMC L1s, negative classes,
mis-wired-sensor misconception class, single-run items) — is
**VALIDATION_PLAN.md Stage 2E**. Open instrument issues and the
parking lot (each with an unpark trigger) are **OPEN_ISSUES.md**.

---

## 6 · Authority and artifact map

| what | authority (YAML — never src/) |
|---|---|
| purpose-1 bands, rungs, sparse gates | `configs/testcases/castle_crashers/_rollup.yaml` |
| purpose-2 claims, thresholds, palette, gates | `configs/testcases/castle_crashers/_claims.yaml` |
| evidence-variable roles (indicator/validation/diagnostic/metadata) | `configs/testcases/castle_crashers/_evidence.yaml` |
| battery routing | `configs/testcases/castle_crashers/_router.yaml` |
| worlds and scenario geometry | playground card + per-scenario battery cards |

| pipeline artifact | contents |
|---|---|
| `stage2_rungs.csv` | purpose-1 goal indicators per run (value/rung/channel/flags/abstain per indicator) |
| `stage2_code_evidence.csv` | production census + trace evidence + SMC vocabulary/audit columns |
| `stage2_fidelity.csv` | sim-vs-telemetry verdicts |
| `stage3_battery_evidence.csv` | per-scenario battery evidence (goal + rubric channels) |
| `stage6_rubric.csv` | one DimensionEvidence per run × dimension (level, fired+strengths, negatives, borderline, u_reason) |
| `stage5_profiles.csv` (+ `.meta.json`) | THE delivery table (stage-5 assembly): one row per run joining the annotated goal profile and the provisional rubric profile, with route, fidelity verdict, and the version fingerprint — the boundary between pipeline and analysis |

Extraction: `rubric_evidence.py` (code/trace), `battery_evidence.py`
(scenarios), `indicators.py`/`rung_sweep.py` (goals). Combination:
`rubric_combiner.py` (purpose 2), `battery_rollup.py` +
`goal_calibration.py` (purpose 1). Between-regeneration column
appends run only from the committed `scripts/backfill_*.py`.
Design-history archive: `docs/archive/SENSOR_TESTBATTERY.md`,
`docs/archive/RUBRIC_SCORING.md`
(decision trails, probe records, rulings ancestry), `FINDINGS.md`
(the ledger), `OPEN_ISSUES.md` (the queue).
