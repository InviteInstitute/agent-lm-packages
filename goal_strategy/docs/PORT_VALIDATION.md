# Port validation

Implemented on 2026-09-10 in `agent-lm-packages/goal_strategy`, package version `0.2.0`, envelope schema `1`. The source checkout is intact. No private datasets, frozen fixtures, generated JavaScript, or changelogs were edited. No service was deployed or package published.

## Completed checks

| Check | Result |
|---|---|
| Full tracked-source inventory | Every source asset has a destination; no unmapped tracked files |
| Original cards, generated Blockly runtime and workbooks | Byte-identical to source |
| Castle Crashers configuration hash | Preserved: `b8505d656e49` |
| Python 3.12 full pytest run | 287 passed, 47 private-data cases skipped |
| Python 3.10.21 standalone pytest run | 287 passed, 47 private-data cases deselected |
| Original target smoke runner | 40 passed, 0 failed; original test file unchanged |
| Extended end-to-end example | Passed; supported, unsupported and missing-outcome runs retain correct index joins |
| Separate-process source/target comparison | Original profile fields match for 0, 200 and 800 mm drives after deliberate flag-order canonicalization; new fields excluded from comparison |
| Five CLI workflows | Passed against 12 public synthetic run records, including malformed XML and eligible sensor programs |
| Synthetic dry run | 10 profiled, 2 explicit parse failures, 0 crashes, 0 timeouts |
| Review application tests | Dev walkthrough, summary, cohort, longitudinal run/walkthrough/rung views and missing-data messages pass |
| Chromium browser inspection | Both apps render Blockly, report no JavaScript/app errors or external asset requests, and have no outer-page horizontal overflow at 1440 px and 390 px widths |
| Wheel and source distribution | Built and inspected; nine cards, detector CSV and local JS/sprite resources present; private data excluded; tests/docs/workbooks in sdist, excluded from wheel |
| Non-editable core installation | API, aliases, strict JSON, timeline, battery and resource rendering pass outside both checkouts in a clean Python 3.12 environment with only base dependencies |
| Strict private-data gate | `--require-goal-data` fails with the missing input paths; it cannot silently report full-corpus success |
| Git whitespace check | Passed |

The 47 private-data cases are the original 45 dataset/fixture-dependent cases plus two generated-CSV checks. The two standalone rung-card tests remain in ordinary discovery. Research count assertions and floating-point tolerances were preserved. The invalid-XML reason assertion and export identity-column assertion were updated for their explicit new contracts.

Python 3.10 exposed an empty-chart warning in the rung-review page. The page now shows an empty-population message; its end-to-end check passes with user warnings treated as errors.

## Reproduced repairs

Regression cases started from the public APIs or application workflow. They cover:

- Target-format unnamespaced XML, including connected shadow inputs and foreign-namespace procedure mutations.
- Shared cooperative execution for profiles, timelines and plots; configured program rejection cannot produce a simulated UI path.
- NaN/infinite/overflowing numeric outcomes, extreme timestamps, malformed/oversized/deep XML, random/round/exponential overflow, and strict JSON output.
- Absolute-turn drivetrain arbitration, per-thread procedure recursion, reachable procedure code facts and procedure-only battery eligibility.
- Repeat zero, capped-loop/unknown-reporter/unknown-statement flags, and named uncertainty while retaining the unmeasured zero-velocity fallback.
- Continuous approach and armed proximity through a target between recorded endpoints.
- Empty battery inputs, invalid scenario-rule configuration errors, scenario uncertainty and versioned reports.
- Cross-process canonical output, modeled sensor-hat labels, early-stop handling, descriptive unexplained-fidelity annotations, and explicit outcome/playground association.
- Optional imports, configuration-source resolution, isolated cached cards, all five batch commands, signal-handler restoration, and stale-artifact rejection.

Browser/application checks also repaired phone-width layout, remote Blockly sprite loading, epoch timestamp formatting, mixed-value table serialization, a pandas `flags` attribute collision, escaped student-authored outline text, import-time application launch, and empty population chart handling.

## Timing observations

These are **synthetic measurements on the review host**, not population latency guarantees. Each row has 12 calls through the plain-data API. Nearest-rank p95 and p99 equal the maximum at this sample size. Configuration/cache/import state and concurrent validation work affect results; the first simple profile took 100.34 ms. No calibrated tail SLA is claimed.

| Fixture | Profile median / maximum (ms) | With timeline median / maximum (ms) | With battery median / maximum (ms) |
|---|---:|---:|---:|
| Drive 200 mm | 5.89 / 100.34 | 6.12 / 8.03 | 18.55 / 19.04 |
| Concurrent 1000/400 mm drives | 8.12 / 8.45 | 8.21 / 9.78 | 20.44 / 20.77 |
| Three nested repeat-20 loops | 565.88 / 607.04 | 648.59 / 700.91 | 552.57 / 588.27 |
| Responsive sensor pusher | 9.62 / 9.95 | 10.89 / 11.04 | 60.28 / 88.53 |

Battery requests on sensor-free fixtures return an ineligible report, so those rows do not measure scenario execution. The pusher row does. Limits on executed statements and modeled time are not CPU deadlines; host request limits/concurrency need measurements on real workloads.

## Pending research and deployment qualification

The implementation and standalone transfer are complete. **Private-corpus equivalence is not established.** The confidential final-state/run datasets, frozen paths and generated fidelity/rung tables were unavailable. The source-referenced `tools/dump_frozen_paths.py` was also absent. No population fidelity statistic, goal-recognition accuracy, frozen-baseline update or research acceptance is claimed.

Behavior changes still require source-protocol corpus attribution and reviewer acceptance before replacing research baselines. `sim_unverified` flags rather than withholds numerical evidence; it is a descriptive implementation of the planned interpretation, not a resolved calibration question. Zero-velocity semantics retain their fallback with a flag until measured in VEX.

Python 3.10 and 3.12 were tested, but actual downstream deployments still need to adopt the new Python 3.10 floor. Automatic raw-event telemetry pairing requires representative host lifecycle fixtures if requested later. B-1 expansion/fourth-channel composition, B-2 rubric scoring and feedback selection remain future features, as in the migration plan.

## Reproduce

From the target checkout, install `.[dev]` and run the commands in the package README. Browser screenshots and operational logs from this review were kept under `/tmp/goal-port-browser` and `/tmp/goal-*`, outside the repository. Synthetic parquet data lives under `/tmp/goal-port-review-data`. Distributions are under `/tmp/goal-port-dist`.

A plain base wheel check must run in a fresh environment and a working directory outside both checkouts. Install the visualization extra separately for installed app checks. Root `test_smoke.py` remains part of default pytest discovery.
