# SENSOR_TESTBATTERY — OI-20 capability stocktake

First OI-20 deliverable (2026-08-25): what the simulator handles vs. where it
has known limitations, broken down by **block classes**, **environmental
features**, and **code structures** — each with full-sample coverage — so the
battery work can split cleanly into "improve the simulation" vs. "design a
test to measure it".

**Sources.** The D2 capability registry (configs/capabilities.yaml), the
measured-model ledger (FINDINGS probe series), and a fresh parse-only census
over the full ccp_run_dataset: **7,984 runs · 205 students** (as-run
workspaces; a run counts when the feature appears anywhere in its code;
students are distinct). Environmental rows come from the Stage-2 sweeps
(simulation claims, not ground truth). Config at census time: `7eb91d4a6c65`.

**Counting caveats.** Block presence ≠ execution (an orphan stack's blocks
never run); sim-derived environment counts (zone entry, attachment, boundary
exit) inherit the fidelity accounting (76.6% endpoint agreement, 99%+
attributed); flags are per-profile markers, deduplicated per run.

---

## 1 · Block classes

| class | coverage (runs / students) | status | known limitations |
|---|---|---|---|
| drivetrain | 7,923 / 205 | **simulates** — velocities measured (OI-16: 9.88 mm/s·%, 4.16 °/s·%) | edge divergence zone: random near-edge slips are non-physical (heading changes, path continues) — ruled unestimable, soft-annotated only |
| magnet | 4,674 / 166 | **simulates** — attachment measured (OI-21 near-contact model, blade 75mm / hitch 40mm gaps) | one boundary-marginal case class (±15mm band, flagged) |
| down-eye blocks | 943 / 85 | **simulates** — measured color zones + NONE-on-grass semantics (OI-10/OI-18) | reads the card's color geometry; a slipped heading (edge quirk) can shift what the eye crosses |
| distance blocks | 898 / 86 | **simulates** — docs-verified banded cone | readings against MOVABLE pieces go stale once the world is disturbed (scatter is random) |
| front-eye blocks | 890 / 74 | **simulates** — measured proximity cone (OI-5: fov 13°, range 124mm); edge-triggered re-arming + mid-stack restart (2026-08-24) | physics-coupled re-triggers off knocked/scattered pieces are unreconstructable (the sensor_uncertainty fidelity lane) |
| operators / variables / math | 345 / 22 | **simulates** — expression evaluator; nonfinite handling (percent clamps, discrete stalls) VEX-probed | 123 runs carry nonfinite clamps — modeled, flagged |
| bumper blocks | 88 / 11 | **simulates** — contact model, measured radii (OI-6); edge-triggered re-arming | contact against scattered debris positions is random (same coupling as the eye) |
| procedures | 71 / 6 | **simulates** — inline synchronous expansion (OI-23) | recursion suppressed (flagged); calls to missing definitions no-op |
| looks / pen | 68 / 8 | **simulates** — faithful no-op (invisible to motion, sensors, goals) | none |
| brightness | 27 / 1 | **foreign in CCP** — invalid block, faithful no-op, `foreign_playground_block` | ruled not worth modeling (2026-08-24); only matters on playgrounds where it exists |
| broadcasts | 12 / 3 | **simulates** — exact for single receivers | concurrency approximated (6 runs flagged) |
| timer blocks | 10 / 3 | **simulates** — movement-consumes-time clock (OI-23) | **idle wall-clock time is not modeled** — a program that "sits" until a timer hat fires cannot be simulated (6 runs `timer_hat_unfired`); turn-to-heading deltas don't consume time (zero co-incidence with timer use) |
| position / heading reporters | 6 / 2 | **simulates** — A3 CLOSED at the Phase-A REVIEW (2026-08-26): position honours UNITS, position_angle/drive_heading report the VEX/card convention, drive_rotation has the true cumulative accumulator, is_done/is_moving are cooperative-aware; tripwire tests pin all four zero-incidence reporters | first close-out claim was premature (rotation alone); corrected same day |
| Switch free-text | 1 / 1 | **rejected faithfully** — whole-program rejection matches VEX's immediate error | valid Switch text would need a parser; incidence 1 run of English prose |

---

## 2 · Environmental features

| feature | coverage (runs / students) | status | known limitations |
|---|---|---|---|
| debris-zone entry (movable-object world) | 6,352 / 204 (sim coverage > 0) | zone geometry + entry modeled; **disturbance model**: any contact or zone entry marks all movable-sensitive readings stale | **the core limitation:** disturbed debris falls RANDOMLY; piece positions after disturbance are unreconstructable — detection timing, distance readings, and contact after entry are uncertain by construction (818 runs / 80 students carry `sensor_reading_stale`). Ruled NOT an improve-sim target. |
| plow attachment & towing | 3,686 / 146 (attach estimated) | **measured** (OI-21 probe series) — attach timing real; attached plow travels with the robot | boundary-marginal band ±15mm flagged |
| island boundary & exit | 2,896 / 199 (sim exit) | §6a modeled — exit truncates scoring; outcome-override lane for drift; on_island_sim indicator | dead-reckoning drift over long programs (override lane, 62 runs); edge divergence zone slips (soft lane, unestimable) |
| weight_cleared physics | outcome-only | **not simulated at all** — kg comes only from the platform blob | sim coverage predicts it well on trusted runs (ρ = 0.819 high-certainty) but the sim produces no kg figure; a battery cannot measure kg either — observed-only signal |
| program-end runoff | 1,171 / 143 (`fabricated_motion`) | modeled per OI-3 rulings (wait-keeps-driving; terminal runoff to 4× field radius) | fabricated segments are honest fiction — marked, never verifiable |
| wall-clock idle time | 6 / 1 flagged today | **machinery built (2026-08-26)**: measured 60Hz loop clock + observed-run-duration budget make idle/timer programs simulable — not yet the default (own track; duration calibration first) | per §12.8: the clock's value is timer hats, the duration channel, and honest idle modelling — NOT rescuing loop-capped runs (8/1,103 recover) |

---

## 3 · Code structures

| structure | coverage (runs / students) | status | known limitations |
|---|---|---|---|
| orphan (unattached) stacks | 1,875 / 116 | parsed, non-executing — faithful | none |
| sensing reporters inside conditions (wait_until / if / while) | 1,648 / 114 | modeled — all sensing reporters evaluate | staleness dominates: conditions over movables after disturbance are uncertain |
| forever loops | 1,532 / 120 | faithful nesting; 50k execution budget as pure backstop | cap is declared, flagged when hit |
| if-family branches | 1,429 / 103 | name-bound slot execution (CROW-C117 fix); empty condition = false (VEX semantics) | none known |
| bounded loops (repeat / while / until) | 949 / 67 | simulates_capped (20-unroll per level) | cap flagged |
| wait / wait+drive idiom | 939 / 51 | wait keeps pending motion armed (reviewer-diagnosed, WREN-C048) | none — matches probed VEX behavior |
| detection hats (eye / bumper) | 303 / 32 | edge-triggered re-arming + mid-stack RESTART with in-flight move truncation (reviewer-probed 2026-08-24) | physics-coupled re-triggers (above) |
| when_started + detection hats together | 300 / 32 | modeled (the restart semantics govern the interleave) | same coupling; the dominant battery-relevant combo |
| **multiple when_started stacks** | 287 / 20 | **RESOLVED (2026-08-26)** — the VR-Seq cooperative scheduler (transliterated from VEX's shipped scratch-vm fork) is the DEFAULT: threads in document order, round-robin at measured yield points, shared last-write-wins drivetrain, measured truncate-and-resume supersession | residual: predicate-bracket-divergent runs keep the U flag (currently 1 run); the C094/C164 static aggregate-detection defect has its own OI |
| wait_until gates | 163 / 10 | gate semantics ratified (OI-3) | unmet conditions flagged (61 runs) — usually movable-dependent |
| multiple detection hats | 63 / 9 | modeled (each re-arms independently) | coupling as above |
| timer hats | 8 / 2 | movement-clock deferral modeled | idle wall-clock gap (above) |

---

## 4 · The battery as execution-characteristic evidence (revised 2026-08-25 against CCP_test_case_design.xlsx)

The reviewer's design (design_instructions/CCP_test_case_design.xlsx)
reframes the battery: test cases are not only pass/fail against playground
goals but **evidence of execution characteristics** — six playground-agnostic
rubric dimensions (Environmental Feedback · Control Structure · Spatial/
Motion Control · Representation & Abstraction · Goal-State Regulation ·
Recovery/Robustness, each with a U-Indeterminate level plus 0–2/0–3 ordinal
levels), nine test cases T1–T9, and a test→dimension map. A student's
solution strategy is read as the composition of characteristics their code
exercises across the battery. **Scope note:** this moves beyond
goal-recognition toward skill-level scoring — a new inference lane; the
rubric levels are claims about the CODE'S regulation structure, which the
simulator can evidence even where absolute playground outcomes (kg) can't
be simulated.

### 4.1 · What already exists to build on

The Phase-5 test-case harness (src/vex_goal_profiles/testcases.py +
configs/testcases/castle_crashers/) already provides: authored scenario
cards (YAML-only — pieces, **spawn/heading overrides**, thresholds, check
rules); an empty-island world with declared static pieces; a **testcase-only
kinematic push model** (pieces are pushed and can clear the island —
deterministic by design, a declared approximation of the random real
physics); `behavioral_divergence` (run WITH vs WITHOUT pieces — detection
evidenced by trajectory response, exactly the rubric's "state causes a
different action"); `min_distance`, `pieces_cleared`, `on_island` checks;
and loop-capped CONDITIONAL inference. Five CCP scenarios exist
(piece_ahead / piece_behind / piece_offaxis ≈ T4; two_pieces_reset ≈ T7;
edge_handling ≈ T3). The dev-corpus battery already ran: five credited
clearers, each attributable to a modeled sensor.

### 4.2 · T1–T9 feasibility against our simulation capabilities

| test | rubric dims (per map) | feasibility | what it needs |
|---|---|---|---|
| T1 canonical execution | Control Structure (+ trace) | **EXISTS** — the Stage-1/2 sweeps are T1: trajectory, contacts, coverage, boundary, hats fired, blocks_executed, timeline | a "structures exercised" trace extract (which loops/branches/hats actually ran) — small addition, sim already records it |
| T8 alternate start | Spatial, Env Feedback, Recovery | **in scope, trivial** — spawn/heading override is a card field; deterministic, no movables | scenario-card variants only (pure YAML) |
| T2 boundary encounter | Env Feedback, Control | **in scope, cheap** — down-eye red line is measured and sim-evidenced; empty island + near-edge spawns at several angles | cards; plus a small harness check for one-shot vs continually-regulated response (level 1 vs 2) |
| T4 block perturbation | Env Feedback, Spatial | **in scope** — three cards exist; static pre-disturbance placement keeps detection trustworthy (measured eye cone 124mm bounds valid placements) | extend to placement FAMILIES + cross-variant comparison (level inference needs behavior ACROSS variants, not one card) |
| T7 repeated opportunities | Representation, Goal-State | **in scope** — two_pieces_reset exists; kinematic push clears pieces deterministically | multi-piece configuration families; pair with code-structure evidence (loops/procedures) |
| T5 engagement perturbation | Spatial, Recovery | **in scope with caveat** — offset spawns + pieces supported; contact model measured; miss-detection evidenced by divergence | post-miss trace check (did behavior change after the miss — level 1 vs 0) |
| T6 achievement transition | Goal-State | **in scope via the harness trick** — don't simulate the real (random) clearing: either read the post-clear trace segment under kinematic push, or MATERIALIZE the post-achievement world state directly (the OI-19 late-materialization pattern) | a new `post_achievement_transition` check rule reading the trace after a pieces_cleared event |
| T9 recovery challenge | Recovery | **in scope for positional failures** (island-edge start — the design's own example — failed approach geometry) | compound scenario cards; failure states that depend on piece physics stay out |
| T3 boundary during clearing | Env Feedback, Goal-State | **partially exists** (edge_handling card) — robot-side behavior and piece-clears-while-robot-stays are both evidenced under the kinematic model | full "coordinate competing goals" LEVEL reading needs the T6-style post-event checks; build after T6 |

### 4.3 · Recommended build order

Ordered by dependency and cost — YAML-only card authoring first, harness
extensions second, compound scenarios last:

1. **T1 trace formalization** — extract "structures exercised" per run from
   existing sim output (nearly free; feeds Control Structure for all 205
   students, sensing users or not).
2. **T8 alternate-start family** — pure YAML cards; discriminates
   Coarse/fixed vs Calibrated vs State-derived for EVERY student (the 91
   students with no sensing blocks are still fully measurable here).
3. **T2 boundary-encounter family** — cards + the response-recurrence check
   (the one-shot/regulated distinction); feeds remain_on_island directly.
4. **T4 placement families** — extend the three existing cards; first
   cross-variant level inference.
5. **T7 multi-piece families** — extend two_pieces_reset; pair with static
   code evidence for Representation & Abstraction.
6. **T5 engagement offsets** — cards + post-miss trace check.
7. **T6 achievement transition** — the new check rule (harness extension);
   unlocks Goal-State Regulation properly.
8. **T9 recovery compounds** — needs T5/T6 machinery.
9. **T3 full reading** — edge_handling upgraded with the T6 checks;
   last because it composes everything.

### 4.4 · Out of scope / structurally capped

- **Absolute clearing outcomes (kg)**: weight is outcome-only; the kinematic
  push model evidences RELATIVE/behavioral claims (responds, re-engages,
  transitions), never kg. Rubric levels are exactly such relative claims —
  the fit is deliberate, but no battery number should be read as predicted
  weight.
- **Goal-State Regulation is proxy-capped in CCP**: student code has no
  sensor for the platform's kg counter; achievement is only observable via
  proxies (piece gone from the eye/distance cone, position). Expect U and
  low levels to dominate legitimately; that is a fact about the playground,
  not the students.
- **Random debris scatter**: still unreconstructable — battery placements
  must be static and pre-disturbance (all existing cards comply).
- **Wall-clock idle** (timer programs, 2 students): unknowable from code;
  real-run only if ever needed.
- **Edge divergence slips**: battery near-edge scenarios (T2/T3/T9) traverse
  the slip zone by construction — carry the edge_zone annotation into
  battery results.

### 4.5 · Considerations for the design

**Rubric-side considerations moved to RUBRIC_SCORING.md** (2026-08-26):
U-level certainty gating via the flag system, the static-first cascade,
cross-variant level inference, per-goal level profiles, which-run-gets-
scored, and the per-dimension population priors all live there now —
they belong to purpose 2 (§6.0).

Battery-side considerations that remain here:
- **Mixed strategies (WHEN in the run a test applies):** students compose
  approaches — dead-reckon to the plow, then sensor-based clearing. Tests
  must be able to scope to the goal-relevant SEGMENT of the run, or the
  composition averages away. Mechanism and tracking rule in §6.4.
- **Conditional-hat treatment**: battery scenarios with detection hats run
  under B1 (execute, the ratified permanent default); the inertness
  tripwire keeps watching.
- **Multi-stack programs**: resolved by the shipped cooperative scheduler
  (Phase A); the one bracket-divergent run stays U-gated.

**Accepted limitations — unchanged** (ruled, no action): debris scatter
randomness (sensor_uncertainty lane), edge divergence slips (soft
annotation), Switch text (faithful rejection), brightness (foreign),
program-end runoff fiction (flagged), weight_cleared physics (outcome-only).

---

## 5 · Full census (runs / students, of 7,984 / 205)

| feature | runs | students |
|---|---|---|
| drivetrain_blocks | 7,923 | 205 |
| enters_debris_zone (sim) | 6,352 | 204 |
| magnet_blocks | 4,674 | 166 |
| plow_attached (sim) | 3,686 | 146 |
| sim_boundary_exit | 2,896 | 199 |
| orphan_stacks | 1,875 | 116 |
| sensing_in_conditions | 1,648 | 114 |
| forever_loops | 1,532 | 120 |
| if_family | 1,429 | 103 |
| fabricated_motion (flag) | 1,171 | 143 |
| bounded_loops | 949 | 67 |
| down_eye_blocks | 943 | 85 |
| wait | 939 | 51 |
| distance_blocks | 898 | 86 |
| front_eye_blocks | 890 | 74 |
| sensor_reading_stale (flag) | 818 | 80 |
| operators_variables | 345 | 22 |
| detection_hats | 303 | 32 |
| when_started_plus_detection | 300 | 32 |
| concurrent_stacks_unverified (flag) | 287 | 20 |
| multiple_when_started | 287 | 20 |
| wait_until | 163 | 10 |
| nonfinite_numeric_clamped (flag) | 123 | 11 |
| bumper_blocks | 88 | 11 |
| procedures | 71 | 6 |
| looks_pen | 68 | 8 |
| multiple_detection_hats | 63 | 9 |
| wait_until_unmet (flag) | 61 | 6 |
| trigger_unfaithful (flag) | 46 | 7 |
| evidence_post_sim_exit (flag) | 30 | 15 |
| brightness_foreign | 27 | 1 |
| broadcasts | 12 | 3 |
| timer_blocks | 10 | 3 |
| timer_hats | 8 | 2 |
| broadcast_concurrency_approximated (flag) | 6 | 2 |
| timer_hat_unfired (flag) | 6 | 1 |
| position_heading_reporters | 6 | 2 |
| switch_text | 1 | 1 |

---

## 6 · Build plan

### 6.0 · Two purposes, one instrument (reviewer ruling 2026-08-26)

The battery scenarios serve TWO readers, and the harness is never forked:

1. **Goal-evidence recovery** — an alternative scoring channel for goals
   whose simulation evidence is U-gated: battery checks/facets feed goal
   ATTAINMENT confidence (the `detects` / `pushes_off` /
   `stays_on_island` pattern, `requires: detects` gating).
2. **Rubric scoring** — execution-characteristic LEVELS read from
   cross-variant behavior (the family→dimension composition; see
   RUBRIC_SCORING.md).

One artifact per scenario run — checks, path, structure_trace with
thread attribution — consumed by both readers. Phase B builds purpose 1
first; purpose 2 follows; every card is authored from day one to carry
the evidence purpose 2 will need (§6.2's forward-design constraint).
The two validation regimes stay distinct: goal-purpose tests validate
like fidelity (the C1 clearer pins); rubric-purpose validates via the
C3 hand-scored reliability sample. The two guards stay attached to
their purposes: `requires: detects` guards goal CREDIT;
bracketing/U-gates guard LEVELS.

Three phases — fix, build, validate — each ending in a reviewer sign-off
gate; any simulator change inside them follows the §6 protocol (one change →
attribution report → sign-off → regenerate pins/fixtures).

### 6.1 · Phase A — simulation fixes — **COMPLETE 2026-08-26**

**A1 · Multi-stack execution — SHIPPED as the VR-Seq cooperative
scheduler.** The creation-order lockout was built, falsified by the
corpus, and replaced by an at-source transliteration of VEX's shipped
scratch-vm fork (docs/archive/{SCHEDULING_MODEL,BUILD_SPEC}.md carry the
full arc). Cooperative is the card default: G3 byte-identity held for
single-thread runs (96% of the sample); G5 attribution = 14 named
verdict changes, all mechanism-attributed; G6-C1 (the five credited
clearers) held through every subsequent change. Residuals, both
instrumented: one predicate-bracket-divergent run carries
`debris_bracket_divergent` (the U-gate), and the C094/C164 family
stays capped-attributed on sub-1.5° edge-margin distance hits — an
ACCEPTED imprecision recorded on the robot card (the once-suspected
"aggregate detection defect" was retracted; the real finding was the
measured 2,000mm distance-sensor range, OI-25 resolved).

**A2 · Structures-exercised trace — BUILT.** Every SimulationResult
carries `loops_exercised` (block → iterations), `branches_exercised`
(block → arms taken), and `structure_trace` — ordered
(thread, event, block, detail) events in the archive §14 vocabulary,
so rubric evidence reads WHICH thread exercised WHAT. The Control
Structure evidence feed for all 205 students.

**A3 · Position/heading reporters — CLOSED (review-corrected).** The
rotation build added the cumulative `drive_rotation_deg` accumulator
and real turn_to time; the Phase-A review then caught and fixed the
rest: `position` honours UNITS, `position_angle`/`drive_heading` report
the VEX/card convention, `is_done`/`is_moving` are cooperative-aware.
Tripwire tests pin all four zero-incidence reporters; the capability
registry's last `testable` class is retired.

**Explicitly out of Phase A** (ruled): debris scatter and edge slips
(accepted limitations), Switch parsing, broadcast concurrency
(2 students). Wall-clock idle GRADUATED from blind spot to built-but-
parked machinery (60Hz clock + duration budgets — see the OPEN_ISSUES
parking lot for the unpark trigger).

### 6.2 · Phase B — battery buildout, two sub-phases (order per §4.3 within each)

**B-1 · Goal-evidence testing (build FIRST).** Scenario card families
whose checks map to goal facets — the existing `detects` / `pushes_off`
/ `stays_on_island` pattern with `requires: detects` gating (accidental
clearing is never credit). Card families: T8 alternate starts, T2
boundary encounters, T4 placement families, T7 multi-piece families;
then the harness checks that serve evidence (response recurrence,
post-miss, post-achievement transition); compounds (T5/T9/T3) last.
**Deliverable: a "test" evidence channel** — goal attainment indicators
fed by battery outcomes where simulation evidence is U-gated, with the
same abstain/flag discipline and a MARKED lower-certainty level (the
`on_island_sim` precedent: a fourth channel beside code / simulation /
outcome). **Router rule: tests run only where the sim channel is
U-gated** — static movable-sensing exposure plus the high-certainty
mask machinery, both already built.

**Forward-design constraint on every B-1 card:** (a) declare which
rubric dimension×level contrasts its variant family will eventually
discriminate; (b) declare its `applies` scope — whole-run vs
timeline-event-anchored segment (the §6.4 mixed-strategy rule) — even
when the scope is "whole run"; (c) preserve the FULL run artifact
(path, structure_trace, thread ids), not just check booleans, so B-2
re-reads B-1's runs without re-running them.

**B-2 · Rubric scoring (build SECOND; own design doc:
RUBRIC_SCORING.md).** The family→dimension-level composition layer with
per-dimension routing: deterministic rules wherever levels are decidable
from code/trace/path (dead-reckoners score Environmental Feedback 0 by
block census; Control Structure reads structure_trace), battery
re-reads only where levels turn on conditional behavior. Carries the
segment-scoping mechanism (§6.4) and the U-gate (flags/bracketing ⇒ U
per affected dimension).

### 6.3 · Phase C — validation

- **C1 · Dev-corpus pins first.** Run the full battery over the 112
  dev programs before any population claim: known behaviors, prior
  precedent (five credited clearers, each sensor-attributable), and the
  results become named tripwires like the OI-21 probe ledger.
- **C2 · Reviewer live-run protocol.** For a stratified sample of
  scenario × program pairs, reproduce the manipulation in VEX VR and
  compare observed behavior to the harness claim. **Open question flagged:
  which manipulations are physically reproducible in the real playground
  (piece repositioning yes; robot spawn override may not be) — the
  protocol should be designed around what the reviewer can actually stage.**
- **C3 · Rubric reliability sample.** The skill-scoring claim needs its own
  validation: reviewer hand-scores a stratified sample of programs on the
  six dimensions (blind to battery output); agreement against
  battery-derived levels is the headline number. Disagreements route to
  the same flag-and-queue loop that worked for fidelity.
- **C4 · Population dry run.** Full 205-student sweep; audit the U-rate per
  dimension (against §4.5 priors), the static-cascade short-circuits, and
  the mixed-strategy segment assignments (§6.4) before any level is
  reported as a finding.

### 6.4 · Mixed strategies: WHEN in the run a test applies

Students compose approaches — dead-reckoning to reach the plow, then a
sensor-based clearing strategy is a real and expected pattern (the rubric's
own premise: strategy = composition of characteristics). A whole-program
score would average the composition away, so:

- **Scoring unit: program × goal × dimension, evaluated over the
  goal-relevant SEGMENT of the run,** not the whole trace. The timeline
  machinery already emits the natural anchors — rung-transition events
  (plow attach step, zone entry, first piece contact, boundary encounter)
  with step indices.
- **Mechanism:** scenario checks gain an optional `applies` scope —
  whole-run (default) or anchored between timeline events (e.g.
  Environmental Feedback for clear_debris_zone reads the segment AFTER
  first zone entry / attach; Spatial for engage_plow reads the approach
  segment BEFORE it). Card-declared, like everything else.
- **Where it may not matter** (track, don't over-engineer): Control
  Structure and Representation read the whole program by nature; T8's
  start-perturbation reads from step 0 by construction. The tracking rule:
  every card family states its scope explicitly, even when the scope is
  "whole run" — so composition handling is visible, never implicit.
- **Corollary for scoring:** a student can legitimately hold DIFFERENT
  levels on the same dimension for different goals (dead-reckoned approach
  = Spatial 1-Calibrated; sensor-clearing = Env Feedback 2-Regulated).
  That per-goal profile IS the strategy fingerprint the design is after —
  report it un-collapsed; any rollup to a single skill level is its own
  later ruling.

---

*Open for reviewer ruling: the §6 phase plan (A1 OI-7 first is ruled; A2/A3
ordering), the C2 reproducibility question (what can be staged in the real
playground), which run gets rubric-scored (session-final vs trajectory),
and the §6.4 segment-scoping mechanism. This document is the OI-20 working
surface — subsequent battery designs and rulings append here.*
