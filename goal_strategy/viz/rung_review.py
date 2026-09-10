"""Rung review page (OI-9 instrument) — population views over stage2_rungs.csv.

Pure aggregation helpers up top (unit-tested, no streamlit); `render()` at the
bottom is the Streamlit page, routed from viz/longitudinal.py. Never
reimplements an indicator, rung assignment, or threshold — rungs and values
come from the sweep CSV, card facts from data.indicator_catalog.
"""
from __future__ import annotations

from goal_strategy.paths import data_path

from pathlib import Path

import pandas as pd
import plotly.graph_objects as go

RUNGS_CSV = data_path() / "ccp_run_dataset" / "stage2_rungs.csv"


# ── pure helpers ──

def ladder_order(labels, direction, absent_label=None):
    """Rung labels in ascending-achievement order; absent_label below worst."""
    order = list(labels) if direction != "lower_is_better" else list(reversed(labels))
    if absent_label and absent_label not in order:
        order = [absent_label] + order
    return order


def rung_ranks(labels, direction, absent_label=None):
    """label -> achievement rank (0 = worst real rung; absent_label = -1)."""
    order = list(labels) if direction != "lower_is_better" else list(reversed(labels))
    ranks = {lab: i for i, lab in enumerate(order)}
    if absent_label:
        ranks.setdefault(absent_label, -1)
    return ranks


def occupancy(df: pd.DataFrame, base: str, labels, direction,
              absent_label=None) -> pd.DataFrame:
    """Rung counts + shares over df, in ascending-achievement order, with an
    (abstained) data-quality row for None rungs."""
    col = df[f"{base}__rung"]
    counts = col.value_counts(dropna=True)
    rows = [{"rung": lab, "runs": int(counts.get(lab, 0))}
            for lab in ladder_order(labels, direction, absent_label)]
    rows.append({"rung": "(abstained)", "runs": int(col.isna().sum())})
    total = len(df)
    for r in rows:
        r["share"] = f"{r['runs'] / total * 100:.1f}%" if total else "—"
    return pd.DataFrame(rows)


def near_edge(df: pd.DataFrame, base: str, edges, pct: float = 0.10):
    """Runs whose value lies within ±pct of any edge (a zero edge falls back
    to pct × the p10–p90 value spread — data-driven, no entity constants).
    Returns (table sorted by value, {edge: tolerance})."""
    vals = pd.to_numeric(df[f"{base}__value"], errors="coerce")
    spread = float(vals.quantile(0.9) - vals.quantile(0.1)) or 1.0
    mask = pd.Series(False, index=df.index)
    tols = {}
    for e in edges:
        tol = abs(e) * pct or pct * spread
        tols[e] = tol
        mask |= (vals - e).abs() <= tol
    out = df.loc[mask, ["run_id", "session", "run_seq",
                        f"{base}__value", f"{base}__rung"]].copy()
    out.columns = ["run_id", "session", "run_seq", "value", "rung"]
    return out.sort_values("value"), tols


def progress_occupancy(df: pd.DataFrame, base: str, labels, direction,
                       absent_label=None, n_bins: int = 10) -> pd.DataFrame:
    """Rung shares per within-session run-position bin (0 = session start,
    n_bins-1 = session end) — the population climbing the ladder as code
    improves. Sessions of any length contribute; a 1-run session lands in
    bin 0."""
    d = df.sort_values(["session", "run_seq"]).copy()
    grp = d.groupby("session")["run_seq"]
    frac = grp.cumcount() / (grp.transform("size") - 1).clip(lower=1)
    d["_bin"] = (frac * n_bins).astype(int).clip(upper=n_bins - 1)
    order = ladder_order(labels, direction, absent_label)
    rows = []
    for b in range(n_bins):
        sub = d.loc[d["_bin"] == b, f"{base}__rung"]
        n = len(sub)
        row = {"bin": b, "n": n}
        for lab in order:
            row[lab] = float((sub == lab).sum() / n) if n else 0.0
        row["(abstained)"] = float(sub.isna().sum() / n) if n else 0.0
        rows.append(row)
    return pd.DataFrame(rows)


def first_reach(df: pd.DataFrame, base: str, labels, direction,
                absent_label=None):
    """Per non-floor rung: fraction of sessions that have reached at least
    that rung by run k (k = 1..longest session). Sessions that never reach
    it hold the curve flat — 'later runs meet rungs earlier ones miss',
    made quantitative."""
    ranks = rung_ranks(labels, direction, absent_label)
    d = df.sort_values(["session", "run_seq"]).copy()
    d["_rank"] = d[f"{base}__rung"].map(ranks)
    d["_k"] = d.groupby("session").cumcount() + 1
    n_sessions = d["session"].nunique()
    max_k = int(d["_k"].max()) if len(d) else 0
    curves = {}
    for lab, rk in ranks.items():
        if rk <= 0:      # skip absent_label (-1) and the floor rung (trivially reached)
            continue
        reached = d[d["_rank"] >= rk].groupby("session")["_k"].min()
        curves[lab] = [float((reached <= k).sum() / n_sessions)
                       for k in range(1, max_k + 1)]
    return curves, max_k, n_sessions


def best_vs_final(df: pd.DataFrame, base: str, labels, direction,
                  absent_label=None) -> dict:
    """Sessions whose best rung (any run) beats their final-telemetry rung
    (the validation-307 row) — how much the 307 snapshot understates
    achievement for this ladder."""
    ranks = rung_ranks(labels, direction, absent_label)
    d = df.copy()
    d["_rank"] = d[f"{base}__rung"].map(ranks)
    best = d.groupby("session")["_rank"].max()
    fin = d[d["validation_307"]].set_index("session")["_rank"]
    joined = pd.DataFrame({"best": best, "final": fin}).dropna()
    reg = joined[joined["best"] > joined["final"]]
    return {"sessions": int(len(joined)), "regressed": int(len(reg)),
            "regressed_share": float(len(reg) / len(joined)) if len(joined) else 0.0}


def high_certainty_mask(df: pd.DataFrame, base: str,
                        verdicts: dict | None = None) -> pd.Series:
    """True where we are MOST CERTAIN of this ladder's value (reviewer ruling
    2026-08-25): the indicator carries no flags (sensor staleness, concurrent
    code, fabrication, nonfinite, …) and no abstention — and, when the run
    has telemetry, its fidelity verdict is `agree` (catches silent sim
    divergence that flags cannot see). Non-telemetry runs pass on flags
    alone: no verdict exists for them."""
    flags = df[f"{base}__flags"].fillna("").astype(str).str.strip() == ""
    no_abstain = df[f"{base}__abstain_reason"].fillna("").astype(str) == ""
    mask = flags & no_abstain
    if verdicts:
        agree = df["run_id"].map(verdicts).eq("agree")
        mask &= agree | ~df["has_params"]
    return mask


def coverage_weight(df: pd.DataFrame):
    """(scatter frame, spearman rho, coverage-decile median-weight overlay)
    over rows where both sim coverage and the real weight outcome exist."""
    d = pd.DataFrame({
        "coverage": pd.to_numeric(
            df["clear_debris_zone__debris_zone_coverage__value"], errors="coerce"),
        "weight": pd.to_numeric(
            df["clear_debris_zone__weight_cleared__value"], errors="coerce"),
        "run_id": df["run_id"], "cohort": df["cohort"],
    }).dropna(subset=["coverage", "weight"])
    # spearman = pearson on ranks (avoids the scipy dependency pandas'
    # method="spearman" pulls in)
    rho = float(d["coverage"].rank().corr(d["weight"].rank())) \
        if len(d) > 2 else float("nan")
    med = pd.DataFrame()
    if len(d) >= 20:
        dec = pd.qcut(d["coverage"].rank(method="first"), 10, labels=False)
        med = d.groupby(dec).agg(cov_mid=("coverage", "median"),
                                 wt_med=("weight", "median")).reset_index(drop=True)
    return d, rho, med


# ── streamlit page ──

def _strip_figure(vals, run_ids, hovers, edges, log_x=False):
    fig = go.Figure()
    ys = [(i % 24) / 24.0 for i in range(len(vals))]   # deterministic jitter
    fig.add_trace(go.Scatter(
        x=list(vals), y=ys, mode="markers",
        text=[f"{rid}<br>{h}" for rid, h in zip(run_ids, hovers)],
        hoverinfo="text", marker={"size": 6, "opacity": 0.55}))
    for e in edges or []:
        fig.add_vline(x=e, line={"color": "#c0392b", "dash": "dash", "width": 1})
        fig.add_annotation(x=e, y=1.06, yref="paper", text=f"{e:g}",
                           showarrow=False, font={"size": 10, "color": "#c0392b"})
    fig.update_layout(height=300, margin=dict(l=10, r=10, t=30, b=10),
                      xaxis={"title": "value", "type": "log" if log_x else "linear"},
                      yaxis={"visible": False}, showlegend=False)
    return fig


def render(by_id) -> None:
    import streamlit as st
    from goal_strategy.viz import data as vd
    @st.cache_data(show_spinner="loading rung sweep…")
    def _rungs():
        path = data_path("ccp_run_dataset", "stage2_rungs.csv")
        if not path.exists():
            return None
        frame = pd.read_csv(path)
        from goal_strategy.artifacts import validate_artifact
        try:
            validate_artifact(frame.to_dict("records"))
        except ValueError as exc:
            st.warning(str(exc))
            return None
        return frame

    @st.cache_data(show_spinner=False)
    def _verdicts():
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
        return {r["run_id"]: r["verdict"] for r in rows}

    df = _rungs()
    if df is None:
        st.warning("no rung sweep on disk — run "
                   "`python -m goal_strategy.rung_sweep --out "
                   "data/ccp_run_dataset/stage2_rungs.csv`")
        return
    catalog = vd.indicator_catalog()

    # ── page controls ──
    st.sidebar.subheader("population")
    pop = st.sidebar.radio(
        "distribution population", ["validation-307", "telemetry runs", "all runs"],
        index=0, key="rr_pop",
        help="occupancy tables always show validation-307 next to the "
             "all-telemetry backdrop; this picks the strip-plot population. "
             "improvement-over-time views always use ALL runs (whole "
             "sessions — the telemetry-MNAR caveat applies to any "
             "telemetry-conditioned view).")
    cohorts = st.sidebar.multiselect("cohorts", sorted(df["cohort"].unique()),
                                     default=[], key="rr_cohorts",
                                     help="empty = pooled (the ruled default)")
    hc_only = st.sidebar.checkbox(
        "high-certainty only", value=True, key="rr_hc",
        help="per ladder (reviewer ruling 2026-08-25): keep only runs whose "
             "indicator carries no flags (sensor staleness, concurrent code, "
             "fabrication, nonfinite, …), no abstention, and — when the run "
             "has telemetry — an `agree` fidelity verdict. The coverage↔"
             "weight scatter applies the coverage ladder's mask.")
    no_overlap = st.sidebar.checkbox(
        "exclude dev-corpus-overlap runs", key="rr_noovl",
        help="calibration was tuned on the dev corpus; excluding its verbatim "
             "matches shows the uncontaminated population")

    base_df = df
    if cohorts:
        base_df = base_df[base_df["cohort"].isin(cohorts)]
    if no_overlap:
        base_df = base_df[~base_df["dev_corpus_overlap"]]
    verdicts = _verdicts()

    st.markdown("## rung review — OI-9")
    st.caption(f"{len(base_df)} runs in scope · "
               f"{int(base_df['has_params'].sum())} with telemetry · "
               f"{int(base_df['validation_307'].sum())} validation-307 · "
               f"config {df['config_version'].iloc[0]}")

    # ── overview: every ladder at a glance ──
    over = [{"ladder": f"{c['goal']} · {c['name']}",
             "provenance": "design" if c["design_informed"] else
             ("exact" if (c["provenance"] or "").startswith("exact")
              else "abstract"),
             "edges": ", ".join(f"{e:g}" for e in c["edges"]) or "categorical",
             "labels": " → ".join(c["labels"]),
             "channel": base_df[f"{c['goal']}__{c['name']}__channel"]
             .mode().iat[0] if len(base_df) else "—"}
            for c in catalog]
    st.dataframe(pd.DataFrame(over), hide_index=True, width="stretch")

    # ── per-ladder detail ──
    names = [f"{c['goal']}__{c['name']}" for c in catalog]
    sel = st.selectbox("ladder", names, key="rr_ladder")
    cat = catalog[names.index(sel)]
    base = sel
    labels, direction = cat["labels"], cat["direction"]
    absent = cat["absent_label"]
    edges = cat["edges"]

    # the certainty mask is per-ladder — apply it here, after selection
    scoped = base_df
    if hc_only:
        scoped = base_df[high_certainty_mask(base_df, base, verdicts)]
        st.caption(f"high-certainty filter: {len(scoped)} of {len(base_df)} "
                   f"runs kept for this ladder "
                   f"({len(base_df) - len(scoped)} excluded as uncertain)")
    tele = scoped[scoped["has_params"]]
    v307 = scoped[scoped["validation_307"]]
    pop_df = {"validation-307": v307, "telemetry runs": tele,
              "all runs": scoped}[pop]

    badge = ("#1d4ed8", "design-informed") if cat["design_informed"] else \
        (("#475569", "exact") if (cat["provenance"] or "").startswith("exact")
         else ("#b45309", "abstract"))
    st.markdown(
        f"<div style='font:13px monospace;margin:6px 0'>"
        f"<span style='border:1.5px solid {badge[0]};color:{badge[0]};"
        f"border-radius:8px;padding:1px 8px'>{badge[1]}</span>"
        f"&nbsp; {cat['rung_kind']} · {direction or 'categorical'}"
        + (f" · reference: {cat['reference']}" if cat["reference"] else "")
        + (f" · absent → {absent}" if absent else "")
        + "</div>", unsafe_allow_html=True)
    if cat["provenance"]:
        st.caption(f"card provenance: {cat['provenance']}")
    for fr in cat["flag_rules"]:
        st.caption(f"flag rule: {fr['flag']} when rung in {fr['when_rung_in']} "
                   f"and {fr['other_indicator']} in {fr['other_rung_in']}")

    # B · distribution + occupancy
    vals = pd.to_numeric(pop_df[f"{base}__value"], errors="coerce")
    numeric = cat["rung_kind"] == "numeric" and vals.notna().any()
    left, right = st.columns([3, 2])
    if numeric:
        keep = vals.notna()
        left.plotly_chart(_strip_figure(
            vals[keep], pop_df.loc[keep, "run_id"],
            pop_df.loc[keep, f"{base}__rung"].fillna("(abstained)"),
            edges), width="stretch")
    else:
        vc = pop_df[f"{base}__rung"].fillna("(abstained)").value_counts()
        if vc.empty:
            left.info("No runs match the selected population and filters.")
        else:
            left.bar_chart(vc)
    occ7 = occupancy(v307, base, labels, direction, absent)
    occt = occupancy(tele, base, labels, direction, absent)
    merged = occ7.merge(occt, on="rung", suffixes=(" (307)", " (telemetry)"))
    right.dataframe(merged, hide_index=True, width="stretch")

    if numeric and edges:
        ne, tols = near_edge(pop_df, base, edges)
        with st.expander(f"near-edge runs (±10%): {len(ne)}"):
            st.caption("tolerances: " + ", ".join(
                f"{e:g}±{t:g}" for e, t in tols.items()))
            st.dataframe(ne, hide_index=True, width="stretch")
            jump = st.selectbox("open in run review", ["—"] + list(ne["run_id"]),
                                key="rr_jump")
            if jump != "—" and st.session_state.get("_last_rrjump") != jump:
                st.session_state["_last_rrjump"] = jump
                r = by_id[jump]
                st.session_state["_pending_view"] = "run review"
                st.session_state["student"] = r.student_study_id
                st.session_state["session"] = r.derived_session_id
                st.session_state["_pending_seq"] = r.run_seq
                st.rerun()

    # C · improvement over time (always ALL runs — whole sessions)
    st.markdown("#### improvement over time")
    time_df = scoped
    order = ladder_order(labels, direction, absent)
    po = progress_occupancy(time_df, base, labels, direction, absent)
    fig = go.Figure()
    for lab in order + ["(abstained)"]:
        fig.add_trace(go.Bar(x=po["bin"], y=po[lab], name=lab))
    fig.update_layout(barmode="stack", height=300,
                      margin=dict(l=10, r=10, t=10, b=10),
                      xaxis={"title": "within-session run position (decile)"},
                      yaxis={"title": "share", "range": [0, 1]},
                      legend={"font": {"size": 10}})
    c1, c2 = st.columns(2)
    c1.caption("rung occupancy vs session progress")
    c1.plotly_chart(fig, width="stretch")
    curves, max_k, n_sess = first_reach(time_df, base, labels, direction, absent)
    fig2 = go.Figure()
    for lab, ys in curves.items():
        fig2.add_trace(go.Scatter(x=list(range(1, max_k + 1)), y=ys,
                                  mode="lines", name=lab))
    fig2.update_layout(height=300, margin=dict(l=10, r=10, t=10, b=10),
                       xaxis={"title": f"run index within session (of {n_sess} sessions)"},
                       yaxis={"title": "fraction reached", "range": [0, 1]},
                       legend={"font": {"size": 10}})
    c2.caption("first-reach curves: sessions having reached each rung by run k")
    c2.plotly_chart(fig2, width="stretch")
    bf = best_vs_final(time_df, base, labels, direction, absent)
    st.caption(
        f"best-vs-final: {bf['regressed']} of {bf['sessions']} sessions "
        f"({bf['regressed_share'] * 100:.1f}%) ended their last telemetry run "
        f"BELOW their session-best rung — the amount the 307 snapshot "
        f"understates achievement on this ladder")

    # E · memo scaffold
    with st.expander("memo scaffold (keep / move edge / restructure)"):
        st.markdown(
            f"- provenance: **{badge[1]}**"
            + (f" — {cat['provenance']}" if cat["provenance"] else "") + "\n"
            f"- edges: `{edges}`; occupancy (307): "
            + ", ".join(f"{r.rung} {r.runs}" for r in occ7.itertuples()) + "\n"
            f"- best-vs-final regression: {bf['regressed_share'] * 100:.1f}% "
            f"of sessions\n"
            f"- decision: keep / move edge / restructure — reviewer ruling, "
            f"recorded in FINDINGS; edge changes are card changes "
            f"(config_version bump)")

    # D · coverage ↔ weight_cleared
    st.divider()
    st.markdown("#### debris-zone coverage ↔ weight cleared")
    cov_cat = next(c for c in catalog if c["name"] == "debris_zone_coverage")
    cov_base = f"{cov_cat['goal']}__{cov_cat['name']}"
    cov_edges = cov_cat["edges"]
    wt_edges = next(c["edges"] for c in catalog if c["name"] == "weight_cleared")
    # the scatter always uses the COVERAGE ladder's certainty mask,
    # whichever ladder is selected above
    sc_src = base_df[base_df["has_params"]]
    if hc_only:
        sc_src = sc_src[high_certainty_mask(sc_src, cov_base, verdicts)]
        st.caption(f"coverage high-certainty mask: {len(sc_src)} of "
                   f"{int(base_df['has_params'].sum())} telemetry runs kept")
    sc, rho, med = coverage_weight(sc_src)
    fig3 = go.Figure()
    for cohort, sub in sc.groupby("cohort"):
        fig3.add_trace(go.Scatter(x=sub["coverage"], y=sub["weight"],
                                  mode="markers", name=cohort,
                                  text=sub["run_id"], hoverinfo="text",
                                  marker={"size": 6, "opacity": 0.5}))
    if len(med):
        fig3.add_trace(go.Scatter(x=med["cov_mid"], y=med["wt_med"],
                                  mode="lines+markers", name="decile median",
                                  line={"color": "#111", "width": 2}))
    for e in cov_edges:
        fig3.add_vline(x=e, line={"color": "#c0392b", "dash": "dash", "width": 1})
    for e in wt_edges:
        fig3.add_hline(y=e, line={"color": "#2563eb", "dash": "dash", "width": 1})
    fig3.update_layout(height=420, margin=dict(l=10, r=10, t=10, b=10),
                       xaxis={"title": "sim debris_zone coverage fraction"},
                       yaxis={"title": "weight_cleared (kg)"},
                       legend={"font": {"size": 10}})
    st.plotly_chart(fig3, width="stretch")
    st.caption(
        f"spearman ρ = {rho:.3f} over {len(sc)} runs with both signals · "
        f"edge lines: coverage {'/'.join(f'{e:g}' for e in cov_edges)} (red), "
        f"weight {'/'.join(f'{e:g}' for e in wt_edges)} (blue)")
    from goal_strategy.config import load_configs
    caveat = (load_configs("castle_crashers").card.get("regions", {})
              .get("debris_zone", {}).get("coverage_fraction_caveat"))
    if caveat:
        st.caption(f"card caveat: {caveat}")
