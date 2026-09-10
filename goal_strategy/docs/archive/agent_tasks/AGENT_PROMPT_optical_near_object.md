# Agent prompt — reclassify `pg_sensing_optical_near_object` as not-yet-handled

**Standalone change. Do NOT bundle into task 3 Part A.** Run it as its own diff, after Part A's
attribution report is signed off, so the two path changes are never conflated.

---

## Why

`pg_sensing_optical_near_object` ("eye near object?") is marked `simulator_status: handled` in
`blocks.csv`, but the implementation in `_eval_expression` is:

```python
if bt in ("pg_sensing_optical_near_object", "pg_sensing_eye", "pg_sensing_optical"):
    for obj in self.ctx.objects.values():
        if _dist(self.x, self.y, obj.x, obj.y) <= obj.tolerance:
            return True
    return False
```

Two defects:

1. **Omnidirectional.** The real eye sensor is forward-facing. This ignores `self.heading` entirely,
   so it fires whether the object is in front of or behind the robot.
2. **Calibrated off `tolerance`, which means four different things.** `castle_debris.tolerance` is
   **1136mm** on a field with ~1700mm playable radius, so the check is true across a large fraction of
   the space. The playground card says this explicitly: *"Tolerance 1136mm = outer hex circumradius;
   pg_sensing_optical_near_object returns True when robot is within the outer castle wall extent."*

A confident wrong answer wearing a `handled` label is worse than an honest `ignored`, because
`ignored` blocks are recorded in `simulator_status_by_block_type` and can be flagged downstream. This
one cannot.

## Scope

**Reclassify these three** (all share the one branch above):

- `pg_sensing_optical_near_object`
- `pg_sensing_eye`
- `pg_sensing_optical`

**Do NOT touch** `pg_sensing_optical_color` / `pg_sensing_optical_detected_color_is`. Those test the
robot's position against `field_hex_vertices` and `field_boundary_color` — the GPS-probed red border,
which the playground card genuinely models. They stay `handled`. (Used by 1 program,
`WREN-C024_715027_S001`.)

## Both changes are required — metadata alone is not enough

**(a) Metadata.** Status becomes `ignored`. `blocks.csv` is a vendored verbatim file, so put the
override in a **project-level config** — e.g. `configs/block_status_overrides.yaml` — applied when
building `simulator_status_by_block_type`, with the reason recorded alongside. That keeps the
vendored CSV untouched and makes the override auditable and reversible in our repo rather than
buried in someone else's data file.

**(b) Behaviour.** Delete the three-type branch from `_eval_expression` so it falls through to the
existing unrecognised-reporter path, which already does the right thing: records the type in
`unknown_reporter_blocks` (stage 0b) and returns falsy without raising. **No new machinery.**

Doing (a) without (b) is a lie in the opposite direction — the simulator would keep returning `True`
while claiming the block is unhandled.

## This is path-changing — exactly one program

`pg_sensing_optical_near_object` is used by **`WREN-C032_wren-co32_S001`** (1 of 119). Where it
currently returns `True` and a branch is taken, it will now return falsy and the other branch runs.

Apply task 3's change protocol:

1. Attribution report **before** touching any fixture: which programs' paths changed, how many steps,
   first divergent step. **Expect exactly `WREN-C032_wren-co32_S001`. If any other program's path moves,
   stop and report** — that would mean the branch was reachable somewhere unexpected.
2. Report before/after on all five task-1 regression pins and on `gps_final_error_mm` (§3b) for
   `WREN-C032`. If the GPS error **drops**, that is direct evidence the reclassification is correct.
3. **Do not regenerate `frozen_paths.parquet` until Chris signs the attribution report.** Then
   regenerate, update pins if they moved, and log the change with date and reason.

## Related — metadata only, no behaviour change

Three **event hats** are also marked `handled` while their conditions are never evaluated (the
simulator runs their stacks unconditionally):

| Block | Programs |
|---|---|
| `pg_events_optical_detect_object` | 7 |
| `pg_events_when_bumper` | 2 |
| `pg_events_when_timer` | 0 |

Same misrepresentation. **Correct their status metadata in this same pass** via the override config —
this is pure metadata and changes no path.

**Do not change how they execute.** That is task 3 Part B, currently in flight, and it is a separate
decision (B1 execute / B2 suppress / B3 abstain). Metadata now, execution there.

## Record in `FINDINGS.md`

- The reclassified types and the reason.
- `WREN-C032_wren-co32_S001`'s path delta and its `gps_final_error_mm` before/after.
- Any regression pin that moved.
- A note that `optical_color` was reviewed and deliberately left `handled`, with its warrant.
