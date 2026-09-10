# FINDINGS — recorded, not resolved

Corpus: the 119 final code states in `data/final_code_states.parquet`.
Built 2026-08-18. All counts below are reproduced by `tests/test_corpus_regression.py`
(pins on full-path values; truncated values printed by
`test_truncated_counts_recorded_for_findings`).

## Truncated (§6a) vs full-path baselines

| Quantity | Full path (design pins) | Truncated (§6a, the pipeline's operating scope) |
|---|---|---|
| `boundary_exceeded` | **68** | 68 (scope-independent) |
| `plow_approach_intent == reached` | **46** | **43** — lost: WREN-C055, WREN-C056, WREN-C101 (all `_S001`) |
| `plow_proximity_execution == armed_within_radius` | **43** | **41** — lost: WREN-C055, WREN-C101 |
| … with `geometry_undescribed` | 19 (see below) | 19 |
| … with `stuck_zone` | **7** | 7 |
| `magnet_activation_intent == boost` | **70** | 70 (code channel, unaffected) |
| abstained `outcome_field_absent` | **7** | 7 (outcome channel, unaffected) |

The three programs losing `reached` under truncation only touch the plow after
leaving the island — exactly the class of simulation fiction §6a exists to exclude.

> **Superseded values (2026-08-18):** after the signed-off task-3 changes, the
> pinned `boundary_exceeded` is **78** (continuous-motion terminal runoffs) and
> the reached/armed membership swapped WREN-C008 → WREN-C052 at equal counts.
> The table above is the task-1 historical record; the current baselines live
> in the signed-off attribution reports at the end of this file, and the pin
> table in `tests/test_corpus_regression.py` is always authoritative.

## Zone flags — the revised all-qualifying-steps rule; geometry count not pinned

Zone flags are evaluated over **all** qualifying steps (armed ∧ within tolerance)
with precedence (spec revision, 2026-08-18): if any qualifying step lands in a
described zone that carries no flag, engagement is plausible — **no flag** —
regardless of where the trajectory started; otherwise the **first** qualifying
step's outcome stands (its zone's flag, or `geometry_undescribed` when it matched
no zone). Under this rule the measured counts are **19 undescribed / 7 stuck**,
matching the design table — which resolves the discrepancy seen under the earlier
first-step-only rule (20/7): the design analysis evidently used the precedence
rule.

- Exactly one engagement clears under precedence: `DOVE-C049_DOVE-NCO49_S002`
  (first qualifying at y=1049, undescribed below the plow; later qualifying steps
  at y=1349, `rotation_assisted`). Note this is an undescribed-then-described
  trajectory, not stuck-then-direct — the rule clears any unflagged described
  zone reached while armed and within tolerance.
- `WREN-C094_WREN-C094_S001` stays `geometry_undescribed`: its qualifying steps sit
  at y=1150.2 (undescribed) and y=1291.6 (stuck zone); it never reaches an
  unflagged described zone, so the first step's outcome stands.
- The 19 undescribed split as **8 below the plow** (y < 1169) and **11 in the
  undeclared 1230–1250 gap** between `direct_attraction` and `stuck_zone` — eight
  of them at exactly y=1249.0 (a common approach path). The gap's status belongs
  in the playground card, not in code.

Reviewer decision (2026-08-18): the geometry count remains **unpinned** ("the
wrong thing to pin") even though it currently matches the design table; it is
computed and recorded here instead.

## Abstentions over the corpus

- **7 sessions abstain `outcome_field_absent`** on `weight_cleared` (the spec's
  wrong-playground sessions — their params carry `coral_damaged` etc. from another
  playground; handled by the generic absent-field mechanism, no special-casing):
  DOVE-C016_S004, DOVE-C065_S004, DOVE-C068_S002, DOVE-C071_S002, DOVE-C076_S002,
  DOVE-C081_S001, DOVE-C089_S002 (full ids in the review CSV).
- **No program abstained on the code or simulation channel**: all 119 XML payloads
  parse (the 3 programs absent from the frozen-path fixture parse but produce no
  path steps, which is a value of 0/empty, not an abstention).
- **No program needed the GPS fallback** on `robot_moved` — all 119 carry
  `gps_x_position`/`gps_y_position`, so the `simulated_fallback` path never fired
  on this corpus (it is covered by unit test instead). Corollary: the R9
  frame-mismatch risk is untested by corpus data; no `moved`-without-movement-block
  contradictions observed.

## Scope decisions that reconciled the pins (recorded for re-derivation)

- **`code_state_authored` counts active (event-attached) blocks only**
  (`linearize(include_orphans=False)`): with orphans included boost = 74; the four
  orphan-only-boost programs (DOVE-C030, WREN-C040, WREN-C059, WREN-C075) put it over
  the design pin of 70. A detached block never executes, matching the simulator's
  own scope.
- **Field values are read from all fields on a block**, not the registry's
  `xml_fields` column: `blocks.csv` says the magnet block's field is `STATE`, but
  the corpus XML carries `ACTION` (the vendored simulator likewise reads both).
  Pin-verified via boost = 70.
- **Zone flags evaluate all qualifying steps with precedence** (unflagged
  described zone anywhere clears; otherwise the first qualifying step's outcome
  stands); see the zone-flags section above.

## Other observations

- `no_declared_intent` fires on **7** programs (proximity `near`-or-better with no
  magnet authored — sweep spillover, as the card's `approach_path_caveat` predicts).
- Our origin-seeded polygon boundary scan agrees with the simulator's
  `exits_field_boundary` on all 119 (asserted as a sanity check, not a pin).
- Performance: `profile()` median ≈ **3ms** over the corpus (target < 50ms).
- Rung-rule interpretation adopted (user decision, 2026-08-18): `direction` is
  required exactly when a rung has numeric edges; categorical label-only rungs are
  exempt; labels map to ascending-value bins. The spec's §5 rule 6 prose conflicts
  with its own example cards in both places (categorical magnet rung and
  `weight_cleared` lack `direction`; "labels best-first" contradicts the G3 ladder).
  Our authored card gives `weight_cleared` an explicit `direction: higher_is_better`.
- §13 open items stand: the 7 wrong-playground sessions are detected generically and
  abstain (not dropped); rung edges are inherited first-pass values —
  `config_version` makes revising them cheap.
- No new goals, indicators, or rungs are proposed.

---

# Task 3 — hat-stack execution fidelity (2026-08-18)

`vendor/goal_strategy_detector/simulation/simulate_path.py` is **no longer
byte-identical** to VEX_model_tracing (recorded in its module docstring). Every
other vendored file remains verbatim and `cmp`-verifiable. Pending decisions
surfaced by this task live in **`OPEN_ISSUES.md`** — the researcher's decision
queue; nothing there is decided by the pipeline.

## §3b ground truth — the two-tier fidelity metric (revised)

A final-coordinate error is meaningless once the robot is off the island —
nobody cares where off the field it ended, only that it did. The metric is
therefore two-tiered (all fields in the review CSV; GPS field names declared in
the playground card under `outcome_metrics.final_gps_position`):

**(a) `off_island_agreement`** — primary, all 119: does the simulated final
position fall outside `field_boundary.polygon_mm` iff the real GPS does?

| | gps ON | gps OFF |
|---|---|---|
| **sim ON** | 42 | 31 |
| **sim OFF** | 5 | 41 |

**Agreement 83/119 = 70%.** Against `boundary_exceeded` (ever off — the pinned
quantity): **89/119 = 75%, 17 under-detections, 13 over-detections.**

**(b) `gps_final_error_mm`** — computed only where both sides agree the robot
stayed on the island, the only subset where coordinates are comparable:
**n=42, median 145mm, 21/42 (50%) within 100mm.** Everywhere else the CSV
carries null with `gps_final_error_reason: off_island_position_not_comparable`.

Subset tables under the new metric:

| Subset | n | off-island agreement | comparable median error |
|---|---|---|---|
| all | 119 | 70% | 145 mm (n=42) |
| clean — no exit, no cap, no fabricated, single hat | 27 | **93%** | **13 mm** (n=25) |
| exits island (`boundary_exceeded`) | 68 | 72% | 613 mm (n=8) |
| multi hat stacks | 10 | 70% | 1996 mm (n=3) |
| loop capped | 22 | 59% | 873 mm (n=6) |
| fabricated motion | 26 | **46%** | 1692 mm (n=5) |

The story is now cleaner than under the old scalar: the simulator is faithful
when no known defect applies (93% agreement, 13mm), and fabricated motion is
decisively the worst subset.

**The 36 disagreements are a debug queue, not a statistic** — full list below
(§"off-island disagreement queue"), tracked as OPEN_ISSUES OI-2.
**Under-detection dominates 31-to-5**: the simulator keeps students on the
island who really drove off — consistent with the 200mm continuous-drive
fallback being too small (OI-3; 12 of the 31 under-detections contain
fabricated motion).

## Part A — inline broadcast execution

Receivers (`pg_events_when_broadcasted`) are excluded from the top-level loop
and execute inline at their broadcast site, matched on `BROADCAST_OPTION`;
recursion guard via an active-event set; multiple receivers run in document
order. Plain `broadcast` inlining is an approximation (flag
`broadcast_concurrency_approximated`); `broadcast_and_wait` inlining is exact.

`WREN-C012_WREN-C012_S001`'s §2 cascade (eye hat → broadcast → receiver
forever{turn}) is real but only *visible* under B2, which silences all 20
receiver turns (69 → 49 steps); under B1 its path is byte-identical because the
receiver already sat immediately after the broadcasting hat in document order.

**The attribution report for sign-off is re-issued at the end of this file**
(§"Part A ATTRIBUTION REPORT — re-issued for sign-off").

## Part B — conditional hats: B1 ADOPTED (decision, 2026-08-18)

**Decision: B1 (execute), on evidence, not principle.** The reasoning of
record: B2 changes **no indicator rung** on any of the 9 conditional-hat
programs, and exactly **one continuous value** sub-rung (WREN-C040's
`debris_zone_coverage`, 0.0351 → 0.0, rung `negligible` both ways — logged as
OPEN_ISSUES OI-1; an earlier report of "no value changes" was an artifact of
1-decimal rounding). The decision therefore reduces to the two
`boundary_exceeded` flips, and the real GPS settles both: **WREN-C018's real
final position is (1506, 1889) and WREN-C103's is (1508, 2641) — both outside
the field. B1 flags both as leaving, matching reality; B2 would flag both as
staying, contradicting it.**

Under the two-tier metric: B1 agrees with reality on off-island status for
C018 and C103; B2 disagrees on both. No other program's agreement changes
between treatments.

**B3 (abstain) is withdrawn**: abstention is right when uncertainty propagates
to what you report, and here it demonstrably does not. B2/B3 remain available
behind the existing flag (`--conditional-hats`,
`VEX_GOAL_PROFILES_CONDITIONAL_HATS`, `_profile` parameter).

**Guard:** `test_conditional_hat_treatment_is_inert` asserts B1 ≡ B2 on every
indicator value and rung across all 119, with exactly three permitted,
documented differences: the two boundary flips and the OI-1 value delta. A new
failure means the treatment has become load-bearing in an unreviewed way — the
failure message directs it into `OPEN_ISSUES.md` for researcher review, not to
an on-the-spot re-pick.

**Note in passing** (decision robustness): the two swing programs are one from
each untrusted-trigger category — C018's hat is an eye (`trigger_unfaithful`),
C103's a bumper (`trigger_unsimulated`) — and the GPS evidence favours B1 in
both, so the decision holds across the categories, not just one.

## Part B′ — the untrusted-trigger taxonomy (flag split, 2026-08-18)

`conditional_hat_unevaluable` conflated three situations with different
resolutions and timelines; it is replaced by:

| Category | Hats | Treatment | Corpus |
|---|---|---|---|
| Evaluable, trusted | `when_started`; `when_broadcasted` (after Part A); `when_timer` (simulated clock) | fires normally, no flag | timer: 0 programs |
| Evaluable, known-unfaithful | `pg_events_optical_detect_object` — answers omnidirectionally against a 1136mm tolerance, pending sensor audit | `trigger_unfaithful` | 7: WREN-C012/-C017/-C018/-C027/-C031/-C040/-C042 |
| Not evaluable at all | `pg_events_when_bumper` — no sensor simulation exists | `trigger_unsimulated` | 2: WREN-C055/-C103 |

The distinction matters: the first flag marks a fidelity defect in something we
**do** model (OI-5); the second marks a capability we have **not built** —
blocked on simulator work, not a modelling choice (OI-6). Under B3 (available,
not default) the abstain reason is the specific flag, `trigger_unsimulated`
taking precedence when both apply.

## Part C — concurrent `when_started`: flagged

`concurrent_stacks_unverified` fires on exactly `WREN-C008_WREN-C008_S001` and
propagates to its simulation-channel indicators. Superseded hypothesis
(corrected 2026-08-18): the VEX API confirms multiple `when started` stacks
run **in parallel** — the one-stack-per-test conjecture is refuted. The open
question is drivetrain arbitration between concurrently-commanding stacks;
see OI-7 for the API text of record and the refined §8 probe. C008 is flagged
as the maximally complex case (parallel stacks + two broadcast receivers).

## Part D — fabricated motion: instrumented, unchanged

`SimulationResult.fabricated_steps` records every fallback step (bare
continuous drive = 200 mm, bare continuous turn = 90°, unsatisfied `wait_until`
= 50 mm probes). `GoalProfile` gains `fabricated_motion` /
`boundary_exit_fabricated`; simulation-channel indicators on affected programs
carry `flags: ["fabricated_motion"]`. No constant and no execution changed.

Dynamic counts (executed fallbacks; the task's table counted static sites, so
sites that never execute don't appear here):

| Fallback | sites (programs) | executed steps | invented travel |
|---|---|---|---|
| continuous drive alone (200 mm) | 28 (21) | 530 | 106,000 mm (steps) / 5,600 mm (sites) |
| continuous turn alone (90°) | 18 (9) | 32 | — (heading only) |
| `wait_until` unsatisfied | 1 (1) | 500 | 25,000 mm (steps) / 2,500 mm (site) |

**26 programs** carry ≥1 executed fabricated element (task's static count: 28).
The step-basis travel dwarfs the site basis because fallbacks inside `forever`
loops re-execute up to 20×.

**`boundary_exit_fabricated` = 6 programs** — the task's predicted five
(`WREN-C015`, `WREN-C019`, `WREN-C026`, `WREN-C065`, `WREN-C027`) **plus
`WREN-C083_WREN-C083_S001`**, whose first out-of-bounds step is also a fallback
step under the dynamic definition. For these, the §6a truncation point is an
artifact of an invented distance, and they are inside the boundary pin of 68.

Under the two-tier metric the fabricated subset is decisively the worst:
**46% off-island agreement** (12/26) and comparable-median error 1692 mm (n=5)
— consistent with the task's direction-of-degradation claim and with Chris's
observed misconception that the 200 mm drive fallback is too small (OI-3;
recorded, not acted on — §8 probe settles it).

## WREN-C082 — the 59-metre outlier, inspected

`WREN-C082_WREN-C082_S001` produces zero simulated path steps because its entire
program body sits inside a `pg_control_while` whose condition is a sensor
reporter the expression evaluator cannot evaluate (returns falsy) — the loop is
never entered. The real run's GPS sits at (−58438, −1669), 59.5 m from spawn
and far outside the ±1.7 m field — the physical robot evidently kept driving
(41 active blocks of drive/turn/wait inside that loop). This is the
unevaluable-condition cousin of defect B, out of scope; recorded.

## §8 probes

The seven real-playground probes are Chris's; nothing here acts on them. The
data above sharpens two: the 200 mm drive fallback (26-program subset, worst
off-island agreement — OI-3) and the plow-from-below geometry (19 undescribed
engagements — OI-4).

## Off-island disagreement queue — the 36, with positions (OI-2)

Sim final vs real GPS final, mm, rounded. **Under-detection dominates
31-to-5**: the simulator keeps students on the island who really drove off,
consistent with the 200mm continuous-drive fallback being too small (OI-3).
`fab` marks programs containing fabricated motion.

**Under-detections (sim ON island, gps OFF) — 31:**

| program | sim final | gps final | fab |
|---|---|---|---|
| DOVE-C007_DOVE-NC007_S001 | (1014, 249) | (−2060, 241) | ✓ |
| DOVE-C028_DOVE-C028_S001 | (1014, 49) | (−1397, −1291) | |
| DOVE-C046_DOVE-NCO46_S001 | (−586, −551) | (−2289, −542) | ✓ |
| DOVE-C049_DOVE-NCO49_S002 | (−816, 399) | (1972, 367) | ✓ |
| DOVE-C060_DOVE-NCO60_S003 | (814, 49) | (−2079, 49) | ✓ |
| WREN-C001_722305_S001 | (694, 99) | (−525, −2088) | ✓ |
| WREN-C004_714980_S001 | (626, 496) | (1118, −1584) | |
| WREN-C006_WREN-C006_S001 | (−829, 794) | (−1246, −2448) | |
| WREN-C012_WREN-C012_S001 | (−129, 649) | (−1963, 283) | |
| WREN-C014_WREN-C014_S001 | (333, −343) | (2102, 537) | |
| WREN-C030_WREN-C030_S001 | (1014, −751) | (−2009, −389) | ✓ |
| WREN-C035_WREN-C035_S001 | (−272, −169) | (−387, −2218) | |
| WREN-C040_WREN-C040_S001 | (−536, −151) | (−2751, 56) | ✓ |
| WREN-C046_WREN-C046_S001 | (125, −103) | (1772, −969) | |
| WREN-C053_WREN-C053_S001 | (−319, 1510) | (910, −1890) | |
| WREN-C055_WREN-C055_S001 | (−595, 1446) | (−1106, 1554) | |
| WREN-C056_WREN-C056_S001 | (690, 411) | (2123, 225) | |
| WREN-C057_WREN-C057_S001 | (1014, 49) | (3020, 20) | |
| WREN-C058_WREN-C058_S001 | (−1435, 925) | (−1058, 1555) | |
| WREN-C060_WREN-C060_S001 | (214, 1449) | (1249, −1305) | ✓ |
| WREN-C062_WREN-C062_S001 | (−1486, 349) | (−1870, 41) | ✓ |
| WREN-C064_WREN-CO64_S001 | (−860, 791) | (1386, −1169) | |
| WREN-C067_WREN-C067_S001 | (−1486, −51) | (−1872, −708) | ✓ |
| WREN-C069_WREN-C069_S001 | (599, −1318) | (−1599, −1593) | |
| WREN-C077_WREN-C077_S001 | (−186, 49) | (−2526, 54) | ✓ |
| WREN-C082_WREN-C082_S001 | (1014, 49) | (−58438, −1669) | |
| WREN-C086_WREN-C086_S001 | (49, 124) | (−1984, 166) | |
| WREN-C089_WREN-C089_S001 | (−822, −414) | (−992, 1636) | |
| WREN-C096_WREN-C096_S001 | (−779, −1447) | (−967, −1845) | |
| WREN-C099_wren-co99_S001 | (132, 152) | (321, 2633) | |
| WREN-C102_710567_S001 | (789, 865) | (−648, −2052) | ✓ |

**Over-detections (sim OFF island, gps ON) — 5:**

| program | sim final | gps final | fab |
|---|---|---|---|
| DOVE-C065_DOVE-NCO65_S004 | (1856, −82) | (−877, −1193) | |
| DOVE-C076_DOVE-NCO76_S002 | (−548, −22454) | (−1030, 470) | |
| WREN-C003_WREN-C003_S001 | (−1957, −870) | (248, 1590) | ✓ |
| WREN-C009_WREN-C009_S001 | (−586, 1949) | (−217, 1737) | |
| WREN-C052_WREN-C052_S001 | (1708, 197) | (−1602, −117) | ✓ |

Standouts for first triage: WREN-C082 (OI-8), DOVE-C076 (simulated 22.4m
off-field while the real robot stayed on — runaway simulated distance).

---

# Part A ATTRIBUTION REPORT — re-issued for sign-off (2026-08-18)

**Change under review:** inline broadcast execution (task 3 Part A) in
`vendor/goal_strategy_detector/simulation/simulate_path.py`. Receivers execute
at their broadcast site (matched on `BROADCAST_OPTION`, recursion-guarded,
document order for multiple receivers, flags
`broadcast_concurrency_approximated` / `broadcast_recursion_suppressed` /
`broadcast_multiple_receivers`), and are excluded from the top-level loop.

**1 · Paths changed: 1 of 119 — `WREN-C008_WREN-C008_S001` only.**
9 → 8 steps; first divergent step **7**. The removed step is the `my_event`
receiver's `stop_driving`, which old document-order execution ran even though
nothing ever broadcasts `my_event` (its `broadcast_and_wait` sits in an if-body
whose condition never passes) — a phantom step. The `Chash` receiver's
continuous-drive now runs at its broadcast site. Movement geometry unchanged.
`WREN-C012` (the other expected program) is byte-identical: its receiver already
sat immediately after the broadcasting eye-hat in document order; it gains the
approximation flag only. No third program moved.

**2 · Task-1 pins, before → after (full-path):**

| pin | before | after |
|---|---|---|
| `boundary_exceeded` | 68 | **68** |
| `reached` | 46 | **46** |
| `armed_within_radius` | 43 | **43** |
| `stuck_zone` | 7 | **7** |
| `boost` | 70 | **70** |
| `outcome_field_absent` | 7 | **7** |

(geometry_undescribed, unpinned by reviewer decision: 19 before, 19 after.)

**3 · Off-island agreement, before → after: 83/119 (70%) → 83/119 (70%).**
Unchanged — WREN-C008's final position is identical before and after (the
phantom `stop_driving` did not move; the relocated receiver drive covers the
same geometry), and it is an off-island-agreeing program under both.

**4 · Fixture status: SIGNED OFF AND REGENERATED (2026-08-18).**
This report was signed off by the reviewer and `data/frozen_paths.parquet` was
regenerated from the post-Part-A simulator (B1 default): 5548 → 5547 rows, the
one removed row being WREN-C008's phantom `stop_driving` step; same 116
programs. The fixture is now the local baseline and intentionally diverges from
the source project's copy. **Pins required no update** — all six pinned values
are identical before and after Part A. `test_path_identity` is green against
the new baseline; any future path-changing edit breaks it again by design, one
change at a time, each with its own attribution.

---

# Task 2 — goal event timeline + review viz (2026-08-18)

## A · timeline.py

`timeline()` / `timeline_result()` in the core package (pyyaml-only, no new
deps). Every event is a rung transition on a card-declared indicator — no
per-goal event conditions, no configuration, no spans. Fast paths per §A3:
running minima and the state latch in one O(n) pass, coverage crossings by
binary search (~log2(n) slices per edge); code/outcome channels evaluate once
through the registry. **Median 11.5ms over the 119 (target < 100ms).**

Conventions adopted (documented in the module docstring):
- The origin pseudo-step is step **-1** (block-less). **Code-channel events
  land there**, not on path step 0 — authored code precedes execution, step 0's
  block did not cause the code state, and a zero-step program (WREN-C082) still
  gets its code events. §A3's "one event at step 0" is read as "at the start of
  the timeline".
- Outcome-channel events land on the final scored step.
- Scored and post-exit lists are split at the §6a boundary (never merged);
  prefix-monotonicity makes full-path crossing steps identical to
  truncated-path ones at steps ≤ exit, so the timeline is computed once.
- §A5 regressions verified: WREN-C094 arms (step 3) before reaching (step 23)
  with a boundary failure at 33; WREN-C050 reaches (step 3) before arming
  (step 6). Binary-search coverage crossings agree with brute force on 10
  programs; monotonicity asserted.

## B · review viz (`viz/`, run: `streamlit run viz/app.py`)

Deps (`viz/requirements.txt`: streamlit, plotly, pandas, pyarrow) stay out of
the core package. `vex_blocks.js` copied **verbatim** from VEX_model_tracing;
`blockly.py` copied; `plots.py` adapted (NodeResult coupling, the node-specific
overlay, and stringified band-edge parsing removed; fabricated/GPS/post-exit
overlays added). The walkthrough is one self-contained HTML component — all
stepping client-side, Blockly canvas rendered once (collapsible, auto-expanded
on multi-stack programs), block-tree list as the steppable contract with
stacks grouped (never flattened), receiver stacks annotated with their inline
broadcast site instead of a top-level ordinal, trust flags on stack headers,
orphan groups marked never-executed, iteration counters on loop-body rows.

§B4 acceptance mapping: OI-1 treatment selector (B1/B2/B3) on View 1, greyed
for non-hat programs; OI-2 real-GPS marker + the prefiltered disagreement
queue (View 3c) with per-row defect attribution persisted to
`data/oi2_triage.json` and an attributed-count; OI-3 fabricated steps marked
on path, tree, and events; OI-4 zone bands from the card via the goal-card
`zones_ref` binding, with the undescribed complement (below-object + declared
gaps) as distinct bands and qualifying steps ringed; OI-5/OI-6 trigger flags
on the specific stack header; OI-8 WREN-C082 renders with the why (unknown
reporter blocks named); OI-9 rung-calibration view with distributions, edges,
counts, event-step histograms, and `config_version` shown. The two-tier
fidelity metric renders as such: the coordinate error appears only where
comparable, elsewhere the reason string.

## Task 2 §E proposals

1. **Block label vocabulary** (revised per reviewer, 2026-08-18): labels are a
   property of the VEX block set, not of a playground — a per-card copy would
   be duplicated by every new playground and drift from the CSV it came from.
   The §E suggestion to put them in the playground card was retracted; instead
   the viz **derives them at load time from the vendored `blocks.csv`** (via
   the block registry's display-name map, `viz/data.py`). Nothing label-related
   lives in any card, and the CSV remains the single source of truth.
   (`block_families` stays in the card — which block types are "the magnet"
   for a card's goals is legitimately playground-specific.)
2. **Near-cut-point δ**: default carried from the old app (5% of the observed
   value range), adjustable 1–20% via a slider in View 3a.

---

# Addendum — the `optical_color` field-name defect (2026-08-18, via viz debugging)

Found while debugging WREN-C082's while-guard rendering in the walkthrough:
`_eval_expression`'s `pg_sensing_optical_color` handler reads
`block.get_field("COLOR")`, but all 12 such blocks in the corpus carry the
field as **`COLORS`** — the simulated down-eye colour check **always returns
False** for every program that uses it (12 programs). Logged as **OI-10** in
the sensor cluster; not fixed — a corrected read is path-changing and goes
through the §6 attribution protocol.

**The causal overlap that makes it matter: all six `boundary_exit_fabricated`
programs (WREN-C015/-C019/-C026/-C027/-C065/-C083) are `optical_color`
programs.** Their authored boundary-avoidance loops (`if downeye detects red:
back up / turn, else: drive on`) never fire in simulation, so the else-branch
continuous drive runs instead — frequently as the 200mm fabricated fallback —
and the simulated robot walks off the island on an invented distance while the
real robot's avoidance kept it on (or vice versa). OI-10 is therefore a prime
suspect behind parts of OI-2 (off-island disagreements) and interacts directly
with OI-3 (the fallback size): fixing the field read may re-attribute several
disagreements before any fallback constant is touched.

OPEN_ISSUES.md was restructured the same day (reviewer instruction): OI-1,
OI-5, OI-6, OI-8 moved into a **sensor-simulation cluster** at the end of the
file, joined by OI-10 (this defect) and OI-11 (the general principle that code
consulting unsupported sensing blocks cannot be evaluated — 5 programs consult
`pg_sensing_distance_found` at runtime). OI-1 was reclassified as
sensor-rooted per the reviewer: WREN-C040's B1/B2 coverage delta comes entirely
from its forced eye-hat stack, so the sub-rung question reduces to "would the
eye have fired?". The whole cluster is re-reviewed together once sensing
capabilities are implemented.

---

# Continuous-motion ATTRIBUTION REPORT — final rule (SIGNED OFF 2026-08-18)

**Change under review** (reviewer-directed, 2026-08-18, two refinements same
day). Continuous `drive`/`turn` semantics, built on the simulator's pending-
motion mechanism:

1. A bare continuous block **arms pending motion**. A later `wait` converts it
   to velocity × time; velocity setters do NOT preempt (a speed change applies
   to the continuing motion); instant blocks pass through leaving it armed.
2. Any **drivetrain command** (drive/turn/drive_for/turn_for/turn_to_*/stop)
   supersedes it — zero elapsed time, zero motion, no step. An in-loop
   trailing bare block is superseded by the next iteration's first drivetrain
   command the same way.
3. **Pending still armed at normal program end = the robot drives
   indefinitely until failure** (reviewer ruling on OI-3): a terminal runoff
   of 4 × field radius (geometry-derived, guaranteed to exit any island from
   any interior point; clamped by the 33m guard), marked **fabricated**.
   Trailing bare turn: nominal 90°. `stop project` halts the robot — no
   runoff.

Motivating cases: DOVE-C007 (`turn right; drive fwd` — the turn never happens,
the terminal runoff drives it off-island westward exactly as its real GPS
says: **now agrees**); the in-loop 200mm crawl artifacts are gone.

**1 · Paths changed: 26 of 119** (supersessions shrink paths; terminal
runoffs extend them). Full per-program diff reproducible from the snapshot.

**2 · §3b fidelity, before → after: off-island agreement 83/119 (70%) →
91/119 (76%)** — **13 resolved** (DOVE-C007, DOVE-C046, DOVE-C049, DOVE-C060,
WREN-C001, WREN-C003, WREN-C030, WREN-C052, WREN-C060, WREN-C062, WREN-C067,
WREN-C077, WREN-C102 — nearly all previously under-detections, confirming the
too-small-fallback hypothesis), **5 new** with a loud common cause: **4 of 5
are `project_stopped_by_user` runs** (DOVE-C064, DOVE-C068, WREN-C008,
WREN-C015) — the runoff models "left running until failure," and these robots
were stopped on-island before failing. DOVE-C068 is additionally a
wrong-playground-GPS artifact; WREN-C083 (the 5th) is an OI-10 sensor-cluster
program. Comparable on-island subset: n=40, **median 61mm** (from 145mm) —
the agreeing set is much cleaner.

**3 · Task-1 pins, before → after:** **boundary 68 → 78** (13 newly exceed —
their terminal runoffs exit, as reality demands; 3 no longer exceed — their
old exits rode the deleted in-loop crawls). reached **46 → 46** and armed
**43 → 43** — counts identical but **membership swaps WREN-C008 out (its old
proximity rode a fallback drive that supersession removed) and WREN-C052 in**
(corrected headings engage the plow; caveat: a stopped-by-user run).
stuck 7, geo 19 (the swap is geo-for-geo), boost 70, outcome-absent 7.

**4 · Part D:** fabricated programs 26 → **16**; `boundary_exit_fabricated`
6 → **16** — most §6a truncation points are now the terminal runoff itself,
i.e. the scored path covers the full authored program and the exit is the
modelled run-to-failure. OI-3 now concerns only the runoff/90° magnitudes
(§8 probe).

**5 · B1/B2 inertness guard TRIPPED (recorded, not re-decided):** under the
new semantics, suppressing WREN-C040's eye stack (B2) lets its started-stack
bare drive's pending survive to a terminal runoff — `debris_zone_coverage`
now changes RUNG across treatments (negligible → some) and its boundary flips
(and its off-island GPS now favours B2 for this one program). Logged as an
amendment to OI-1 in the sensor cluster; **default remains B1** pending the
cluster re-review. C018/C103 boundary flips unchanged.

**6 · CLOSED — signed off 2026-08-18.** `frozen_paths.parquet` regenerated
(5547 → 5000 rows, same 116 programs — supersessions removed steps, runoffs
added them); boundary pin updated to **78**; the four test expectations and
the inertness-guard allowlist updated; OI-2 rebuilt (28 disagreements: 18
non-sensor, 10 sensor-deferred); review CSV regenerated. Suite fully green
(106 tests). Current §3b baselines: off-island agreement **91/119 (76%)**;
comparable on-island subset **n=40, median 61mm**; fabricated-motion programs
**16**; `boundary_exit_fabricated` **16** (mostly terminal runoffs). These
supersede the earlier task-3 tables above, which are retained as the
historical record.


---

# Corpus filter + loop-cap ruling (2026-08-18, reviewer-directed)

**The seven wrong-playground sessions are excluded from the testing set**
(DOVE-C016_S004, DOVE-C065_S004, DOVE-C068_S002, DOVE-C071_S002, DOVE-C076_S002,
DOVE-C081_S001, DOVE-C089_S002 — params carry another playground's run). This
overrides task-1 §13's "detect and abstain; do not drop the row". The rule is
card-driven (`corpus_filter.required_outcome_field: weight_cleared` in the
playground card) and enforced identically by tests/helpers.py, cli.py, and
viz/data.py. profile() itself is unchanged — a wrong-playground session passed
to it directly still abstains generically on the outcome channel, and the
`outcome_field_absent` pin now sits at **0** as a leak guard.

**Post-filter baselines (fixture regenerated: 109 programs, 4863 rows; suite
106 green):** testing set **112**; pins boundary **75** / reached 46 / armed
43 / stuck 7 / geo 19 / boost 70 / outcome-absent **0**; off-island agreement
**87/112 (78%)**; comparable on-island subset **n=36, median 40mm**;
disagreements **25** (10 sensor-deferred, 15 non-sensor).

**Loop-cap ruling:** capped `forever`/`repeat-until` programs are, by virtue
of the 20-iteration approximation, *expected* final-XY disagreement sites —
accepted, not a fix target. The four loop-cap rows in OI-2 carry that standing
attribution, leaving **7 genuinely unattributed** disagreements as the open
triage queue.

---

# Parser-fidelity ATTRIBUTION REPORT — OI-13 + OI-14 joint fix (awaiting sign-off)

**Change** (reviewer-authorised 2026-08-18): faithful capture of VEX's
Blockly-convention XML plus its non-Blockly extensions.
1. `parse_blocks.py` (**second vendored file opened**, recorded in its
   docstring): a `<value>` slot now prefers the connected `<block>` over the
   obscured `<shadow>` default — core Blockly convention; the old first-child
   rule silently dropped students' variable/operator/random blocks (5
   programs, 15 slots).
2. `simulate_path.py`: `math_number_string` and `math_whole_number` (VEX
   additions beyond stock Blockly) recognised as numeric literals;
   `_get_numeric` evaluates real reporter blocks in value slots (variables,
   operators) instead of only scanning shadow literals; `pg_operator_random`
   made **deterministic** (midpoint of the declared range) — replay identity
   forbids nondeterministic paths (BUG-14 lesson).
3. viz block-tree fields summary shows the student's reporter (`⟨variable
   rive⟩`, `⟨distance found object? frontdistance⟩`) instead of the stale
   shadow number — the canvas and the list now agree; this also closes the
   earlier while-condition rendering gap.

**Paths changed: 3 of 112** — exactly the programs whose overlay blocks are in
executed code: WREN-C053 (the rive/urn spiral now drives its variable amounts;
**boundary flips False→True** as the growing spiral exits), WREN-C069 (eight
variable-driven drives now real), WREN-C083 (random-distance drive, midpoint).
C059/C099's misparsed operators sit in orphan stacks — never executed, no path
change (C099's is `Infinity + Infinity × Infinity`, a detached experiment).

**Metrics:** off-island agreement unchanged **87/112**; comparable subset
unchanged n=36, median 40mm (all three changed programs still disagree —
C053/C083 remain cap/sensor-attributed; C069's disagreement was NOT explained
by this fix and stays unattributed). **Pins: boundary 75 → 76** (C053); all
others unchanged (46/43/7/70/0).

**Red pending sign-off:** `test_path_identity` (3 programs),
`test_full_path_pins` (boundary 76), timeline exited-count (76). New semantics
covered by 4 unit tests (block-over-shadow, string literal, variable-driven
accumulation, deterministic random).

---

# Screenshot calibration of playground geometry (2026-08-18)

Reviewer supplied two identical-viewport screenshots (`data/screenshot_50mm/`):
robot at spawn, and after driving 50mm forward. Analysis: frame-diff localises
the robot (centroid displacement 10.71px at −179.7° — spawn heading due west,
confirmed); scale **4.667 mm/px**; origin anchored at the known spawn
(1014, 49). Independent validation: the red boundary ring measures **89mm**
against the VEX API's documented ~88mm border.

Results (full detail in OPEN_ISSUES OI-15): the card's boundary polygon is
40–100mm outside the actual grass/ring interface — it traces closer to the
ring's outer edge; measured replacement vertices recorded. Adopting them moves
the boundary pin 76 → 82 and REDUCES nominal agreement 87 → 85, exposing a
semantic split between GPS (robot centre) and red-detection (down-eye
position) at the edge — decision queued, not applied. Plow marker measured
~98mm from the card anchor (inconclusive — marker vs anchor semantics; feeds
OI-4).

---

# Boundary semantics RULING + combined pending state (2026-08-18)

**Reviewer ruling: the island ends at the OUTER edge of the red ring** — a
robot on the ring is still on the island; the ring is the sensor-detectable
safety margin. Card updated: `field_boundary.polygon_mm` = measured outer
hexagon; the grass/ring interface preserved as
`red_detection_inner_polygon_mm` for the sensor cluster. The previous card
polygon (traced between the two edges) is retired with provenance in the card.

**Combined pending state** (parser/literal fix + outer boundary, filtered
corpus of 112): pins boundary **72** / reached 46 / armed 43 / stuck 7 /
geo 19 / boost 70 / outcome-absent 0; off-island agreement **88/112 (79%)**;
disagreements **24**; comparable **n=38, median 54mm**; fabricated-motion
programs 15; `boundary_exit_fabricated` 15. Paths differ from the frozen
fixture only for the 3 parser-fix programs (the polygon change moves no
paths). One combined sign-off closes both cycles: fixture regeneration + pin
table (72) + the three count expectations + OI-2/CSV refresh.

**Any-part-on-island rule (reviewer-confirmed 2026-08-18):** the robot stays
on the island while any part of its body touches it, so centre coordinates
(sim finals, path steps, GPS) are classified with a card-derived tolerance of
`robot.length_mm / 2` (66.5mm) beyond the outer polygon — implemented in
`profile._on_island` / `_find_boundary_exit`, no constant in Python. Tolerance
sweep validated stability (66.5 and 71mm identical; flat 88/112 agreement).

**FINAL combined pending state** (parser fix + outer boundary + any-part rule):
pins boundary **63** / reached 46 / armed 43 / stuck 7 / geo 19 / boost 70 /
outcome-absent 0; off-island agreement **88/112 (79%)**; disagreements **24**;
comparable **n=43, median 28mm**; fabricated 15 / boundary_exit_fabricated 15.
Nine further programs' exits were annulus-grazes within half a robot of the
edge — never real fall-offs; their §6a scope extends accordingly.

**Drive-until-red probe (2026-08-18, `data/screenshot_drivetillred/`):**
rotate-180 + drive-until-downeye-red. Robot body measured 114mm long in-frame
(card: 133mm; blob under-segmentation), local scale re-validated via ring width
(4.944 mm/px in this viewport). Stop position: centre **+35mm inside the
red-detection line**, nose 25mm onto the ring, 124mm inside the island edge —
consistent with the any-part-on-island rule and calibrating the down-eye's
mounting at **≈35mm ahead of centre** (`sensors.down_eye.forward_offset_mm`).
This is the reference measurement for validating the eventual OI-10/OI-5
sensor simulation.

---

# COMBINED SIGN-OFF CLOSED (2026-08-18)

The three stacked cycles — parser shadow/literal fix (OI-13/14), the measured
outer-ring island boundary (OI-15), and the any-part-on-island half-robot
tolerance — are signed off and closed. `frozen_paths.parquet` regenerated
(109 programs, 4863 rows; the 3 parser-fix paths are the only path changes);
pin table and count expectations updated; suite **110 green**; review CSV
regenerated (112 × 42).

**Standing baselines:** testing set 112 · pins: boundary **63** / reached 46 /
armed 43 / stuck 7 / geo 19 / boost 70 / outcome-absent 0 · off-island
agreement **88/112 (79%)** · disagreements **24** (9 sensor-deferred, 6
accepted, **9 unattributed**) · comparable pairs **n=43, median 28mm** ·
fabricated-motion 15 · boundary_exit_fabricated 15.

OPEN_ISSUES.md was rebuilt to hold only outstanding work: OI-2 (the 9-row
unattributed triage queue), OI-3/OI-4 (probes), OI-7 (arbitration), OI-9
(rung calibration), and the six-entry sensor cluster (OI-1, 5, 6, 8, 10, 11)
— now fully specified by the day's screenshot calibrations. Retired: OI-12,
13, 14, 15 (rulings and fixes recorded above).

---

# §6a-consistent fidelity metric (adopted 2026-08-19)

Prompted by reviewer inspection of WREN-C004 in the viz: several "on-island"
sim finals were fictional returns after a mid-program island exit — the real
robots fell off exactly where the sim exited (gps-to-exit-point: WREN-C089
68mm, C058 72mm, C099 143mm). Adopted: **`sim_final_off_island` =
`boundary_exceeded`** — an exiting simulated run ends at its exit point per
the run-to-failure semantics; the wall-less simulator's post-exit wandering is
already fiction under §6a and no longer pollutes the metric.

Impact: 10 disagreements resolved, 3 created (all honest sim-predicted-falloff
cases — two are stopped-by-user runs whose terminal runoffs over-ran a stopped
robot). **Baselines now: agreement 95/112 (85%), disagreements 17
(8 sensor-deferred, 5 accepted, 4 unattributed of which 2 on-trajectory),
comparable n=40 median 18mm.** No pins moved, no paths changed; suite 110
green. The `gps→trajectory` distance (real final to nearest simulated-path
point) proved decisive for triage and is recorded per-row in OI-2.

**Velocity miscalibration identified (2026-08-19, OI-16):** WREN-C086's
`drive+wait 5.4s` reaches the island edge in reality → real 50% velocity
≈520–535 mm/s vs the simulator's 100 mm/s (~5× slow). All six wait-motion
programs show matching under-travel (comparable errors 2130/446/227mm vs 18mm
median). C086's disagreement decomposes into: velocity miscalibration
(under-travel) + a student bug the reviewer identified (repeat body opens with
`drive` rather than `turn`, driving the edge-parked robot off). Awaiting the
velocity screenshot probe before changing constants (§6 cycle).

---

# Velocity calibration SIGNED OFF (2026-08-19, closes OI-16)

Constants measured via the reviewer's three-run screenshot protocol
(`data/screenshot_velocitytest2/`, two drive durations cancelling
ramp/stop-latency; cross-validated by the earlier batch and by WREN-C086's
edge arithmetic): **drive 9.88 mm/s per %** (494 mm/s at the 50% default,
~5× the old guess), **turn 4.16 °/s per %** (208 default, ~2.7×), linear
%-scaling confirmed at 100% for both. ~50–80ms stop latency observed,
second-order, not modelled.

Impact: exactly the 6 wait-motion programs changed. **WREN-C086 resolved**
(the origin case: drive+wait reaches the edge; the student's drive-before-turn
repeat-body bug carries it off). WREN-C091 entered as a stopped-by-user
disagreement (accepted category). Pins updated at sign-off: **boundary 65,
reached 48, armed 45, stuck 8** (WREN-C048 and WREN-C086 genuinely engage the
plow at real speeds; C048 in the stuck zone), boost 70 / absent 0 hold.
Fixture regenerated (109 programs, 4863 rows); suite **110 green**; CSV
regenerated. Baselines: agreement **95/112 (85%)**, disagreements **17**
(8 sensor-deferred, 6 accepted, **3 unattributed**: WREN-C004 edge-tip,
WREN-C032 runoff over-prediction, WREN-C096 near-trajectory), comparable
**n=39, median 16mm**.

**Tolerance refinement + attribution close-out (2026-08-19):** the
any-part-on-island tolerance is now the half-diagonal (71.2mm,
√((L/2)²+(W/2)²)) — the correct maximum-reach bound; corpus-verified to change
zero classifications. WREN-C032 re-diagnosed (no bare drives — the earlier
"runoff" note was wrong): its flag came from a single 87mm edge excursion 58
steps into a 70m contact-free dead-reckoned sweep; attributed (hypothesis) to
**contact-free simulation drift**, with C096 alongside and C004 as the
mirror-image edge-marginal tip. The OI-2 queue now has zero hard-unattributed
rows. The reviewer's outcome-arbitration rule for failure conditions is
designed and recorded as OI-17 (zero current candidates; awaits richer run
data).

**OI-3 ratified (2026-08-19):** `wait_until` has no self-motion — it gates
EXECUTION (code after it never runs if the condition is never met) while
motors continue their last command; unsatisfiable + driving ⇒ run-to-failure,
unsatisfiable + stationary ⇒ hang. Naturally sensor-paired, so implementation
belongs to the sensor-cluster build; WREN-C027 (the only executing case,
sensor-deferred) keeps legacy behaviour until then per reviewer decision.
Zero-incidence conventions (trailing-turn 90°, loop under-credit) are now
tripwire-guarded in the regression suite. With this, OI-3 requires no
physical probes — the queue's only remaining probe is OI-4 (plow geometry),
addressable by the screenshot method.

---

# OI-4 CLOSED — plow-engagement geometry measured (2026-08-19)

Reviewer ran the seven-probe screenshot series (P1–P7: east-approach probes at
y = 1000/1100/1200/1249/1285/1350 plus two facing-north variants). Results:
attach NO/NO/YES/YES/YES/YES; P2b (y=1100, rotated to face the plow) YES;
P7 (y=1050 facing, magnet ≈52mm from anchor) NO.

**Findings:**
1. **Above/at anchor level (y ≥ 1169): attachment succeeds across the whole
   band** — including the formerly-undeclared 1230–1250 gap and the former
   `stuck_zone` (1250–1320), whose failure claim did not replicate. Reviewer
   ruling: the original WREN-C007-variant observation was likely physics
   variance; simulations are estimations and attachment is estimated within a
   range — **the stuck zone is removed from the model** (provenance preserved
   in the card).
2. **Below the anchor, the 190mm circle is not sufficient**: attachment
   requires near-contact with the magnet facing the anchor — bracketed
   between ~3mm (attach) and ~52mm (fail) magnet-to-anchor distance, with the
   magnet front-mounted (the same mounting logic as the calibrated down-eye).
3. Cards rewritten: zones are now `attaches` (y ≥ 1169) and `below_anchor`
   (flag `below_anchor_attach_unlikely`), tiling the whole band — the
   `geometry_undescribed` tripwire can no longer fire on this playground.

**Evidence impact:** `stuck_zone` (8) and `geometry_undescribed` (19) flags
retire; **`below_anchor_attach_unlikely` fires on 6 programs** (WREN-C012,
C031, C039, C088, C093, C096 — armed engagements whose qualifying trajectory
never reached anchor level; four of them sit in the uncertain 25–47mm
magnet-distance band, two beyond). The 13 other former geo-flagged programs
are cleared by the precedence rule — they later qualified at/above anchor
level where attachment is expected. The stuck pin retires with its flag; the
new flag is deliberately unpinned per the standing precedent.
`armed_within_radius` (45) is unchanged — centre-based proximity evidence
stands; the flag now carries the attachment estimate. Suite 111 green;
config_version rotated with the cards.

---

# Continuous sampling + uniform 190mm attraction (2026-08-19)

**Trigger:** Reviewer ran WREN-C031 on the live playground — the plow attached
as the robot passed by. Our model had flagged it `below_anchor_attach_unlikely`
("clearly no"). The trace exonerated the simulator: C031's sim final position
matches GPS to sub-mm. The defect was **waypoint sampling** — the zone logic
saw only segment endpoints (closest recorded point 176mm at y=1112), while the
continuous pass stays inside the 190mm radius from y≈1042 to y≈1237, crossing
anchor level at ~171mm. The robot occupies every point of a drive.

**Reviewer ruling:** adopt continuous segment-level sampling AND the prior
goal_strategy_detector work's empirically-verified
`magnet_attraction_radius_mm: 190` as the uniform attachment estimate. The
below-anchor near-contact bracket (from the static P1/P2/P7 probes; fail at
~52mm magnet-to-anchor) is judged wrong for pass-by dynamics — static
placements did not predict attachment in motion. Zone bands are removed
entirely; `below_anchor_attach_unlikely` and the `geometry_undescribed`
tripwire retire (the generic zone machinery remains in src, card-opt-in).

**Change:** `indicators.py` — `min_distance_to_object` and
`state_active_within_radius` now evaluate the continuous polyline (per-segment
closest approach; origin seeding falls out naturally as the polyline start).
Zone sampling, where a card opts in, samples radius entry/closest/exit points
per qualifying segment. Vendored simulator untouched; paths byte-identical;
frozen_paths.parquet unchanged.

**Evidence deltas (full-path, 112-session corpus):**
- `reached` 48 → 67 (+19), `armed_within_radius` 45 → 59 (+14) — continuous
  minima are never larger than waypoint samples, so credit only increases.
  Largest corrections: WREN-C045 851→23mm, WREN-C035 599→68mm, WREN-C017
  492→35mm, WREN-C054 496→89mm.
- `below_anchor_attach_unlikely` 6 → retired. Of the six, C031 (ground truth:
  attaches) and C093 cross anchor level continuously; C012/C088/C096/C039
  pass at 20/20/48/90mm centre distance — all within the uniform estimate.
- boundary 65, boost 70, outcome_field_absent 0 unchanged (sampling does not
  move the robot).
- Inertness guard: WREN-C042 B1-vs-B2 plow values diverge under continuous
  sampling (16.2 vs 186.4mm, same rung) — a pre-existing conditional-hat path
  difference that waypoint sampling masked (same class as the C040 rounding
  incident). Allowlisted with log entry; queued to the sensor cluster.

**Provenance note:** the discarded ~52mm fail bracket came from probe P7
(static, below anchor, facing). Recorded, not erased: static near-field
behaviour and pass-by dynamics disagree; the model follows the dynamic case,
per the standing "simulations are estimations" ruling.

---

# ATTRIBUTION REPORT — Sensing build Phase 1: down-eye red-line model +
# wait_until gate (2026-08-19) — AWAITING SIGN-OFF

**Change (one §6 change, vendored simulate_path.py + cards):**
1. `pg_sensing_optical_color` rebuilt: reads the corpus field name COLORS
   (legacy COLOR fallback — OI-10's one-line defect plus its two latent
   companions), resolves WHICH eye from OPTICAL, evaluates at the EYE POINT
   (centre + calibrated 35mm offset from the new shared robot card), and
   matches card color_zones honoring per-eye applicability and ring bands.
   The red ring is now a down-eye band zone between the measured detection
   line and the island edge; interior grass is a green down-eye zone bounded
   by the detection line (stale polygon fixed).
2. Down-eye near_object is floor-tuned: only a 3D body (body_radius_mm;
   objects or castle pieces) under the eye point registers. Front eye
   unchanged this phase (Phase 2).
3. `wait_until` = the ratified OI-3 gate: NO self-motion. Pending motion
   marches (virtually, 10mm/2° granularity) until the condition turns true,
   then commits ONE real velocity-held move — genuine drive-till-red. A
   condition that never turns true gates the stack (new flag
   wait_until_unmet; armed drives run off first, as at program end). The
   legacy 50mm fabricated probes are RETIRED.
4. Plumbing: shared robot card configs/robot/vr_robot.yaml (hardware specs;
   reviewer ruling), loaded into config_version and passed to
   PlaygroundContext; SimulationResult.color_detections (step, eye, color)
   additive observable; identity test gains one documented adaptation line.

**Validation:** synthetic replica of the reviewer's physical drive-till-red
probe (turn 180, bare drive, wait until down-eye red, stop): sim stops the
robot centre at x=1604 vs physically measured 1599 (within the 10mm march
granularity), eye point on the detection line, one detection event, zero
fabricated steps. The model reproduces the calibration measurement.

**Path deltas (identity fixture, 119 programs): 8 changed.**
- 7 are wrong-playground DOVE sessions (fixture-only; excluded from all
  evidence): their color conditions now genuinely evaluate (e.g. green under
  the down eye at spawn), so previously-inert code paths run. Two show
  wait_until runoffs off-field — semantically correct for unmet conditions.
- 1 corpus program: WREN-C027 — the deferred wait_until case. Its
  `wait until front-eye detects NONE` could never turn true under the broken
  evaluator: 621 path steps, ~500 of them fabricated 50mm probes, final at
  (-21.0m, +20.9m). Now 'none' evaluates true (no color at the eye point),
  the gate passes instantly, and the path is the student's actual geometry:
  121 steps, fabricated_motion FALSE, off-island agreement TRUE (GPS is also
  off-island — the code genuinely runs off the field under §6a).

**Corpus metrics: unchanged.** All pins hold (boundary 65, reached 67, armed
59, boost 70, outcome_field_absent 0); fidelity 95/112 off-island agreement,
16.4mm median error (baseline 95 / 16). No corpus program fires
wait_until_unmet; no corpus program records a ring detection — corpus
eye-red checks live inside capped loops/branches whose discrete evaluation
points never land on the 89mm ring band. The model's corpus value arrives
with Phase 2 (evaluable eye hats) and the test-case harness; what this phase
buys today is C027's fidelity, the retirement of fabricated wait_until
motion, and a validated red-line sensor for student code that gates on it.

**Semantic choice to queue (not decided silently):** eye color 'NONE' now
means "no detectable color at the eye point" — immediately true away from
color zones/objects. The VEX docs sentence ("close enough to an object to
detect a color (red, green, blue, none)") admits a stricter reading: 'none'
= near a colorless OBJECT. The loose reading is what un-bombed C027; the
strict reading would keep its gate held. Flagged for reviewer review with
the Phase-2 front-eye model, where object proximity becomes modelled.

**Suite: 110/112 green.** The 2 failures are test_path_identity — the §6
expected signal, awaiting sign-off before frozen_paths.parquet regeneration.

**SIGNED OFF 2026-08-19** with reviewer clarification (VEX API): the down eye
is tuned to not detect the floor as an object; other items register. Reviewer
ruling: detectability requires being a DEFINED OBJECT in the space — the red
boundary line IS one; the island ground and ocean are not (grass remains
color-detectable). Amendment folded in before fixture regeneration:
`registers_as_object: true` on the red zone (card-driven); down-eye
near_object now fires over the ring as well as over 3D bodies. Amendment
changed zero additional paths. frozen_paths.parquet regenerated over the
112-session testing set (109 programs with paths, 4363 rows — the corpus
filter also governs the identity fixture; wrong-playground DOVE sessions are
excluded from it, resolving their would-be fixture rows). profiles.csv
regenerated. Suite 121 green including the new tests/test_sensing.py (9
tests: drive-till-red calibration pin, gate semantics, eye-point geometry,
per-eye zones, object-registration, piece detection).

---

# ATTRIBUTION REPORT — Sensing build Phase 2: front-eye cone, evaluable eye
# hats, contact staleness (2026-08-19) — AWAITING SIGN-OFF

**Change (one §6 change, vendored simulate_path.py + cards):**
1. **Front-eye cone model**: assumed cone (robot card: fov 30°, range
   1000mm, front-mounted) against declared 3D bodies (objects + castle
   pieces with body_radius_mm). Replaces the omnidirectional-1136mm
   behaviour for near_object; eye color additionally reports the nearest
   cone body's declared color. Every cone consumer flags
   `sensor_model_assumed` (conditional tier).
2. **Eye hats fire at modeled detection, never eagerly**: hats register
   before any stack runs (they are parallel programs), detection is sampled
   ALONG each traversed segment (50mm latch sampling — hats are async
   interrupts; execution joins at the next block boundary, the same
   sequential approximation as broadcast), and a still-armed hat can preempt
   an indefinite drive ("drive until the eye sees something, then the hat
   stack" — WREN-C040's real shape). trigger_unfaithful RETIRES for modeled
   eyes (corpus incidence now 0); unmodeled/non-'detects' hats keep legacy
   eager + flag.
3. **Contact staleness (hybrid ruling)**: first body contact with a movable
   target — evaluated along the whole traversed segment — is recorded
   (SimulationResult.object_contacts, additive); sensor readings against
   stale targets flag `sensor_reading_stale`. The main sim never moves
   objects.

**Cone-parameter derivation (assumed, reviewer to ratify):** fov 30° /
range 1000mm is anchored to TWO ground truths: WREN-C042 (hat fires early —
first westward drive sweeps pieces at ~825mm; magnet still boosts before the
16mm plow pass, sentinel PRESERVED: armed at 16.2mm) and WREN-C070, which
FALSIFIED the provisional piece colors: its eye-detects-RED check never
fired in reality (GPS matches the never-fired path exactly, 0mm) despite
passing ~90mm from a castle tower — so castle pieces are NOT 'red' to the
eye; piece colors are back to null pending reviewer readings, and C070's
path reverts to its exact-GPS-match baseline. Sensitivity sweep (fov
30/90/130/180 × range 600-1000) recorded in the session log; corpus outcomes
are insensitive above 30° once segment-latch sampling exists.

**Path deltas (identity fixture): 4 programs — all eye-hat programs.**
- WREN-C012: hat fires at modeled detection (magnet step 0→23); final shifts
  12mm; stays in the sensor-deferred disagreement queue.
- WREN-C018: hat latches mid-westward-sweep through the debris corridor and
  its stack now runs from there (was: eager at start). Final error vs GPS
  improves 2517→2047mm; still exits mid-path, so boundary and agreement
  accounting are unchanged.
- WREN-C040: runoff preemption — drives west until first detection (~80mm),
  then the hat stack's 1350mm drive + turn. Error 2424→2334mm; stays in the
  sensor-deferred queue.
- WREN-C042: path unchanged; only the magnet step moves 0→1 (still before
  the pass). B1/B2 guard allowlist re-derived: boundary-diff set UNCHANGED
  {C018, C040, C103}; value-diff adds C012 (three indicators, one RUNG-level:
  debris systematic-vs-meaningful — logged in OI-1) and C018 (sub-precision).
- WREN-C027 and WREN-C070 changed under intermediate states and REVERTED once
  piece colors were nulled — final delta set excludes them.

**Corpus metrics: unchanged.** Pins hold (boundary 65, reached 67, armed 59,
boost 70, absent 0); fidelity 95/112, 16.4mm median — identical to baseline.
Flag incidence: sensor_model_assumed 9 programs, trigger_unsimulated 2
(bumpers, Phase 4), trigger_unfaithful 0 (retired), sensor_reading_stale 0
(machinery live; no corpus sensor read follows a contact yet).

**Suite: 123 green + the 2 expected identity failures awaiting sign-off.**
New unit tests: deferred hat firing, B2 suppression, segment-based contact
staleness, cone range limit (tests/test_sensing.py, 13 total).

**Phase 2 SIGNED OFF 2026-08-19** (reviewer). frozen_paths.parquet
regenerated (testing set), profiles.csv regenerated. Reviewer directed the
build to proceed to Phase 4 (bumper); Phase 3 (distance sensor) deferred.

---

# ATTRIBUTION REPORT — Sensing build Phase 4: bumper model (2026-08-19) —
# AWAITING SIGN-OFF

**Change (one §6 change; Phase 3 distance deferred per reviewer):**
1. **Bumper switch model**: pressed when the bumper's mount point (front
   corners, geometry in the shared robot card) reaches the surface of a
   declared 3D body. Side selection is honored — the left/right tracks are
   50.8mm apart and it matters (the unit test's castle pass hits the right
   bumper and misses the left by 17mm). Reporters
   (`pg_sensing_bumper*`) evaluate; `pg_events_when_bumper` (OPTIONS
   pressed) defers and fires at first modeled contact via the generalized
   sensor-hat machinery (Phase-2 latch sampling, runoff preemption
   included). Marked `assumed: true` in the card — contact geometry is
   solid but the pieces' body radii are provisional — so bumper evidence
   carries sensor_model_assumed (conditional tier).
2. `trigger_unsimulated` RETIRES for modeled bumpers: corpus incidence now
   0. Combined with Phase 2, NO corpus program carries any trigger_* flag —
   every sensor hat is evaluable.

**Path deltas: 1 program.** WREN-C103's bumper hat fires at modeled contact
instead of eagerly: its stack interleaves mid-run, diverting the trajectory
before the old plow approach. B1 still exits the boundary — matching the
off-island GPS (1508, 2641) — while B2 (suppressed) does not exit; B1
remains the reality-matching default. WREN-C055 (the other bumper program):
path unchanged — its hat never reaches contact, so its stack faithfully
never runs (previously it ran eagerly but contributed no motion).

**Pin changes (§6 stop-and-report):** reached 67→66, armed_within_radius
59→58 — C103's plow evidence moves outside the §6a-scored span under the
new trajectory. Boundary 65, boost 70, absent 0 unchanged. Fidelity
unchanged: 95/112, 16.4mm median. Guard allowlist: C103's three RUNG-level
B1/B2 divergences added with log entry (boundary-diff set unchanged).

**Flag census:** sensor_model_assumed 11 programs (9 eye + 2 bumper),
sensor_reading_stale 2, trigger_unfaithful 0, trigger_unsimulated 0.

**Suite: 127 green + 1 expected identity failure (C103 per-step), awaiting
sign-off.** New unit tests: bumper side selection at contact, hat firing on
modeled contact + B2 suppression, castle drive-through latch (16 sensing
tests total).

**Phase 4 SIGNED OFF 2026-08-19** (reviewer). frozen_paths.parquet and
profiles.csv regenerated. With Phases 1/2/4 in: zero trigger_* flags remain
in the corpus — every sensor hat is modeled; conditional evidence now flows
through sensor_model_assumed / sensor_reading_stale. Phase 3 (distance)
remains deferred; Phase 5 (test-case harness) next, pending reviewer's
scenario designs.

**Hardware confirmations (reviewer, 2026-08-19):** only the red line has a
detectable color — castle piece colors are NOT readable by the eyes,
ratifying the C070 falsification as ground truth (piece color: null is now
confirmed, not provisional). The front DISTANCE sensor IS readable from the
pieces — recorded for Phase 3 (deferred), and grounds for prioritizing it
after Phase 5.

---

# Sensing build Phase 5 — test-case playground harness DELIVERED (2026-08-19)

Built per the reviewer's scenario design rulings (recorded verbatim in the
session): five scenario cards (piece ahead / off-axis / behind, the
reviewer-added two-piece RESET scenario, and the separate edge-handling
boundary test), kinematic push model under a testcase-only switch (main sim
byte-identical with it off — identity fixture unchanged, suite green),
loop caps raised per-scenario (loop_unroll: 60), behavioral-divergence
"detects" (code runs with AND without pieces; only a responding trajectory
passes), navigate-to and push-off as SEPARATE checks, per-check
loop/conditional progress rules (conditional + annotation, never silent
credit), and the roll-up into clear_debris_zone facet mappings
(object_detection, object_pursuit, push_execution, repeat_acquisition,
edge_failure_handling) — the unobservable-goal evidence layer.
Eligibility: sensor-sensitivity only (reviewer ruling) — programs whose only
sensing is down-eye color (red line) are ineligible; the sim already
evidences them. 19 corpus programs qualify; testcases_report.csv holds the
per-check and roll-up rows (python -m vex_goal_profiles.testcases).
tests/test_testcases.py pins the core distinction: a responsive bumper-gated
pusher passes detects; a blind sweeper clears the piece while failing
detects; down-eye-only code is ineligible; the main pipeline's context
carries no testcase physics.

**Queued composition question (not decided):** navigates_to can pass by
blind traversal (C070 drives through the ahead-piece: min distance 0 with
zero divergence), so the object_pursuit facet can read "pass" without
detection. Options: gate pursuit on detects, or add a combined
responsive_pursuit facet. Reviewer to rule.

**Phase-5 amendment (reviewer ruling 2026-08-19): detection-gated evidence.**
Card checks gained `requires: detects` (navigates_to, pushes_off,
resets_to_next): reaching or clearing a piece WITHOUT a behavioral detection
response is accidental and contributes no evidence — the accident stays
visible in the check detail, never in the status. The gate also matters for
sequential-goal strategies (code that pursues another goal first): see the
queued late-materialization design question below.

**Option A DELIVERED (reviewer-approved 2026-08-19): late materialization,
robot-relative, per-construct.** The baseline (no-piece) run now records a
sensor-consultation trace (SimulationResult.sensor_first_eval, additive);
scenarios with RELATIVE piece placements run one variant per qualifying
sensing construct — pieces materialize at the step that construct was first
consulted (hats: step 0, armed from start), placed relative to the robot's
pose at that moment (ahead_mm + bearing_deg, CCW from heading). The four
acquisition scenarios are now robot-relative; edge_handling stays absolute
static (its purpose is positional). All machinery rides the testcase-only
switch — main sim byte-identical, identity fixture untouched, suite 136.
Sequential-goal isolation is pinned by test: a program that pursues another
goal first earns full clearing credit when its phase-2 sensing responds,
with phase 1 uncontaminated. Corpus battery (440 rows, construct column):
evidence stable and sharpened — C040 (pass) and C012 (conditional) remain
the only credited clearers; C018's hat now shows detection + pursuit without
push credit; blind-traversal credit is fully eliminated.

---

# ATTRIBUTION REPORT — Sensing build Phase 3: distance sensor (2026-08-19) —
# AWAITING SIGN-OFF

**Change (one §6 change):** the docs-verified banded cone — 10° under
1000mm, 5° to 2000mm, 2° to the 3000mm cap, nearest object SURFACE
(centre distance minus body radius), UNIT honored (mm/inches), no-object
reading 3000mm (assumed, card-declared). `pg_sensing_distance_found` and
the numeric distance reporters evaluate; previously they silently returned
0 via the unknown-reporter path (the OI-11 class). Card-marked assumed
(spec verified; piece body radii provisional) → sensor_model_assumed.
Reviewer's hardware confirmation on record: front distance IS readable
from the castle pieces.

**Path deltas: 2 programs.**
- **WREN-C082 (OI-8 resolved): the headline.** Its entire program sits in
  `while (distance found object?)` — zero simulated steps for the project's
  whole history vs GPS 58 METERS off-field. The guard now evaluates (castle
  in the cone at spawn): 15 steps, loop-capped, exits the field exactly as
  the real robot did. Off-island agreement 95 → 96 (86%); boundary pin
  65 → 66. The last unevaluable-sensing corpus case is gone.
- WREN-C064: its distance checks now branch (54→35 steps); final error vs
  GPS improves 2981 → 2502mm.

**Battery impact (the bigger story):** distance-consulting programs now
exercise properly under Option A. THREE new credited clearers surface —
WREN-C035, WREN-C046 (detect + pursue + push + edge-handling pass, reset
conditional) and WREN-C064 (detect + pursue + push) — all distance-sensor
strategies whose responsivity was invisible until this phase. With C012
(bumper/eye) and C040 (eye), the corpus now has FIVE programs with credited
clearing evidence, each attributable to a specific modeled sensor.

**Metrics:** median error unchanged 16.4mm; flags: sensor_model_assumed 13
programs, sensor_reading_stale 3; unknown_reporter incidence for distance
blocks: 0. Suite 136 green + 3 expected identity failures (C082 enters the
fixture with paths for the first time). New unit tests: banded-cone
narrowing, range-cap flip on the clean plow lane, nearest-surface + units,
no-object reading (19 sensing tests).

**Phase-3 amendments (same sign-off, 2026-08-19):**
1. **OI-18 RESOLVED by reviewer probe:** the ground is CODED AS NO COLOR —
   down-eye 'detect none' is TRUE on open grass (paired with `not`, the
   idiom for reacting to any colored object). The green interior zone was
   therefore WRONG and is removed; only the red line has a detectable color
   (castle/plow colorless despite UI appearance — reviewer-confirmed).
   WREN-C027's front-eye NONE reading is ground-truth-ratified; had that
   student wanted castle detection, front `distance found` was the right
   block (reviewer note — pedagogically relevant insight for the viz).
   Zero corpus paths changed (no down-eye green/none checks in the corpus).
2. **Body radii RATIFIED by measurement:** equivalent-area circle radii
   from the calibrated screenshot blobs, +7% bias correction
   cross-validated on the rocks (blob 94/80/80 vs visual 100/85/85).
   The 45-55mm eyeballs were ~25% under: corner blocks 72mm, all towers
   70mm (±10mm). `assumed` DROPPED for bumpers and distance (contact
   geometry and spec now fully measured); the front eye keeps it (fov/range
   still observation-anchored assumptions). Effect: WREN-C035's distance
   branches now track reality — error 2052 -> 584mm, and it exits like its
   GPS: **off-island agreement 96 -> 97 (87%), disagreements 15**; boundary
   pin 66 -> 67; flag incidence sensor_model_assumed shrinks to the
   eye-only programs.

Combined Phase-3 sign-off scope: distance model + grass-colorless + radius
ratification. Path deltas vs the Phase-4 fixture: C082 (0->15), C064
(54->35), C035 (25->28), C040 (magnet-point 20mm shift). Suite 136 green +
3 expected identity failures.

**Phase 3 (+ amendments) SIGNED OFF 2026-08-19** (reviewer). Fixture and
profiles regenerated; OI-8, OI-11, OI-18 retired. THE SENSING BUILD IS
COMPLETE: all five phases plus Option A delivered in one day. Day's arc for
the fidelity metric: 95/112 -> 97/112 off-island agreement (87%),
disagreements 17 -> 15, median 16.4mm; zero trigger_* flags; five credited
clearers in the battery, each attributable to a specific modeled sensor.

**Edge-slip ruling (reviewer, 2026-08-19):** WREN-C004 and WREN-C096 are
explainable/acceptable deviations — the playground's fall-off physics makes
the robot slip and shift as it goes over the edge. Fidelity thresholds are
now RECORDED IN THE PLAYGROUND CARD (settling D6's values/placement):
on-island XY 71.2mm (robot half-diagonal); off-island binary agreement, with
a 400mm gps→trajectory edge-slip tolerance when off-island status disagrees.
Applied symmetrically the rule also covers WREN-C032 (the sim-side mirror) —
flagged in OI-2 for reviewer confirmation. Result: ZERO unattributed
disagreements across the full 112-session sample.

**Outcome-override ruling (reviewer, 2026-08-19, WREN-C032):** C032's exit is
accumulated dead-reckoning drift over an 81m contact-heavy rosette — one
3000mm spoke endpoint 16mm past the any-part tolerance, while the real run
(not stopped) ended on-island 32mm from the simulated trajectory. Ruling:
defer to the outcome — ignore the boundary exit for scoring, deliver the
FULL-program goal mapping, and flag indicators whose evidence depends on the
post-exit path (`evidence_post_sim_exit`, conditional tier). Implemented
card-driven (`fidelity_thresholds.sim_exit_outcome_override` with
`stopped_field` + `trajectory_corroboration_mm: 400`); the corroboration
guard keeps genuinely divergent trajectories truncated (WREN-C060 at 1374mm
stays §6a). Effect: C032 agreement TRUE (full final 1436mm from GPS,
drift-attributed, on-island comparable), debris coverage flagged conditional
(0.9/systematic — the one indicator built on the post-exit spokes), plow
evidence (reached/armed at 140.5mm, pre-exit) stands confident.
boundary_exceeded remains True as a sim fact; new GoalProfile field
boundary_exit_overridden records the deferral. Fidelity close-of-day:
98/112 agreement (87.5%), 40 comparable, zero unattributed. Suite 139.

## Front-eye calibration — OI-5 probe (2026-08-21, reviewer-run)

**The last assumed sensor model is retired.** Probe A (back-away flip at
rock_ne_small: park eye 42mm from the surface, drive reverse until
`not near object`): detection dropped at eye-to-surface **123.5mm** — 8×
shorter than the 1000mm docs-analogy assumption. The front eye's "near
object" is a SHORT-RANGE PROXIMITY DETECTOR, not a long cone. Probe B
(in-place sweeps through the rock at eye-to-surface 80mm and 40mm; exits
read on both drive-heading and location-angle instruments, replicated):
windows 41°/44°, symmetric about the rock bearing. Fitted against the
simulator's exact cone predicate (any-part, linearized spread, along-axis
surface range, eye at +66.5mm with orbit-of-eye modeled): **fov 13.0°,
range 124mm**, rms 2.6° ≈ integer-print quantization; turn-latency fit 0.0°.

Fit notes: (a) every model class independently places rock_ne_small ~10mm
west of its card x — a 1/distance-scaling bias signature, consistent with
the ±10–20mm blob-centroid uncertainty; the rock card is NOT changed (would
be a second §6 change; queue if a residual ever hinges on it). (b) fov and
effective target radius are degenerate on 4 exits — (13°, physical radii) ≈
(30°, radii×0.7) behave identically at corpus scales; the card takes the
parsimonious member. (c) The C042 "fires early" anchor is REINTERPRETED:
the hat fires on close pass (~190mm center distance at courtyard_tower_1,
37mm off its westward lane), not at 825mm.

**Corpus attribution (card fov 30→13, range 1000→124; §6 change):**
- `sensor_model_assumed` retired: 9 → **0** (flag was gated on the card's
  `assumed:` key, which is dropped). Conditional evidence now flows through
  `sensor_reading_stale` only: 3 → 7 programs (C012, C017, C027, C042 join —
  their front-eye reads now reference contacted movables at close range).
- **WREN-C040 FIXED** (agreement False→True): its bare-drive runoff was
  previously halted by the eager 1000mm cone after 70mm; the measured cone
  stays silent, the robot runs off the west edge — matching its GPS. Second
  ground-truth datapoint where the measured model is the reality-matching
  side. Coverage rung negligible→some (§6a slice now crosses the zone).
- **WREN-C018 newly divergent** (agreement True→False): its front-eye hat no
  longer fires (nothing within the measured cone on its route), so the
  7-step hat stack that used to carry the sim off the west edge never runs;
  sim ends on-island east, GPS off-island. Sensor-attributable; mechanism
  open — its 2667mm westward drive ends 50mm short of the west edge, so
  candidates are dead-reckoning past that margin or a real eye reaction at
  the ring/edge that the card doesn't model. → OI-2 sensor column.
- WREN-C012: plow-approach values 28.5→20.0, coverage rung
  systematic→some — hat timing shifts under the measured cone.
- WREN-C042 SENTINEL HOLDS: plow values (reached/armed) byte-identical; the
  hat now fires on the close pass, still early enough to attach the plow.
- Net fidelity: **98/112 (87.5%) unchanged**, median 16.4mm unchanged,
  disagreement count 14 unchanged (C040 out, C018 in). Pins unchanged
  (boundary 67 net, reached 66, armed 58, boost 70, absent 0).
- Battery: **0 of 440 rows changed** — Option-A materialization places
  pieces on the approach path, so detection still fires during the drive.
- Tests: 137 green; only the two path-identity tripwires fail (expected,
  §6) pending sign-off + fixture regeneration. One sensing unit test
  updated (asserted the retired flag).

**SIGNED OFF (reviewer, 2026-08-21)** — after reconciling with the VEX
distance-sensor documentation: that spec describes the front DISTANCE sensor
(already modeled with those exact bands, Phase 3, unchanged); the eye is a
different device whose measured 13° aperture is statistically compatible
(±~4°) with the distance sensor's documented 10° near band — plausibly the
same optics family, distinguished by the eye's short trigger range. Card
comment records the compatibility; the measured value stands. Fixture
regenerated (110 programs, 4356 rows — the −7 delta is exactly C018's
retired hat stack); profiles.csv + testcases_report.csv promoted; OI-5
retired.

## OI-7 arbitration — determinism probe + creation-order recovery (2026-08-21)

**Probe result (reviewer-run):** with two `when started` stacks commanding
opposing drivetrain motion, the **most recently CREATED stack takes
precedence — regardless of selection state or subsequent edits**. The
arbitration rule is deterministic; the latent is stack creation order.

**Observability:** the workspace XML carries NO timestamps (checked — top
blocks have only random `id` + canvas `x`/`y`). Reviewer's export test makes
document-order-as-creation-order unlikely. Recovery path: **block-id
first-appearance across per-run workspace snapshots** (ids are stable across
edits; a pasted/re-created stack gets a fresh id, which is CORRECT under the
rule since re-creation is creation). ONLINE has snapshots natively (Stage 0);
offline needs the fuller sample planned for the validation stage — the
current dataset is a final-state timeslice only.

**Corpus census:** exactly 1/112 programs contested — WREN-C008 (2 started
stacks both driving + 2 driving broadcast receivers). Concurrency is a ~1%
phenomenon.

**WREN-C008 dual-ordering experiment:** simulated under both document
orderings of its started stacks — **byte-identical results** (8 steps, final
(−2627,−5091), same flags). The sequential approximation is
ordering-insensitive here; its GPS disagreement (sim far off-island, reality
on-island) is attributable to the approximation summing both stacks' motion,
where the real lockout rule would execute only the winner's drivetrain
commands. Fallback when creation order is unrecoverable: dual-ordering
consensus costs nothing and, at least for C008, changes nothing — the
current flags (`concurrent_stacks_unverified`,
`broadcast_concurrency_approximated`) remain the honest treatment until the
lockout rule is modeled with real creation-order input.

**Open sub-questions before the lockout rule can be coded (queued, not
guessed):** (a) suppression vs preemption — does the losing stack's
drivetrain command execute at all (e.g., briefly, before the winner's next
command) or is it locked out entirely? (b) do broadcast-receiver stacks
enter the same precedence pool by their own creation times? (c) censoring —
stacks created before a sample window opens have unknown relative order;
ingest must mark them `creation_order_censored`.

**OI-7 suppression sub-answer (reviewer probe detail, 2026-08-21):** the
losing stack's drive was COMPLETELY ABSENT — full lockout, not preemption.
The precedence winner owns the drivetrain outright; losers' drivetrain
commands never execute, even briefly. Lockout-model spec firms up to:
winner's drivetrain commands execute; losing stacks' drivetrain commands are
no-ops. Remaining detail tier (queued): (a) whether a loser's no-op drive
consumes its duration (blocks its stack) or is skipped instantly — matters
only when a losing stack has post-drive non-drivetrain effects (magnet,
broadcasts); (b) whether broadcast receivers join the precedence pool by
their own creation times.

## WREN-C032 plow-attachment timing — reviewer ground truth (2026-08-21)

**Observation (reviewer, live run): C032 attaches the plow on its SECOND
drive forward — sim step 4.** The sim's continuous minimum on that pass is
221.6mm from the anchor — inside close/engage zones (250/300), magnet armed
since step 0, but 32mm OUTSIDE the 190mm attachment radius. The sim's only
sub-190 crossing is step 32 (140.5mm) — attachment is estimated ~28 steps
late relative to reality; the intervening rosette legs run plow-attached in
reality but plow-free in the estimate. RUNGS UNAFFECTED (already
reached / armed_within_radius / boost); this is a timing-evidence question.

Two candidate explanations, discriminable by probe (queued as OI-21):
- **A · radius underestimate** (real attraction ≥ ~222mm): no pass-by
  NON-attachment ground truth exists above 190 to bound the radius from
  above (C031's 171mm attach only bounds below).
- **B · step-4 drift** (sim's pass geometry ~32mm wide of reality): the
  miss is 2% of the ~1,500mm driven by step 4 — exactly C032's documented
  drift scale (it is THE drift program: 1436mm final error, outcome-override).

**Corpus stakes census (full 112):** 66 programs pass ≤190 (attach estimated
today); the contested 190–260 band contains ONLY DOVE-C022 (231mm at step 18)
— whose magnet NEVER fires (attachment impossible at any radius) and whose
pass sits 17.4m into its path (drift-swamped). A radius change would
therefore alter NOTHING corpus-wide except C032's attachment timing, plus
the reached/near rung edge if moved past 231 (OI-9 ladder territory).

**OI-21 expanded — the reference-point hypothesis (2026-08-21).** Prompted by
the reviewer's magnet-cone conjecture, all attachment ground truth was
re-measured against the plow BODY CENTER (159, 1318 — the card anchor
(163,1169) is the robot-GPS-at-front-face point, 149mm south). Result: ONE
parameter unifies every datapoint — attachment when the magnet point comes
within R of the body center, R bracketed [188, 201]:
P-ladder body distances 318/218/118/69/33/32 = NO/NO/YES/YES/YES/YES
(monotone — the same ladder is incoherent against the anchor: P1 fails
INSIDE 190, P6 succeeds outside); P2b magnet-to-body 151 YES / P7 201 NO;
C031's final drive passes 187.6 from the body (attached); C032 step 4
passes ~95 (attached, reviewer-observed) — no radius bump or drift excuse
needed. The old "static probes don't predict pass-by dynamics" ruling
dissolves: statics and dynamics agree once measured from the body. A cone
is REQUIRED by no datapoint (P3–P6 attach with the body abeam, killing
narrow forward cones; P2b/P7 discriminate by distance, not angle) — but all
evidence has the plow in the robot's front half; rear-gating is untested.
Corpus stakes census (path geometry, R=195): 2 lose (WREN-C054 at 200.7,
WREN-C039 at 207.7 body — both the P1/P2 south-side geometry the statics
call non-attaching), 0 gain. Probes designed; awaiting reviewer runs before
any card/§6 change.

**OI-21 probe series M1-M3 (reviewer-run, 2026-08-21) — attachment is
NEAR-CONTACT AT THE MAGNET POINT, front-gated.**
- M1 (pass 150mm north of blade): NO — falsified the body-centered radius.
- M2 (pass 242mm north): NO.
- M3 (reverse to ~1mm rear contact, magnet boosted, magnet point ~190 away):
  **NO — rear contact does not attach. Front-gated confirmed** (the
  reviewer's cone conjecture, resolved as gating rather than a cone).
Unified model fitting ALL 13 ground-truth datapoints: attach when the
MAGNET POINT comes within near-contact range of the plow STRUCTURE —
the blade rectangle (292x106 at (159,1318)) with threshold bracketed
[32, 97)mm, or the south hitch (the card anchor marks it) with threshold
[31, 52)mm. The historical "190mm attraction radius" was a reference-point
artifact (robot-center distances at attach ~= 66.5 mount + near-contact +
geometry). The statics-vs-dynamics contradiction dissolves entirely.
Corpus census under the new model: attacher population nearly unchanged
(63/65/66 at blade threshold 40/65/90 vs 66 today) — the correction is
ATTACHMENT TIMING (C032: step 4 via its blade-corner clip, not step 32) and
three threshold-sensitive programs: C086 (41.0), C017 (61.0), C054 (68.2).
Refinement statics designed to pin the blade threshold to ±10 and settle
all three; §6 change drafts after.

**M3b — the accidental refinement probe (reviewer, 2026-08-21):** appending
`turn to heading 180` after M3's reverse swings the front magnet on its
66.5mm arm from 134.5mm above the blade edge down to 68mm — and the plow
"swings up to attach" mid-turn. Fourteenth datapoint; confirms magnet-point
near-contact from the north side, attachment while essentially stationary
(rotation only), and TIGHTENS the blade threshold bracket to **[68, 97)**
(M1's 97mm miss still caps it). Effect on the three threshold-sensitive
programs: C086 (41.0) and C017 (61.0) now attach ROBUSTLY under any
in-bracket threshold; WREN-C054 (68.2) sits exactly ON the bracket's low
edge — boundary-marginal, conditional-tier candidate whatever value is
chosen.

# ATTRIBUTION REPORT — Attachment model: magnet-point near-contact
# (OI-21, 2026-08-21) — AWAITING SIGN-OFF

**Change (one §6 change, profile layer ONLY — vendored simulator untouched,
paths byte-identical, frozen fixture UNCHANGED):**
1. Playground card: `plow.attachment` block — blade rect (viz-measured body,
   292×106 at (158.9,1317.9)) gap 75mm [bracket 68–82), hitch point (the
   anchor) gap 40mm [bracket 31–52), `marginal_band_mm: 15`. `tolerance: 190`
   RETAINED as the navigation-semantic radius (approach rungs/landmarks —
   OI-9 reviews those edges); it no longer models attachment.
2. Robot card: `magnet.mount_forward_mm: 66.5` (attachment is evaluated at
   the magnet point — front-gated, probe M3).
3. `indicators.py`: new generic `state_active_attachment_clearance` — value
   is the minimum clearance (mm) of the magnet point beyond the structure
   gaps over the armed window (drives = shifted segments, in-place turns =
   swept arcs; net-sweep normalization noted in-code). ≤0 estimates
   attachment; `attachment_boundary_marginal` inside ±15mm.
4. Goals card: `plow_proximity_execution` rewired to the new indicator;
   labels [attach_estimated, armed_never_close], edge [0.0].
5. `timeline.py`: dedicated scanner — the attach event lands on the step
   whose travel first brings the magnet within reach (true attachment
   timing, the point of the whole change).
6. `viz/data.py`: qualifying-step highlighting under the new model;
   `attachment_boundary_marginal` in the scope flag group.
7. `tests/test_attachment.py`: the 15-datapoint probe ledger as named
   tripwires (P-ladder, P2b/P7, M1–M3c, C031, C032-step-4).

**Attribution:**
- **Zero attachment-verdict flips across 112 programs** (57 delivered / 58
  full-path, identical membership) — the measured mechanism reproduces the
  old population exactly; what changes is honesty and timing.
- **Timing now delivered (timeline):** WREN-C032's attach event moves to
  step 4 — the reviewer-observed second drive (blade-corner clip, margin
  −75) — formerly credited at its step-32 anchor pass. WREN-C094 re-reads
  from "arm then approach" to "arm AT the plow": it parks 45mm from the
  blade, arms, attaches immediately (parked-attach per the P statics), then
  drives away; regression test updated with the reasoning.
- **WREN-C017 is the sole boundary-marginal case** (margin −14.1, inside the
  ±15 band) → flagged conditional. WREN-C054, the census's presumed marginal,
  is `not_armed` (magnet never fires) — moot.
- Values change semantics: min-distance-mm → clearance-margin-mm (≤0 =
  attach). No other profile column moved; fidelity metrics untouched.
- Suite: 165 green + the expected §6 pin tripwire
  (`armed_within_radius` 58 → label retired). Pin at sign-off:
  `attach_estimated: 58` (measured, full-path basis).

**SIGNED OFF (reviewer, 2026-08-21).** Pin renamed
armed_within_radius -> attach_estimated: 58 (same membership); profiles.csv
promoted (values now clearance margins); frozen fixture untouched (sim
unchanged). OI-21 retired. Suite 166 green including the 15-datapoint
attachment probe ledger as named tripwires.

## ONLINE-plan rulings D2 and D7 (reviewer, 2026-08-21)

**D2 — capability registry: three-layer decomposition (reviewer's design,
from their VEX VR research).** VEX VR blocks behave consistently across
playgrounds, but playgrounds differ in ROBOT MODEL (which determines which
blocks exist — e.g., the magnet block only on magnet-equipped models) and in
WORLD PROPERTIES (which determine whether standard sim suffices). Hence:
1. `configs/capabilities.yaml` — OUR simulation capability per block type,
   transferable across playgrounds, hashed into config_version; unknown
   types default to unsimulable-with-named-flag (never a crash).
2. Robot card — the robot model's available block set; a block in code but
   outside the model's set is an anomaly signal (foreign starter code —
   cf. the two Coral-Reef-template sessions), not a capability question.
3. Playground card — simulability properties of the world itself
   (impermanence, physics-movable objects → test-case lane), deliberately
   not expressed in terms of blocks.
Vendored blocks.csv stays pristine. The validation campaign's Stage-1 sweep
populates layer 1 from the measured novel-block incidence table.

**D7 — unexplained divergence: FLAG-AND-DEGRADE.** The run-scoped
`sim_unverified` modifier delivers all sim-channel evidence at conditional
tier with the disagreement magnitude on the flag (consumers threshold as
they see fit — research context preserves analyst choice). Riders: every
firing queues offline as a candidate modeling gap (the C082/C035 discovery
path); a severity cap escalating to withholding remains available as a
measured response after Stage-2 validation, not preemptively.

## VALIDATION CAMPAIGN Stage 0 — adapter + sanity gate (2026-08-21)

**Built:** `src/vex_goal_profiles/ccp_runs.py` (`load_ccp_runs`,
`unwrap_params`) — rows in the pipeline-consumer shape (program_id = run_id,
as-run workspace_xml, playground_params UNWRAPPED to the flat dev shape),
plus run-grain fields, `cohort` (school × era: CROW/2026-04 2,849,
WREN/2026-02 4,161, DOVE/2026-02 973, LARK/2026-04 1) and
`dev_corpus_overlap` tags (168 runs). Card gains
`corpus_filter.playground_self_id: CasteCrasherPlus` (the platform's literal
typo) — positive routing preferred over field-presence where blobs exist.
8 loader tests (tests/test_ccp_loader.py) pin the dataset shape, unwrapping
contract, tags, and the gate.

**Sanity gate result — and a real finding.** All 112 dev finals match a
run's XML verbatim; 107 also match a SAME-RUN params blob exactly, and their
profiles reproduce bit-for-bit through the new loader (spread subset fully
evaluated). **FIVE dev rows carry session-level (xml, params) pairings that
are not same-run pairs**: C020/C046/C064 (final xml only ever ran WITHOUT
telemetry; the dev blob matches no run in the session — plausibly one of
the orphan blobs the run-linkage build drops), C074 and C050 (the final run
HAS telemetry but with different values — C050: dev 4725 kg/154.4 s vs the
run's 4375 kg/69.3 s). The dev extraction paired final code with
session-level telemetry that could cross runs. Fidelity-history impact:
C064 is one of the 14 disagreements (its attribution may be a pairing
artifact); C050's 10.6mm agreement and C074's 2667mm error were computed
against the suspect blobs. Queued as OI-22 for Stage-2 re-adjudication with
per-run truth; dev pins/fixtures UNTOUCHED (they pin sim behavior, not
pairing).

**Stage 0 SIGNED OFF (reviewer, 2026-08-21).** Reviewer confirmed the dev
pairing provenance ("last run + last playgroundData, before the telemetry
-loss issue was known"); per-run linkage is the pairing of record; OI-22
holds the five-row re-adjudication for Stage 2. Stage 1 opens.

## VALIDATION CAMPAIGN Stage 1 — online dry-run report (2026-08-21)

**Exit criterion met: 7,984/7,984 runs profile without a crash, timeout, or
parse failure.** Classification: 3,978 profiled_clean (exactly the
telemetry-bearing runs), 4,006 profiled_with_abstentions — every abstention
is `outcome_field_absent` (missing telemetry degrades the outcome channel
and nothing else). Sweep harness: src/vex_goal_profiles/dryrun.py; per-run
report: data/ccp_run_dataset/stage1_dryrun.csv.

**Failure modes found and fixed (each a graceful-degradation change, dev
corpus byte-identical, 178 tests green):**
1. **Unbounded nested-loop unrolling (hang).** Students nest loops to depth
   47 (70 runs ≥3); unrolling is multiplicative (20^depth) — the sim hung.
   Fix: global execution budget in the vendored sim (50k blocks, ~83x the
   dev-corpus max of 602; card-overridable via
   simulation.execution_budget_blocks), halting like stop_project with flag
   `execution_budget_exhausted` (fires on 26 runs). New SimulationResult
   field blocks_executed doubles as a complexity metric.
2. **Non-finite student math (crash + silent poison).** Divide-by-zero-style
   expressions crashed int(TIMES) on 2 runs — and flowed silently into
   distances/positions on ~121 more. Fix: central sanitizer at the numeric
   boundary (`_sanitize_numeric`: infinities clamp sign-preserving to 1e9 so
   downstream caps bind — infinite repeat behaves like forever, infinite
   distance exits and truncates; NaN → 0), flag
   `nonfinite_numeric_clamped` (123 runs / 9 students).
3. **Un-expanded procedures (silent wrongness).** procedures_call is never
   expanded; the student's factored-out code was invisible with NO flag.
   Now covered by the registry wiring (below); modeling queued (OI-23).

**D2 registry populated (all three ruled layers):**
- `configs/capabilities.yaml` — 70 observed types classified
  (simulates / simulates_capped / testable / unsimulable), unknown-type
  default = unsimulable + `unmodeled_blocks`, hashed into config_version.
  Wired into _profile: any ACTIVE unsimulable block flags every sim-channel
  indicator by name (72 runs carry `unmodeled_blocks`: procedures 36,
  brightness 27, when_timer 8, Switch-mode 1). Orphan blocks deliberately
  don't flag (unreachable code degrades nothing). blocks.csv untouched —
  its upstream simulator_status is demonstrably stale for OUR sim (marks
  distance_found "ignored"; we model it).
- Robot card `available_blocks` (layer 2) — the vr model's set, census+docs
  derived; discriminating only when a second robot model arrives.
- Playground simulability properties (layer 3) — already carried per-object
  (movable/impermanence/testcase_physics); no change needed.

**Other sweep texture (full-sample flag incidence):** fabricated_motion
1,157 · concurrent_stacks_unverified 287 · sensor_reading_stale 241 ·
attachment_boundary_marginal 63 · wait_until_unmet 57 · trigger_unfaithful
46 (when_timer-adjacent hats — capability card covers the class) ·
evidence_post_sim_exit 31 · broadcast_concurrency_approximated 6.

**Queued:** OI-23 (procedures inline expansion — highest value; when_timer
clock from calibrated velocities; brightness probe). Tests: 4 registry
tests (tests/test_capabilities.py) incl. an every-observed-type-covered
tripwire that fails on any NEW block type arriving in either corpus.

# ATTRIBUTION REPORT — OI-24 rulings implemented (2026-08-24) — AWAITING SIGN-OFF

**Change (one §6 change; reviewer rulings 2026-08-24 from their OI-23/24
review pass + four clarifying answers):**
1. **Faithful forever nesting** (vendored sim): an inner forever that runs
   to its unroll cap stops every ENCLOSING loop — exact semantics (a real
   forever never exits, so outer iteration 2 never happens); collapses
   depth-47 nesting to linear cost. Scoped to forever only (a capped
   repeat_until/while might have exited legitimately). Flag cleared per
   top-level stack; saved/restored around sensor-hat firing (parallel
   programs). `repeat Infinity` = forever (reviewer-probed), same treatment.
2. **Category-aware non-finite handling** (vendored sim): percents max out
   and continue (existing clamp, now known VEX-faithful); DISCRETE
   parameters (drive/turn/turn-to/wait) with non-finite values GATE the
   stack — VEX hangs the block — flag `nonfinite_parameter_stall`,
   replacing the off-island-driving 1e9 clamp at those sites.
3. **Switch rejection** (profile layer, card-driven `rejects_program`):
   a Switch block anywhere in the workspace = VEX rejects the project —
   no simulation; sim channel abstains with reason `switch_syntax_error`
   (EvalContext.sim_unavailable_reason plumbed through all 7 no-sim
   abstain sites); code channel intact.
4. **Foreign-block availability layer** (robot card
   `available_blocks.unavailable`): brightness in CCP = foreign code,
   faithful no-op, flag `foreign_playground_block` (not unmodeled).

**Attribution:**
- **Dev corpus: ZERO path changes** — the only candidate program,
  WREN-C060 (repeat{forever}), has repeat TIMES=1, so stopping after
  iteration 1 is a no-op. Identity, pins, and all 192 tests green with NO
  fixture regeneration needed.
- **Run dataset (7,984 re-swept): zero crashes/timeouts/parse failures
  unchanged; `execution_budget_exhausted` 26 → 0** — the collapse handles
  every CROW-C015 monster; the budget is now a pure backstop.
  `unmodeled_blocks` 72 → 44 (brightness's 27 → foreign_playground_block;
  the Switch run → sim-channel abstention). `nonfinite_parameter_stall`:
  2 runs (DOVE-C007 — the former crashes' siblings with Infinity in
  discrete fields). fabricated_motion 1,157 → 1,168 (+11: faithful loop
  termination changes where some programs end, altering terminal-runoff
  incidence — expected consequence).
- 8 new ruling tests (tests/test_oi24_rulings.py) pin all four semantics,
  including prefix-once/inner-caps, the C060 shape, linear cost at depth
  30, stall-with-parallel-stacks, and code-channel survival under Switch
  rejection.

# ATTRIBUTION REPORT — OI-23 build 1: procedure inline expansion
# (2026-08-24) — AWAITING SIGN-OFF

**Change (§6):** Blockly stores procedure identity in a <mutation> element
(foreign xhtml namespace) the parser never captured — BlockNode gains an
additive `mutation` dict (parse_blocks). The simulator registers
definitions (orphan stacks; proccode from the prototype's mutation; body =
the definition's next-chain) and `procedures_call` executes the body
inline and synchronously — a stall or forever inside the body faithfully
affects the caller. Recursion suppressed with
`procedure_recursion_suppressed`; missing definitions no-op with
`procedure_undefined`. Capability entries → simulates.

**Attribution:** dev corpus: exactly ONE program changes — WREN-C095 (the
one live call): path 12 → 92 steps (the body's loops now execute), yet its
DELIVERED PROFILE IS UNCHANGED (boundary True, agreement True, every
indicator identical — the §6a truncation scopes the same). WREN-C020
(definition-only, never called) unchanged. Pins unchanged. Run dataset: 36
procedure runs now execute their factored-out code; zero
procedure_undefined / recursion flags in the wild (no pathological usage).

# ATTRIBUTION REPORT — OI-23 build 2: when_timer clock
# (2026-08-24) — AWAITING SIGN-OFF

**Change (§6):** the simulated clock now advances with MOVEMENT (drives,
turn-for, wait_until march commits) at the calibrated velocities — fixing
the known timer_value defect (previously waits only). `when_timer` hats
DEFER on the resettable timer instead of running eagerly in document
order: they join the pending-hat machinery and fire between blocks once
the threshold is crossed (monotonic clock — at most one block late,
documented). Programs whose stacks finish before the threshold flag
`timer_hat_unfired` (whether the real project stays open to fire it is
not modelled). En route: `math_positive_number_only` joined the numeric
literals (when_timer thresholds parsed as 0 without it). New result field
sim_time_s (elapsed-clock instrument). turn-to-heading/rotation deltas
still don't consume time (documented approximation; zero co-incidence
with timer use).

**Attribution:** dev corpus: ZERO path changes (no when_timer, no
timer_value, no math_positive_number_only in dev; the one reset_timer
program is unaffected) — identity clean except the C095 change above.
Run dataset: the 8 when_timer runs re-simulate — 6 flag timer_hat_unfired
(stacks end before threshold, e.g. CROW-C015's 67s threshold against
short runs), 2 fire mid-program (their hat stacks now execute:
wait_until_unmet 57 → 61). **unmodeled_blocks: 44 → 0 across the whole
sample** — with both builds, every observed block type is simulated,
foreign-flagged, or switch-rejected. Suite: 204 tests, only the expected
C095 identity tripwire pending sign-off + fixture regeneration.

**OI-23 builds SIGNED OFF (reviewer, 2026-08-24).** Fixture regenerated
(the +80-row delta is exactly WREN-C095's expanded procedure body);
profiles.csv and stage1_dryrun.csv were already current from the
attribution sweep. OI-23 retires.

## Reset vs stop — reviewer domain knowledge (2026-08-24)

Missing playground_params frequently reflects students RESETTING the
playground rather than stopping it. Semantics of the two endings:
- **Reset:** the program is ENDED and the robot returns to its start
  position — NO outcome blob is ever generated. A missing blob is thus
  often EXPECTED behavior (an intentional reset, possibly cutting the run
  short), not telemetry loss.
- **Stop:** halts the code and produces the kg-cleared final report (the
  blob, with project_stopped_by_user=true) for the student to reflect on
  before resetting.
Interpretation consequences: (a) no-blob runs must not be read as
"completed but telemetry lost" — many never had an outcome; the loss
report's activity correlation (busy editors missing blobs) is consistent
with fast-iterating students resetting instead of stopping; (b) blob
presence itself is a behavioral signal (the student chose the reflective
stop path); (c) the ONLINE plan's Stage-0 stop-reason vocabulary should
include `reset` alongside completed/stopped once the platform can emit it.
No pipeline behavior changes — fidelity already conditions on blob
presence — this reframes Stage-2/3 interpretation and the MNAR caveat.

**VALIDATION CAMPAIGN Stage 1 CLOSED (reviewer, 2026-08-24). Stage 2 opens:**
fidelity validation over the 307-run set + ~4k backdrop, the viz
disagreement queue, OI-22 re-adjudication, then the OI-9 rung review.

## VALIDATION CAMPAIGN Stage 2 — fidelity results (2026-08-24)

**Population fidelity over ALL 3,978 telemetry runs, fully AUTOMATED
attribution (no hand-rulings): 76.3% agree · 98.4% attributed · 1.6%
UNATTRIBUTED (63 runs).** The dev corpus's hand-ruled taxonomy
(stopped / capped / stalled / edge-slip / override / sensor-conditional)
machine-applies at population scale: stopped 643 · capped 115 · override
63 · edge_slip 40 · sensor_cond 18. Verdicts + gps→trajectory per run in
data/ccp_run_dataset/stage2_fidelity.csv (src/vex_goal_profiles/
fidelity_sweep.py).

**On-island precision: median error 1.4mm, p90 27.1mm** (n=1,427 on-island
agreements) — the calibrated velocities and measured sensor models predict
endpoints near-exactly for the bulk of real student code.

**Cohorts (pooled per ruling; breakdown columns):** WREN/Feb 77.1% agree ·
1.3% unattributed; DOVE/Feb 83.1% · 1.3%; **CROW/Apr (never touched the
pipeline before): 70.5% agree · 2.4% unattributed** — the model
generalizes to the held-out cohort/era with modest degradation.

**Validation-307 (last telemetry run per session): 58.6% agree, 5
unattributed.** Final runs skew complex — the dominant lane is stopped
(92/307): consistent with the reviewer's reset-vs-stop insight, a
session's last telemetry run is very often the reflective stop-to-see-
the-score. D1 semantics (waived XY matching) carries them.

**The D7 lane is small and structured:** 63 unattributed runs (worst
3.4m), clustered in recognizable students (WREN-C042/C040/C018 siblings,
CROW-C117/C066). This is the reviewer's debugging queue — live in the
longitudinal viz (stage-2 fidelity queue: verdict filter, worst-first,
jump-to-run with the full code/diff/walkthrough panel).

## OI-22 RESOLVED — the five cross-run pairings re-adjudicated (2026-08-24)

Same-run truth changes every verdict:
- **DOVE-C074: TRUE error 2.2mm** (dev recorded 2667mm — pure pairing
  artifact; actually one of our best agreements).
- **WREN-C050: TRUE error 289.2mm** (dev's celebrated 10.6mm was a
  coincidence of stop positions across different programs). Its blob says
  project_stopped_by_user → the stopped lane carries it (D1).
- **DOVE-C064: fidelity N/A** — the final run has NO blob (reset-or-loss);
  its dev "disagreement" (one of the 14) was an artifact of comparing
  against another run's telemetry. It EXITS the disagreement ledger.
- DOVE-C020, DOVE-C046: fidelity N/A (no-blob finals; dev binary agreements
  were untestable claims).
Dev-corpus OI-2 accounting annotated (14 disagreements → 13 real + 1
artifact); the run-dataset table is the record going forward.

## CROW-C066_S006_run_053 investigated — post-attachment dynamics (2026-08-24)

Reviewer-queried unattributed case (2599mm, on-island both). Diagnosis:
magnet arms at step 4; by step 7 the sim has the robot INSIDE the plow
blade footprint (attachment per our own model); GPS final (156, 1238) is
the robot PARKED AGAINST THE BLADE's south face. The real robot attached
and towed/anchored; the sim — per the deliberate Hybrid ruling (main sim
never moves objects; attachment is evidence, not dynamics) — dead-reckoned
freely for 31 more steps through 5 object contacts and ended 2.6m away.
Clocks agree to 0.7s (28.9 real / 29.6 sim): the program completed in both
worlds. gps→trajectory is only 96mm — the geometry is corroborated; the
endpoint diverges from towing physics we deliberately do not model.

**Census of the 63 unattributed under this lens:** 3 share the full
attachment signature (magnet + plow contact + gps→trajectory ≤400mm); 14
more share the contact signature (objects hit, trajectory corroborated);
12 are contact-free; 45 have gps→trajectory >400 (trajectory NOT
corroborated — the true D7 residue). Notable: the contact-free large
divergences cluster in WREN-C018 / C040 / C042 — the SAME students whose
dev-corpus finals carried the sensor-divergence mechanisms; their sibling
runs likely share those real-eye/hat behaviors.

**PROPOSED (reviewer ruling needed): a `contact_dynamics` taxonomy lane** —
machine criteria: attachment estimated or object contact before the
divergence + on-island disagreement + gps→trajectory within the card's
400mm corroboration bound. Would attribute 17 of the 63 (queue 63 → 46).
Recorded in OI-2; not implemented pending ruling.

**CORRECTION to the C066 diagnosis (2026-08-24, after reviewer live probe):**
the reviewer authored and ran the first several lines — NO deviation before
or after plow contact; the early path runs exactly as simulated. The
"anchored at the plow from step 7" narrative is FALSIFIED (and contained a
reference-frame error: an attached plow travels WITH the robot, so
GPS-near-the-plow's-START-position is not evidence of anchoring). Blob
linkage was re-verified solid (wall 29.6s ≈ blob 28.9s; blob ts at
projectEnd −0.00s; single blob; same-code neighbor runs have none).
Re-localized: the GPS final lies 173mm off the STEP-33 eastward sweep
((−1015,1373)→(917,855)) — every later sim segment is 850mm+ away — so if
the endpoint is physical, the divergence begins ON that sweep (~t 21–25s
of 29) and the remaining ~6 commands produced no net translation. That
same sweep line passes 160mm from the castle's north corner post, inside
a towed-blade envelope (~171mm half-width). MECHANISM UNRESOLVED — the
reviewer doubts the contact framing; decisive probe = full-program live
run watching (a) whether the plow travels with the robot after contact,
(b) the eastward sweep vs the castle's north corner, (c) the resting
place at ~29s. The proposed contact_dynamics lane stays PROPOSED, pending
that probe.

**C066 CLOSED AS UNEXPLAINED (reviewer live full-program rebuild,
2026-08-24): THE SIMULATION IS CORRECT.** The rebuilt code, run live,
follows the simulated path — the stuck-late hypothesis is falsified along
with the earlier anchoring story. The original run's blob (linkage
re-verified solid) reports an endpoint 2.6m from where the same code
verifiably goes. Residual candidate that no rebuild can test:
session-accumulated world state — run_053 ran on a field rearranged by 52
prior runs, state that is unobservable and unreproducible (the rebuild
necessarily ran fresh). Weak supporting signal: unattributed runs skew
LATE in their sessions (48% in the final third vs 35% baseline; median
position 0.59 vs 0.50) — consistent with accumulated-state effects, far
from conclusive. DISPOSITION: unexplained, exactly what the D7 lane is
for — sim evidence delivers flag-and-degraded with the magnitude
attached; the case stays in the queue as a documented anomaly, not a
model defect. The proposed contact_dynamics lane is PARKED: its flagship
case just demonstrated sim-correctness on rebuild, so contact signatures
cannot be presumed causal without state capture.

# ATTRIBUTION REPORT — edge-triggered re-arming detection hats +
# detection_physics lane (reviewer rulings 2026-08-24) — AWAITING SIGN-OFF

**Ruling 1 (semantics):** the real runtime CONTINUALLY checks detection
hats and re-runs the hat program on every new detection event — the
fires-at-most-once modelling choice was unfaithful (the reviewer's
knock-pieces-retrigger-repeat cascade is impossible under it). Implemented
as EDGE-TRIGGERED RE-ARMING for eye, bumper, AND timer hats: fire on each
false->true transition (mid-move transitions latch; a continuously-true
condition is ONE edge, so the static world cannot infinite-loop; execution
budget backstops; after a reset_timer, a timer hat re-fires on the next
crossing). New result field sensor_hats_fired (hat -> fire steps).

**Ruling 2 (taxonomy):** detection-based programs interacting with movable
pieces get an ATTRIBUTABLE endpoint lane — `detection_physics`: a
detection hat fired AND movable-object contact occurred; the real hat
re-triggers off physics feedback (knocked pieces re-entering detection)
that is inherently unreconstructable.

**Dev-corpus attribution:** two programs change paths —
- **WREN-C012: the ruling's mechanism CONFIRMED.** Its eye hat re-fires
  (path 69 -> 109 steps); repeated hat executions carry it off the island
  — boundary False->True and **off_island_agreement False->TRUE** (its GPS
  is off-island; the faithful semantics matches reality). Dev
  disagreements 14 -> 13. Count pins move together: boundary 67 -> 68,
  timeline exited 67 -> 68. New B1/B2 boundary divergence (B2 suppresses
  the hat) -> allowlisted, documented in OI-1.
- WREN-C103 (bumper): re-fires benignly (21 -> 25 steps), verdicts
  unchanged.
- WREN-C042: byte-identical (its hat stack is a magnet set — no motion to
  re-trigger anything).

**Population attribution (re-swept):** agreement stable (3,035/3,978 =
76.3%); `detection_physics` attributes 16 runs (largely re-classified from
the generic sensor_cond lane, 18 -> 4 — the mechanism is now NAMED);
UNATTRIBUTED holds at 63, still dominated by the contact-free
trajectory-uncorroborated cluster (WREN-C018/C040/C042 siblings — the
front-eye edge-detection probe question) plus C066 (closed unexplained).
Validation-307: agree 181 (up 1). Zero crashes/timeouts.

Sign-off actions: pins (boundary 68, timeline 68, viz disagreements 13),
allowlist entry, fixture + profiles regeneration.

**AMENDMENT (2026-08-24, reviewer probe): RESTART semantics.** The reviewer
tested the front eye live: a new detection during the hat's own execution
RESTARTS its behavior (Scratch heritage) — not ignore-until-done as first
implemented. Reworked: while a hat stack runs, its own condition keeps
being monitored; a new false->true edge TRUNCATES the in-flight move at
the detection point (the real robot abandons the drive there) and re-runs
the script from the top. Restarts are capped at the unroll constant with
`hat_restart_capped` (fires on ZERO runs in the wild — pure backstop);
each restart is recorded as a firing event in sensor_hats_fired. Bonus
fidelity fix folded in: OTHER hats' detection transitions during a hat's
execution now LATCH instead of being lost (they fire at completion —
sequential approximation of parallel hats). Dev corpus: identical blast
radius to the re-arming change (C012 109 steps / C103 25 — their hat
stacks hit no mid-stack edges); the C012 agreement improvement stands.
Population: agree 3,036 (76.3%), detection_physics 15, unattributed 63,
zero crashes. 38 hat-semantics tests green (incl. mid-stack restart,
truncation, one-edge-while-true, timer reset re-crossing).

## Edge-slippage mechanism (reviewer live replays, 2026-08-24)

**Reviewer finding:** near the island edge the robot can SLIP — an
unintentional, RANDOM heading change (a wheel over the rim losing
traction) that poisons all subsequent dead-reckoning. Replaying
DOVE-C076_S001_run_015's code several times produced BOTH outcomes:
sometimes falls off, sometimes stays on but slipped. The mechanism is
inherently non-deterministic — per-run reconstruction is impossible even
in principle.

**run_015 geometry:** the sim path's centre passes **21mm from the outer
edge** (steps 2-3) — the 50.8mm-wide robot's body OVERHANGS the void.
Verdict UNATTRIBUTED, gps→trajectory 551mm (post-slip dead-reckoning is
rotated — trajectory-uncorroborated, the cluster signature).

**Census (exposure = path centre within 71.2mm of the edge — any part of
the robot overhanging):** 41/63 unattributed exposed (65%) — but 61% of a
120-run agree sample is ALSO exposed. Exposure is a NECESSARY condition,
not a predictor: the slip fires stochastically, and the agreeing runs are
the no-slip draws (exactly what the reviewer's replays showed). Notable:
**CROW-C066_S006_run_053 is exposed at 7mm** — the closed-unexplained case
has a candidate mechanism after all: a slip draw its single clean rebuild
didn't reproduce. The 22 NON-exposed unattributed runs still need other
mechanisms (the WREN-C018/C040/C042 contact-free cluster — the front-eye
edge-detection probe question — is largely in this group).

**Taxonomy decision for the reviewer:** an `edge_slip_zone` lane
(UNATTRIBUTED + exposure → attributable as stochastic slip) would take the
queue 63 → 22 — but because exposure is common among agreeing runs too, it
is a PERMISSIVE lane: it attributes by possibility, not by evidence, and
would also absorb any future genuine model bug that happens near the edge.
Alternative: carry exposure as an annotation column without
auto-attributing. Reviewer's ruling requested; queued in OI-2.

**AMENDMENT 2 (2026-08-24, reviewer diagnosis on WREN-C048): the wait does
NOT stop the drivetrain.** A bare `drive` followed by `wait` KEEPS DRIVING
after the wait expires — nothing changes the drive until another
drivetrain command (or program end, where the ratified OI-3 terminal
runoff takes over). Our wait branch wrongly CLEARED the pending drive,
stopping the robot dead at wait-end. Fixed: the wait commits its
velocity x time motion and leaves the motion pending (drives AND turns);
existing runoff/hat-preemption machinery handles the rest; a later
drivetrain command still supersedes.

Attribution: dev corpus — WREN-C042's fidelity error COLLAPSES 1284.6mm ->
74.4mm (its own trailing drive+wait was being stopped dead; the continuing
drive lands it near-threshold; coverage rung some -> negligible), path
10 -> 11 steps. Population: **agree 3,036 -> 3,045; UNATTRIBUTED 63 -> 55**
— the entire WREN-C048 six-run monotonic cluster resolves to agreement
(their growing divergences were growing amounts of post-wait driving as
the student added code), plus two more. Four wait-semantics unit tests
updated to the ruling (wait-portion real, trailing runoff fabricated).
Standing §6 tripwires: pins boundary 67->68 (C012), timeline exited
67->68, viz disagreements 14->13, identity C012/C042/C103 — regeneration
at sign-off.

**AMENDMENT 3 (2026-08-24, reviewer diagnosis on CROW-C072): staleness
completed to NEGATIVE readings.** C072's code plows the debris zone, then
`if <distance found object?> -> drive fwd` (bare drive, no interrupt).
Reality: surrounded by shoved-around debris, the condition is TRUE — the
robot drives forever and off the island (elapsed 12s vs 9.4s nominal,
seven runs, consistent ~700mm signature). Our sim: FALSE against card
positions — with NO flag, because staleness only fired when a reading
referenced a specifically-contacted object. The Hybrid-ruling completion:
once ANY movable contact has occurred the world has diverged from the
card, so EVERY subsequent movable-sensitive evaluation is conditional —
including "found nothing." Implemented at the distance and front-eye
evaluators (_movable_world_disturbed); flag-only, no path changes.
Attribution: dev stale-flag programs 7 -> 12 (honest widening; pins and
paths untouched); population sensor_cond 4 -> 15, **UNATTRIBUTED 55 -> 44
(1.1%)** — the C072 seven and four more attributed. Day's queue
trajectory: 63 -> 55 (wait ruling) -> 44 (staleness completion), with the
44 dominated by slip-zone-exposed runs awaiting the edge_slip_zone ruling
plus the deep-sensor cluster awaiting the edge-detection probe.

**AMENDMENT 4 (2026-08-24): edge-slip disposition RULED — annotation only,
no attribution lane.** The reviewer's decisive observation: the
environment's slips are a playground QUIRK, not physics — e.g.
DOVE-C076's slip changes the heading yet the robot travels the intended
path with wheels crabbed, which no real-robot model can represent. A
mechanism-consistent fit is therefore impossible in principle (the
rotational-fit prototype was abandoned accordingly — it notably rejected
C076 itself). Ruling: simulate as best we can; ANNOTATE paths entering
the edge-overhang band as divergence-possible; never attribute; don't
over-explain (each playground will have its own quirks). Implemented
card-driven: `fidelity_thresholds.edge_divergence_zone_mm: 71.2` in the
playground card; `edge_zone_traversed` column in stage2_fidelity.csv (an
annotation, deliberately NOT a verdict and NOT an evidence flag); the
longitudinal viz shows "⚠ edge zone (divergence possible)" on annotated
runs. Verdict population unchanged; UNATTRIBUTED stands at 44 — honest:
the queue is the queue, with the annotation marking where the quirk could
be the story.

**AMENDMENT 5 (2026-08-24, reviewer investigation of CROW-C117): name-bound
conditional branches.** The reviewer's Blockly reading was correct — an
if/else with an EMPTY if-branch and a forever in the else. The parser
stored branch bodies as an anonymous positional list, so the else body
landed at children[0] and the simulator executed it AS the if-branch:
condition false (not on red) -> the sim skipped the "if-branch" (really
the else) and ran nothing, while the real robot entered the else-forever
(elapsed 66.4s vs 2.5s nominal) and serpentined off-island. FIX: the
parser now records statement and value SLOT NAMES (BlockNode.statements /
value_slots, additive); the if-family executes by name — if_then_else via
CONDITION/SUBSTACK/SUBSTACK2, if_elseif_else via CONDITION{n}/SUBSTACK{n}/
SUBSTACK_ELSE — with empty condition slots evaluating false (VEX
semantics, replacing the legacy execute-first-branch convention on the
name-bound path). Five branch-binding tests pin it.
Attribution: dev corpus ZERO affected (no else-only or empty-condition
conditionals; identity unchanged: still C012/C042/C103 only).
**CROW-C117_S010_run_012 resolves to AGREEMENT** (else-forever executes,
capped serpentine exits like its GPS; 3,356mm unattributed -> agree).
Population: agree 3,046 (76.6%), UNATTRIBUTED 43 (1.1%).

**AMENDMENT 6 (2026-08-24, reviewer question on WREN-C040): the
hat-dependent-divergence precedent encoded.** WREN-C040_S002_run_003:
eye-hat program; our sim's hat confidently never fires (nothing in the
measured 124mm cone on its corridor) — zero flags — while reality's
elapsed (+5.2s, the hat stack's duration) and off-island-west GPS show
the real hat FIRED at something unmodeled. The dev corpus had already
ruled this signature BY HAND (WREN-C018 placed in OI-2's sensor column at
the OI-5 attribution: "hat-dependent divergence"); the automated taxonomy
never encoded it. Now it does: a disagreeing run with a detection hat
(eye/bumper) present that never fired in sim -> sensor_cond. Attributes
the whole cluster (WREN-C040 x2, WREN-C018 x2): sensor_cond 15 -> 19,
**UNATTRIBUTED 43 -> 39 (1.0%)**. The open mechanism behind the cluster
remains the front-eye edge-detection probe. Day's queue trajectory:
63 -> 55 -> 44 -> 43 -> 39.

**AMENDMENT 7 (2026-08-24, reviewer physics): the C018/C040 cluster's
mechanism is DISTURBED DEBRIS, not edge detection — the front-eye edge
probe RETIRES unneeded.** Reviewer: these runs drove through the debris
zone; disrupted pieces fall randomly, often in front of the robot,
potentially out to the boundary — so real hats trigger on scattered
debris the card cannot place. Encoding: the debris zone is card-marked
`disturbs_world: true`; `_movable_world_disturbed` now includes zone
ENTRY (not just modeled contact) — after either, every movable-sensitive
reading and unfired-hat prediction is conditional. Same epistemics as the
C072 staleness ruling, extended from readings to hats, and grounded in
the same physics. Flag-only (no path changes; the 5 standing tripwires
unchanged): sensor_reading_stale now marks 818 runs (was 241) — the
honest scope of world-state uncertainty in a physics playground.
Verdicts unchanged (agree 3,046 / 76.6%, UNATTRIBUTED 39 / 1.0%); the
hat-dependent sensor_cond attributions now carry their mechanism.

**AMENDMENT 8 (2026-08-24, reviewer refinement): `edge_zone_possible` soft
lane.** Zone-annotated disagreements leave the unattributed bucket — they
have a NAMED plausible cause (the slip quirk) even though the mechanism
can never be established per-run. Implemented as the LAST rung of the
verdict ladder (every specific mechanism outranks it), reported as
possible-not-established. Final Stage-2 taxonomy over 3,978 telemetry
runs: agree 3,046 (76.6%) · stopped 641 · capped 115 · override 62 ·
edge_slip 40 · edge_zone_possible 36 · sensor_cond 19 · detection_physics
16 · **UNATTRIBUTED 3 (0.08%)**: DOVE-C058_run_023 (1,860mm),
DOVE-C071_run_021 (690mm), WREN-C003_run_016 (656mm — 74mm edge
clearance, 3mm above the zone threshold; arguably a borderline zone
case). Day's queue trajectory: 63 -> 55 -> 44 -> 43 -> 39 -> 3.

**Final unattributed disposition (reviewer ruling, 2026-08-24):**
DOVE-C058_S001_run_023 and DOVE-C071_S001_run_021 are UNEXPLAINED — no
candidate mechanism assigned. (C058 sanity-checked read-only: the code
diff vs its run_013 sibling is simulated correctly, the blob is
timing-verified as its own, and no code variation produces the reported
GPS.) Reviewer ruling: contact/towing physics is NOT a problem in this
playground and is not to be cited as a candidate. WREN-C003_run_016
stands as recorded (borderline zone threshold). The contact_dynamics
lane stays retired — confirmed not a mechanism here.

**WREN-C003_S001_run_016 → UNEXPLAINED (reviewer live run, 2026-08-24):**
the code stays on the island when rerun — the borderline-zone framing is
retired; the run joins DOVE-C058 and DOVE-C071 as formally unexplained.
Final unexplained set: 3 runs + C066 (closed earlier, sim verified
correct on rebuild).

## Stage-2 FIDELITY PHASE CLOSE (2026-08-24, reviewer sign-off)

Final taxonomy over ALL 3,978 telemetry runs (stage2_fidelity.csv):

| grouping | lanes | runs | share |
|---|---|---|---|
| agreement | agree | 3,046 | 76.6% |
| hard-attributed | stopped 641 · capped 115 · override 62 · edge_slip 40 · sensor_cond 19 · detection_physics 16 | 893 | 22.4% |
| soft/possible | edge_zone_possible | 36 | 0.9% |
| unexplained | DOVE-C058 · DOVE-C071 · WREN-C003 | 3 | 0.08% |

Agreement + attribution = 99.02%; + soft lane = 99.92%. On-island agree
precision: median 1.4mm, p90 27.2mm, p99 61.1mm (n=1,429). Cohorts:
WREN 77.5% agree (2,312), DOVE 83.1% (628), CROW held-out 70.6% (1,037)
— CROW's lower agree is absorbed almost entirely by the hard lanes
(28.2%), not by unexplained (0). Validation-307: 59.0% agree, 122 hard,
3 soft, 1 unexplained — the last-run-of-session set over-samples
deliberate endings (stops, exits), as expected.

Queue trajectory: 63 UNATTRIBUTED at the automated sweep → 55 → 44 →
43 → 39 → 3, every reduction a reviewer-verified mechanism (edge-slip
threshold, wait-keeps-driving, staleness/zone disturbance, name-bound
branches, hat restart semantics, edge-zone soft lane). Sign-off package
executed: PINS_FULL boundary_exceeded 67→68 (C012's re-firing eye hat
exits, matching GPS), timeline exited 67→68, viz cohort disagreements
14→13, frozen_paths.parquet regenerated (4,436→4,481 rows: C012 69→109,
C042 10→11, C103 21→25), profiles.csv regenerated. Suite: 210 passed.

Remaining Stage-2 deliverable: the OI-9 rung review.

**Amendment (2026-08-24, post-close, reviewer-ruled): `detection_physics`
and `sensor_cond` merged into `sensor_uncertainty`.** Whether the
detection hat fired is mechanism detail, not a different attribution —
both lanes claim the same thing: the run turned on a sensing question
our deterministic model cannot decide. The detail survives in the flags
column (stale/timer/wait flags; fired-with-contact is derivable). The
merged rung sits BELOW edge_slip (the more specific geometric claim
wins): one former detection_physics run meeting the edge-slip geometry
migrated. Re-swept table:

| grouping | lanes | runs | share |
|---|---|---|---|
| agreement | agree | 3,046 | 76.6% |
| hard-attributed | stopped 641 · capped 115 · override 62 · edge_slip 41 · sensor_uncertainty 34 | 893 | 22.4% |
| soft/possible | edge_zone_possible | 36 | 0.9% |
| unexplained | DOVE-C058 · DOVE-C071 · WREN-C003 | 3 | 0.08% |

All grouping totals unchanged; reporting-layer only (fidelity_sweep +
viz verdict list); no simulator or pin changes; suite green.

## Rung-review instrument delivered (2026-08-24) — OI-9's Stage-2 deliverable, review pending

Built per the approved plan: a "rung review" page in the longitudinal viz
(sidebar view router; viz/rung_review.py) over a new all-runs rung sweep
(src/vex_goal_profiles/rung_sweep.py → data/ccp_run_dataset/
stage2_rungs.csv: all 7,984 runs × 7 indicators, value/rung/channel/flags
per indicator — code- and sim-channel indicators compute without
telemetry, so the improvement-over-time views see whole sessions and
avoid the telemetry-MNAR bias). Edge provenance is now card-readable: an
inert `rungs.provenance` note on every ladder in the goals card
(design: plow_approach 190/380/570 from object.tolerance,
plow_proximity margin vs measured attach gaps · abstract: robot_moved
100mm, coverage T-3 ladder, weight edges 0.001/810 · exact:
movement_authored, magnet categorical). Inertness proven: profiles.csv
regeneration differs ONLY in config_version (895478e6bdf8 →
dc99e9d010e8); suite 223 passed.

First facts off the instrument (reviewer to work the page for rulings):
- **coverage↔weight: Spearman ρ = 0.652 over 3,978 telemetry runs** —
  the reviewer's "noisy but correlated" intuition confirmed; the decile-
  median curve rises monotonically through the coverage ladder.
- movement_authored is saturated as expected (validation-307: 100%
  authored); the ladder review interest is in the other six.
- Dataset note: a fourth cohort value exists — LARK/2026-04, a single
  run in a single session (present in stage2_fidelity.csv all along;
  prior cohort tables listed the three known cohorts explicitly).
  Flagged for reviewer disposition.

**Amendment (2026-08-25, reviewer-ruled): high-certainty filter on the
rung-review page.** For rung calibration we limit ourselves to the
programs we are most certain of. Per-ladder rule
(viz/rung_review.py:high_certainty_mask): the indicator carries NO flags
(sensor staleness, concurrent code, fabrication, nonfinite, …) and no
abstention, and — when the run has telemetry — its fidelity verdict is
`agree` (catches silent sim divergence flags cannot see); non-telemetry
runs pass on flags alone. The filter defaults ON, prints its kept/
excluded counts (no silent caps), and the coverage↔weight scatter always
applies the COVERAGE ladder's mask regardless of the selected ladder.
Effect on the correlation: **ρ 0.652 (all 3,978) → 0.819 (2,261
high-certainty runs)** — much of the apparent noise in weight_cleared
was sim-uncertainty, not outcome scatter; on trusted simulations the
coverage→weight relationship is strong. Coverage-ladder census: 6,004 of
7,984 runs unflagged; 5,489 high-certainty overall; 116 of the 307.
Suite: 224 passed.

## §6 card change (2026-08-25, reviewer-ruled): weight_cleared rungs re-anchored to the communicated student goal

Old: edges [0.001, 810] / labels [none, some, substantial] (810 = round
10% of max — abstract). New: **edges [0.001, 701, 2500, 4000] / labels
[none, initial_goal, med_goal, high_goal, advanced_goal]** — bands
anchored to what students were told (at least 700kg, then maximize):
initial achievable without strategy, med in a single drive
(physics-dependent), high needs planning, advanced systematic clearing.
Provenance flips abstract → design. Shared-edge convention sends the
edge value to the better bin: 700 → initial_goal (edge 701), 2500 →
high_goal, 4000 → advanced_goal. (Reviewer's bands listed 2500 in both
med and high; encoded per the card convention as high — flagged.)

Attribution: dev corpus (112) — none 7 (unchanged), some 18 → initial 16
+ med 2, substantial 87 → med 48 + high 33 + advanced 6. Population
occupancy: telemetry (3,978): none 23% · initial 23% · med 37% · high
14% · advanced 4%; validation-307: none 6% · initial 12% · med 31% ·
high 22% · advanced 28% — the end-of-session set climbs the ladder
sharply vs mid-session runs, so the goal-anchored bands discriminate
where the old substantial rung (>810) had collapsed 87/112 dev programs
into one bin. config_version dc99e9d010e8 → e74c6b2cc4d8. profiles.csv +
stage2_rungs.csv regenerated; only the weight rung column and
config_version changed. Suite: 224 passed (weight-ladder unit test
re-pinned to the new bands).

## §6 card change (2026-08-25, reviewer-ruled): movement_authored removed

playground_engagement drops its intent indicator (saturated — 100% of
the validation-307 authored movement; redundant with robot_moved, which
carries the goal on real evidence). Empty intent is a modelling
statement per the card contract. The indicator function stays in the
registry (toy cards and tests still exercise it); only the real card
drops it. profiles.csv: exactly the four movement_authored columns
removed, no other column changed but config_version
(e74c6b2cc4d8 → 5fe5a961aa10). stage2_rungs.csv regenerated (6
indicators × 5 columns). Suite: 224 passed.

## OI-9 RUNG-REVIEW MEMO (2026-08-25) — per-ladder rulings

| ladder | provenance | ruling |
|---|---|---|
| playground_engagement · movement_authored | exact | **RESTRUCTURE: removed** (saturated, redundant with robot_moved) |
| playground_engagement · robot_moved | abstract (100mm) | **KEEP** — 339/7,983 below the edge are dominated by true zeros; 159 (2%) sit in the 50-200mm band; the edge separates stationary from moved cleanly |
| engage_plow · magnet_activation_intent | exact (categorical) | **KEEP** (reviewer: behaving as expected) |
| engage_plow · plow_approach_intent | design (190/380/570) | **KEEP** (reviewer: rungs look good) |
| engage_plow · plow_proximity_execution | design (measured gaps) | **KEEP** (reviewer: rungs look good) |
| clear_debris_zone · debris_zone_coverage | abstract (T-3) | **KEEP** — reviewer reviewed incl. the drive-straight baseline fact (~0.054 clears the 0.05 edge) and ruled the ladder good |
| clear_debris_zone · weight_cleared | design (goal-anchored) | **RESTRUCTURED** same day: [0.001, 701, 2500, 4000] / none-initial-med-high-advanced per the communicated 700kg target |

Supporting evidence: high-certainty coverage↔weight ρ=0.819; occupancy
and improvement-over-time views in the rung-review page; dev + population
attribution tables above. Loose ends at memo time: 2500 shared-edge
encoded as high_goal (flagged), LARK/2026-04 single-run cohort
disposition, OI-20 battery explicitly out of scope (no battery run over
this set).

## §6 card changes (2026-08-25, reviewer-ruled): rung-review follow-ups + the remain_on_island goal

Four rulings executed:
1. **robot_moved KEEP** — provenance note now records the rationale: the
   default drive block travels 200mm, so the 100mm edge sits well inside
   meaningful movement.
2. **weight_cleared high_goal starts at 2501** — edges now
   [0.001, 701, 2501, 4000]; 2500 belongs to med_goal. Population
   effect: 15 runs moved high_goal → med_goal (high 543→528, med
   1471→1486); dev corpus unaffected (0 programs in [2500, 2501)).
3. **LARK/2026-04 stays pooled** (single run, single session).
4. **OI-20 battery: next work item** — unchanged, still open.

**New goal `remain_on_island`** (two attainment indicators by design;
empty intent): `on_island_observed` (new indicator outcome_on_island —
final GPS vs the island boundary polygon with the any-part-on-island
tolerance, both card-driven; abstains gps_unavailable without GPS) and
`on_island_sim` (new indicator sim_on_island — §6a rule: simulated
boundary exit = off). The observed reading is authoritative; the sim
reading fills abstentions and carries the simulation channel as the
lower-certainty marker. Both categorical [unknown, off_island,
on_island].

Attribution (7,984 runs): observed — on 2,166 · off 1,812 · abstained
4,006; sim — on 5,087 · off 2,896 · abstained 1 (the Switch-rejected
program). The sim side fills 4,005 of the 4,006 observed-abstentions
(on 3,097 / off 908). Where both exist, observed-vs-sim agree 85.8%
(3,412/3,978) — consistent with the Stage-2 tier-a fidelity accounting.
Dev corpus: observed off 64/on 48; sim off 68/on 44; profiles.csv gains
exactly the eight new columns (46 total), nothing else changed but
config_version (→ 7eb91d4a6c65 after all three card edits).

Tripwires resolved during the change: C012 and C103 on_island_sim
B1/B2 divergences are value-level restatements of their ALLOWLISTED
boundary-level divergences (OI-1) — allowlisted with comments; the
profile contract test now admits gps_unavailable as an abstain reason
and expects four goals. Suite: 226 passed.

## STAGE 2 CLOSED (2026-08-25, reviewer sign-off) — OI-9 retired

Both Stage-2 phases complete: fidelity (closed 2026-08-24: 76.6% agree,
99.02% agree+attributed, 3 unexplained runs, queue 63→3) and rung review
(closed 2026-08-25: every ladder reviewer-ruled over the instrument —
memo above; weight_cleared goal-anchored, movement_authored removed,
remain_on_island added, high-certainty filter the ruled default).
OI-9 retired to the OPEN_ISSUES retired ledger. OI-20 (battery
thresholds) explicitly NOT reviewed — no battery run over the set;
ruled the next work item. Final state: config_version 7eb91d4a6c65,
226 tests green, stage2_fidelity.csv + stage2_rungs.csv current.
Stage 3 (evolution & analysis prep) is open.

## OI-20 opened: capability stocktake delivered (2026-08-25)

SENSOR_TESTBATTERY.md created — the OI-20 working surface. Simulate-vs-
limitation stocktake by block class, environmental feature, and code
structure, each with full-sample coverage (parse census over 7,984 runs /
205 students + sweep-derived environment rows). Headline coverage: 204/205
students' code enters the debris zone (sim), 74 students touch the front
eye, 85 the down eye, 86 distance, 11 bumper; 20 students (287 runs) have
multiple when_started stacks — the largest actionable improve-sim gap
(OI-7 lockout, rule known, blocked on Stage-3 creation-order). §4 of the
document proposes the improve-vs-test split for reviewer ruling; six
battery scenario families sketched.

**OI-20 (2026-08-25): SENSOR_TESTBATTERY §4 rewritten against the
reviewer's CCP_test_case_design.xlsx** (6-dimension playground-agnostic
rubric × T1–T9 tests × test→dimension map — the battery reframed as
execution-characteristic evidence / skill-level scoring lane). Key finds:
the Phase-5 harness already covers most needs (scenario cards with spawn
overrides, kinematic push model, behavioral-divergence checks; 5 existing
cards ≈ T3/T4/T7); recommended build order T1-trace → T8 → T2 → T4 → T7 →
T5 → T6 → T9 → T3 (YAML-first, harness extensions second, compounds
last); capped items: kg never battery-readable, Goal-State Regulation
proxy-capped in CCP (no kg sensor in the block set); OI-7 lockout argued
FORWARD as battery prerequisite (20 students otherwise U everywhere);
U-levels proposed certainty-gated via the flag system; static-first
cascade (~91/205 students decidable from code alone on several
dimensions). Four rulings requested at document end.

**OI-20 (2026-08-25): SENSOR_TESTBATTERY §6 build-plan sketch added.**
Three gated phases: A — sim fixes (A1 OI-7 lockout FIRST per reviewer
ruling, pulling creation-order feeding forward from Stage 3, with honest
U-fallback where order is unresolvable; A2 structures-exercised trace
extract; A3 position-reporter units); B — battery buildout (B1 YAML card
families → B2 harness checks + the family→level composition layer → B3
compounds); C — validation (C1 dev-corpus pins as tripwires, C2 reviewer
live-run protocol [open question: which manipulations are stageable in
the real playground], C3 blind hand-scored rubric reliability sample —
the skill-scoring claim's own validation, C4 population dry run with
U-rate audit). §6.4 adds the mixed-strategy rule the reviewer raised:
scoring unit = program × goal × dimension over the goal-relevant SEGMENT,
anchored on timeline events; every card family declares its scope
explicitly even when "whole run"; per-goal level profiles reported
un-collapsed (the strategy fingerprint), rollup its own later ruling.

## §6 change (2026-08-25, A1): OI-7 drivetrain lockout — built, GATED by a falsification — AWAITING SIGN-OFF

Change: `simulate_path` gains `stack_precedence` (winning when_started
block id; losers' drivetrain commands are no-ops, non-drive effects still
run; absent -> byte-identical). Adapter: `ccp_runs.session_snapshots`
(warm-start chained) + `stack_precedence_map`. Threaded through _profile
and all three sweeps. Dev corpus: profiles.csv BYTE-IDENTICAL (no
precedence on that path) — no pin or fixture changes.

Census (287 multi-when_started runs / 20 students): resolved 226 ·
window_censored 45 · reappearance_ambiguous 9 · tied_generation 7;
drivetrain-contested 188; probe-dependent losers (drive+effects) 71.

**Falsification found by the attribution sweep:** ungated lockout
regressed 25 agreeing runs — ALL monitor-winner configurations (newest
stack drives only inside conditionals; CROW-C094: five wait+if monitors
+ one dead-reckoning driver whose motion the GPS confirms). Encoded
gate: precedence applies only when the winner UNCONDITIONALLY drives
(the probed configuration). Gated attribution: 107 runs mapped; zero
verdict regressions; zero error_mm changes; one capped->override
refinement (more specific lane); concurrent_stacks_unverified 287 -> 180
sample-wide (113 -> 71 on telemetry runs) — a certainty upgrade with no
endpoint churn. stack_lockout_timing_assumed: 1 telemetry run. Two
probes queued in OI-7 (monitor-winner ownership; loser drive duration).
Suite: 235 passed. Canonical stage CSVs NOT yet regenerated — held for
reviewer sign-off per §6.

## OI-7 REVERSAL (2026-08-25, same day): parallel-execution investigation supersedes the lockout

The reviewer's VEX VR API investigation (vr_thread compilation, shared-
drivetrain command replacement, interleaved scheduling) plus our
arbitration adjudication overturned the exclusive-ownership premise:
over live telemetry runs with >=2 driving stacks, sequential-sum agrees
with GPS 89% (tier-1 n=9) / 84% (tier-2 n=62) while first-wins scores
33%/27%, last-doc-wins 67%/42% — every static-owner policy loses.
Interleaved replacement means multiple stacks genuinely contribute
motion; the sequential approximation captures the sum. A1's lockout
application PAUSED (no precedence passed by sweeps; canonical CSVs never
regenerated under it; machinery/census/tests retained). Full
section-by-section simulator comparison in PARALLEL_EXECUTION.md —
headline matches: pending-motion model = the doc's non-blocking
replacement semantics; hat mid-move truncation = the INTERRUPTED
outcome; between-blocks checks = natural yield points. Suite: 235
passed.

## VR-Seq Stage 1 (2026-08-26): generator conversion — zero behavior change

Per BUILD_SPEC PR1: execute_stack/execute_block are now generators (13
recursive sites -> yield from; per-iteration loop yields at the scratch-vm
back-edge position; hat firing and the top-level loop drain inline).
Gates: G1 frozen_paths.parquet byte-identical, G2 all 235 tests green,
profiles.csv byte-identical. Suite runtime 31s -> 40s (generator
overhead; timeline median still under the 100ms pin).

## VR-Seq Stage 2 (2026-08-26): built through G3; G4 STOPPED PER SPEC — awaiting reviewer ruling

Built per BUILD_SPEC PR2 + the four spec deltas (measured
truncate_and_resume; symmetric re-entrant truncation with a mutual-
truncation regression test; thread_start_order config, document default,
settled by measurement; supersession markers as RESULT FIELDS
motions_superseded / drivetrain_contentions — never flags, so the
high-certainty masks stay clean; no latency modeling). Machinery:
_Sequencer (round-robin at scratch-vm yield points, event-driven clock),
_Park protocol, per-thread _forever_completed, global stop, PARKED_COND
via the march solvers, exact-magnitude completion slices and
remaining-seconds wait accounting (both needed for byte-identity).

**Gates:** G1 frozen paths byte-identical · G2 suite green (now 247)
· G3 cooperative byte-identical on single-executable-stack runs — dev
corpus pin + 500/500 population spot-check (eager-unfaithful-hat runs
correctly reclassified as multi-thread; 3 in the sample).

**G4 FAILED and the build STOPPED per the spec's own instruction ("do
not tune"):** tier-2 off-island agreement — sequential 52/62 (84%),
cooperative 42/62 (68%) under all three supersession policies. The
deficit is fully explained by stratification:

| stratum | n | sequential | cooperative |
|---|---|---|---|
| no movable-object sensing (CLEAN) | 26 | 24/26 | **24/26 — ties exactly** |
| movable-sensing exposed | 36 | 28/36 | 18/36 |

The scheduler matches sequential on every run where the world model is
trustworthy. The whole deficit sits where interleaving multiplies
mid-path evaluations of movable-debris conditions (near_object /
distance_found / detection hats) against our DETERMINISTIC debris world
— the known-unreconstructable sensor_uncertainty territory. Mechanism
verified on CROW-C094 (11 of the 14 regressions, one session): zero
supersessions, zero color events — pure ordering composition of the
same stacks' motions, steered by movable-object conditions evaluated at
poses reality never presented. Sequential "wins" the exposed stratum by
EVALUATING LESS — one-shot conditions shield it from the Layer-2
uncertainty — not by modeling the runtime better. Note also: exposure
must be classified statically (block kinds); the coop path can miss the
debris zone entirely and carry no staleness flag.

**State:** sweeps and all defaults remain sequential; scheduler is
opt-in; canonical CSVs untouched; nothing regenerated. Decision queued:
(a) accept the stratified reading — gate the scheduler's claims on the
clean stratum (24/26) and let exposed runs carry sensor_uncertainty as
they already do under the fidelity ladder; or (b) treat G4 at face
value and shelve cooperative mode. Reviewer's call, with the P7/P8-style
VR probes able to arbitrate further if wanted.

## VR-Seq clock/duration campaign (2026-08-26, reviewer-directed) — results

**A3 rotation build (own §6): DONE.** turn_to_heading now takes
shortest-path time; turn_to_rotation is cumulative (new
drive_rotation_deg accumulator, CW+, 0 at spawn — updated at every
physical rotation site) and takes time; the drive_rotation reporter
returns the true accumulator (closes the A3 units-blind item). The
heading-endpoint expression is kept bit-identical to legacy (castle
spawn is VEX heading 0, so absolute and spawn-relative readings
coincide): dev paths AND dev profiles byte-identical — attribution
rides on the duration channel (530 population runs). Suite: 249.

**Loop clock + observed-run budget machinery: DONE.** 60Hz tick top-up
per loop iteration (measured 60.15Hz); when clock+budget are both set
the unroll caps are replaced by the wall-clock budget; budget
exhaustion halts like a stop (no runoff); sequencer slices and single
moves truncate at the budget.

**Duration-fidelity channel (NEW, run first as ordered):** population
5,343 self-terminating runs with observed duration. Aggregate Pearson
r=0.02 is an artifact of structural censoring; the honest stratum
(no loop caps / timer idle / runoff / nonfinite / unmet waits / and —
key exclusion — no boundary exits, whose post-exit sim time is §6a
fiction while the real run ends at the fall): **n=2,431, Spearman
0.630, monotone across all deciles.** Residual structure: **~6.2s
constant overhead + ~0.7s per blocking command** (median-binned; the
0.12s probe latency is a component, not the whole — the empirical read
bundles latency, any velocity underestimate, and reporting overhead;
reconcile before modeling). The 60Hz clock is inert on the clean
stratum (no loops there, as expected); the legacy-loop-capped
population (1,103 runs) is NOT recoverable at a 160s backstop — only
8 runs become uncensored, the rest remain structurally censored.

**G4 2×2 (tier-2, n=62), with per-cell clean/exposed stratification:**

| cell | ALL | clean (26) | exposed (36) |
|---|---|---|---|
| sequential + cap | 52/62 | 24 | 28 |
| cooperative + cap | 42/62 | 24 | 18 |
| sequential + clock+budget | 25/62 | 16 | 9 |
| cooperative + clock+budget | 21/62 | 12 | 9 |

Two decisive reads:
1. **CROW-C094's single session IS the original G4 gap:** excluding its
   11 runs, cooperative+cap EDGES sequential 42/51 vs 41/51 (clean
   identical; exposed 18/25 vs 17/25). Confusion detail: 12 regressions
   (11 = C094) + 2 improvements (WREN-C095_S009 runs 001/002), net -10.
   Per-student: only C094 (11/11 -> 0) and C091/C203 move materially.
2. **The clock+budget cells collapse for a mechanical reason: the
   observed-duration budget binds EARLY.** Our sim clock runs ~6.2s +
   0.7s/command behind reality, so budget = raw observed duration
   truncates TERMINATING programs mid-execution. The reviewer's
   sequencing (empirical calibration before latency modeling) is
   vindicated and extends: calibration must also precede
   observed-duration budget gating. The population fidelity baseline
   under clock configs is deferred for the same reason — running it
   uncalibrated would measure the offset, not the model.

Gates: sequential+cap remains byte-identical (suite is the pin);
G5 not run; canonical CSVs untouched. Rulings queued: (a) C094 session
disposition — one program family (5 movable-sensing monitors + driver),
live-probe recommended; (b) approve the calibrate-then-budget sequence
(duration calibration as its own flagged change); (c) whether
cooperative+cap becomes a candidate default given C094-excluded parity.

## C094 zone-entry diagnostic (2026-08-26, close-out step 1) — BEFORE; static defect FOUND

All 11 runs: first spurious monitor fire at step 9, uniformly, and the
cooperative path NEVER enters the debris zone — the §12.6 "before"
branch. Root cause identified: the firing predicate is
`distance_found(frontdistance)`, and the detected object is
**`castle_debris` — the debris field modeled as a single aggregate
object — at 1,503mm, +5° relative bearing** (reading 1,811mm, inside
the 3m range). At the firing pose the distance predicate is true across
a ~125° heading window: the aggregate-object model presents a large
detectable surface at range that the REAL scattered pieces do not (the
GPS proves the real monitors never fired: 650+ real evaluations, zero
fires). This is a STATIC card-level world-model defect — the
unreconstructable-scatter story does not apply pre-disturbance — and it
is fixable at the card (e.g., the aggregate debris object should not be
long-range distance-detectable in its undisturbed state). Card ruling
queued; the VR probe (drive C094's approach, read distance_found)
earns its keep per §12.6.

## PHASE A CLOSED (2026-08-26): VR-Seq cooperative is the DEFAULT; A2 built; A3 registry-closed

Close-out order executed in full (reviewer ruling, SCHEDULING_MODEL
§12.4-12.8):
1. **C094 diagnostic**: BEFORE zone entry, all 11 runs — static
   aggregate-object detection defect (castle_debris at 1,503mm across a
   ~125° window). Fixable; OI-25 opened (card fix + VR probe).
2. **Predicate bracketing** (new sim mode movable_predicates
   floor/ceiling): 33/34 exposed tier-2 runs bracket-INVARIANT; exactly
   one scatter-undecidable run (CROW-C153_S009_run_009) keeps the U flag.
3. **G5 attribution**: 14 named verdict changes in 3,978 — 11 = C094
   (agree->capped, the OI-25 defect), 2 = C164 eager-'loses'-hat runs
   (same static family), 1 = capped->override refinement. All named,
   all mechanism-attributed.
4. **G6 battery gate**: 927 eligible programs, 31 changes (3.3%), all
   multi-thread, zero errors. Passed.
5. **DEFAULT FLIPPED**: card `simulation.scheduler: cooperative`;
   dev-corpus attribution = WREN-C008's flags only (sheds
   concurrent_stacks_unverified; values/rungs/paths byte-identical —
   PINS UNCHANGED, frozen fixture UNCHANGED). Canonical CSVs
   regenerated: stage1 (zero crashes, concurrent flag 287->0),
   stage2_fidelity (agree 3,033 · capped 127 · override 63; UNATTRIBUTED
   still 3), stage2_rungs (7,984). config a1a0cc40a1ff.
6. **Flag retirement**: concurrent_stacks_unverified now marks exactly
   the bracket-divergent population: ONE run.
7. **Docs**: OI-7 retired to the ledger; OI-25 opened; SENSOR_TESTBATTERY
   stocktake updated (multi-stack RESOLVED; wall-clock machinery built,
   §12.8 scope note; A3 closed — capabilities registry's last `testable`
   class retired).

**A2 delivered**: structures-exercised trace — `loops_exercised`
(block_id -> iterations) and `branches_exercised` (block_id -> arms
taken) on every SimulationResult, additive, tested. **Phase A of the
SENSOR_TESTBATTERY build plan is COMPLETE.** Suite: 250 passed.
Non-blocking own track remains: latency/ramp decomposition ->
budget-gated cells -> population baseline under the clock.

## Phase-A close-out REVIEW corrections (2026-08-26, reviewer-directed)

1. **A3 was NOT closed — now it is, by fixing the code**: pg_sensing_position
   honours UNITS (was raw mm); position_angle/drive_heading report the
   VEX/card convention (inverse of card_heading_to_math; was internal math
   heading); drive_is_done/is_moving are cooperative-aware (a sibling
   thread polling during an in-flight motion reads the truth; sequential
   stays synchronous). Tripwire tests pin all four zero-incidence
   reporters. SimulationResult additionally exports final `variables`.
2. **Flag identity restored (BUILD_SPEC §1)**: bracket divergence now has
   its OWN flag `debris_bracket_divergent` (one run:
   CROW-C153_S009_run_009); `concurrent_stacks_unverified` retires to
   ZERO under the cooperative default — concurrency is verified.
   Reconciliation of the earlier entry: stage1 287->0 AND the divergent
   run are both true — the latter now carries the new flag, not the old.
3. **G6 rerun with the real criterion (§6.3 C1)**: the five credited
   clearers (WREN-C012/C035/C040/C046/C064) all still clear under
   cooperative, identical scenarios and statuses, detects-gating intact.
   MUST RE-RUN after OI-25 (credit against the aggregate surface would
   be credit against a defect).
4. **KNOWN-DEFECT DISCLOSURE**: the regenerated canonical CSVs ship with
   OI-25 open — the aggregate castle_debris object is
   distance/proximity-detectable at range in a way the real sensors are
   not. Static exposure: 890 runs / 74 students (front eye), 898 / 86
   (distance), 303 (detection hats). The 14 moved verdicts understate
   the defect's reach (sequential sampled few poses). Expect movement
   well beyond 14 runs when OI-25 lands.

**34-vs-36 reconciled**: the two runs are CROW-C184_S006 runs 055/056 —
exposed only under SEQUENTIAL via the path-dependent stale flag (their
cooperative path never disturbs the world; they contain no
movable-sensing blocks, so the bracket cannot bite them). Exposure
classification is now explicitly static-by-block-kinds, with path-stale
a separate axis.

**Queued (non-blocking)**: A2 thread attribution — loops/branches
records gain the executing thread id and adopt the PARALLEL_EXECUTION
§14 event vocabulary, so scheduler traces and battery evidence share a
format ("concurrent policy composition" evidence needs which thread ran
what).

## OI-25 RETRACTION (2026-08-26, reviewer challenge verified): no aggregate defect; card correct; C094 reopened as a timing question

Reviewer's three questions, answered against the loaded context:
1. Code path = `_distance_hits` (modeled banded cone). The actual hit at
   C094's firing pose: `castle_debris.inner_corner_tower_sw`, r=70mm,
   measured position, surface 1,811mm at −1.6° relative — inside the 5°
   band. Legitimate point-target geometry.
2. Robot card fully present (all five sensor_specs loaded); no silent
   omnidirectional fallback on the production path. (The toy-card unit
   tests pass {} as robot_card by design; noted.)
3. The "1,503mm / ~125° aggregate surface" figures were a DIAGNOSTIC
   ARTIFACT: a center-distance candidate listing that included the
   radius-None aggregate the sensing code skips. Neither tolerance nor
   defect was measured by the real predicate.

Consequences: the FINDINGS known-defect disclosure is WITHDRAWN — the
canonical CSVs do not ship with a sensing defect; they ship with the
C094 family attributed (capped) under a genuinely-modeled detection
whose real-world FIRING TIME under interleaving is the open question.
No card change was ever applied (correctly — a body radius on the
aggregate would have created a 12× overshoot). G6-C1's credited-clearer
attribution stands on measured geometry and needs no post-fix re-run
(there is no fix). The C094 before/after-zone-entry disposition is
superseded: the fire is pre-disturbance AND legitimate; the VR probe of
the program family is the sole settler. OI-25 re-scoped accordingly.

## OI-25 probe result (2026-08-26, reviewer-run): distance-sensor range FALSIFIED

The C094-pose fan came back ALL FALSE across runs: the real
`distance found` does not see the castle structure at 1,265/1,369/
1,811mm where the model (docs-verified range 3,000mm, banded cone)
says TRUE. The OI-5 precedent repeats: docs-verified is not
behaviorally measured (the eye's 1000mm docs-analogy measured to
124mm). Consequences: (a) the model over-fires distance predicates —
the C094/C164 cooperative divergence is now fully explained as
model-side spurious firing, no VEX-side mystery remains; (b) the
back-away measurement probe is specified in OI-25; one §6 card change
follows it (range + possibly split found-vs-reporter semantics), with
full re-attribution (fidelity, rungs, G6-C1); (c) the
tower-itemization proposal is sensing-moot beyond the measured range
but stands as structure documentation. The canonical CSVs' distance
predicates over-fire until the fix — 898 runs / 86 students exposed;
disclosed here.

## §6 change (2026-08-26): front_distance range MEASURED — OI-25 RESOLVED

Probe series (reviewer-run, Python mode — sensor facts transfer):
1. C094-pose fan: ALL FALSE at 1,265-1,811mm against castle structure.
2. rock_se back-away (24×100mm steps): found TRUE to 1,922mm, FALSE at
   ~2,022mm — bound 1,972±50mm; reporter prints exactly 3000.000 on
   every FALSE (no_object_reading MEASURED); found and reporter share
   one bound. Free validations: 24 exact 100mm odometry steps (OI-16),
   park predicted 150mm/read 122mm (28mm drift), NE island edge crossed
   where the polygon says, fall physics visible post-edge.
3. Castle dead-on at start: TRUE — detectable close-range, no class rule.

Card: range_mm 3000->2000, 2-3m band removed, no-object annotation
ASSUMED->measured, edge-margin caveat recorded (reviewer declined a
precision acceptance model — prior window test sufficient). Margins of
the three C094 fan hits: +0.9°/+1.3°/-0.3° (edge-clip) — all inside
real aim tolerance, explaining ALL-FALSE without a castle mystery.

Attribution: dev corpus UNTOUCHED (config_version only — no dev program
leaned on >2m detections; pins and fixtures stand). Sensing test
re-pinned to the measured cap. G6-C1: the same five credited clearers,
identical credits. Canonical CSVs regenerated: aggregate verdicts
UNCHANGED (agree 3,033 · capped 127 · UNATTRIBUTED 3). ACCEPTED
RESIDUAL: C094 (11) + C164 (2) stay capped — their model hits are
inside 2m at sub-1.5° margins; per the reviewer's ruling these carry
the card caveat rather than a precision model. Suite: 252 passed.
Config version bumped with the card.

## Documentation cleanup for collaborator handoff (2026-08-26)

README rewritten as the front door (state of play, goals table incl.
remain_on_island, doc map, layout, §6 protocol, batch tools).
docs/archive/ created holding SCHEDULING_MODEL / BUILD_SPEC /
PARALLEL_EXECUTION (completed scheduler-era process docs) with an index;
live pointers updated. PIPELINE_DATAFLOW currency pass (scheduler
supersedes the creation-order ingest paragraph; capability classes
updated; stage->module map for the online implementer). VALIDATION_PLAN
header: Stages 0-2 COMPLETE, Stage 3 open. OPEN_ISSUES: OI-22 and OI-24
retired to the ledger (both long-resolved); OI-20 status refreshed
(Phase A complete). Live issues now exactly three: OI-1, OI-2, OI-20.
Suite 252 green throughout.

## §6 change (2026-08-26, reviewer-adopted): castle structure itemised — and C018's disagreement RESOLVES

Adopted per ruling: four outer-hex gray vertex towers (N/S measured
clean at r≈100; NE/SE at structural post coordinates, PROVISIONAL ±60mm)
+ the east gate (r≈94) itemised as pieces; `castle_structure`
documentation block (outer-hex ring, inner-square extent);
`castle_footprint` region (structure extent, evidence-only — debris_zone
keeps the fall-area and staleness semantics; no coverage-rung change).

Dev attribution (§6 tripwires, all named): C018 path 6→20 — its eye hat
FINALLY has its real target, the sim exits at step 5 like its GPS always
said: **the longest-standing dev disagreement resolves** (viz 13→12; the
OI-5-era "ends 50mm short of the west edge" note closes). C046 path
7→34 — a tower detection detours it into the override lane (error
1860→2793; coverage some→systematic); ITS FIRING TOWER IS A PROVISIONAL
NE/SE COORDINATE — flagged: the ±60mm placement is load-bearing for this
one program. C103 path 25→27, no verdict change. Pins: boundary 68→70,
timeline 68→70, viz 13→12; C018 re-enters the B1/B2 allowlist
(reality-matching side, as ever). Fixture 4,481→4,524 rows. The
banded-cone sensing test moved to a synthetic world (no real corridor is
guaranteed empty any more) + the measured-cap checks kept on the card.

Population: agree 3,033→3,037 (+4 net), override 63→64, capped 127→125,
sensor_uncertainty 34→32, edge_slip 41→40; UNATTRIBUTED unchanged at 3.
Stage-1 still zero crashes. G6-C1: the same five clearers, identical
credits (empty-island scenario worlds). A2 thread attribution built the
same day (structure_trace: (thread, event, block, detail) in the §14
vocabulary; per-thread loop/branch exercise now readable). Suite: 253.

## Duration-residual decomposition (2026-08-26, pre-registered; REPORT ONLY — nothing ships)

Pre-registered predictions (reviewer's, recorded before running):
b4≈0.0167 confirms the 60Hz clock / b4≈0 refutes it; b1≈0.12 = latency,
b1>>0.12 with b2≈0 = ramp; b2≠0 = drive-velocity error (5% ≈ 1e-4 s/mm);
b3≠0 = turn-velocity error. Ship criterion: ρ must rise well above 0.630.

Population: same construction as the ρ=0.630 stratum → **n=2,425**
(quoted 2,431; 6 runs moved because the sim has since gained rotation
time, castle pieces, and the cooperative default; baseline ρ reproduces
at 0.633 — comparable). Model: residual = obs − sim_time regressed on
n_blocking_commands, total_distance_mm, total_turn_deg,
total_loop_iterations (from A2's loops_exercised).

| coefficient | joint fit (95% CI) | prediction outcome |
|---|---|---|
| b0 | +11.8s [+5.2, +18.4] | NOT a constant: cohort-dependent — CROW +17.4, WREN +7.7, DOVE +20.2. The "6.2s constant" characterization is RETRACTED: it is cohort/device/era-varying overhead. |
| b1 n_cmd | +1.16 [+0.06, +2.25]; commands-only +0.28 [−0.15, +0.71]; VIF 6.5 | UNSTABLE across specifications (collinearity) — no clean latency or ramp read; the earlier "0.7s/command" is likewise retracted as an artifact. |
| b2 dist | −0.00058 [−0.0019, +0.0008] | **≈0 CONFIRMED — the OI-16 drive velocity stands at population scale** (|b2| well under the 1e-4 five-percent-error scale). The one clean positive result. |
| b3 turn | −0.008 [−0.033, +0.016] | ≈0 in the joint fit — turn velocity stands (CROW shows a small negative; unstable). |
| b4 loop_iter | −1.07 [−2.63, +0.48] | **UNIDENTIFIABLE — a fourth outcome none of the pre-registered branches anticipated: only 129/2,425 honest runs (5%) have ANY loop iterations.** The stratum construction (excluding loop-capped runs) removed the loop-bearing population; the 60Hz hypothesis CANNOT be tested on this stratum by design. |

Diagnostics: joint R²=0.002 (the four predictors explain essentially
nothing of the residual); decile means are a noisy near-flat ~10–25s;
**ρ(obs, sim+fit) = 0.622 < 0.633 — the correction WORSENS rank
agreement; per the pre-registered criterion NOTHING SHIPS.** Cohort
refits disagree in sign and size; the correction damages WREN
(0.614→0.528) and DOVE (0.550→0.449). Multi-thread subgroup n=49,
uninformative. FULL population sanity: R²=0.379 with b0=28.5s —
censored classes carry large STRUCTURED residuals, confirming the
censoring explanation of the r=0.02 aggregate.

**Conclusions.** (1) The duration channel is ordinal-valid (ρ 0.633)
but its within-stratum residual is per-run noise plus cohort-level
overhead, not decomposable code-structure signal — the earlier
"6.2s + 0.7s/command" reading is withdrawn. (2) The OI-16 velocity
calibration is corroborated at population scale — the strongest
independent validation it has received. (3) The 60Hz loop clock is
NEITHER confirmed NOR refuted: the honest stratum structurally excludes
loop-bearing runs. A population-scale clock test needs a different
design — clocked-sim vs observed duration on the loop-CAPPED population
(1,103 runs, 28% loop support in the full sample) — which belongs to
the parked loop-clock item and its own report. (4) Nothing was enabled;
no defaults changed; no CSVs regenerated.

## GitHub preparation: anonymization sweep + data exclusion (2026-08-26)

Reviewer directive: no student data on GitHub; the original institution
acronyms are not anonymous and must not appear. Executed:
1. **Identifier sweep**: every tracked text file (17 files: docs incl.
   archive and agent_tasks, tests, configs, code comments) moved to the
   bird-name scheme. Context census before sweeping confirmed every
   occurrence was id-shaped (no incidental substrings); the one
   prose mapping line in VALIDATION_PLAN — itself de-anonymizing — was
   neutralized to name only the bird cohorts.
2. **Local data renamed to match** (final_code_states.parquet,
   frozen_paths.parquet string columns; profiles.csv regenerated) so the
   suite stays consistent end-to-end: 253 passed post-sweep.
3. **.gitignore**: data/ excluded wholesale (datasets, fixtures,
   generated CSVs, screenshots), plus profiles.csv/full.csv at root,
   caches, Office temp files, logs.
4. **Verification**: zero acronym occurrences in any tracked file type
   outside data/; both design_instructions workbooks internally CLEAN
   (zip-level grep); the ccp parquet was already fully bird-named.
README gains a Data section stating the policy and the fresh-clone
consequence (corpus tests need data delivered separately).

## Design ruling (2026-08-26): two purposes, one instrument — B-1 before B-2

The battery scenarios serve two readers and the harness is never
forked: (1) GOAL-EVIDENCE recovery — checks/facets feed a "test"
attainment channel where simulation evidence is U-gated (router =
static movable-sensing exposure + the high-certainty machinery;
`requires: detects` guards credit; marked lower-certainty like
on_island_sim); (2) RUBRIC scoring — cross-variant behavior read into
dimension levels (RUBRIC_SCORING.md stub created; per-dimension router
sends rule-decidable levels to deterministic reads of census/trace/
path, battery re-reads only where levels turn on conditional behavior;
bracketing/U-gates guard levels; C3 hand-scoring validates — never the
fidelity gates). Phase B builds B-1 first; every B-1 card carries the
forward-design constraint: declare its dimension×level contrasts,
declare its `applies` scope even when whole-run, preserve the full run
artifact so B-2 re-reads without re-running. Docs restructured
(SENSOR_TESTBATTERY §6.0/§6.2/§4.5, PIPELINE_DATAFLOW Stage 4 note +
optional Stage 6, OI-20, README); no code, no card behavior, no CSVs.
