"""Block classification registry loaded from the VEX VR blocks CSV.

This module is the single source of truth for which block_name values belong
to each functional category.  To add support for a new block — whether from a
new VEX VR version, a playground-specific variant, or a newly observed
alternate name — add a row to:

    src/goal_strategy.detector/data/blocks.csv

No code changes are required.

Classification values used in the CSV:
    movement    – drivetrain movement blocks
    loop        – repeat / forever / while / repeat-until
    conditional – if / if-else / if-else-if-else
    sensor      – sensing blocks that return a value or boolean
    variable    – variable assignment / mutation blocks
    magnet      – electromagnet control blocks
    event       – event-handler hat blocks
    drawing     – pen / fill blocks
    console     – print / cursor blocks
    timer       – timer reset / read blocks
    operator    – math / comparison / string operator blocks
    procedure   – My Blocks (function definitions)
    switch      – hybrid Switch/Python blocks
    other       – everything else (wait, break, stop-project, comments, etc.)

The xml_fields column (semicolon-separated) documents the XML field names that
carry parameter values for a block.  It is informational for now; code_features.py
still reads fields directly.  Future work can use get_xml_fields() to drive
extraction automatically.
"""

from __future__ import annotations

import csv
from importlib.resources import files

_CSV_PATH = files("goal_strategy.detector").joinpath("data", "blocks.csv")


def _load() -> tuple[dict[str, frozenset[str]], dict[str, list[str]], dict[str, str], dict[str, str]]:
    """Parse blocks.csv and return (classification_map, xml_fields_map, display_name_map,
    simulator_status_map).

    classification_map:   classification → frozenset of block_name strings
    xml_fields_map:       block_name → list of XML field name strings
    display_name_map:     block_name → human-readable "Block Name", lowercased
    simulator_status_map: block_name → simulator_status ("handled"/"ignored"/…)
                          [stage 0b, additive — fidelity propagation]
    """
    cls_groups: dict[str, list[str]] = {}
    fields_map: dict[str, list[str]] = {}
    display_map: dict[str, str] = {}
    status_map: dict[str, str] = {}

    with _CSV_PATH.open("r", newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            block_name = row.get("block_name", "").strip()
            classification = row.get("classification", "").strip()
            xml_fields_raw = row.get("xml_fields", "").strip()
            display_name = (row.get("Block Name") or "").strip().lower()
            simulator_status = (row.get("simulator_status") or "").strip()

            if not block_name or not classification:
                continue

            cls_groups.setdefault(classification, []).append(block_name)

            if display_name:
                display_map[block_name] = display_name

            if simulator_status:
                status_map[block_name] = simulator_status

            if xml_fields_raw:
                fields_map[block_name] = [
                    f.strip() for f in xml_fields_raw.split(";") if f.strip()
                ]

    return (
        {cls: frozenset(names) for cls, names in cls_groups.items()},
        fields_map,
        display_map,
        status_map,
    )


_classification_map, _xml_fields_map, _display_name_map, _simulator_status_map = _load()


def simulator_status(block_name: str) -> str:
    """The simulator_status recorded in blocks.csv, or 'unknown' if absent.

    Stage 0b (additive): the fidelity signal for "does the simulator actually
    execute this block". Values in the CSV today: handled / ignored / partial
    variants; a block type missing from the CSV entirely is 'unknown'.
    """
    return _simulator_status_map.get(block_name, "unknown")

# ---------------------------------------------------------------------------
# Public sets — drop-in replacements for the hardcoded sets in block_program.py
# ---------------------------------------------------------------------------

MOVEMENT_BLOCK_TYPES: frozenset[str] = _classification_map.get("movement", frozenset())
LOOP_BLOCK_TYPES: frozenset[str] = _classification_map.get("loop", frozenset())
CONDITIONAL_BLOCK_TYPES: frozenset[str] = _classification_map.get("conditional", frozenset())
SENSOR_BLOCK_TYPES: frozenset[str] = _classification_map.get("sensor", frozenset())
MAGNET_BLOCK_TYPES: frozenset[str] = _classification_map.get("magnet", frozenset())
VARIABLE_BLOCK_TYPES: frozenset[str] = _classification_map.get("variable", frozenset())

# --- Movement sub-sets -----------------------------------------------------
# The `movement` classification covers EVERY drivetrain block — turns, stop,
# and configuration blocks (set drive/turn velocity, heading, rotation, timeout)
# as well as the blocks that actually translate the robot.  Counting all of them
# together is rarely what an indicator means by "how far did the student drive".
#
# DRIVE_BLOCK_TYPES narrows `movement` to the translation blocks, identified by
# their human-readable Block Name in blocks.csv ("drive", "drive for").  A new
# drive variant added to the CSV under a name starting with "drive" is picked up
# automatically; no code change is needed.
DRIVE_BLOCK_TYPES: frozenset[str] = frozenset(
    bt for bt in MOVEMENT_BLOCK_TYPES
    if _display_name_map.get(bt, "").startswith("drive")
)

# TURN_BLOCK_TYPES narrows `movement` to the blocks that REORIENT the robot,
# identified the same way: a Block Name starting with "turn".  That is
# "turn", "turn for", "turn to heading", "turn to rotation" — and it correctly
# excludes "set drive heading", which relabels the gyro without moving.
#
# It exists because three ad-hoc, mutually inconsistent turn sets had grown up
# in code_features.py: `turn_angles` counted only `turn_for`, the drive/turn
# symbol sequence counted `turn_for`/`turn_to*`/`turn`, and `_turn_inside_loop`
# counted `turn_for`/`turn_to_heading`/`set_heading`.  Each answered a different
# question by accident rather than by design.
TURN_BLOCK_TYPES: frozenset[str] = frozenset(
    bt for bt in MOVEMENT_BLOCK_TYPES
    if _display_name_map.get(bt, "").startswith("turn")
)

# Additional sets available for future feature work
EVENT_BLOCK_TYPES: frozenset[str] = _classification_map.get("event", frozenset())
DRAWING_BLOCK_TYPES: frozenset[str] = _classification_map.get("drawing", frozenset())
CONSOLE_BLOCK_TYPES: frozenset[str] = _classification_map.get("console", frozenset())
OPERATOR_BLOCK_TYPES: frozenset[str] = _classification_map.get("operator", frozenset())
PROCEDURE_BLOCK_TYPES: frozenset[str] = _classification_map.get("procedure", frozenset())
SWITCH_BLOCK_TYPES: frozenset[str] = _classification_map.get("switch", frozenset())


def get_xml_fields(block_name: str) -> list[str]:
    """Return the XML field names for a block, or an empty list if unknown."""
    return _xml_fields_map.get(block_name, [])


def classify(block_name: str) -> str:
    """Return the classification string for a block_name, or 'other' if not in registry."""
    for cls, names in _classification_map.items():
        if block_name in names:
            return cls
    return "other"
