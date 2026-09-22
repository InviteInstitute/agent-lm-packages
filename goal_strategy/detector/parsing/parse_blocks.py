"""Parse Blockly workspace XML into a BlockProgram IR.

VENDORING STATUS — no longer byte-identical to VEX_model_tracing (OI-14 fix,
reviewer-authorised 2026-08-18): the <value> branch now prefers a connected
<block> over the obscured <shadow> default, per Blockly convention. This is the
only divergence in this file.

The Blockly XML schema uses namespace https://developers.google.com/blockly/xml.
All tag lookups require the fully-qualified name, e.g. ``{ns}block``.

Key XML element types handled:
  <block type="..." id="...">   — a single block node
  <next>                        — contains the next sibling block in sequence
  <statement name="...">        — contains a body stack (loop/conditional body)
  <value name="...">            — contains a reporter/shadow block input
  <field name="...">text</field> — a named parameter value
  <shadow type="...">           — literal value block (treated same as block)
  <variables><variable>...</variable></variables> — declared variables

Building on the pattern in learner_model_pipeline/src/preprocess_events.py
(_count_workspace_blocks) for namespace handling.
"""

from __future__ import annotations

import copy
import xml.etree.ElementTree as ET
from typing import Optional

from .block_program import BlockField, BlockNode, BlockProgram, classify_block

_NS = "https://developers.google.com/blockly/xml"
_B = f"{{{_NS}}}"   # namespace prefix shorthand

# Tag constants
_TAG_XML = f"{_B}xml"
_TAG_BLOCK = f"{_B}block"
_TAG_SHADOW = f"{_B}shadow"
_TAG_NEXT = f"{_B}next"
_TAG_STATEMENT = f"{_B}statement"
_TAG_VALUE = f"{_B}value"
_TAG_FIELD = f"{_B}field"
_TAG_VARIABLES = f"{_B}variables"
_TAG_VARIABLE = f"{_B}variable"


def parse_workspace(xml_str: str, program_id: str) -> Optional[BlockProgram]:
    """Parse a Blockly workspace XML string into a BlockProgram.

    Args:
        xml_str:    Raw workspace XML string.
        program_id: Unique identifier for this program (e.g. student+session key).

    Returns:
        A populated BlockProgram, or None if xml_str is empty/unparseable.
    """
    if not xml_str or not xml_str.strip():
        return None

    try:
        root = ET.fromstring(xml_str)
    except ET.ParseError:
        return None

    # ------------------------------------------------------------------ #
    # 1. Extract declared variables
    # ------------------------------------------------------------------ #
    variables: list[str] = []
    vars_el = root.find(_TAG_VARIABLES)
    if vars_el is not None:
        for var_el in vars_el.findall(_TAG_VARIABLE):
            name = (var_el.text or "").strip()
            if name:
                variables.append(name)

    # ------------------------------------------------------------------ #
    # 2. Parse top-level block stacks
    # ------------------------------------------------------------------ #
    top_level_stacks: list[BlockNode] = []
    event_handler_stacks: list[BlockNode] = []
    orphan_stacks: list[BlockNode] = []
    total = active = orphan = 0

    for block_el in root.findall(_TAG_BLOCK):
        node = _parse_block_el(block_el, parent=None)
        if node is None:
            continue
        top_level_stacks.append(node)
        stack_count = _count_nodes(node)
        total += stack_count

        if classify_block(node.block_type) == "event_handler":
            event_handler_stacks.append(node)
            active += stack_count
        else:
            orphan_stacks.append(node)
            orphan += stack_count

    return BlockProgram(
        program_id=program_id,
        variables=variables,
        top_level_stacks=top_level_stacks,
        event_handler_stacks=event_handler_stacks,
        orphan_stacks=orphan_stacks,
        total_block_count=total,
        active_block_count=active,
        orphan_block_count=orphan,
        raw_xml=xml_str,
    )


# ------------------------------------------------------------------ #
# Internal helpers
# ------------------------------------------------------------------ #

def _parse_block_el(
    el: ET.Element,
    parent: Optional[BlockNode],
) -> Optional[BlockNode]:
    """Recursively parse a <block> or <shadow> element into a BlockNode."""
    block_type = el.get("type", "")
    block_id = el.get("id", "")
    if not block_type:
        return None

    node = BlockNode(
        block_type=block_type,
        block_id=block_id,
        parent=parent,
    )

    for child_el in el:
        tag = child_el.tag

        if tag == _TAG_FIELD:
            name = child_el.get("name", "")
            value = (child_el.text or "").strip()
            node.fields.append(BlockField(name=name, value=value))

        elif tag.endswith("}mutation") or tag == "mutation":
            # Additive (OI-23 procedures build, 2026-08-24): procedure
            # identity (proccode) lives in a <mutation> element in a foreign
            # xhtml namespace — captured verbatim as an attribute dict.
            node.mutation = dict(child_el.attrib)

        elif tag == _TAG_NEXT:
            # Next sibling in sequence — exactly one <block> or <shadow>
            for sub in child_el:
                if sub.tag in (_TAG_BLOCK, _TAG_SHADOW):
                    node.next = _parse_block_el(sub, parent=node.parent)
                    break

        elif tag == _TAG_STATEMENT:
            # Body of a loop or conditional — one root block in the body.
            # The slot NAME is recorded too (CROW-C117 fix, 2026-08-24):
            # branch identity must survive empty earlier slots.
            for sub in child_el:
                if sub.tag in (_TAG_BLOCK, _TAG_SHADOW):
                    body_root = _parse_block_el(sub, parent=node)
                    if body_root is not None:
                        node.children.append(body_root)
                        node.statements[child_el.get("name", "")] = body_root
                    break

        elif tag == _TAG_VALUE:
            # Reporter/value input. Blockly convention (OI-14 fix, 2026-08-18):
            # when a real block is connected over a slot's editable default, the
            # XML retains BOTH the obscured <shadow> and the <block> — the
            # <block> is the active input and must win. Taking the first child
            # regardless of tag captured the stale shadow literal and silently
            # dropped the student's block (5 corpus programs, 15 slots).
            chosen = None
            for sub in child_el:
                if sub.tag == _TAG_BLOCK:
                    chosen = sub
                    break
                if sub.tag == _TAG_SHADOW and chosen is None:
                    chosen = sub
            if chosen is not None:
                value_node = _parse_block_el(chosen, parent=node)
                if value_node is not None:
                    node.values.append(value_node)
                    node.value_slots[child_el.get("name", "")] = value_node

        elif tag in (_TAG_BLOCK, _TAG_SHADOW):
            # Inline block (unusual but handle gracefully)
            inline = _parse_block_el(child_el, parent=node)
            if inline is not None:
                node.values.append(inline)

    return node


def _count_nodes(node: Optional[BlockNode]) -> int:
    """Count total BlockNodes reachable from node (sequence + tree)."""
    if node is None:
        return 0
    count = 1
    for child in node.children:
        count += _count_nodes(child)
    for value_node in node.values:
        count += _count_nodes(value_node)
    count += _count_nodes(node.next)
    return count


def linearize(program: BlockProgram, include_orphans: bool = False) -> list[BlockNode]:
    """Return a flat execution-order list of blocks in the program.

    Iterates event handler stacks in document order.  Within each stack,
    performs a pre-order traversal: emit the block, recurse into children
    (body stacks), then continue to next sibling.  Value/reporter inputs
    are NOT included (they are parameters, not executable statements).

    Args:
        program:         Parsed BlockProgram.
        include_orphans: If True, also include orphan stacks at the end.

    Returns:
        List of BlockNode in approximate execution order.
    """
    result: list[BlockNode] = []
    stacks = program.event_handler_stacks
    if include_orphans:
        stacks = program.top_level_stacks

    for root in stacks:
        _linearize_stack(root, result)
    return result


def _linearize_stack(node: Optional[BlockNode], out: list[BlockNode]) -> None:
    """Recursive pre-order linearization helper."""
    if node is None:
        return
    out.append(node)
    for child in node.children:
        _linearize_stack(child, out)
    _linearize_stack(node.next, out)


def block_program_slice(
    program: BlockProgram,
    block_ids: list[str],
) -> BlockProgram:
    """Build a BlockProgram containing only the blocks in block_ids.

    The returned BlockProgram preserves the original nesting structure, restricted
    to the selected blocks: a selected loop keeps the selected blocks of its body
    as ``children``, and siblings at each level are chained via ``next``.  Blocks
    that were not selected are skipped, and any selected descendants of a skipped
    block are spliced into the nearest surviving level so nothing is lost.

    Every selected block therefore appears EXACTLY ONCE in linearize(), while the
    structural features that walk ``children`` — has_nested_loops,
    sensor_inside_loop, has_turn_in_loop, nesting_depth, and the drive/turn symbol
    sequence — continue to see real nesting.

    An earlier implementation flattened the segment into a chain of ``next``
    pointers built from ``copy.copy`` nodes.  Because those shallow copies kept
    their original ``children``, linearize() (pre-order: emit, recurse children,
    then next) walked loop and conditional bodies twice — once via children and
    again via the flat chain — and pulled in body blocks the caller had
    deliberately excluded.  That inflated every code feature on ~20% of segments,
    by up to 5x.

    Args:
        program:   The original full BlockProgram.
        block_ids: IDs to include.  Execution order is taken from the original
                   tree, not from the order of this list.

    Returns:
        A new BlockProgram containing only the selected blocks.
    """
    selected = set(block_ids)
    if not selected:
        return BlockProgram(
            program_id=program.program_id,
            variables=program.variables,
        )

    def _rebuild(node: Optional[BlockNode]) -> Optional[BlockNode]:
        """Copy one sibling chain, keeping only selected blocks."""
        head: Optional[BlockNode] = None
        tail: Optional[BlockNode] = None

        def _append(first: BlockNode) -> None:
            nonlocal head, tail
            if tail is None:
                head = first
            else:
                tail.next = first
            last = first
            while last.next is not None:
                last = last.next
            tail = last

        current = node
        while current is not None:
            original_next = current.next
            if current.block_id in selected:
                kept = copy.copy(current)
                kept.parent = None
                kept.next = None
                kept.children = [
                    branch
                    for branch in (_rebuild(child) for child in current.children)
                    if branch is not None
                ]
                _append(kept)
            else:
                # Not selected: preserve any selected descendants by splicing
                # them into this level rather than dropping them.
                for child in current.children:
                    branch = _rebuild(child)
                    if branch is not None:
                        _append(branch)
            current = original_next

        return head

    roots = [
        root
        for root in (_rebuild(stack) for stack in program.event_handler_stacks)
        if root is not None
    ]
    if not roots:
        return BlockProgram(
            program_id=program.program_id,
            variables=program.variables,
        )

    total = sum(1 for _ in _iter_slice_blocks(roots))

    return BlockProgram(
        program_id=program.program_id,
        variables=program.variables,
        top_level_stacks=roots,
        event_handler_stacks=roots,
        orphan_stacks=[],
        total_block_count=total,
        active_block_count=total,
        orphan_block_count=0,
        raw_xml="",
    )


def _iter_slice_blocks(roots: list[BlockNode]):
    """Yield every node reachable from these stacks, each exactly once."""
    for root in roots:
        node = root
        while node is not None:
            yield node
            for child in node.children:
                yield from _iter_slice_blocks([child])
            node = node.next
