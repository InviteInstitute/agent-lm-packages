# VALIDATION PLAN — the ccp_run_dataset campaign

Status: ACTIVE (adopted 2026-08-21). **Stages 0-2 COMPLETE** (Stage 0
2026-08-21; Stage 1 2026-08-24; Stage 2 — fidelity + rung review —
2026-08-25). Stage 3 (evolution & analysis prep) is the open stage.
Stages are strictly gated: **reviewer sign-off closes each stage before
the next opens** — loose ends land in OPEN_ISSUES, never carried in
flight. Post-campaign note: the execution model shipped 2026-08-26 (the
VR-Seq cooperative scheduler, see docs/archive/) and the canonical CSVs
were regenerated under it with reviewer-verified attribution.

## The dataset

`data/ccp_run_dataset/ccp_runs.parquet` (canonical; dictionary + build script
+ telemetry-loss report alongside). One row per CastleCrasherPlus run, Spring26
full sample:

- **7,984 runs · 205 students · 317 sessions · 6,362 distinct workspaces**
- `workspace_xml` AS-RUN, 100% populated, never backfilled
- `playground_params` on **49.8%** of runs (nested blob:
  `{"playground": "CasteCrasherPlus" — the platform's literal typo — ,
  "parameters": {...}}`; the loader must unwrap and match the typo exactly)
- Positive per-run `playground` identifier (upgrades the field-presence router)
- Full ordering: `run_seq`, timestamps, `ccp_session_seq`,
  `starts_with_existing_code` (creation-order censoring marker),
  `end_status`, `n_playground_data` (run_id-overwrite quirk marker)

**Census (2026-08-21, this session):**
- Runs per session: median 22, p90 51, max 90; 81% of consecutive runs
  changed the code — the evolution signal is dense.
- Novel block types (never seen in the dev corpus): 191 runs (2.4%) —
  operators (and_or / range / not / comparison), optical_brightness,
  control_break, control_stop_project, when_timer hats, looks/pen blocks,
  a bumper reporter variant, `text`, `math_positive_number_only`, others.
- **Calibration overlap: 112/119 dev-corpus finals appear verbatim** —
  DOVE (31 matching runs) and WREN (137). All existing calibration
  and sign-offs were tuned on Feb DOVE/WREN data; CROW (April, 2,849 runs)
  never touched the pipeline before.

**Reviewer rulings (2026-08-21):**
- **Cohorts are POOLED** for validation claims, with the calibration overlap
  stated as a caveat wherever a claim could be misread; per-cohort
  (school × era) breakdown columns ride along on every report — CROW is the
  unofficial held-out signal.
- **Stage-2 validation set = each session's LAST TELEMETRY RUN (n=307)**,
  not final-run-only (159) or per-student.

**Standing caveats (import from the data dictionary; restate under any claim
they could bias):**
- Telemetry loss is **missing-not-at-random**: driven by edit-while-running
  activity, school/device fleet, and date/platform era. Analyses conditioning
  on telemetry undercount live-iterating students, CROW most of all.
- **Reset vs stop (reviewer, 2026-08-24):** a missing blob frequently means
  the student RESET the playground (program ended, robot re-spawned, no
  outcome ever generated) rather than stopped it (which produces the
  kg-cleared report blob first). No-blob runs are often intentional
  endings, not lost telemetry; blob presence is itself a behavioral signal
  (the reflective stop path).
- No platform termination reason beyond projectEnd; `project_stopped_by_user`
  lives inside the params blob as before.
- Sessions are often warm starts (~1/3 begin with substantial pre-existing
  code) — creation-order recovery must respect `starts_with_existing_code`.

**Standing constraints (unchanged by this campaign):**
- The 112-session dev corpus REMAINS the §6 regression base:
  `frozen_paths.parquet`, the pins, and the probe-ledger tripwires are
  untouched by anything here. Any simulator/profile change this data forces
  is its own §6 change with attribution and sign-off.
- YAML-only extensibility; flag-and-queue; graceful degradation over silent
  modeling — a crash is fixed by abstaining with a named flag, and the
  modeling question goes to OPEN_ISSUES.

---

## Stage 0 — Adapter (small; unblocks everything) — **COMPLETE 2026-08-21**

Build the loader; change no behavior.

- [x] `load_ccp_runs()` (alongside `load_final_code_states` in tests/helpers
      or promoted into src/): rows in the same SimpleNamespace shape the
      pipeline consumes (`program_id` = `run_id`, `workspace_xml`,
      `playground_params` UNWRAPPED from the nested blob), plus run-grain
      fields: run_seq, timestamps, school, session ids, ccp_session_seq,
      starts_with_existing_code, end_status, n_playground_data.
- [x] Tag each row: `cohort` (school × era) and `dev_corpus_overlap`
      (verbatim-XML match against final_code_states).
- [x] Wrong-playground router upgraded to prefer the positive `playground`
      field, falling back to field-presence — a card/config concern, not
      Python constants.
- [x] **Sanity gate:** all 112 dev finals match run XML verbatim; 107 are
      same-run (xml, params) pairs reproducing profiles bit-for-bit; FIVE
      dev rows exposed as cross-run pairings (C020/C046/C064/C074/C050) —
      FINDINGS Stage-0 report, queued as OI-22 for Stage-2 re-adjudication.
      Dev suite green.

Exit: loader merged, sanity gate green, reviewer sign-off.

## Stage 1 — Online dry-run: robustness & graceful failure (reviewer item 1) — **COMPLETE; all constituent sign-offs in (2026-08-24)**

Post-completion review chain, all signed off: the OI-24 reviewer pass ruled
on all three failure modes (faithful forever nesting; category-aware
non-finite handling with the VEX-probed stall semantics; Switch rejection;
foreign-block availability layer) and the OI-23 builds landed (procedure
inline expansion; movement-aware when_timer clock) — `unmodeled_blocks` is
now 0 sample-wide and the execution budget never fires (pure backstop).
Formal stage-gate closure at reviewer's word opens Stage 2.

"If the pipeline had been running online this term, what would have happened?"

- [x] Sweep ALL 7,984 runs through parse → simulate → profile
      (src/vex_goal_profiles/dryrun.py; report stage1_dryrun.csv).
- [x] **Zero crashes / timeouts / parse failures certified** (3,978 clean +
      4,006 telemetry-absent abstentions). Three failure modes found and
      fixed gracefully: nested-loop blowup → 50k execution budget +
      `execution_budget_exhausted`; non-finite student math → central
      sanitizer + `nonfinite_numeric_clamped` (123 runs); un-expanded
      procedures → registry flag (below). FINDINGS Stage-1 report.
- [x] Capability registry populated per the D2 ruling: configs/
      capabilities.yaml (70 types classified, unknown default flagged,
      wired into _profile — 72 runs carry `unmodeled_blocks`), robot-card
      available_blocks, playground properties already in place.
- [x] OI-23 queued: procedures inline expansion (highest value),
      when_timer clock, brightness probe. break/stop_project turned out
      already modeled.

Deliverables: robustness report in FINDINGS (counts, named failure modes,
fixes applied), the three D2-ruled cards populated from measured incidence,
OI entries. Exit: zero-crash sweep, registry populated, reviewer sign-off.

## Stage 2 — Fidelity validation + rung review (reviewer item 2) — **COMPLETE 2026-08-25 (fidelity 2026-08-24; rung review 2026-08-25; reviewer sign-off)**

Fidelity close-out (reviewer sign-off 2026-08-24): 3,978 telemetry runs —
agree 3,046 (76.6%) · hard-attributed 893 (22.4%) · edge_zone_possible 36
(0.9%) · unexplained 3 (0.08%: DOVE-C058, DOVE-C071, WREN-C003). Queue
worked 63→3 through reviewer-verified mechanisms; §6 package executed
(pins 68/68/13, fixture + profiles regenerated, 210 tests green). Full
report in FINDINGS.

- [x] **Validation set: last telemetry run per session (n=307)** (ruled).
- [x] Fidelity machinery run (fidelity_sweep.py → stage2_fidelity.csv):
      ALL 3,978 telemetry runs, automated taxonomy — 76.3% agree, 98.4%
      attributed, 63 UNATTRIBUTED (1.6%); on-island median 1.4mm;
      validation-307: 58.6% agree / 5 unattributed; CROW held-out 70.5%.
- [x] **Reviewer debugging loop COMPLETE (2026-08-24):** the longitudinal viz's stage-2
      fidelity queue (verdict filter incl. UNATTRIBUTED, 307-only toggle,
      worst-first jump; per-run fidelity strip on the main panel).
      Reviewer works the 63-run queue down; new mechanisms → rulings → §6.
- [x] Automated backdrop delivered (same table; cohort columns show
      generalization: WREN 77.1 / DOVE 83.1 / CROW 70.5% agree).
- [x] **Rung-review INSTRUMENT delivered (2026-08-24):** the longitudinal
      viz's "rung review" page (viz/rung_review.py, sidebar-routed) over
      the new all-runs rung sweep (src/vex_goal_profiles/rung_sweep.py →
      stage2_rungs.csv, 7,984 rows); card-readable edge provenance
      (`rungs.provenance` key, inert); distributions + occupancy (307 vs
      backdrop), near-edge queue with run-review jump,
      improvement-over-time views (occupancy vs session progress,
      first-reach curves, best-vs-final), coverage↔weight correlation.
- [x] **Rung review — OI-9's ruling pass COMPLETE (2026-08-25, OI-9
      retired):** reviewer ruled ladder by ladder over the instrument —
      engage_plow ×3, coverage, robot_moved KEEP (rationales recorded in
      card provenance); movement_authored REMOVED; weight_cleared
      RESTRUCTURED to the communicated-goal bands [0.001, 701, 2501,
      4000] / none-initial-med-high-advanced; **remain_on_island goal
      ADDED** (observed GPS + sim indicators; sim fills abstentions at
      marked-lower certainty; 85.8% observed-vs-sim agreement).
      High-certainty filter ruled the review default (coverage↔weight
      ρ 0.652 → 0.819 under it). Memo + attributions in FINDINGS;
      config 7eb91d4a6c65; suite 226. OI-20's battery thresholds NOT
      reviewed here (no battery run over the set) — next work item.

Deliverables: validation fidelity report (FINDINGS), worked disagreement
queue, rung-review memo. Exit: queue attributed (or explicitly parked),
rung rulings recorded, reviewer sign-off. **All met — stage closed
2026-08-25; Stage 3 open.**

## Stage 3 — Evolution & analysis prep (reviewer item 3; explicitly later)

- [ ] Per-run profile time series per session (the Stage-1 cached sweep
      makes this nearly free).
- [ ] Rung-trajectory extraction: per goal, the rung sequence over run_seq;
      goal-completion timing (first run reaching each rung, regressions,
      final state) — the progress-toward-goal-completion view.
- [ ] **OI-7 unblocks:** feed `recover_creation_order` from the adapter
      (per session; chained per-student across ccp_session_seq where
      warm starts link back); census resolution rates (resolved /
      window_censored / tied / reappearance-ambiguous) and the contested
      multi-started-stack incidence in this sample; if incidence warrants,
      the drivetrain-lockout §6 change per the OI-7 design
      (`stack_precedence` input, byte-identical when absent).
- [ ] Deliverable: an analysis-ready longitudinal table
      (run_id × goals × rungs × flags × outcome, with cohort and ordering
      columns) plus a descriptive FINDINGS sketch of what trajectories look
      like. **Scope fence: this stage ENDS at the prepared table and
      sketch** — research analyses are their own subsequent work.

Exit: table delivered, OI-7 disposition decided, reviewer sign-off.

---

## Cross-cutting

- Runtime: the full sweep is minutes (core profile <50ms × 6,362 distinct
  workspaces); nothing here needs infrastructure.
- Every report carries: pooled numbers, cohort columns, the calibration-
  overlap caveat, and the telemetry-MNAR caveat where relevant.
- ONLINE plan linkage: Stage 1 ≈ Stage-1 triage gate + D2; Stage 2 ≈ Stage-3
  fidelity gates at population scale; Stage 3 ≈ the run-archive longitudinal
  consumer. What this campaign learns feeds PIPELINE_DATAFLOW directly.
