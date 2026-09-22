# Migration map

The authoritative implementation is now `/var/www/agent-lm-packages/goal_strategy`. The source checkout remains intact for comparison and rollback. No source history was deleted and no private data was copied.

Source baseline: `vex-goal-profiles` commit `2ad1770b3d1c6606fa456a015d505ff091810f7f`.
Target baseline: `agent-lm-packages` commit `c341a2a225aafe0a96eb538556fd9f63b2301d26`.
Port implementation version: `0.2.0`; dictionary envelope schema: `1`.

| Original location | New location |
|---|---|
| `src/vex_goal_profiles/*.py` | `goal_strategy/*.py` |
| `vendor/goal_strategy_detector/` | `goal_strategy/detector/` |
| `configs/` | `goal_strategy/configs/` |
| `viz/` | `goal_strategy/viz/` |
| `tests/` | `goal_strategy/tests/` |
| Root research/design Markdown | `goal_strategy/docs/` |
| Root source README | `goal_strategy/docs/SOURCE_README.md` |
| `docs/archive/` | `goal_strategy/docs/archive/` |
| `design_instructions/` | `goal_strategy/design_instructions/` |
| Private `data/` | External `GOAL_STRATEGY_DATA_DIR` |

The original 13 package modules, 27 test modules, eight visualization modules, nine YAML cards, detector CSV, VEX/Blockly JavaScript, both workbooks, living documents and archives are preserved. New shared execution, fidelity, adapter, serialization, streaming, resource and validation helpers live alongside them. Root packaging/configuration changes are merged with the sibling packages.

Replace Python imports `vex_goal_profiles` with `goal_strategy`, and `goal_strategy_detector` with `goal_strategy.detector`. Replace CLI module prefixes similarly. There is no compatibility alias that leaves a hidden dependency on the old repository. Public typed profile/timeline/battery APIs remain at their corresponding module paths.

Use the package README for current commands and contracts. Historical source documents retain their original paths and modeling claims for attribution; those references resolve using this table. Source tests no longer add source/vendor/viz folders to `sys.path`.

Bundled YAML contents and the Castle Crashers card hash (`b8505d656e49`) are unchanged. The pipeline version identifies changes in execution and evidence semantics. Semantic changes include namespace handling, explicit invalid-input reasons, procedure reachability, absolute-turn scheduling, zero repetitions, shared scoring scope, uncertainty propagation and fidelity annotations. Frozen outputs have not been regenerated or accepted as new research baselines.

## Dependency compatibility

The target's Python floor is now 3.10, matching the source. Existing log-parser and learner-model exports and smoke tests remain intact. Base installation adds PyYAML; analysis/UI dependencies are optional. The source distribution includes tests, workbooks and research notes; the wheel contains runtime code and declared resources.

## Third-party assets

The nested detector preserves the source's provenance comments. The existing Blockly 10.4.3 runtime and VEX definitions/corrections are copied without modifying generated JavaScript. The matching `viz/vendor/sprites.png` comes from `https://unpkg.com/blockly@10.4.3/media/sprites.png` and is embedded with the runtime so its controls work without remote requests. The matching upstream Apache license is included as `viz/vendor/BLOCKLY_LICENSE`. Preserve upstream notices in the bundled files.

## Research qualification

The missing `tools/dump_frozen_paths.py` referenced by source tests was not present to transfer. Private data and that producer script are still required for fixture regeneration and corpus attribution. Known modeling questions, including the true VEX behavior of zero velocity, remain unchanged pending measurement.

Status correction (2026-09-22). This document's original baseline was source `2ad1770`, and it previously listed the full battery and rubric scoring as future work. A later bulk copy brought in the post-`2ad1770` source, so the shipped package now contains the full 19-scenario, 7-family battery and purpose-2 rubric scoring (`rubric_combiner.py`, `rubric_evidence.py`, `_claims.yaml`, `_evidence.yaml`), byte-identical to current source and covered by tests. The stage-5 assembly and goal calibration are present too. Rubric scoring is now also reachable online through the opt-in, provisional `include_rubric` flag. The live ECD reference [EVIDENCE_MODEL.md](EVIDENCE_MODEL.md), the validation audit app (`goal_strategy/viz/validate.py` and components), and the maintenance scripts (`goal_strategy/scripts/`) have also been ported. What genuinely remains future work: automatic fourth-channel composition into the goal rollup, feedback selection, automatic raw-event outcome pairing, and the data-dependent transfers (the human-review corpus and `tools/dump_frozen_paths.py`). See [PORT_COMPARISON.md](PORT_COMPARISON.md) for the tier-by-tier detail.
