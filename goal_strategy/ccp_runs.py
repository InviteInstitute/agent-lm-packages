"""Loader for the ccp_run_dataset — Stage 0 of VALIDATION_PLAN.md.

One row per CastleCrasherPlus run (Spring26 full sample, 7,984 runs / 205
students / 317 sessions; see data/ccp_run_dataset/data_dictionary.md for
provenance and the telemetry-loss characterization). Rows are exposed in the
same SimpleNamespace shape `load_final_code_states` produces — `program_id`,
`workspace_xml`, `playground_params` (FLAT dict, unwrapped) — so every
pipeline consumer works unchanged, plus the run-grain fields the validation
campaign needs.

Handling rules (from the data dictionary, 2026-08-21):
- `playground_params` arrives NESTED: {"playground": <self-id>,
  "parameters": {...}} — unwrapped here. The platform's blobs self-identify
  with the literal misspelling "CasteCrasherPlus" (PARAMS_SELF_ID); match it
  exactly. Null blob = no telemetry logged — frequently a playground RESET
  (reviewer, 2026-08-24: reset ends the program and returns the robot to
  start WITHOUT generating an outcome; stop produces the kg-cleared report
  blob first). Treat missing blobs as often-intentional endings, not just
  loss; see also the dictionary's caveat 1 (MNAR) before conditioning any
  analysis on blob presence.
- `workspace_xml` is AS-RUN and never backfilled; a null means the capture
  was missing at source and the row must survive as a gap (creation-order
  recovery treats missing as skip, never as deletion).
- `dev_corpus_overlap` marks runs whose XML matches a dev-corpus final
  verbatim — ALL calibration was tuned on those sessions (Feb DOVE/WREN);
  reports pool cohorts per the reviewer's 2026-08-21 ruling but carry this
  tag so the caveat stays checkable.
"""
from __future__ import annotations

from goal_strategy.paths import data_path, require_data

import json
from pathlib import Path
from types import SimpleNamespace

DEFAULT_PATH = data_path() / "ccp_run_dataset" / "ccp_runs.parquet"
DEV_CORPUS_PATH = data_path() / "final_code_states.parquet"

# The platform's literal (mis)spelled self-ID inside playgroundData blobs.
PARAMS_SELF_ID = "CasteCrasherPlus"


def unwrap_params(blob):
    """Nested playgroundData JSON -> (flat params dict | None, self_id | None).

    A blob that is already flat (dev-corpus style) passes through unchanged
    with self_id None — the two corpora share one downstream shape.
    """
    if isinstance(blob, str):
        try:
            blob = json.loads(blob)
        except (ValueError, RecursionError):
            return None, None
    if not isinstance(blob, dict):
        return None, None
    if "parameters" in blob:
        params = blob["parameters"]
        return (dict(params) if isinstance(params, dict) else None), blob.get("playground")
    return dict(blob), None


def load_ccp_runs(path: str | Path | None = None,
                  tag_dev_overlap: bool = True,
                  dev_corpus_path: str | Path | None = None) -> list:
    """All runs, ordered by (derived_session_id, run_seq)."""
    import pandas as pd

    df = pd.read_parquet(require_data(path or data_path("ccp_run_dataset", "ccp_runs.parquet")))
    df = df.sort_values(["derived_session_id", "run_seq"], kind="stable")

    overlap_xmls: frozenset = frozenset()
    if tag_dev_overlap:
        dev = pd.read_parquet(require_data(dev_corpus_path or data_path("final_code_states.parquet")))
        overlap_xmls = frozenset(x for x in dev["workspace_xml"] if x)

    runs = []
    for row in df.to_dict("records"):
        params, self_id = unwrap_params(row.get("playground_params"))
        xml = row.get("workspace_xml")
        if isinstance(xml, float):          # parquet null -> NaN
            xml = None
        school = row.get("school")
        date = str(row.get("date"))
        runs.append(SimpleNamespace(
            # pipeline-consumer shape (matches load_final_code_states)
            program_id=row["run_id"],
            workspace_xml=xml,
            playground_params=params,
            # run identity & ordering
            run_id=row["run_id"],
            run_seq=int(row["run_seq"]),
            run_start_ts=row.get("run_start_ts"),
            run_end_ts=row.get("run_end_ts"),
            end_status=row.get("end_status"),
            n_playground_data=int(row.get("n_playground_data") or 0),
            # duration channel (2026-08-26): observed wall duration + natural-
            # end marker — the time-budget source and the duration-fidelity
            # validation's ground truth
            run_duration_ms=(float(row["run_duration_ms"])
                             if row.get("run_duration_ms") == row.get("run_duration_ms")
                             and row.get("run_duration_ms") is not None else None),
            has_project_end=bool(row.get("has_project_end")),
            playground=row.get("playground"),
            params_playground_self_id=self_id,
            # student / session
            student_study_id=row["student_study_id"],
            derived_session_id=row["derived_session_id"],
            derived_session_num=int(row["derived_session_num"]),
            ccp_session_seq=int(row["ccp_session_seq"]),
            school=school,
            class_code=row.get("class_code"),
            date=date,
            session_start_ts=row.get("session_start_ts"),
            session_end_ts=row.get("session_end_ts"),
            starts_with_existing_code=bool(row.get("starts_with_existing_code")),
            # campaign tags
            cohort=f"{school}/{date[:7]}",
            dev_corpus_overlap=bool(xml) and xml in overlap_xmls,
        ))
    return runs


def session_snapshots(runs: list, session_id: str,
                      chain_warm_starts: bool = True) -> list:
    """(run_seq, workspace_xml) snapshots for creation-order recovery (OI-7),
    for one session — the thin adapter `creation_order.recover_creation_order`
    was built to await.

    Warm-start chaining: when the session's first run starts with pre-existing
    code, the code was authored in an EARLIER session — prepend the same
    student's prior sessions (walking back while each remains a warm start,
    consecutive sessions only) so the observation window reaches toward the
    code's actual creation. A warm start whose prior session is not in the
    data leaves the window censored — honest, per the recovery contract.
    Chained snapshots use a (session_ordinal, run_seq) tuple as the run key so
    ordering never collides across sessions."""
    target = [r for r in runs if r.derived_session_id == session_id]
    if not target:
        return []
    student = target[0].student_study_id
    sessions: dict = {}
    for r in runs:
        if r.student_study_id == student:
            sessions.setdefault(r.derived_session_num, []).append(r)
    nums = sorted(sessions)
    chain = [target[0].derived_session_num]
    if chain_warm_starts:
        while True:
            first = sessions[chain[0]][0]
            idx = nums.index(chain[0])
            if not first.starts_with_existing_code or idx == 0:
                break
            prev = nums[idx - 1]
            if prev != chain[0] - 1:      # non-consecutive: don't bridge gaps
                break
            chain.insert(0, prev)
    return [((num, r.run_seq), r.workspace_xml)
            for num in chain
            for r in sorted(sessions[num], key=lambda x: x.run_seq)]


_IF_FAMILY = frozenset({"pg_control_if_then", "pg_control_if_then_else",
                        "pg_control_if_elseif_else"})


def _unconditionally_drives(root) -> bool:
    """True when the stack reaches a drivetrain block without entering an
    if-family branch (loop substacks ARE entered — a drive inside a forever
    is an active driver; a drive behind a condition is a monitor)."""
    def walk(node):
        while node is not None:
            if node.block_type.startswith("pg_drivetrain_"):
                return True
            if node.block_type not in _IF_FAMILY:
                for child in (node.statements or {}).values():
                    if walk(child):
                        return True
            node = node.next
        return False
    return walk(root.next)


def stack_precedence_map(runs: list) -> dict:
    """run_id -> winning when_started block id (OI-7), for every run where
    ≥2 when_started stacks are present, creation order resolves a winner,
    AND the winner UNCONDITIONALLY drives — the configuration the
    reviewer's probe actually established (two stacks, both actively
    driving). When the most-recently-created stack is a conditional
    MONITOR, static lockout is falsified by the data (2026-08-25
    attribution: 25 agreeing runs regressed, every one a monitor-winner —
    real ownership may be claimed at USE time, not creation time; probe
    queued in OI-7). Runs absent from the map keep the legacy sequential
    approximation and its honest flag — never silently guessed.
    Per-session recovery results are cached; the parse cost is paid only
    for multi-when_started runs."""
    from goal_strategy.detector.parsing.parse_blocks import parse_workspace

    from .creation_order import recover_creation_order, resolve_precedence

    order_cache: dict = {}
    out: dict = {}
    for r in runs:
        prog = parse_workspace(r.workspace_xml or "", r.run_id)
        if prog is None:
            continue
        started = [s for s in prog.event_handler_stacks
                   if s.block_type == "pg_events_when_started"]
        if len(started) < 2:
            continue
        sid = r.derived_session_id
        if sid not in order_cache:
            order_cache[sid] = recover_creation_order(
                session_snapshots(runs, sid))
        res = resolve_precedence(order_cache[sid], [s.block_id for s in started])
        if res.reason != "resolved":
            continue
        winner = next(s for s in started if s.block_id == res.winner)
        if _unconditionally_drives(winner):
            out[r.run_id] = res.winner
    return out
