"""The review viz (task 2 §B): streamlit shell over profile() + timeline().

Run:  streamlit run viz/app.py
Views: Walkthrough (step a program), Program summary (one screen, no
interaction), Cohort (program finder / rung calibration / OI-2 disagreement
queue). This layer renders — every value comes from the core package.
"""
from __future__ import annotations

from goal_strategy.paths import data_path

import json
import sys
from pathlib import Path

import pandas as pd
import streamlit as st
from goal_strategy.viz.embed import render_html


from goal_strategy.viz import data as vd
from goal_strategy.viz import plots as vp
from goal_strategy.viz.walkthrough import walkthrough_html

from goal_strategy.detector.parsing.parse_blocks import parse_workspace
from goal_strategy.detector.simulation.simulate_path import simulate_path
from goal_strategy.config import load_configs
from goal_strategy.profile import _profile
from goal_strategy.timeline import timeline_result



_TRIAGE_PATH = data_path() / "oi2_triage.json"
_DEFECT_CHOICES = ["", "OI-3 fabricated motion", "OI-5 eye trigger", "OI-6 bumper trigger",
                   "OI-7 concurrent stacks", "OI-8 unevaluable guard", "loop cap",
                   "other (note in OPEN_ISSUES)"]


@st.cache_data(show_spinner="loading corpus…")
def _corpus():
    return vd.load_corpus()


@st.cache_data(show_spinner="profiling cohort…")
def _cohort():
    return vd.cohort_table()


@st.cache_data(show_spinner=False)
def _payload(program_id: str, treatment: str):
    pid, xml, params = next(r for r in _corpus() if r[0] == program_id)
    return vd.walkthrough_payload(pid, xml, params, treatment=treatment)


def _triage_load() -> dict:
    if _TRIAGE_PATH.exists():
        return json.loads(_TRIAGE_PATH.read_text())
    return {}


def _open_in_walkthrough(program_id: str):
    st.session_state["program"] = program_id
    st.session_state["view"] = "Walkthrough"
    st.rerun()


def _select_program(container) -> str | None:
    ids = [r[0] for r in _corpus()]
    query = container.text_input("search programs",
                                 placeholder="substring of program id").strip().lower()
    if query:
        ids = [p for p in ids if query in p.lower()]
        if not ids:
            container.warning("no program id matches the search")
            return None
    label = f"program — {len(ids)} match{'es' if len(ids) != 1 else ''}"
    current = st.session_state.get("program")
    index = ids.index(current) if current in ids else 0
    return container.selectbox(label, ids, index=index, key="program_select")


# ---------------------------------------------------------------- View 1

def walkthrough():
    c1, c2 = st.columns([3, 1])
    program_id = _select_program(c1)
    if not program_id:
        return
    st.session_state["program"] = program_id
    _, xml, _params = next(r for r in _corpus() if r[0] == program_id)
    conditional = vd.is_conditional_hat_program(xml, program_id)
    treatment = c2.selectbox(
        "conditional-hat treatment (OI-1)",
        ["execute", "suppress", "abstain"],
        format_func={"execute": "B1 · execute (default)",
                     "suppress": "B2 · suppress",
                     "abstain": "B3 · abstain"}.get,
        disabled=not conditional,
        help="Only differs on the 9 conditional-hat programs; greyed elsewhere.")
    if not conditional:
        c2.caption("no conditional hats — treatments identical")
    render_html(walkthrough_html(_payload(program_id, treatment)),
                    height=1150, scrolling=True)


# ---------------------------------------------------------------- View 2

def summary():
    program_id = _select_program(st)
    if not program_id:
        return
    st.session_state["program"] = program_id
    pid, xml, params = next(r for r in _corpus() if r[0] == program_id)
    from goal_strategy.execution import prepare_execution
    execution = prepare_execution(xml, pid, params)
    cfg, full = execution.config, execution.context.full_sim
    prof = _profile(xml, pid, params, _execution=execution)
    tl = timeline_result(xml, pid, params, _execution=execution)

    left, right = st.columns([3, 2])
    if full is not None:
        gps = None
        spec = (cfg.card.get("outcome_metrics") or {}).get("final_gps_position") or {}
        gx, gy = params.get(spec.get("x_field")), params.get(spec.get("y_field"))
        if gx is not None and gy is not None:
            gps = (float(gx), float(gy))
        left.plotly_chart(
            vp.path_figure(cfg.context, full, events=tl.events,
                           exit_step=tl.boundary_exit_step,
                           fabricated_steps=full.fabricated_steps, gps_final=gps),
            width="stretch")
    else:
        left.info("no simulation — workspace XML failed to parse")

    rows = [{"goal": g.goal, "indicator": i.name, "kind": kind,
             "channel": i.channel, "value": i.value, "rung": i.rung,
             "flags": ";".join(i.flags), "abstain": i.abstain_reason}
            for g in prof.goals
            for kind, inds in (("intent", g.intent), ("attainment", g.attainment))
            for i in inds]
    right.subheader("goal profile")
    right.dataframe(pd.DataFrame(rows).astype({"value": "string"}), hide_index=True, width="stretch")
    right.metric("boundary exit step",
                 prof.boundary_exit_step if prof.boundary_exceeded else "none",
                 border=True)
    fidelity = (f"{prof.gps_final_error_mm:.0f}mm" if prof.gps_final_error_mm is not None
                else f"null — {prof.gps_final_error_reason}")
    right.metric("gps_final_error_mm (only comparable on-island)", fidelity, border=True)
    right.metric("off-island agreement",
                 {True: "agree", False: "DISAGREE", None: "n/a"}[prof.off_island_agreement],
                 border=True)

    st.subheader("events")
    ev_rows = [{"scope": scope, **{k: getattr(e, k) for k in
                ("step", "goal", "indicator", "kind", "from_rung", "to_rung", "value")},
                "flags": ";".join(e.flags)}
               for scope, evs in (("scored", tl.events), ("post-exit", tl.post_exit_events))
               for e in evs]
    st.dataframe(pd.DataFrame(ev_rows).astype({"value": "string"}) if ev_rows else pd.DataFrame(), hide_index=True, width="stretch")


# ---------------------------------------------------------------- View 3

def cohort():
    df = _cohort()
    catalog = vd.indicator_catalog()
    st.caption(f"config_version: {df.config_version.iloc[0]} · n={len(df)}")

    st.header("(a) Program finder")
    rung_cols = [c for c in df.columns if c.endswith("__rung")]
    c1, c2 = st.columns(2)
    rung_filter = {}
    col = c1.selectbox("filter by indicator rung", ["(none)"] + rung_cols)
    if col != "(none)":
        values = sorted(df[col].dropna().unique())
        chosen = c1.multiselect("rungs", values, default=values)
        rung_filter[col] = chosen
    flag_query = c2.text_input("filter by flag substring",
                               placeholder="e.g. stuck_zone, trigger_")
    view = df
    for column, allowed in rung_filter.items():
        view = view[view[column].isin(allowed)]
    if flag_query.strip():
        view = view[view["flags"].str.contains(flag_query.strip(), na=False)]
    st.dataframe(view[["program_id", "boundary_exceeded", "flags"] + rung_cols],
                 hide_index=True, width="stretch", height=280)
    pick = st.selectbox("open in walkthrough", ["(pick)"] + list(view.program_id))
    if pick != "(pick)":
        _open_in_walkthrough(pick)

    st.subheader("near cut points")
    delta_pct = st.slider("δ as % of observed range (old app default 5%)", 1, 20, 5)
    near_rows = []
    for ind in catalog:
        if not ind["edges"]:
            continue
        vcol = f"{ind['goal']}__{ind['name']}__value"
        if vcol not in df.columns:
            continue
        vals = pd.to_numeric(df[vcol], errors="coerce")
        span = float(vals.max() - vals.min()) or 1.0
        delta = delta_pct / 100.0 * span
        mask = vals.apply(lambda v: pd.notna(v)
                          and any(abs(v - e) <= delta for e in ind["edges"]))
        for _, row in df[mask].iterrows():
            near_rows.append({"program_id": row.program_id,
                              "indicator": f"{ind['goal']}·{ind['name']}",
                              "value": row[vcol],
                              "rung": row[f"{ind['goal']}__{ind['name']}__rung"],
                              "edges": ind["edges"]})
    st.dataframe(pd.DataFrame(near_rows), hide_index=True, width="stretch")

    st.header("(b) Rung calibration")
    for ind in catalog:
        if not ind["edges"]:
            continue
        vcol = f"{ind['goal']}__{ind['name']}__value"
        rcol = f"{ind['goal']}__{ind['name']}__rung"
        vals = pd.to_numeric(df[vcol], errors="coerce")
        ok = vals.notna()
        if not ok.any():
            continue
        st.subheader(f"{ind['goal']} · {ind['name']}  — edges {ind['edges']}")
        left, right = st.columns([3, 1])
        left.plotly_chart(vp.cohort_figure(
            vals[ok], df.program_id[ok],
            [f"rung: {r}" for r in df[rcol][ok]], ind["edges"]), width="stretch")
        right.dataframe(df[rcol].value_counts().rename("programs"), width="stretch")
        ecol = f"first_event_step__{ind['name']}"
        if ecol in df.columns and df[ecol].notna().any():
            right.caption("first event step distribution")
            right.bar_chart(df[ecol].dropna().astype(int).value_counts().sort_index())

    st.subheader("flag counts")
    flag_counts = (df["flags"].str.split(";").explode().replace("", pd.NA).dropna()
                   .value_counts())
    st.dataframe(flag_counts.rename("programs"), width="stretch")

    st.header("(c) Off-island disagreement queue — OI-2")
    dq = df[df.off_island_agreement == False].copy()  # noqa: E712
    dq["direction"] = dq.apply(
        lambda r: "under-detection (sim ON, gps OFF)" if not r.sim_final_off_island
        else "over-detection (sim OFF, gps ON)", axis=1)
    dq = dq.sort_values(["direction", "program_id"])
    triage = _triage_load()
    dq["attributed_to"] = [triage.get(p, "") for p in dq.program_id]
    attributed = sum(bool(v) for v in dq.attributed_to)
    st.caption(f"{len(dq)} disagreements · attributed {attributed} / {len(dq)}")
    edited = st.data_editor(
        dq[["program_id", "direction", "fabricated_motion",
            "boundary_exit_fabricated", "flags", "attributed_to"]],
        hide_index=True, width="stretch",
        column_config={"attributed_to": st.column_config.SelectboxColumn(
            "attributed to", options=_DEFECT_CHOICES)},
        disabled=["program_id", "direction", "fabricated_motion",
                  "boundary_exit_fabricated", "flags"])
    if st.button("save attributions"):
        merged = {**triage, **{r.program_id: r.attributed_to
                               for r in edited.itertuples() if r.attributed_to}}
        _TRIAGE_PATH.write_text(json.dumps(merged, indent=1, sort_keys=True))
        st.success(f"saved to {_TRIAGE_PATH.name}")
    pick2 = st.selectbox("open disagreement in walkthrough",
                         ["(pick)"] + list(dq.program_id))
    if pick2 != "(pick)":
        _open_in_walkthrough(pick2)


def main():
    st.set_page_config(page_title="Goal recognition review", layout="wide")
    st.sidebar.title("Goal recognition")
    pages = {"Walkthrough": walkthrough, "Program summary": summary, "Cohort": cohort}
    page = st.sidebar.radio("view", list(pages), key="view")
    try:
        if not _corpus():
            st.info("No programs are available in this dataset.")
            return
        pages[page]()
    except FileNotFoundError:
        st.title("Goal recognition review")
        st.info("No review dataset is configured. Set GOAL_STRATEGY_DATA_DIR to the directory containing final_code_states.parquet, then restart the app.")


if __name__ == "__main__":
    main()
