"""Intermediate Representation (IR) dataclasses for Blockly block programs.

These dataclasses form a tree mirroring the Blockly XML structure:
  BlockProgram → top-level stacks of BlockNode trees
  BlockNode    → one block with fields, value inputs, body children, and a
                 pointer to the next sibling in sequence
  BlockField   → a named parameter value on a block

The IR is produced by parse_blocks.py and consumed by code_features.py,
simulation/simulate_path.py, and segmentation/segment_code.py.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .block_registry import (  # noqa: E402
    MOVEMENT_BLOCK_TYPES,
    DRIVE_BLOCK_TYPES,
    LOOP_BLOCK_TYPES,
    CONDITIONAL_BLOCK_TYPES,
    SENSOR_BLOCK_TYPES,
    MAGNET_BLOCK_TYPES,
    VARIABLE_BLOCK_TYPES,
    classify as _registry_classify,
)


@dataclass
class BlockField:
    """A named field (parameter) on a block.

    Examples:
        BlockField(name="DIRECTION", value="fwd")
        BlockField(name="NUM", value="700")
        BlockField(name="UNITS", value="mm")
    """

    name: str
    value: str


@dataclass
class BlockNode:
    """One Blockly block in the program tree.

    Attributes:
        block_type: VEX block type string, e.g. "pg_drivetrain_drive_for".
        block_id:   Blockly-assigned unique ID for this block.
        fields:     Inline parameter fields (name → value).
        values:     Reporter/value inputs, typically shadow blocks holding
                    a numeric or string literal that feeds a parameter slot.
        next:       The next block in the same sequence (sibling), or None.
        children:   Blocks nested inside statement bodies (loop body,
                    conditional branches, etc.).  Each entry is the *first*
                    block of that body stack.
        parent:     Parent BlockNode, or None for top-level stacks.
                    Populated by parse_blocks after tree construction.
    """

    block_type: str
    block_id: str
    # Additive (OI-23 procedures build, 2026-08-24): Blockly stores procedure
    # identity (proccode / proceduredefid) in a <mutation> element in a
    # foreign (xhtml) namespace, which the field/value walk never captured.
    # Plain attribute dict; None for blocks without one.
    mutation: dict | None = None
    # Additive (CROW-C117 fix, 2026-08-24): slot NAMES for statements and
    # value inputs. Positional children/values lose branch identity when an
    # earlier slot is empty (an else-only if_then_else put the else body at
    # children[0], and the simulator executed it as the if-branch).
    statements: dict = field(default_factory=dict)   # slot name -> body root
    value_slots: dict = field(default_factory=dict)  # slot name -> value node
    fields: list[BlockField] = field(default_factory=list)
    values: list[BlockNode] = field(default_factory=list)
    next: BlockNode | None = None
    children: list[BlockNode] = field(default_factory=list)
    parent: BlockNode | None = None

    # ------------------------------------------------------------------ #
    # Convenience accessors
    # ------------------------------------------------------------------ #

    def get_field(self, name: str) -> str | None:
        """Return the value of a named field, or None if not present."""
        for f in self.fields:
            if f.name == name:
                return f.value
        return None

    def iter_sequence(self) -> "BlockNodeIterator":
        """Yield this block and all subsequent siblings via .next links."""
        node: BlockNode | None = self
        while node is not None:
            yield node
            node = node.next

    def __repr__(self) -> str:  # pragma: no cover
        fields_str = ", ".join(f"{f.name}={f.value!r}" for f in self.fields)
        return f"BlockNode({self.block_type!r}[{fields_str}])"


# Type alias to help type checkers — iter_sequence yields BlockNode
BlockNodeIterator = "BlockNode"


# ------------------------------------------------------------------ #
# Block type classification helpers
# ------------------------------------------------------------------ #

EVENT_HANDLER_PREFIXES = ("pg_events_",)

# Block type sets are loaded from src/goal_strategy.detector/data/blocks.csv
# via block_registry.py.  To add or fix a block, edit the CSV — no code change needed.
# The names below are re-exported so that existing imports from this module continue
# to work unchanged.
__all__ = [
    "MOVEMENT_BLOCK_TYPES",
    "DRIVE_BLOCK_TYPES",
    "LOOP_BLOCK_TYPES",
    "CONDITIONAL_BLOCK_TYPES",
    "SENSOR_BLOCK_TYPES",
    "MAGNET_BLOCK_TYPES",
    "VARIABLE_BLOCK_TYPES",
    "classify_block",
]


def classify_block(block_type: str) -> str:
    """Return a coarse category string for a block type.

    Returns one of: 'event_handler', 'movement', 'loop', 'conditional',
    'sensor', 'magnet', 'variable', 'other'.

    Classification is driven by data/blocks.csv via block_registry.  The
    'event_handler' label is kept distinct from 'event' (hat blocks) for
    backward compatibility with downstream callers.
    """
    if any(block_type.startswith(p) for p in EVENT_HANDLER_PREFIXES):
        return "event_handler"
    cls = _registry_classify(block_type)
    # 'event' in the registry means hat/event-handler blocks — map to
    # 'event_handler' for backward compatibility if the prefix check missed it.
    if cls == "event":
        return "event_handler"
    return cls


@dataclass
class BlockProgram:
    """Top-level container for a parsed Blockly workspace.

    Attributes:
        program_id:              Unique identifier (e.g. student_study_id + session).
        variables:               Variable names declared in the <variables> section.
        top_level_stacks:        All top-level BlockNode roots (event handlers
                                 and orphans combined, in document order).
        event_handler_stacks:    Subset of top_level_stacks rooted at an event handler.
        orphan_stacks:           Subset not rooted at an event handler.
        total_block_count:       Total blocks across all stacks (set by parser).
        active_block_count:      Blocks reachable via event handlers.
        orphan_block_count:      Blocks in orphan stacks.
        raw_xml:                 Original XML string (for debugging).
    """

    program_id: str
    variables: list[str] = field(default_factory=list)
    top_level_stacks: list[BlockNode] = field(default_factory=list)
    event_handler_stacks: list[BlockNode] = field(default_factory=list)
    orphan_stacks: list[BlockNode] = field(default_factory=list)
    total_block_count: int = 0
    active_block_count: int = 0
    orphan_block_count: int = 0
    raw_xml: str = ""

    def iter_all_blocks(self) -> "BlockNode":
        """Yield every BlockNode in the program via depth-first traversal.

        Only traverses event_handler_stacks (active code).  Use
        iter_all_blocks_including_orphans() to include disconnected blocks.
        """
        definitions = {}
        for root in self.top_level_stacks:
            if root.block_type == "procedures_definition" and root.children:
                name = (root.children[0].mutation or {}).get("proccode")
                if name and root.next is not None:
                    definitions.setdefault(name, root.next)
        pending = list(reversed(self.event_handler_stacks))
        seen = set()
        while pending:
            node = pending.pop()
            if id(node) in seen:
                continue
            seen.add(id(node))
            yield node
            if node.next is not None:
                pending.append(node.next)
            pending.extend(reversed(node.values))
            pending.extend(reversed(node.children))
            if node.block_type == "procedures_call":
                body = definitions.get((node.mutation or {}).get("proccode"))
                if body is not None:
                    pending.append(body)

    def iter_all_blocks_including_orphans(self) -> "BlockNode":
        """Yield every BlockNode in the program including orphan stacks."""
        for root in self.top_level_stacks:
            yield from _dfs(root)


def _dfs(node: BlockNode):
    """Depth-first traversal of a BlockNode tree."""
    yield node
    for child in node.children:
        yield from _dfs(child)
    for value_node in node.values:
        yield from _dfs(value_node)
    if node.next is not None:
        yield from _dfs(node.next)
