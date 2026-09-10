"""Read-only Blockly workspace component — the longitudinal tool's code view.

Renders a run's AS-RUN workspace XML as REAL Blockly blocks (the old
webapp's readability) using this repo's correctness assets (vex_blocks.js
definitions + corrections + the unknown-block auto-stub) on a VENDORED
Blockly 10.4.3 runtime (viz/vendor/blockly_local.js — no CDN, works
offline; the exact version the corrections were written against).

Diff overlay: pass the block-ids added/changed since the previous run and
they get colored outlines on the canvas (green = added, amber = changed).
Removed blocks aren't in the current workspace — the caller shows those in
its change list.
"""
from __future__ import annotations

import json
from pathlib import Path
from importlib.resources import files
from .assets import BLOCKLY_MEDIA

_HERE = files("goal_strategy.viz")
_BLOCKLY_JS = (_HERE / "vendor" / "blockly_local.js").read_text()
_VEX_BLOCKS_JS = (_HERE / "vex_blocks.js").read_text()
_VEX_CORRECTIONS_JS = (_HERE / "vex_blocks_corrections.js").read_text()

_TEMPLATE = """
<style>
  html, body { margin: 0; padding: 0; }
  #bkDiv { height: __HEIGHT__px; width: 100%; }
  .diff-added > .blocklyPath { stroke: #16a34a; stroke-width: 3px; }
  .diff-changed > .blocklyPath { stroke: #d97706; stroke-width: 3px; }
  #bkErr { color: #a33; font: 12px monospace; white-space: pre-wrap; }
</style>
<div id="bkDiv"></div>
<div id="bkErr"></div>
<script>__BLOCKLY_JS__</script>
<script>__VEX_BLOCKS_JS__</script>
<script>__VEX_CORRECTIONS_JS__</script>
<script>
try {
  defineVexBlocks();
  defineVexBlockCorrections();
  const ws = Blockly.inject("bkDiv", {
    readOnly: true, media: __BLOCKLY_MEDIA__, sounds: false, scrollbars: true, trashcan: false,
    zoom: {controls: true, wheel: true, startScale: 0.8, maxScale: 1.2},
    theme: Blockly.Themes.Classic,
  });
  const dom = Blockly.utils.xml.textToDom(__XML_JSON__);
  stubUnknownBlocks(dom);
  Blockly.Xml.domToWorkspace(dom, ws);
  ws.zoomToFit();
  const mark = (ids, cls) => ids.forEach(id => {
    const b = ws.getBlockById(id);
    if (b && b.getSvgRoot()) b.getSvgRoot().classList.add(cls);
  });
  mark(__ADDED_JSON__, "diff-added");
  mark(__CHANGED_JSON__, "diff-changed");
} catch (err) {
  document.getElementById("bkErr").textContent =
    "Blockly render failed: " + String(err).slice(0, 300);
}
</script>
"""


def workspace_html(workspace_xml: str,
                   added_ids=(), changed_ids=(),
                   height: int = 520) -> str:
    esc = lambda s: json.dumps(s).replace("</", "<\\/")
    return (_TEMPLATE
            .replace("__HEIGHT__", str(int(height)))
            .replace("__BLOCKLY_MEDIA__", json.dumps(BLOCKLY_MEDIA)).replace("__BLOCKLY_JS__", _BLOCKLY_JS)
            .replace("__VEX_BLOCKS_JS__", _VEX_BLOCKS_JS)
            .replace("__VEX_CORRECTIONS_JS__", _VEX_CORRECTIONS_JS)
            .replace("__XML_JSON__", esc(workspace_xml or "<xml></xml>"))
            .replace("__ADDED_JSON__", json.dumps(sorted(added_ids)))
            .replace("__CHANGED_JSON__", json.dumps(sorted(changed_ids))))


# ── run-to-run diff (pure; tested in tests/test_longitudinal.py) ──

def _block_signatures(workspace_xml: str) -> dict:
    """block_id -> (type, ((field_name, value), ...)) for every id-bearing
    block/shadow. Ids are stable across edits (the creation-order insight),
    so id-keyed comparison separates added / removed / changed cleanly."""
    import xml.etree.ElementTree as ET
    if not workspace_xml:
        return {}
    root = ET.fromstring(workspace_xml)
    out = {}
    for el in root.iter():
        tag = el.tag.rsplit("}", 1)[-1]
        if tag not in ("block", "shadow"):
            continue
        bid = el.get("id")
        if not bid:
            continue
        fields = []
        for child in el:
            if child.tag.rsplit("}", 1)[-1] == "field":
                fields.append((child.get("name") or "", child.text or ""))
        out[bid] = (el.get("type") or "", tuple(sorted(fields)))
    return out


def diff_runs(prev_xml: str, cur_xml: str) -> dict:
    """{'added': {id: sig}, 'removed': {id: sig}, 'changed': {id: (old, new)}}"""
    a, b = _block_signatures(prev_xml), _block_signatures(cur_xml)
    return {
        "added": {i: b[i] for i in b.keys() - a.keys()},
        "removed": {i: a[i] for i in a.keys() - b.keys()},
        "changed": {i: (a[i], b[i]) for i in a.keys() & b.keys() if a[i] != b[i]},
    }
