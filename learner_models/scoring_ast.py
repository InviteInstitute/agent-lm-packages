"""The tree that run scoring diffs. It is xml_to_block_ast over the code that runs,
with the values typed into it.

  * Only live code counts. A top-level stack is kept when log_parser_delta_engine's
    liveness rules say it runs (an enabled hat, or a My Block definition that live
    code calls), so the renderers and the scorer agree on what is an orphan.
  * Blocks that do nothing are dropped with everything inside them, and the block
    after each one moves up into its place. That is a disabled block (Blockly skips
    it and runs on) and a comment block. Disabling a block scores like deleting it,
    and adding or editing a comment block scores 0.
  * Typed-in values count. A shadow is not a node, so the value it holds (a number,
    some text, a dropdown default, and the same for any shadow inside it) is copied
    onto the block that owns the slot, as a field named SLOT.FIELD. Changing drive
    100 to 150 is one field change. A shadow hidden behind a connected block is not
    what runs, so it is skipped. A real literal block (one dragged into the slot) is
    already a node with its own field, so it is not copied up and an edit to it
    still costs 1, not 2.
  * Which My Block a call runs counts. The proccode lives in a <mutation>, not a
    field, so it is copied onto procedures_call and procedures_definition as a
    PROCCODE field. Otherwise calls to two different My Blocks look identical.

Everything else Blockly writes that does not change what runs is already ignored
by the parser: block ids, positions, collapsed and inline state, block and workspace
comments, variable declarations and empty connections.
"""
import xml.etree.ElementTree as ET

from log_parser_delta_engine.liveness import (
    is_disabled,
    next_block,
    procedure_name,
    split_stacks,
    strip_namespaces,
    value_input,
)

from .ast_builder import root_to_block_ast

COMMENT_BLOCK = "aim_other_comment"


def _drop_inert(root):
    """Remove each disabled or comment block and splice its next chain into its place."""
    parent = {child: el for el in root.iter() for child in el}
    inert = [b for b in root.iter("block") if b in parent
             and (is_disabled(b) or b.get("type") == COMMENT_BLOCK)]
    for block in inert:
        container = parent[block]
        after = next_block(block)
        container.remove(block)
        if after is not None:
            container.append(after)
            parent[after] = container


def _shadow_fields(slot, shadow):
    """(SLOT.FIELD, text) for every field in a shadow and in the shadows inside it."""
    out, pending = [], [(slot, shadow)]
    while pending:
        prefix, el = pending.pop()
        for child in el:
            if child.tag == "field" and child.get("name"):
                out.append((f"{prefix}.{child.get('name')}", child.text))
            elif child.tag == "value":
                inner = value_input(child)
                if inner is not None and inner.tag == "shadow":
                    pending.append((f"{prefix}.{child.get('name')}", inner))
    return out


def scoring_ast(xml):
    """{nodes, edges, roots} for the live code in a workspace XML. Blank, malformed
    or hat-less input gives an empty tree."""
    try:
        root = strip_namespaces(ET.fromstring(xml)) if xml else None
    except (ET.ParseError, ValueError):  # ValueError: lone surrogates
        root = None
    if root is None:
        return {"nodes": {}, "edges": [], "roots": []}

    live = {id(el) for el in split_stacks(root)[0]}
    for el in list(root):
        if id(el) not in live:
            root.remove(el)
    _drop_inert(root)

    for block in list(root.iter("block")):
        added = []
        name = procedure_name(block)
        if name:
            added.append(("PROCCODE", name))
        for value in block.findall("value"):
            inner = value_input(value)
            if inner is not None and inner.tag == "shadow":
                added.extend(_shadow_fields(value.get("name"), inner))
        for key, text in added:
            ET.SubElement(block, "field", name=key).text = text
    return root_to_block_ast(root)
