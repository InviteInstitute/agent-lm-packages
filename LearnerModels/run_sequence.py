"""Walks a student's events in order and builds the per-run edit-distance sequence
that every trigger reads off of.

Only runProject events count here. Each run after the first gets its distance against
the run before it. The very first run has nothing to compare to, so its distance is
None.

Public API:
    compute_run_edit_distances(events) -> {
        "runs": [{"index": int, "edit_distance": int|None, "ts": float|None,
                  "playground": str|None}, ...]
    }

`events` is a time-ordered list of dicts, each with at least
    {"event_type": "...", "content": {...parsed VEX log content...}, "ts": float|None}
"""
import json

from .ast_builder import xml_to_block_ast, extract_workspace_xml
from .distance import cached_edit_distance


def _extract_runs(events):
    """For each runProject event, in order, grab the workspace XML, parse it into a
    block AST, read which playground it was, and keep all that next to the event's
    timestamp."""
    runs = []
    for ev in events:
        if ev.get("event_type") != "runProject":
            continue
        content = ev.get("content") or {}
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except json.JSONDecodeError:
                content = {}
        xml = extract_workspace_xml(content)
        playground = content.get("playground")
        runs.append((xml, xml_to_block_ast(xml), ev.get("ts"), playground))
    return runs


def compute_run_edit_distances(events):
    """Return {"runs": [{"index", "edit_distance", "ts", "playground"}]}. distance is
    None for the first run overall and also for the first run after a playground
    switch, because diffing code across two different challenges wouldn't mean
    anything. If a run is missing its playground, it's treated as continuing the
    current one instead of starting a fresh stretch."""
    runs = _extract_runs(events)
    out = []
    prev_pg = None
    for i, (xml, ast, ts, playground) in enumerate(runs):
        pg = playground if playground is not None else prev_pg
        if i == 0 or pg != prev_pg:
            dist = None
        else:
            prev_xml, prev_ast, _, _ = runs[i - 1]
            dist = cached_edit_distance(prev_xml, xml, prev_ast, ast)
        out.append({"index": i, "edit_distance": dist, "ts": ts, "playground": pg})
        prev_pg = pg
    return {"runs": out}
