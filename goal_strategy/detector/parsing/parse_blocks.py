"""Parse Blockly workspace XML into a BlockProgram IR.

VENDORING STATUS — no longer byte-identical to VEX_model_tracing:
  * OI-14 fix (reviewer-authorised 2026-08-18): the <value> branch prefers a
    connected <block> over the obscured <shadow> default, per Blockly convention.
  * Liveness: hats are the explicit HAT_BLOCK_TYPES set (not a "pg_events_"
    prefix, which also caught broadcast blocks), called My Block definitions are
    live (procedure_stacks), and disabled blocks are dropped at parse time.

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

import xml.etree.ElementTree as ET
from typing import Optional

from .block_program import (
    PROCEDURE_CALL,
    PROCEDURE_DEFINITION,
    BlockField,
    BlockNode,
    BlockProgram,
    _dfs,
    classify_block,
    procedure_name,
)

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
    # Each stack is parsed as it executes (disabled blocks dropped) to decide
    # liveness. A stack that turns out to be an orphan is re-parsed as
    # authored, disabled blocks included: nothing in it runs either way, and
    # the orphan view should show what is actually on the canvas.
    executed: list[tuple[ET.Element, Optional[BlockNode], int]] = []
    for block_el in root.findall(_TAG_BLOCK):
        dropped = [0]
        node = _parse_block_el(block_el, parent=None, disabled=dropped)
        executed.append((block_el, node, dropped[0]))

    # ------------------------------------------------------------------ #
    # 3. Liveness: hat stacks, then the My Block definitions they call
    # ------------------------------------------------------------------ #
    event_handler_stacks, procedure_stacks, _ = _split_live(
        [node for _, node, _ in executed if node is not None])
    live_ids = {id(n) for n in event_handler_stacks + procedure_stacks}
    top_level_stacks: list[BlockNode] = []
    orphan_stacks: list[BlockNode] = []
    disabled_count = 0
    for block_el, node, dropped in executed:
        if node is not None and id(node) in live_ids:
            disabled_count += dropped
        else:
            node = _parse_block_el(block_el, parent=None)
            if node is None:
                continue
            orphan_stacks.append(node)
        top_level_stacks.append(node)
    active = sum(_count_nodes(n) for n in event_handler_stacks + procedure_stacks)
    orphan = sum(_count_nodes(n) for n in orphan_stacks)

    return BlockProgram(
        program_id=program_id,
        variables=variables,
        top_level_stacks=top_level_stacks,
        event_handler_stacks=event_handler_stacks,
        procedure_stacks=procedure_stacks,
        orphan_stacks=orphan_stacks,
        total_block_count=active + orphan,
        active_block_count=active,
        orphan_block_count=orphan,
        disabled_block_count=disabled_count,
        raw_xml=xml_str,
    )


def _split_live(stacks: list[BlockNode]) -> tuple[list, list, list]:
    """Partition top-level stacks into (hat stacks, called procedure
    definitions, orphans), each in document order.

    A definition is live when a call to its proccode is reachable from a hat
    stack, directly or through other called definitions. When a proccode is
    defined twice, the first definition wins (the simulator resolves calls
    the same way) and the duplicate is an orphan."""
    hats = [n for n in stacks if classify_block(n.block_type) == "event_handler"]
    definitions: dict[str, BlockNode] = {}
    for n in stacks:
        if n.block_type == PROCEDURE_DEFINITION:
            name = procedure_name(n)
            if name:
                definitions.setdefault(name, n)

    called: set[int] = set()
    pending = list(hats)
    while pending:
        for block in _dfs(pending.pop()):
            if block.block_type != PROCEDURE_CALL:
                continue
            definition = definitions.get(procedure_name(block) or "")
            if definition is not None and id(definition) not in called:
                called.add(id(definition))
                pending.append(definition)

    hat_ids = {id(n) for n in hats}
    return (hats,
            [n for n in stacks if id(n) in called],
            [n for n in stacks if id(n) not in hat_ids and id(n) not in called])


# ------------------------------------------------------------------ #
# Internal helpers
# ------------------------------------------------------------------ #

def _is_disabled(el: ET.Element) -> bool:
    """Blockly marks a disabled block with disabled="true" (older XML) or a
    non-empty disabled-reasons attribute (newer XML)."""
    return el.get("disabled") in ("true", "1") or bool(el.get("disabled-reasons"))


def _count_dropped(el: ET.Element) -> int:
    """Blocks and shadows owned by a disabled element: the element and its
    statement / value subtrees, but not its <next> chain (which still runs)."""
    count = 1
    for child_el in el:
        if child_el.tag in (_TAG_STATEMENT, _TAG_VALUE):
            count += sum(1 for d in child_el.iter()
                         if d.tag in (_TAG_BLOCK, _TAG_SHADOW))
    return count


def _parse_block_el(
    el: ET.Element,
    parent: Optional[BlockNode],
    disabled: Optional[list] = None,
) -> Optional[BlockNode]:
    """Recursively parse a <block> or <shadow> element into a BlockNode.

    With `disabled` (a one-element counter), the tree is parsed as it
    executes: a disabled block does not run, and neither does anything inside
    its statement bodies or value slots, but the block after it still does
    (Blockly's code generators skip a disabled block and continue with its
    next). So a disabled block is dropped, its <next> chain is spliced into its
    place, and the dropped blocks are counted. Without it (None), the tree is
    parsed as authored."""
    block_type = el.get("type", "")
    block_id = el.get("id", "")
    if not block_type:
        return None

    if disabled is not None and _is_disabled(el):
        disabled[0] += _count_dropped(el)
        for child_el in el:
            if child_el.tag == _TAG_NEXT:
                for sub in child_el:
                    if sub.tag in (_TAG_BLOCK, _TAG_SHADOW):
                        return _parse_block_el(sub, parent=parent, disabled=disabled)
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
                    node.next = _parse_block_el(sub, parent=node.parent,
                                                disabled=disabled)
                    break

        elif tag == _TAG_STATEMENT:
            # Body of a loop or conditional — one root block in the body.
            # The slot NAME is recorded too (CROW-C117 fix, 2026-08-24):
            # branch identity must survive empty earlier slots.
            for sub in child_el:
                if sub.tag in (_TAG_BLOCK, _TAG_SHADOW):
                    body_root = _parse_block_el(sub, parent=node,
                                                disabled=disabled)
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
            # A disabled connected block contributes nothing, so the slot
            # falls back to its shadow default.
            chosen = None
            for sub in child_el:
                if sub.tag == _TAG_BLOCK:
                    if disabled is not None and _is_disabled(sub):
                        disabled[0] += _count_dropped(sub)
                        continue
                    chosen = sub
                    break
                if sub.tag == _TAG_SHADOW and chosen is None:
                    chosen = sub
            if chosen is not None:
                value_node = _parse_block_el(chosen, parent=node,
                                             disabled=disabled)
                if value_node is not None:
                    node.values.append(value_node)
                    node.value_slots[child_el.get("name", "")] = value_node

        elif tag in (_TAG_BLOCK, _TAG_SHADOW):
            # Inline block (unusual but handle gracefully)
            inline = _parse_block_el(child_el, parent=node, disabled=disabled)
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
