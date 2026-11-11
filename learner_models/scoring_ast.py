"""The tree that run scoring diffs. It differs from xml_to_block_ast in two ways.

  * Only live code counts. A top-level stack is kept when log_parser_delta_engine's
    liveness rules say it runs (an enabled hat, or a My Block definition that live
    code calls), so the renderers and the scorer agree on what is an orphan. A
    disabled block inside a live stack is dropped with everything inside it, and
    the block after it moves up into its place, because Blockly skips it and runs
    on. Disabling a block scores like deleting it.
  * Which My Block a call runs counts. The proccode lives in a <mutation>, not a
    field, so it is copied onto procedures_call and procedures_definition as a
    PROCCODE field. Otherwise calls to two different My Blocks look identical.
  * Typed-in values count. A shadow is not a node, so the value it holds (a number,
    some text, a dropdown default) is copied onto the block that owns the slot, as
    a field named SLOT.FIELD. Changing drive 100 to 150 is one field change. A shadow
    hidden behind a connected block is not what runs, so it is skipped. A real
    literal block (one dragged into the slot) is already a node with its own field,
    so it is not copied up and an edit to it still costs 1, not 2.
"""
import xml.etree.ElementTree as ET

from log_parser_delta_engine.liveness import (
    is_disabled, next_block, procedure_name, split_stacks, strip_namespaces, value_input,
)
from .ast_builder import root_to_block_ast


def _drop_disabled(root):
    """Remove each disabled block and splice its next chain into its place."""
    parent = {child: el for el in root.iter() for child in el}
    for block in [b for b in root.iter("block") if is_disabled(b)]:
        container = parent[block]
        after = next_block(block)
        container.remove(block)
        if after is not None:
            container.append(after)
            parent[after] = container


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
    _drop_disabled(root)

    for block in list(root.iter("block")):
        name = procedure_name(block)
        if name:
            ET.SubElement(block, "field", name="PROCCODE").text = name
        for value in block.findall("value"):
            shadow = value_input(value)
            if shadow is None or shadow.tag != "shadow":
                continue
            for field in shadow.findall("field"):
                if field.get("name"):
                    name = f"{value.get('name')}.{field.get('name')}"
                    ET.SubElement(block, "field", name=name).text = field.text
    return root_to_block_ast(root)
