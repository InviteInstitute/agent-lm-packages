"""Plotly figures for the review viz.

Adapted from VEX_model_tracing/src/vex_model_tracing/viz/plots.py: the
NodeResult coupling, the node-specific overlay, and the stringified band_edges
parsing are gone — figures take explicit arguments. No thresholds and no
playground entity names live here; geometry and edges arrive from the caller.
"""
from __future__ import annotations

import math

import plotly.graph_objects as go


def _circle(x: float, y: float, r: float, name: str, color: str, dash: str = "dot"):
    theta = [i * 2 * math.pi / 72 for i in range(73)]
    return go.Scatter(
        x=[x + r * math.cos(t) for t in theta],
        y=[y + r * math.sin(t) for t in theta],
        mode="lines", name=name, line={"color": color, "width": 1, "dash": dash},
        hoverinfo="name",
    )


def path_figure(context, sim_result, events=None, exit_step=None,
                fabricated_steps=(), gps_final=None) -> go.Figure:
    """The playground with the simulated path.

    context: PlaygroundContext; sim_result: SimulationResult (full path).
    events: GoalEvents to annotate. exit_step: grey the path after it.
    fabricated_steps: step indices drawn as open diamonds. gps_final: (x, y)
    real final GPS, drawn with a connector to the simulated final position.
    """
    fig = go.Figure()
    ctx = context

    if getattr(ctx, "field_hex_vertices", None):
        vx = [v[0] for v in ctx.field_hex_vertices] + [ctx.field_hex_vertices[0][0]]
        vy = [v[1] for v in ctx.field_hex_vertices] + [ctx.field_hex_vertices[0][1]]
        fig.add_trace(go.Scatter(x=vx, y=vy, mode="lines", name="field boundary",
                                 line={"color": "#888", "width": 1}))

    for rid, r in (ctx.regions or {}).items():
        fig.add_shape(type="rect", x0=r.x_min, x1=r.x_max, y0=r.y_min, y1=r.y_max,
                      line={"color": "rgba(46,134,193,0.8)", "width": 1},
                      fillcolor="rgba(46,134,193,0.08)")
        fig.add_annotation(x=r.x_min, y=r.y_max, text=rid, showarrow=False,
                           font={"size": 10, "color": "#2e86c1"}, xanchor="left")

    for oid, obj in (ctx.objects or {}).items():
        fig.add_trace(go.Scatter(x=[obj.x], y=[obj.y], mode="markers+text", name=oid,
                                 text=[oid], textposition="top center",
                                 marker={"size": 9, "symbol": "x", "color": "#c0392b"}))
        if getattr(obj, "tolerance", 0):
            fig.add_trace(_circle(obj.x, obj.y, obj.tolerance,
                                  f"{oid} tolerance ({obj.tolerance:.0f}mm)", "#c0392b"))

    fig.add_trace(go.Scatter(x=[ctx.spawn_x], y=[ctx.spawn_y], mode="markers",
                             name="spawn", marker={"size": 10, "symbol": "star",
                                                   "color": "#27ae60"}))

    path = sim_result.path
    if path:
        cut = len(path) if exit_step is None else exit_step + 1
        xs = [sim_result.origin_x] + [p.x for p in path[:cut]]
        ys = [sim_result.origin_y] + [p.y for p in path[:cut]]
        hover = ["origin"] + [f"step {p.step} · {p.block_type} · {p.block_id}"
                              for p in path[:cut]]
        fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines+markers", name="path",
                                 text=hover, hoverinfo="text",
                                 line={"color": "#34495e", "width": 2},
                                 marker={"size": 5, "color": list(range(len(xs))),
                                         "colorscale": "Viridis", "showscale": False}))
        if cut < len(path):
            xs2 = [path[cut - 1].x] + [p.x for p in path[cut:]]
            ys2 = [path[cut - 1].y] + [p.y for p in path[cut:]]
            fig.add_trace(go.Scatter(
                x=xs2, y=ys2, mode="lines+markers", name="post-exit (fiction)",
                text=[f"step {p.step} · {p.block_type} · POST-EXIT"
                      for p in path[cut - 1:]], hoverinfo="text",
                line={"color": "#bbb", "width": 1, "dash": "dot"},
                marker={"size": 4, "color": "#ccc"}))

        fab = [p for p in path if p.step in set(fabricated_steps)]
        if fab:
            fig.add_trace(go.Scatter(
                x=[p.x for p in fab], y=[p.y for p in fab], mode="markers",
                name="fabricated step (invented distance)",
                text=[f"step {p.step} · {p.block_type} · FABRICATED" for p in fab],
                hoverinfo="text",
                marker={"size": 10, "symbol": "diamond-open",
                        "color": "#e67e22", "line": {"width": 2}}))

    for ev in events or []:
        if ev.step < 0 or ev.step >= len(path):
            continue
        ps = path[ev.step]
        fig.add_trace(go.Scatter(
            x=[ps.x], y=[ps.y], mode="markers",
            name=f"{ev.goal}: {ev.to_rung} (step {ev.step})",
            marker={"size": 13, "symbol": "circle-open", "line": {"width": 3},
                    "color": "#c0392b" if ev.kind == "failure" else "#8e44ad"}))

    if gps_final is not None:
        fx = sim_result.final_x
        fy = sim_result.final_y
        fig.add_trace(go.Scatter(x=[gps_final[0]], y=[gps_final[1]], mode="markers",
                                 name="real final GPS",
                                 marker={"size": 12, "symbol": "star-diamond",
                                         "color": "#16a085"}))
        fig.add_trace(go.Scatter(x=[fx, gps_final[0]], y=[fy, gps_final[1]],
                                 mode="lines", name="sim vs real final",
                                 line={"color": "#16a085", "width": 1, "dash": "dash"},
                                 hoverinfo="name"))

    fig.update_layout(height=560, margin=dict(l=10, r=10, t=10, b=10),
                      yaxis_scaleanchor="x", legend={"font": {"size": 10}})
    return fig


def band_strip(value: float, edges: list[float], axis: str = "") -> go.Figure | None:
    """A continuous value positioned against its rung edges."""
    if not edges or value is None:
        return None
    val = float(value)
    lo = min([val] + list(edges))
    hi = max([val] + list(edges))
    pad = 0.15 * (hi - lo or 1.0)
    fig = go.Figure()
    for e in edges:
        fig.add_vline(x=e, line={"color": "#c0392b", "dash": "dash", "width": 1})
        fig.add_annotation(x=e, y=1.2, text=f"{e:g}", showarrow=False, font={"size": 10})
    fig.add_trace(go.Scatter(x=[val], y=[1], mode="markers+text",
                             text=[f"{val:g}"], textposition="bottom center",
                             marker={"size": 14, "color": "#2e86c1"}, name="this program"))
    fig.update_layout(height=120, margin=dict(l=10, r=10, t=10, b=10),
                      xaxis={"range": [lo - pad, hi + pad], "title": axis},
                      yaxis={"visible": False}, showlegend=False)
    return fig


def cohort_figure(values, program_ids, hover_labels, edges) -> go.Figure:
    """Strip plot of a continuous value across the cohort, edges as cut lines."""
    fig = go.Figure()
    # deterministic jitter for visibility (no randomness — BUG-14 lesson)
    ys = [(i % 20) / 20.0 for i in range(len(values))]
    fig.add_trace(go.Scatter(
        x=list(values), y=ys, mode="markers",
        text=[f"{pid}<br>{lbl}" for pid, lbl in zip(program_ids, hover_labels)],
        hoverinfo="text", marker={"size": 8, "opacity": 0.75}, name="programs"))
    for e in edges or []:
        fig.add_vline(x=e, line={"color": "#c0392b", "dash": "dash", "width": 1})
        fig.add_annotation(x=e, y=1.06, yref="paper", text=f"{e:g}", showarrow=False,
                           font={"size": 10, "color": "#c0392b"})
    fig.update_layout(height=320, margin=dict(l=10, r=10, t=30, b=10),
                      xaxis={"title": "value"}, yaxis={"visible": False},
                      showlegend=False)
    return fig
