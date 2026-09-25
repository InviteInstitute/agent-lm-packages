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
    RunDistanceStream().push(event) -> the same run dicts, one event at a time, for a
        live host that would otherwise recompute the whole session on every new run.

`events` is a time-ordered list of dicts, each with at least
    {"event_type": "...", "content": {...parsed VEX log content...}, "ts": float|None}
"""
import json

from .ast_builder import xml_to_block_ast, extract_workspace_xml
from .distance import edit_distance_for, xml_digest


def _content_of(ev):
    content = ev.get("content") or {}
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except json.JSONDecodeError:
            content = {}
    return content


class RunDistanceStream:
    """The incremental form of compute_run_edit_distances. Push events in order;
    each runProject appends one run dict to .runs and returns it, anything else
    returns None. Pushing a session's events one by one gives exactly the runs the
    batch call gives for the same events.

    Only the previous run's XML is kept, so each push costs the same however long
    the session gets. A workspace is parsed into an AST only when its distance is
    actually computed (not for identical re-runs or pairs already in the cache).
    """

    def __init__(self):
        self.runs = []
        self._prev = None  # (xml, digest, lazy ast, playground) of the last run

    def push(self, ev):
        if ev.get("event_type") != "runProject":
            return None
        content = _content_of(ev)
        xml = extract_workspace_xml(content)
        playground = content.get("playground")
        i = len(self.runs)
        prev_pg = self._prev[3] if self._prev else None
        pg = playground if playground is not None else prev_pg
        digest = xml_digest(xml)
        ast = _LazyAst(xml)
        if i == 0 or pg != prev_pg:
            dist = None
        else:
            prev_xml, prev_digest, prev_ast, _ = self._prev
            dist = edit_distance_for(prev_xml, xml, prev_ast, ast,
                                     prev_digest=prev_digest, curr_digest=digest)
        run = {"index": i, "edit_distance": dist, "ts": ev.get("ts"), "playground": pg}
        self.runs.append(run)
        self._prev = (xml, digest, ast, pg)
        return run


class _LazyAst:
    """A workspace AST built on first use and kept after that."""

    def __init__(self, xml):
        self._xml = xml
        self._ast = None

    def __call__(self):
        if self._ast is None:
            self._ast = xml_to_block_ast(self._xml)
        return self._ast


def compute_run_edit_distances(events):
    """Return {"runs": [{"index", "edit_distance", "ts", "playground"}]}. distance is
    None for the first run overall and also for the first run after a playground
    switch, because diffing code across two different challenges wouldn't mean
    anything. If a run is missing its playground, it's treated as continuing the
    current one instead of starting a fresh stretch."""
    stream = RunDistanceStream()
    for ev in events:
        stream.push(ev)
    return {"runs": stream.runs}
