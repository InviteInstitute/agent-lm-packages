# OPEN ISSUES — the researcher's decision queue

Decisions deferred to the validation stage. Nothing in this file is decided by
the pipeline: `FINDINGS.md` records measurements and **all resolved rulings**;
this file holds only what still needs a human ruling, the concrete corpus
cases to inspect, and what would settle each.

Status: `open` (needs review) · `blocked` (needs external data or build work) ·
`probe` (settled only by running the real playground).

**Retired entries** (resolutions recorded in FINDINGS.md, numbering gaps
intentional):
- OI-12 run-termination ruling, OI-13 string-literal fix, OI-14 parser shadow
  fix, OI-15 boundary geometry ruling (2026-08-18).
- **OI-4** plow-engagement geometry (2026-08-19 probe series, superseded same
  day by the WREN-C031 live falsification: uniform 190mm attraction radius +
  continuous segment sampling; zone bands removed).
- **OI-16** velocity calibration (drive 9.88 mm/s per %, turn 4.16 °/s per %,
  measured via the reviewer's two-duration screenshot protocol).
- **OI-10** eye-color field defect (sensing Phase 1: COLORS read, eye-point
  geometry, card color zones — validated against the drive-until-red probe).
- **OI-3** continuous-motion semantics (ratified; wait_until gate implemented
  in Phase 1 — no self-motion, pending motion marches to the condition, unmet
  gates the stack; WREN-C027 resolved itself as predicted). The two
  zero-incidence conventions stay tripwire-guarded in the census tests.
- **OI-6** bumper trigger (Phase 4: contact model, side selection, hats fire
  at first modeled contact; trigger_unsimulated retired; radii since measured).
- **OI-8 / OI-11** unevaluable sensing reporters (Phase 3: distance sensor
  modeled — banded cone, docs-verified; WREN-C082's while-guard now evaluates
  and it exits like its GPS; unknown-reporter incidence for sensing blocks 0).
- **OI-18** eye 'NONE' semantics (reviewer probe 2026-08-19: the ground is
  coded as NO color — 'none' TRUE on open grass, `not none` is the
  react-to-any-color idiom; green interior zone removed; only the line has a
  detectable color).
- **OI-19** sequential-goal test isolation (Option A delivered: late
  materialization, robot-relative, per-construct battery variants).
- **OI-21** plow attachment model (2026-08-21, one day open-to-retired: the
  reviewer's magnet-cone conjecture -> 15-datapoint probe series (M1-M3c) ->
  magnet-point NEAR-CONTACT model, front-gated, blade gap 75mm [68,82) /
  hitch gap 40mm [31,52). Zero verdict flips corpus-wide; attachment TIMING
  now real (C032 attaches step 4 as observed; C094 re-read as arm-AT-plow);
  C017 sole boundary-marginal (flagged). The 190mm "attraction radius" was a
  reference-point artifact; the statics-vs-dynamics contradiction dissolved.
  Probe ledger lives as named tripwires in tests/test_attachment.py; signed
  off same day).
- **OI-23** unmodeled blocks (2026-08-24: reviewer ruled procedures +
  when_timer worth modeling, brightness NOT [foreign/invalid in CCP —
  availability layer]. Both builds delivered and signed off same day:
  procedure inline expansion (mutation capture, registry, recursion guard;
  WREN-C095 path 12→92, profile unchanged) and the movement-aware timer
  clock (timer_value defect fixed; when_timer defers; timer_hat_unfired).
  unmodeled_blocks 44→0 sample-wide).
- **OI-1** conditional-hat treatment sensitivity (RETIRED 2026-08-26,
  reviewer-approved: the validation-stage review happened at population
  scale — B1 (execute) is RATIFIED as the permanent default, with two
  ground-truth datapoints in its favor (C042, C103), every B1/B2
  divergence allowlisted with mechanism, and
  test_conditional_hat_treatment_is_inert failing loudly on any new one).
- **OI-2** fidelity disagreement accounting (RETIRED 2026-08-26,
  reviewer-approved: the full-sample accounting was delivered and closed
  in Stage 2 — zero unattributed dev disagreements, 3 documented
  unexplained population runs; monitoring is embodied in
  fidelity_sweep.py and its taxonomy, not in this queue).
- **OI-24** Stage-1 failure modes (REVIEWED, RULED & BUILT 2026-08-24,
  signed off with the Stage-1 closure: faithful forever nesting;
  category-aware non-finite handling with the VEX-probed stall semantics;
  Switch rejection; foreign-block availability layer. Attribution in
  FINDINGS).
- **OI-22** dev-corpus cross-run pairing (RESOLVED 2026-08-24: run-dataset
  per-run linkage is the pairing of record; the five affected dev rows
  re-adjudicated — C074 2.2mm, C050 289mm/stopped, C064's disagreement was
  an artifact, C020/C046 untestable).
- **OI-25** distance-sensor range (RESOLVED 2026-08-26, same-day probe
  series: the C094-pose fan falsified the docs' 3m figure; the rock_se
  back-away probe MEASURED the found-bound at 1,972±50mm -> card
  range_mm 2000, the 2-3m band removed, no_object_reading 3000 upgraded
  ASSUMED->measured, found and the reporter share one bound; castle
  structure confirmed detectable close-range. Dev corpus untouched
  (config_version only); G6-C1's five clearers identical; canonical
  CSVs regenerated. ACCEPTED RESIDUAL per reviewer ruling (no precision
  acceptance model): hits within ~1.5° of the cone edge are
  aim-marginal — the C094 session (11 runs) + C164 (2 runs) stay
  capped-attributed on such hits; caveat recorded on the robot card.
  Arc note: began as a mis-attributed "aggregate defect" (retracted),
  ended as the OI-5 docs-vs-measured lesson repeating on a second
  sensor).
- **OI-7** concurrent when_started (RESOLVED 2026-08-26: the VR-Seq
  cooperative scheduler — transliterated from VEX's shipped
  @vexcode/scratch-vm fork, at-source-confirmed — is the card DEFAULT.
  Arc: lockout built/falsified -> nine-probe plan -> spec-first
  adoption -> G1-G3 byte-identity -> G4 demoted to diagnostic by
  ruling (one session drove the metric) -> bracketing instrument ->
  G5 (14 named changes) -> G6 battery gate -> flip. WREN-C008 sheds
  its flag; bracket-divergent runs keep it — currently one:
  CROW-C153_S009_run_009. Static-detection residue -> OI-25).
- **OI-9** rung edges (2026-08-25, reviewer-ruled ladder by ladder over the
  rung-review instrument: engage_plow ×3 + coverage + robot_moved KEEP;
  movement_authored REMOVED; weight_cleared RESTRUCTURED to goal-anchored
  bands [0.001, 701, 2501, 4000]; remain_on_island goal ADDED
  (observed + sim indicators). Full memo + attributions in FINDINGS;
  edges stay card-revisable via config_version as ever).
- **OI-5** front-eye cone (2026-08-21 reviewer-run probe: fov 13°, range
  124mm — a short-range PROXIMITY detector, 8× shorter than the docs-analogy
  assumption; `sensor_model_assumed` retired 9→0; WREN-C040 fixed by the
  measured model; WREN-C018 newly sensor-attributable. FINDINGS has the full
  attribution; reviewer signed off 2026-08-21).

**Sensing build status: COMPLETE (2026-08-19; last assumed model retired
2026-08-21)** — Phases 1–5 + Option A signed off in one day; the OI-5 probe
then measured the final assumed sensor model. Zero trigger_* flags; ALL
sensor models now measured/calibrated or docs-verified. Conditional evidence
flows through `sensor_reading_stale` alone (7 programs). Fidelity: 98/112
agreement (87.5%), 14 disagreements, 16.4mm median, zero unattributed.
Battery: five credited clearers, each attributable to a specific modeled
sensor (0/440 rows moved under the measured cone).

---

## Parking lot — deliberately deferred, with unpark triggers

Not open questions (each has a plan); parked by reviewer ruling
2026-08-26 until its trigger arrives.

| item | what it is | unpark when | what resolves it |
|---|---|---|---|
| **Phase B battery card families** | The T1-T9 scenario families (SENSOR_TESTBATTERY §4.3, T8 first) + the family->rubric-level composition layer | Reviewer says go (held 2026-08-26) | Card authoring (YAML) + two harness check rules + C-phase validation incl. the hand-scored reliability sample |
| **Loop clock as default** | The measured 60Hz iteration clock + observed-duration budgets, machinery built and opt-in; would make timer-idle programs simulable | After the duration-channel calibration lands (below) — budgets bind early without it | Its own §6 ruling + attribution; G3-style identity gate is impossible by design (it changes single-stack time), so the gate is the 76.6% fidelity baseline |
| **Duration-channel calibration (latency/ramp)** | Decompose duration ~ β0 + β1·commands + β2·distance + β3·turn_deg on the clean stratum (n=2,431, ρ=0.630); test the ramp model explicitly; falsifiable prediction: ρ must rise substantially or the calibration does not ship | Anytime — own track, not blocking | The regression + a probe-grade read of the per-command constant vs the measured ~0.12s; a materially better ramp fit is a Layer-2 finding (shifts mid-move hat firing) |
| **Sensor hats as threads** | BUILD_SPEC PR3: detection hats become scheduler threads via restartExistingThreads instead of phase-1 inline firing | If hat-timing divergences ever surface in fidelity, or before any playground where hat concurrency is load-bearing | Own identity gate + attribution report; the restart machinery already matches scratch-vm's _restartThread |
| **VR Python programs** | The corpus is 7,983 Blocks / 1 Switch / 0 Python, but Python mode (Pyodide, vr_thread co-op tasks) is a different runtime | If program_type ever includes Python at scale | Its own scheduling evidence (block-runtime findings do not transfer) |

## OI-20 · Battery thresholds and rollup composition — `open` (ACTIVE; build-plan Phase A COMPLETE 2026-08-26)

**SENSOR_TESTBATTERY.md is the working surface.** Phase A (simulation
fixes) is complete: the cooperative scheduler shipped as default, the
structures-exercised trace (A2) built, the sensor registry fully
measured (A3). Next: **Phase B in two sub-phases (ruled 2026-08-26,
§6.0 there): B-1 goal-evidence testing FIRST** (card families whose
checks feed a "test" attainment channel where sim evidence is U-gated;
T8 alternate-starts first), **then B-2 rubric scoring**
(RUBRIC_SCORING.md — currently a design stub). Then Phase C validation
(C1 clearer pins for goal evidence — held under every change so far;
C3 hand-scoring for rubric levels).

First-pass values inside the scenario cards, all card-revisable: detects
divergence 100mm; navigates_to within 180mm; the progress rules (final-third
vs first-third distance trend; capped-with-contact for pushes). The
`requires: detects` gating (reviewer ruling: accidental clearing is not
evidence) and the best-across-scenarios-and-constructs rollup are design
choices to revisit once real cohort batteries run. Related: piece body radii
are measured to ±10mm (blob areas, rock-cross-validated) — a physical
distance-stop probe (`drive; wait until object distance < 200; stop`) would
tighten them if a residual case ever hinges on radius.

- Settles it: validation-stage review of the battery output against known
  student behavior.

