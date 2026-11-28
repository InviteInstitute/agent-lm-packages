"""Block classification registry loaded from the VEX VR blocks CSV.

This module is the single source of truth for which block_name values belong
to each functional category.  To add support for a new block — whether from a
new VEX VR version, a playground-specific variant, or a newly observed
alternate name — add a row to:

    goal_strategy/detector/data/blocks.csv

No code changes are required.

Classification values used in the CSV:
    movement    – drivetrain movement blocks
    loop        – repeat / forever / while / repeat-until
    conditional – if / if-else / if-else-if-else
    sensor      – sensing blocks that return a value or boolean
    variable    – variable assignment / mutation blocks
    magnet      – electromagnet control blocks
    event       – hat blocks (start a stack); this set IS the parser's HAT_BLOCK_TYPES
    drawing     – pen / fill blocks
    console     – print / cursor blocks
    timer       – timer reset / read blocks
    operator    – math / comparison / string operator blocks
    procedure   – My Blocks (function definitions)
    switch      – hybrid Switch/Python blocks
    other       – everything else (wait, break, stop-project, comments, etc.)
"""

from __future__ import annotations

import csv
from importlib.resources import files

_CSV_PATH = files("goal_strategy.detector").joinpath("data", "blocks.csv")


def _load() -> tuple[dict[str, frozenset[str]], dict[str, str]]:
    """Parse blocks.csv and return (classification_map, simulator_status_map).

    classification_map:   classification → frozenset of block_name strings
    simulator_status_map: block_name → simulator_status ("handled"/"ignored"/…)
    """
    cls_groups: dict[str, list[str]] = {}
    status_map: dict[str, str] = {}

    with _CSV_PATH.open("r", newline="", encoding="utf-8") as fh:
        for row in csv.DictReader(fh):
            block_name = row.get("block_name", "").strip()
            classification = row.get("classification", "").strip()
            simulator_status = (row.get("simulator_status") or "").strip()

            if not block_name or not classification:
                continue

            cls_groups.setdefault(classification, []).append(block_name)

            if simulator_status:
                status_map[block_name] = simulator_status

    return {cls: frozenset(names) for cls, names in cls_groups.items()}, status_map


_classification_map, _simulator_status_map = _load()


def simulator_status(block_name: str) -> str:
    """The simulator_status recorded in blocks.csv, or 'unknown' if absent.

    The fidelity signal for "does the simulator actually execute this block".
    Values in the CSV today: handled / ignored / partial
    variants; a block type missing from the CSV entirely is 'unknown'.
    """
    return _simulator_status_map.get(block_name, "unknown")

MAGNET_BLOCK_TYPES: frozenset[str] = _classification_map.get("magnet", frozenset())


def classify(block_name: str) -> str:
    """Return the classification string for a block_name, or 'other' if not in registry."""
    for cls, names in _classification_map.items():
        if block_name in names:
            return cls
    return "other"
