# Archive — completed process documents

These captured phases of work that are now COMPLETE; they are kept verbatim
as the evidentiary record behind decisions that shipped. The living state of
the project is in the top-level docs (README, FINDINGS, OPEN_ISSUES,
VALIDATION_PLAN, SENSOR_TESTBATTERY, PIPELINE_DATAFLOW).

| doc | what it captured | outcome |
|---|---|---|
| `SCHEDULING_MODEL.md` | The VEX VR runtime investigation: the scratch-vm lineage case, the at-source bundle inspection (§10 — authoritative), the rate probes and the G4 ruling (§12). | The VR-Seq cooperative scheduler, shipped as the simulator default 2026-08-26. |
| `BUILD_SPEC.md` | The scheduler implementation contract: yield rules, DrivetrainCell, gates G1–G5, hazards, the post-probe changelog. | Implemented; gates G1–G3 held byte-identity, G4 demoted to diagnostic by ruling, G5/G6 passed. |
| `PARALLEL_EXECUTION.md` | The simulator-vs-runtime comparison and the nine-probe protocol (§4) that preceded the source reading. | Probes P0–P5/P9 retired by reading VEX's shipped source; P7/P8 run and measured (truncate_and_resume). |

**`agent_tasks/`** — the original task briefs and prompts from the early
build phases (goal profiles, hat-execution fidelity, timeline/viz, the
optical near-object probe). Process artifacts, kept for provenance.

Code comments citing these documents by name refer to the versions here.
