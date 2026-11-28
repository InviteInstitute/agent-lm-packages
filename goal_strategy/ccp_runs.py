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


def duration_budgets(runs) -> "tuple[dict, float]":
    """OI-28 (2026-08-28): the wall-clock budget rule, in ONE place so
    every sweep uses the same one. Returns (session_median_ms,
    global_median_ms). A run's budget is its OBSERVED run_duration_ms;
    where that is missing the reviewer ruled: impute the SESSION median
    (falling back to the corpus median), flag it `duration_imputed`, and
    run no sensitivity sweep."""
    import statistics
    by_session: dict = {}
    for r in runs:
        if getattr(r, "run_duration_ms", None):
            by_session.setdefault(r.derived_session_id, []).append(
                float(r.run_duration_ms))
    session_median = {sid: statistics.median(v) for sid, v in by_session.items()}
    allv = [d for v in by_session.values() for d in v]
    return session_median, (statistics.median(allv) if allv else 0.0)


def budget_for(run, session_median: dict, global_median: float):
    """(seconds, imputed?) for one run — see duration_budgets."""
    if getattr(run, "run_duration_ms", None):
        return float(run.run_duration_ms) / 1000.0, False
    med = session_median.get(run.derived_session_id) or global_median
    return (med / 1000.0, True) if med else (None, False)
