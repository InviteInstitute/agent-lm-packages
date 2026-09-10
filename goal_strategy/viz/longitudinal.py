"""Longitudinal viz — per-run review over the ccp_run_dataset.

    python3 -m streamlit run viz/longitudinal.py
    (use the project python — the bare `streamlit` on PATH may resolve to an
    interpreter without this repo's dependencies)

Phase A (2026-08-24): student → session → run drilldown with a real-Blockly
code view, run-to-run diff, per-run facts (classification / flags /
telemetry), a flagged-run review queue (the OI-24 entry point), and an
embedded per-run walkthrough (absorb-over-time step 1 — viz/app.py remains
the dev-corpus tool until this one covers everything).

Phase B (2026-08-24): the stage-2 fidelity queue + per-run fidelity strip.
Phase C step 1 (2026-08-24): the RUNG REVIEW page (viz/rung_review.py, routed
from the sidebar) — OI-9's instrument: ladder provenance, distributions +
occupancy, improvement-over-time views, coverage↔weight correlation.
Remaining roadmap: creation-order overlays (OI-7), goal-evolution summaries
(Stage 3).
"""
from __future__ import annotations

from goal_strategy.paths import data_path

import sys
import html
from datetime import datetime, timezone
from pathlib import Path


import streamlit as st
# components.html is deprecation-marked (post-2026-06) in favor of st.iframe;
# kept for consistency with viz/app.py — migrate both together when the old
# app is absorbed.
from goal_strategy.viz.embed import render_html



FLAGS_OF_INTEREST = [
    "any flag", "execution_budget_exhausted", "nonfinite_numeric_clamped",
    "unmodeled_blocks", "sensor_reading_stale", "wait_until_unmet",
    "attachment_boundary_marginal", "evidence_post_sim_exit",
    "concurrent_stacks_unverified", "trigger_unfaithful", "fabricated_motion",
]
_QUEUE_FLAGS = set(FLAGS_OF_INTEREST) - {"any flag"}


@st.cache_resource(show_spinner="loading fidelity table…")
def _fidelity():
    """Stage-2 fidelity sweep results (stage2_fidelity.csv), keyed by run_id.
    Empty dict until the sweep has produced the file."""
    import csv
    path = data_path() / "ccp_run_dataset" / "stage2_fidelity.csv"
    if not path.exists():
        return {}
    with open(path) as fh:
        rows = list(csv.DictReader(fh))
    from goal_strategy.artifacts import validate_artifact
    try:
        validate_artifact(rows)
    except ValueError as exc:
        st.warning(str(exc))
        return {}
    return {r["run_id"]: r for r in rows}


@st.cache_resource(show_spinner="loading run dataset…")
def _index():
    import csv
    from collections import defaultdict
    from goal_strategy.ccp_runs import load_ccp_runs

    runs = load_ccp_runs()
    by_id = {r.run_id: r for r in runs}
    sessions = defaultdict(list)          # session -> runs in run_seq order
    students = defaultdict(list)          # student -> [session ids]
    for r in runs:
        sessions[r.derived_session_id].append(r)
    for sid, rs in sessions.items():
        students[rs[0].student_study_id].append(sid)
    for sid in students:
        students[sid].sort()

    sweep = {}
    sweep_path = data_path() / "ccp_run_dataset" / "stage1_dryrun.csv"
    if sweep_path.exists():
        with open(sweep_path) as fh:
            rows = list(csv.DictReader(fh))
        from goal_strategy.artifacts import validate_artifact
        try:
            validate_artifact(rows)
        except ValueError as exc:
            st.warning(str(exc))
            rows = []
        for row in rows:
            sweep[row["run_id"]] = {
                "classification": row["classification"],
                "flags": [f for f in (row["flags"] or "").split(";") if f],
            }
    return runs, by_id, dict(sessions), dict(students), sweep


def _flag_chips(flags):
    from goal_strategy.viz import data as vd
    group_of = {f: g for g, fl in vd.FLAG_GROUPS.items() for f in fl}
    colors = {"trust": "#b45309", "fabrication": "#b91c1c",
              "sensing": "#6d28d9", "scope": "#475569"}
    spans = "".join(
        f"<span style='background:{colors.get(group_of.get(f), '#475569')}22;"
        f"border:1px solid {colors.get(group_of.get(f), '#475569')};"
        f"border-radius:8px;padding:1px 7px;margin-right:5px;"
        f"font:11px monospace'>{html.escape(str(f))}</span>"
        for f in flags)
    return spans or "<span style='color:#888;font:11px monospace'>none</span>"


def _outline_rows(workspace_xml: str, run_id: str):
    """Indented text outline (old webapp readability + OI-14 reporter
    rendering) — parse only, no simulation."""
    from goal_strategy.detector.parsing.parse_blocks import parse_workspace
    from goal_strategy.viz import data as vd
    program = parse_workspace(workspace_xml or "", run_id)
    if program is None:
        return []
    rows = []
    for root in program.top_level_stacks:
        orphan = root not in program.event_handler_stacks
        hat_fields = vd._fields_summary(root)
        rows.append({"depth": 0, "text": f"▸ {vd._block_label(root.block_type)}"
                     + (f" {hat_fields}" if hat_fields else "")
                     + ("   [unattached]" if orphan else "")})
        sub: list = []
        vd._walk_rows(root.next, 1, sub, {})
        rows.extend({"depth": r["depth"],
                     "text": r["label"] + (f"  {r['fields']}" if r["fields"] else "")}
                    for r in sub)
    return rows


def _time_label(value):
    if isinstance(value, (int, float)):
        try:
            value = datetime.fromtimestamp(value, tz=timezone.utc)
        except (ValueError, OverflowError, OSError):
            return "time unavailable"
    return value.strftime("%H:%M:%S") if hasattr(value, "strftime") else "time unavailable"


def _duration(start, end):
    if start is None or end is None:
        return None
    difference = end - start
    return difference.total_seconds() if hasattr(difference, "total_seconds") else float(difference)


def main() -> None:
    st.set_page_config(page_title="Goal run review", layout="wide")
    try:
        runs, by_id, sessions, students, sweep = _index()
    except FileNotFoundError:
        st.title("Goal run review")
        st.info("No run dataset is configured. Set GOAL_STRATEGY_DATA_DIR to the directory containing ccp_run_dataset/ccp_runs.parquet and final_code_states.parquet, then restart the app.")
        return
    if not runs:
        st.info("No runs are available in this dataset.")
        return
    from goal_strategy.viz import data as vd
    from goal_strategy.viz.workspace import diff_runs, workspace_html

    # ── sidebar: view router + review queue + drilldown ──
    st.sidebar.title("longitudinal viz")
    with st.sidebar.expander("about / roadmap"):
        st.markdown(
            "**Phase A**: per-run code view, diff, flags, walkthrough — "
            "built for the OI-24 review.\n\n"
            "**Phase B**: fidelity queue + per-run fidelity strip "
            "(Stage-2 debugging loop, complete).\n\n"
            "**Phase C step 1**: the rung review page (OI-9 instrument). "
            "OI-20 battery thresholds are out of scope until a battery runs "
            "over this set.\n\n"
            "*Remaining*: creation-order overlays (OI-7), goal-evolution "
            "summaries (Stage 3).")

    # a page can't set another widget's key after it exists — cross-page
    # jumps write _pending_view, applied here before the radio builds;
    # ?view=… deep-links a view on first load
    if "_pending_view" in st.session_state:
        st.session_state["view"] = st.session_state.pop("_pending_view")
    elif "view" not in st.session_state and \
            st.query_params.get("view") in ("run review", "rung review"):
        st.session_state["view"] = st.query_params["view"]
    view = st.sidebar.radio("view", ["run review", "rung review"],
                            key="view", horizontal=True)
    if view == "rung review":
        from goal_strategy.viz import rung_review
        rung_review.render(by_id)
        return

    fid = _fidelity()
    if fid:
        st.sidebar.subheader("stage-2 fidelity queue")
        verdicts = ["UNATTRIBUTED", "all disagreements", "edge_zone_possible",
                    "edge_slip", "override", "stalled",
                    "sensor_uncertainty", "capped", "stopped"]
        fverd = st.sidebar.selectbox("verdict filter", verdicts, key="fverd")
        only307 = st.sidebar.checkbox("validation set (307) only", value=True,
                                      key="f307")
        def _want(row):
            if only307 and row["validation_307"] != "True":
                return False
            if fverd == "all disagreements":
                return row["verdict"] != "agree"
            return row["verdict"] == fverd
        queue = [(float(r["error_mm"] or r["gps_to_trajectory_mm"] or 0), rid)
                 for rid, r in fid.items() if _want(r)]
        queue.sort(reverse=True)
        st.sidebar.caption(f"{len(queue)} in queue (worst first)")
        fpick = st.sidebar.selectbox(
            "jump to fidelity case",
            ["—"] + [f"{rid}  ·  {err:.0f}mm" for err, rid in queue],
            key="fpick")
        if fpick != "—" and st.session_state.get("_last_fjump") != fpick:
            st.session_state["_last_fjump"] = fpick
            rid = fpick.split("  ·")[0]
            r = by_id[rid]
            st.session_state["student"] = r.student_study_id
            st.session_state["session"] = r.derived_session_id
            st.session_state["run_seq"] = r.run_seq
            st.rerun()
        st.sidebar.divider()

    st.sidebar.subheader("review queue")
    qflag = st.sidebar.selectbox("flag filter", FLAGS_OF_INTEREST, key="qflag")
    flagged = [(rid, s) for rid, s in sweep.items()
               if (s["flags"] if qflag == "any flag"
                   else [f for f in s["flags"] if f == qflag])
               and (qflag != "any flag" or set(s["flags"]) & _QUEUE_FLAGS)]
    flagged.sort()
    st.sidebar.caption(f"{len(flagged)} flagged runs")
    pick = st.sidebar.selectbox(
        "jump to flagged run", ["—"] + [rid for rid, _ in flagged], key="qpick")
    if pick != "—" and st.session_state.get("_last_jump") != pick:
        st.session_state["_last_jump"] = pick
        r = by_id[pick]
        st.session_state["student"] = r.student_study_id
        st.session_state["session"] = r.derived_session_id
        st.session_state["run_seq"] = r.run_seq
        st.rerun()

    st.sidebar.divider()
    st.sidebar.subheader("browse")
    student = st.sidebar.selectbox("student", sorted(students), key="student")
    sess_ids = students[student]
    session = st.sidebar.selectbox(
        "session", sess_ids, key="session",
        format_func=lambda s: f"{s.split('_')[-1]} · {sessions[s][0].date}"
        f" · {len(sessions[s])} runs"
        + (" · warm start" if sessions[s][0].starts_with_existing_code else ""))
    sess_runs = sessions[session]
    seqs = [r.run_seq for r in sess_runs]
    # Buttons render AFTER the slider, and Streamlit forbids touching a
    # widget's key once it exists in the current script run — so navigation
    # writes a PENDING jump + rerun, applied here before the slider builds.
    if "_pending_seq" in st.session_state:
        st.session_state["run_seq"] = st.session_state.pop("_pending_seq")
    if st.session_state.get("run_seq") not in seqs:
        st.session_state["run_seq"] = seqs[0]
    run_seq = st.sidebar.select_slider(
        "run", options=seqs, key="run_seq",
        format_func=lambda q: f"{q} · "
        f"{_time_label(sess_runs[seqs.index(q)].run_start_ts)}")
    idx = seqs.index(run_seq)
    c1, c2 = st.sidebar.columns(2)
    if c1.button("◀ prev", disabled=idx == 0):
        st.session_state["_pending_seq"] = seqs[idx - 1]
        st.rerun()
    if c2.button("next ▶", disabled=idx == len(seqs) - 1):
        st.session_state["_pending_seq"] = seqs[idx + 1]
        st.rerun()
    # telemetry hops: nearest earlier/later run in this session with a blob
    tel_seqs = [r.run_seq for r in sess_runs if r.playground_params]
    prev_tel = max((q for q in tel_seqs if q < run_seq), default=None)
    next_tel = min((q for q in tel_seqs if q > run_seq), default=None)
    c3, c4 = st.sidebar.columns(2)
    if c3.button("◀ prev tel", disabled=prev_tel is None,
                 help="previous run in this session WITH telemetry"):
        st.session_state["_pending_seq"] = prev_tel
        st.rerun()
    if c4.button("tel next ▶", disabled=next_tel is None,
                 help="next run in this session WITH telemetry"):
        st.session_state["_pending_seq"] = next_tel
        st.rerun()

    run = sess_runs[seqs.index(run_seq)]
    prev_run = sess_runs[seqs.index(run_seq) - 1] if run_seq != seqs[0] else None

    # ── main: per-run facts ──
    info = sweep.get(run.run_id, {"classification": "?", "flags": []})
    st.markdown(f"### {run.run_id}")
    cols = st.columns(5)
    cols[0].metric("run", f"{run.run_seq} / {seqs[-1]}")
    dur = _duration(run.run_start_ts, run.run_end_ts)
    cols[1].metric("duration", f"{dur:.1f}s" if dur is not None else "no end")
    p = run.playground_params
    cols[2].metric("weight cleared", f"{p['weight_cleared']}" if p else "no telemetry")
    cols[3].metric("gps final",
                   f"({p['gps_x_position']}, {p['gps_y_position']})" if p else "—")
    cols[4].metric("classification", info["classification"])
    st.markdown(_flag_chips(info["flags"]), unsafe_allow_html=True)

    frow = _fidelity().get(run.run_id)
    if frow:
        v = frow["verdict"]
        color = {"agree": "#16a34a", "UNATTRIBUTED": "#b91c1c"}.get(v, "#b45309")
        st.markdown(
            f"<div style='font:13px monospace;margin:4px 0'>"
            f"<span style='border:1.5px solid {color};color:{color};"
            f"border-radius:8px;padding:1px 8px'>fidelity: {v}</span>"
            f"&nbsp; sim_off={frow['sim_off']} gps_off={frow['gps_off']} "
            f"err={frow['error_mm'] or '—'}mm "
            f"gps→traj={frow['gps_to_trajectory_mm'] or '—'}mm"
            + (" · ⚠ edge zone (divergence possible)"
               if frow.get('edge_zone_traversed') == 'True' else '')
            + (" · validation-307" if frow["validation_307"] == "True" else "")
            + "</div>", unsafe_allow_html=True)

    # ── diff vs previous run (first run has no base — no overlay) ──
    diff = (diff_runs(prev_run.workspace_xml, run.workspace_xml or "")
            if prev_run is not None
            else {"added": {}, "removed": {}, "changed": {}})
    n_changes = sum(len(v) for v in diff.values())
    if prev_run is None:
        st.caption("first run of the session — no diff base")
    elif n_changes == 0:
        st.caption("code unchanged since previous run")
    else:
        with st.expander(f"diff vs run {prev_run.run_seq}: "
                         f"+{len(diff['added'])} added, "
                         f"−{len(diff['removed'])} removed, "
                         f"~{len(diff['changed'])} changed", expanded=False):
            for bid, (btype, fields) in sorted(diff["added"].items()):
                st.markdown(f"`+` **{vd._block_label(btype)}** "
                            f"{dict(fields) if fields else ''}")
            for bid, (btype, fields) in sorted(diff["removed"].items()):
                st.markdown(f"`−` ~~{vd._block_label(btype)}~~ "
                            f"{dict(fields) if fields else ''}")
            for bid, (old, new) in sorted(diff["changed"].items()):
                st.markdown(f"`~` **{vd._block_label(new[0])}**: "
                            f"{dict(old[1])} → {dict(new[1])}")

    # ── the code space (real Blockly; diff tints) ──
    render_html(
        workspace_html(run.workspace_xml,
                       added_ids=diff["added"].keys(),
                       changed_ids=diff["changed"].keys()),
        height=540, scrolling=False)

    with st.expander("text outline"):
        for row in _outline_rows(run.workspace_xml, run.run_id):
            st.markdown(f"<div style='font:12px monospace;white-space:pre'>"
                        f"{'  ' * row['depth']}{html.escape(row['text'])}</div>",
                        unsafe_allow_html=True)

    # ── embedded walkthrough (absorb-over-time step 1) ──
    if st.toggle("run walkthrough (simulate + profile this run)"):
        from goal_strategy.viz.walkthrough import walkthrough_html as wt_html
        payload = vd.walkthrough_payload(run.run_id, run.workspace_xml or "",
                                         run.playground_params)
        render_html(wt_html(payload), height=1150, scrolling=True)


if __name__ == "__main__":
    main()
