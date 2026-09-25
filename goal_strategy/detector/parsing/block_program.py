"""Intermediate Representation (IR) dataclasses for Blockly block programs.

These dataclasses form a tree mirroring the Blockly XML structure:
  BlockProgram → top-level stacks of BlockNode trees
  BlockNode    → one block with fields, value inputs, body children, and a
                 pointer to the next sibling in sequence
  BlockField   → a named parameter value on a block

The IR is produced by parse_blocks.py and consumed by simulation/simulate_path.py
and the goal_strategy evidence layers (codefacts, testcases, rubric_evidence).
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
    EVENT_BLOCK_TYPES,
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

# Hat blocks: the only top-level blocks that start a program. This is exactly
# the registry's `event` class. It is an explicit list on purpose: a prefix test
# like "pg_events_" also matches broadcast / broadcast-and-wait, which are
# ordinary stack blocks, and made a detached broadcast stack run as live code.
HAT_BLOCK_TYPES: frozenset[str] = EVENT_BLOCK_TYPES

# Block type sets are loaded from detector/data/blocks.csv via block_registry.py.
# To add or fix a block, edit the CSV - no code change needed. The names below
# are re-exported so that existing imports from this module continue to work
# unchanged.
__all__ = [
    "HAT_BLOCK_TYPES",
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

    Returns 'event_handler' for hat blocks (HAT_BLOCK_TYPES), otherwise the
    registry classification ('movement', 'loop', 'conditional', 'sensor',
    'magnet', 'variable', ..., or 'other'). The 'event_handler' label is kept
    distinct from the registry's 'event' for backward compatibility with
    downstream callers.
    """
    if block_type in HAT_BLOCK_TYPES:
        return "event_handler"
    return _registry_classify(block_type)


PROCEDURE_DEFINITION = "procedures_definition"
PROCEDURE_CALL = "procedures_call"


def procedure_name(node: BlockNode) -> str | None:
    """The proccode a My Block definition declares or a call invokes, or None.

    A call carries it on its own <mutation>; a definition carries it on the
    mutation of its procedures_prototype shadow (the definition's statement
    child)."""
    if node.block_type == PROCEDURE_CALL:
        return (node.mutation or {}).get("proccode") or None
    if node.block_type == PROCEDURE_DEFINITION:
        for child in node.children:
            code = (child.mutation or {}).get("proccode")
            if code:
                return code
    return None


@dataclass
class BlockProgram:
    """Top-level container for a parsed Blockly workspace.

    Liveness: a top-level stack is live when VEX can execute it - it is rooted
    at an (enabled) hat block, or it is a My Block definition that live code
    calls (directly or through other called definitions). Everything else is an
    orphan. Disabled blocks are removed at parse time (see parse_blocks), so
    they never appear in any stack.

    Attributes:
        program_id:              Unique identifier (e.g. student_study_id + session).
        variables:               Variable names declared in the <variables> section.
        top_level_stacks:        All top-level BlockNode roots (event handlers,
                                 procedure definitions and orphans combined, in
                                 document order).
        event_handler_stacks:    Subset of top_level_stacks rooted at a hat block.
                                 These are the stacks that start threads.
        procedure_stacks:        My Block definitions that live code calls. Their
                                 bodies execute inline at each call site; they
                                 never start a thread of their own.
        orphan_stacks:           Everything else: detached stacks and uncalled
                                 definitions.
        total_block_count:       Total blocks across all stacks (set by parser).
        active_block_count:      Blocks in event handler and called procedure stacks.
        orphan_block_count:      Blocks in orphan stacks.
        disabled_block_count:    Blocks dropped because they (or an ancestor
                                 that owns them) were disabled.
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
    procedure_stacks: list[BlockNode] = field(default_factory=list)
    disabled_block_count: int = 0

    @property
    def live_stacks(self) -> list[BlockNode]:
        """Every stack whose blocks can execute: hat stacks, then called
        procedure definitions. Walk this (not event_handler_stacks) for any
        question about "the code that runs"."""
        return self.event_handler_stacks + self.procedure_stacks

    def iter_all_blocks(self) -> "BlockNode":
        """Yield every BlockNode in the program via depth-first traversal.

        Only traverses live_stacks (active code, including called procedure
        bodies).  Use iter_all_blocks_including_orphans() to include
        disconnected blocks.
        """
        for root in self.live_stacks:
            yield from _dfs(root)

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
