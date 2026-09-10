"""Blockly workspace embed — adapted from the frozen project's
detection_v2/webapp/pages/session_evidence.py (_blockly_html), CARRY_FORWARD.md: adapt.
Requires network access for the Blockly CDN; degrades to an error banner without it.

Custom VEX block types (pg_*) are registered via vex_blocks.js — ported from
VEXVR-EventViewer/script.js (defineVexBlocks) — before the workspace XML is
parsed; without them domToWorkspace throws "Invalid block definition".
Types missing from the explicit list are stubbed by pre-scanning the parsed
XML (stubUnknownBlocks), so they render as generic labeled blocks instead of
crashing the embed.

The XML is embedded as a JSON string literal (not a JS template literal):
json.dumps handles every quoting/escaping case, and the "</" -> "<\\/" rewrite
keeps the parser from seeing a premature </script>.
"""
from __future__ import annotations

import json
from pathlib import Path
from importlib.resources import files
from .assets import BLOCKLY_MEDIA

# vex_blocks.js is the verbatim upstream copy; the corrections file overwrites
# parameter-carrying blocks with input_value sockets so authored values render
# (see vex_blocks_corrections.js header).
_BLOCKLY_JS = files("goal_strategy.viz").joinpath("vendor", "blockly_local.js").read_text()
_VEX_BLOCKS_JS = ((files("goal_strategy.viz") / "vex_blocks.js").read_text()
                  + "\n" + (files("goal_strategy.viz") / "vex_blocks_corrections.js").read_text())

_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    html, body { margin:0; padding:0; width:100%; height:100%; overflow:hidden; background:#f8f8f8; }
    #blocklyDiv { position:absolute; top:0; left:0; right:0; bottom:0; }
  </style>
  <script>__BLOCKLY_JS__</script>
</head>
<body>
  <div id="blocklyDiv"></div>
  <script>
__VEX_BLOCKS_JS__
    defineVexBlocks();
    defineVexBlockCorrections();
    const ws = Blockly.inject('blocklyDiv', {
      readOnly: true, media: __BLOCKLY_MEDIA__, sounds: false,
      scrollbars: true,
      zoom: { controls: true, wheel: true, startScale: 0.75 },
      theme: Blockly.Themes.Classic,
    });
    try {
      const dom = Blockly.utils.xml.textToDom(__WORKSPACE_XML_JSON__);
      stubUnknownBlocks(dom);
      Blockly.Xml.domToWorkspace(dom, ws);
      ws.scrollCenter();
    } catch(e) {
      document.body.textContent = 'XML parse error: ' + String(e);
    }
  </script>
</body>
</html>
"""


def blockly_html(workspace_xml: str) -> str:
    xml_json = json.dumps(workspace_xml).replace("</", "<\\/")
    return _TEMPLATE.replace("__BLOCKLY_MEDIA__", json.dumps(BLOCKLY_MEDIA)).replace("__BLOCKLY_JS__", _BLOCKLY_JS).replace("__VEX_BLOCKS_JS__", _VEX_BLOCKS_JS).replace(
        "__WORKSPACE_XML_JSON__", xml_json
    )
