"""
Parses a VEX workspace XML into an AST-ish dict that the distance code can work
with.

The shape it spits out ({nodes, edges, roots}) is deliberately the same one the
training pipeline used, so the APTED distance computed here lines up with the
numbers the model was trained on. Don't change the shape without checking that.
"""
import json
import xml.etree.ElementTree as ET


def _strip_namespace(elem):
    # iter() walks the whole tree without recursion (Blockly nests every next
    # block inside the previous one, so a long program is a very deep tree).
    for el in elem.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]


def _parse_xml_string(xml_string):
    root = ET.fromstring(xml_string)
    _strip_namespace(root)
    return root


def _get_immediate_fields(block_elem):
    fields = {}
    for child in block_elem:
        if child.tag == "field":
            name = child.attrib.get("name")
            if name:
                fields[name] = (child.text or "").strip()
    return fields


def _get_block_node_info(block_elem):
    return {
        "id": block_elem.attrib.get("id"),
        "type": block_elem.attrib.get("type", "unknown"),
        "fields": _get_immediate_fields(block_elem),
    }


def _find_child_blocks(container_elem, allow_shadow=False):
    out = []
    for child in container_elem:
        if child.tag == "block":
            out.append(child)
        elif allow_shadow and child.tag == "shadow":
            out.append(child)
    return out


def xml_to_block_ast(xml_string, keep_shadow=False):
    """Parse workspace XML into {nodes, edges, roots}. nodes maps a block id to its
    type and fields, edges record the parent/child links (tagged by connection kind,
    value/statement/next, plus the slot), and roots lists the top-level blocks. Shadow
    blocks are dropped unless keep_shadow is set, and blank or malformed input returns
    an empty AST instead of raising."""
    if not xml_string:
        return {"nodes": {}, "edges": [], "roots": []}

    try:
        root = _parse_xml_string(xml_string)
    except ET.ParseError:
        return {"nodes": {}, "edges": [], "roots": []}
    nodes, edges, roots = {}, [], []

    def register(block_elem):
        info = _get_block_node_info(block_elem)
        bid = info["id"] or f"generated_{len(nodes)}"
        info["id"] = bid
        nodes[bid] = {"type": info["type"], "fields": info["fields"]}
        return bid

    def children_of(block_elem, current_id):
        """(element, parent_id, edge_type, slot, order) for each child block, in
        document order."""
        out = []
        for child in block_elem:
            if child.tag in ("next", "statement", "value"):
                slot_name = child.attrib.get("name") if child.tag != "next" else None
                nested = _find_child_blocks(child, allow_shadow=keep_shadow)
                for i, nb in enumerate(nested):
                    out.append((nb, current_id, child.tag, slot_name, i))
        return out

    # Pre-order walk with an explicit stack. The order (and so the generated ids
    # and edge order) is exactly what the recursive version produced, but a long
    # program no longer costs a stack frame per block.
    pending = []
    for child in reversed(list(root)):
        if child.tag == "block" or (child.tag == "shadow" and keep_shadow):
            pending.append((child, None, None, None, 0))
    while pending:
        block_elem, parent_id, edge_type, slot, order = pending.pop()
        if block_elem.tag == "shadow" and not keep_shadow:
            continue
        current_id = register(block_elem)
        if parent_id is None:
            roots.append(current_id)
        else:
            edges.append({
                "source": parent_id, "target": current_id,
                "edge_type": edge_type, "slot": slot, "order": order,
            })
        pending.extend(reversed(children_of(block_elem, current_id)))

    return {"nodes": nodes, "edges": edges, "roots": roots}


def extract_workspace_xml(log_content):
    """Extract the workspace XML from a parsed log content dict. The `project` field
    shows up sometimes as a nested dict and sometimes as a JSON string, so both are
    handled. Returns "" when there's nothing usable in there."""
    project = log_content.get("project", {}) if isinstance(log_content, dict) else {}
    if isinstance(project, str):
        try:
            project = json.loads(project)
        except json.JSONDecodeError:
            return ""
    if not isinstance(project, dict):
        return ""
    return project.get("workspace", "") or ""
