# RUBRIC_SCORING — execution-characteristic levels (STUB; filled at Phase B-2)

Status: design stub (2026-08-26, reviewer ruling: two purposes, one
instrument — see SENSOR_TESTBATTERY.md §6.0). This document becomes the
design surface for purpose 2 when Phase B-2 opens. Nothing here is built.

## The dimensions

Six playground-agnostic dimensions, each with a U (indeterminate) level
plus ordinal levels. **The authority is
`design_instructions/CCP_test_case_design.xlsx`** (rubric tab: dimensions,
levels, evidence indicators; test_cases tab: T1–T9; test_rubric_map tab:
how levels manifest): Environmental Feedback · Control Structure ·
Spatial/Motion Control · Representation & Abstraction · Goal-State
Regulation · Recovery/Robustness.

## The scoring unit

**program × goal × dimension × segment.** A student can legitimately hold
different levels on the same dimension for different goals (dead-reckoned
approach = Spatial-Calibrated; sensor clearing = Feedback-Regulated); that
un-collapsed per-goal profile IS the strategy fingerprint. Segments are
timeline-event-anchored per the mixed-strategy rule (SENSOR_TESTBATTERY
§6.4); any rollup to a single skill level is its own later ruling.
Which run gets scored (session-final vs level trajectories over runs) is
an open ruling to take before scoring starts.

## The per-dimension router (rules vs battery)

Deterministic rules wherever a level is decidable from code, trace, or
path — battery re-reads only where a level turns on conditional behavior:

| dimension | deterministic-rule sketch | battery needed when |
|---|---|---|
| Environmental Feedback | no sensing blocks ⇒ level 0 (block census; ~91/205 students short-circuit) | sensing present: does state actually change behavior (T2/T3/T4/T8 families) |
| Control Structure | read `structure_trace` / `loops_exercised` / `branches_exercised`: which structures RAN, which arms | rarely — levels are largely trace-decidable |
| Spatial / Motion Control | calibrated-vs-coarse from path geometry vs card geometry | state-derived motion needs variant families (T4/T5/T8) |
| Representation & Abstraction | procedures/variables/loop census + structure reuse | T7 multi-instance generalization |
| Goal-State Regulation | proxy-capped in CCP (no kg sensor): timeline achievement events vs subsequent behavior | T6 post-achievement transitions |
| Recovery / Robustness | rarely rule-decidable | T5/T9 perturbation families |

## The U-gate

Any flag compromising a test's evidence channel ⇒ U for the dimensions
that test feeds — the `high_certainty_mask` pattern (flags-empty rule),
plus `debris_bracket_divergent` from predicate bracketing. U is
certainty-gated by instrument, never judged ad hoc. Population priors
(from the SENSOR_TESTBATTERY census): Environmental Feedback can exceed
level 0 only for the 114 sensing-in-conditions students (+32 with
detection hats); Control Structure has real range (120 loop, 103
branch); Representation's top level is rare (6 students use procedures,
22 variables/operators) — expect a floor-heavy distribution.

## Validation

The C3 regime (SENSOR_TESTBATTERY §6.3): a hand-scored reliability
sample — reviewer scores a stratified sample on the six dimensions blind
to battery output; agreement against derived levels is the headline
number; disagreements route to flag-and-queue. Distinct from the
goal-evidence regime (C1 clearer pins), and never substituted for it.

## Output separation

**Rubric levels are not goal indicators.** They live in a separate
output object from `GoalProfile`, with `evidence_source` provenance
stamps on every level: `simulated | outcome | test | rules`. Goal
attainment answers "did the code pursue/attain the goal"; rubric levels
answer "how is the execution organized" — the two never mix in one
object, and neither reader forks the harness that feeds them.
