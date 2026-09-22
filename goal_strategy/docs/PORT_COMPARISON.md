# Port comparison - what is implemented here versus the source repo

Date: 2026-09-22. Author: engineering review.

This compares the shipped `goal_strategy/` package against the live source
repository `vex-goal-profiles` at its current `main` (`cf0a715`), not the
`2ad1770` baseline named in [MIGRATION_MAP.md](MIGRATION_MAP.md). The two
are worth separating because the port was planned against `2ad1770` but a
later bulk copy brought in most of the post-`2ad1770` source, while the
port's high-level wiring and docs were not updated to match. The result is
three tiers, and the tier a feature lands in matters more than a flat
present or absent list.

All claims below were checked by reading both trees, diffing files, and
running the port's own tests plus synthetic reproductions. No private data
was used. The source tree was read only, and this document lives in the
target repo.

## The one fact that explains the rest

[MIGRATION_MAP.md](MIGRATION_MAP.md) states the source baseline as
`2ad1770` and lists rubric scoring as "future work". But the files on disk
tell a different story:

- `rubric_combiner.py`, `rubric_evidence.py`, and
  `configs/testcases/castle_crashers/_claims.yaml` are **byte-identical to
  current source HEAD** (verified with `diff`).
- All 23 Castle Crashers testcase cards are present (the full 19-scenario,
  7-family battery plus the four `_rollup`/`_claims`/`_evidence`/`_router`
  cards), not the smaller battery that existed at `2ad1770`.
- The purpose-2 tests (`test_rubric_combiner.py`, `test_profile_assembly.py`,
  `test_battery_evidence.py`) pass here: 34 passed, 5 skipped.

So purpose-2 rubric scoring, the full battery, stage-5 assembly, and goal
calibration were physically copied in and work. What was never done is
wiring them into the online API surface or updating the port docs. Hence
Tier 2 below.

## Tier 1 - implemented, wired into the online API, validated

The per-run goal product plus a genuine online integration layer the
source repo does not have.

| Capability | Where | Notes |
|---|---|---|
| Goal profiles (purpose 1) | `profile.py`, `indicators.py`, `config.py`, `codefacts.py`, `timeline.py`, `detector/` | Cards unchanged, card hash `b8505d656e49` |
| Online dict API | `adapter.py` (`goal_profile`, `goal_profile_from_content`, `goal_profile_from_run_event`, `goal_profiles_from_events`) | Port-new. Event to profile, `learner_models` run-index alignment, telemetry pairing |
| Real-time streaming | `streaming.py` (`GoalProfileStream`) | Port-new. Prefix-equivalence guarantee with the batch driver |
| Strict-JSON envelope | `serialize.py` (`profile_to_dict`, schema/pipeline versions) | Port-new |
| Shared execution artifact | `execution.py` | Port-new. One simulation shared by profile, timeline, plot (closes source review finding 1) |
| Fidelity annotation | `fidelity.py` | Port-new extraction |
| Bundled-resource card loading | `paths.py`, `artifacts.py` | Port-new. Cards load from any cwd or installed wheel (closes source review finding 6) |
| Content-hash result cache | `adapter.py`, `execution.py` | Port-new |
| Walkthrough / longitudinal review apps | `viz/app.py`, `viz/longitudinal.py`, `viz/rung_review.py`, `viz/walkthrough.py`, `viz/workspace.py`, `viz/data.py`, `viz/plots.py`, `viz/blockly.py` | Bundled Blockly assets |

Source-review bug fixes verified live against this package (the same
reproductions that still fail on source HEAD):

- Non-finite telemetry: `weight_cleared=NaN` returns `status=invalid_input`,
  `reason=gps_invalid`, and the run abstains, instead of the source's
  confident `advanced_goal`.
- Output is strict-JSON-safe: `json.dumps(result, allow_nan=False)` passes.
- Cards resolve from a foreign cwd: a profile call from `/tmp` returns
  `status=profiled`.
- The README additionally documents fixes for input depth and size limits,
  absolute-turn arbitration, procedure reachability, zero repetitions, and
  shared scoring scope.

## Tier 2 - present and tested, but NOT on the online surface (and the docs disown it)

These files were copied in (identical to source) and their tests pass, but
`adapter.py`, `serialize.py`, and `streaming.py` contain zero references to
them, and the README and MIGRATION_MAP still call them "future work". They
are reachable only through typed imports and the batch sweeps, never in the
`goal_profile()` result envelope.

| Capability | Where | Reachable via | Evidence |
|---|---|---|---|
| Purpose-2 rubric scoring | `rubric_combiner.py`, `rubric_evidence.py`, `_claims.yaml`, `_evidence.yaml` | `combine_run(...)`, batch sweep | Byte-identical to source HEAD |
| Full 19-scenario battery | `battery_evidence.py`, 23 testcase cards | `battery_evidence(...)`, sweep | README describes only a "five-scenario battery" |
| Stage-5 delivery assembly | `profile_assembly.py` | batch | Tests pass |
| Goal calibration | `goal_calibration.py` | batch | Tests pass |

Important nuance - rubric is provisional by design. In the source,
purpose-2 ships as `rubric_status = provisional_stage2E` with per-dimension
caveats and is under active human validation (see the source
`VALIDATION_PLAN.md` Stage 2E and `EVIDENCE_MODEL.md`). So the port author
leaving it off the live feedback surface may be a correct product call, not
only an oversight. The defect is that the docs mislead: they imply the code
does not exist, when in fact it exists, is tested, and is deliberately
provisional. The fix must make that true status legible, and any online
exposure must carry the provisional label loudly rather than present rubric
levels as settled per-run feedback.

## Tier 3 - not ported at all (present in source, absent here)

| Missing capability | Source location |
|---|---|
| Validation audit app and its stack | `viz/validate.py`, `viz/validation_bundle.py`, `viz/validation_store.py`, `viz/battery_review.py`, `viz/testcase_scoring.py`, `viz/validation_display.yaml` |
| Human-review corpus | `validation/manifest.csv`, `validation/reviews/*.json` (saved judgments) |
| Maintenance and backfill scripts | `scripts/backfill_stage2_columns.py`, `scripts/backfill_state_gated_executed.py`, `scripts/reverdict_unattributed.py`, `scripts/build_validation_manifest.py`, `scripts/generate_battery_cards.py` |
| Live ECD reference | `EVIDENCE_MODEL.md` (the current authority that superseded the ported `RUBRIC_SCORING.md` and `SENSOR_TESTBATTERY.md`) |
| Frozen-fixture producer | `tools/dump_frozen_paths.py` (MIGRATION_MAP already notes this was missing to transfer) |

This is the research and validation half of the source project. It is a
larger and more self-contained effort than Tiers 1 and 2, and much of it
(the human-review corpus, the frozen-fixture producer) depends on private
data that does not belong in this repo.

## Fix plan

Scope for this pass is the Tier-2 gap - the shipped-but-hidden, misdocumented
features - because it is bounded, additive, and high value. Tier 3 is
recommended as a separate follow-up, not folded in here.

1. Documentation truth (always safe, do first):
   - README "Execution and confidence": replace the "five-scenario battery"
     description with the real 19-scenario, 7-family battery.
   - README and MIGRATION_MAP "Research qualification": stop listing rubric
     scoring, the full battery, and stage-5 as "future work" or
     not-implemented. State the real status: implemented, byte-identical to
     source, tested, and provisional pending Stage 2E validation, currently
     reachable via typed and batch APIs.
   - PORT_VALIDATION: record the Tier-2 finding and this document.

2. Online exposure of purpose-2, opt-in and clearly provisional:
   - Add `include_rubric=False` to `goal_profile` and its siblings,
     mirroring `include_timeline` and `include_battery`, threaded through
     `_result`, `_compute_result`, `GoalProfileStream`, and the result
     cache key.
   - Compose per-run rubric from the shared execution artifact: production
     code evidence via `rubric_evidence.code_evidence(program, sim)`, the
     per-scenario battery evidence via `battery_evidence(...)`, then
     `rubric_combiner.combine_run(...)`. Reuse the exact row shapes from
     `battery_sweep._evidence_row` and the `rung_sweep` code-evidence row so
     the online path and the offline sweep cannot diverge.
   - Serialize each `DimensionEvidence` (level, ceiling, fired with
     strengths, negatives, borderline, u_reason) plus a `provisional: true`
     marker and a `status` note into `result['rubric']`.
   - Extend the prefix-equivalence and cache-key tests to the new channel.

The decision that gates step 2 is whether provisional rubric levels should
be exposed on the online API at all. Options: docs-only (leave rubric off
the online surface, correct the record); docs plus an opt-in
`include_rubric` flag labeled provisional (recommended - additive, defaults
off, makes the shipped feature reachable without presenting it as settled
feedback); or docs plus a default rubric channel (not recommended while the
dimension is provisional).

## Verification performed

- Diffed `rubric_combiner.py`, `rubric_evidence.py`, `_claims.yaml`
  (identical to source HEAD) and `profile.py` (port import edits only).
- Confirmed 23 testcase cards present in both trees.
- Grepped `adapter.py`, `serialize.py`, `streaming.py` for rubric, stage5,
  combine_run, dimension: no references.
- Ran the port's rubric, stage-5, and battery-evidence tests: 34 passed,
  5 skipped.
- Reproduced the source-review bug fixes against the online API.
