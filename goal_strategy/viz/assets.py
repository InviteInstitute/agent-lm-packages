"""Bundled Blockly media, embedded so standalone review HTML works offline."""
import base64
from importlib.resources import files

# Blockly appends /sprites.png. A URL fragment keeps that suffix out of the
# encoded image while preserving its native zoom controls without a server.
BLOCKLY_MEDIA = 'data:image/png;base64,' + base64.b64encode(
    files('goal_strategy.viz').joinpath('vendor', 'sprites.png').read_bytes()
).decode('ascii') + '#'
