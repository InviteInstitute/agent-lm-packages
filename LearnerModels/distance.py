"""
Takes two block ASTs and gives me back a single number: how much the code changed
between them, as a tree-edit distance.

I turn each AST into an APTED tree and run it through a VEX-specific cost model
(see VexConfig below). The result is a whole number. 0 means the two runs are
identical, and the bigger it gets the more the student rewrote. Every trigger except
inactive is defined straight off this number, so it's the load-bearing piece.
"""
import hashlib
from collections import defaultdict
from apted import APTED, Config

from .constants import (
    BLOCK_DELETE_COST, BLOCK_INSERT_COST, EDGE_DELETE_COST, EDGE_INSERT_COST,
    FIELD_CHANGE_COST, TYPE_CHANGE_COST, EDGE_CHANGE_COST,
)


# A cache I never invalidate. The distance between two XMLs never changes, so once
# I've computed a pair it's good forever. Keyed on the SHA1 of both workspace XMLs
# and just held in memory for as long as the process is alive.
_distance_cache = {}


def clear_cache():
    """Wipe the cache. Only need this if I'm resetting a session."""
    _distance_cache.clear()


def _xml_hash(xml_string):
    return hashlib.sha1(xml_string.encode("utf-8")).hexdigest()


def cached_edit_distance(prev_xml, curr_xml, prev_ast, curr_ast):
    """Same as compute_edit_distance but memoized on the XML pair. If the two XMLs
    are byte-for-byte identical I return 0 immediately and never build a tree, which
    is the common case when a student keeps re-running without editing."""
    if prev_xml == curr_xml:
        return 0
    key = (_xml_hash(prev_xml), _xml_hash(curr_xml))
    cached = _distance_cache.get(key)
    if cached is not None:
        return cached
    dist = compute_edit_distance(prev_ast, curr_ast)
    _distance_cache[key] = dist
    return dist


class AptedNode:
    def __init__(self, name, node_type=None, fields=None):
        self.name = name
        self.node_type = node_type
        self.fields = fields or {}
        self.children = []

    def add_child(self, node):
        self.children.append(node)


def _make_node_label(node_info, include_fields=True, field_keys=None):
    block_type = node_info.get("type", "unknown")
    fields = dict(node_info.get("fields", {}))
    if not include_fields:
        return block_type
    if field_keys is not None:
        fields = {k: v for k, v in fields.items() if k in field_keys}
    if not fields:
        return block_type
    field_str = "|".join(f"{k}={fields[k]}" for k in sorted(fields))
    return f"{block_type}|{field_str}"


def ast_to_apted_tree(ast_dict, include_fields=True, field_keys=None, include_edge_nodes=True):
    """Turn an AST dict ({nodes, edges, roots}) into a tree of AptedNodes that APTED
    can chew on. I order children the same way every time (value, then statement,
    then next, each in its recorded order) so the distance is deterministic. When
    include_edge_nodes is on, I drop an extra node in for every edge, which makes the
    distance care about how blocks are wired together and not just which blocks are
    present. If there's more than one root, I hang them all under a fake ROOT."""
    nodes = ast_dict.get("nodes", {})
    edges = ast_dict.get("edges", [])
    roots = ast_dict.get("roots", [])

    children_map = defaultdict(list)
    for e in edges:
        children_map[e["source"]].append(e)

    edge_priority = {"value": 0, "statement": 1, "next": 2}

    def edge_sort_key(e):
        return (edge_priority.get(e.get("edge_type"), 9), e.get("order", 0))

    for pid in children_map:
        children_map[pid] = sorted(children_map[pid], key=edge_sort_key)

    def build_subtree(node_id):
        info = nodes[node_id]
        label = _make_node_label(info, include_fields=include_fields, field_keys=field_keys)
        root_node = AptedNode(name=label, node_type=info.get("type"), fields=info.get("fields", {}))

        for e in children_map.get(node_id, []):
            child_tree = build_subtree(e["target"])
            if include_edge_nodes:
                edge_label = (
                    e["edge_type"] if e.get("slot") is None
                    else f"{e['edge_type']}:{e['slot']}"
                )
                edge_node = AptedNode(name=edge_label, node_type="__edge__", fields={})
                edge_node.add_child(child_tree)
                root_node.add_child(edge_node)
            else:
                root_node.add_child(child_tree)
        return root_node

    if len(roots) == 0:
        return AptedNode("EMPTY")
    if len(roots) == 1:
        return build_subtree(roots[0])

    super_root = AptedNode("ROOT")
    for r in roots:
        super_root.add_child(build_subtree(r))
    return super_root


class VexConfig(Config):
    """The cost model that makes the distance mean something for VEX. Inserting
    or deleting a real block costs 1.0. The synthetic edge nodes cost 0 to add or
    remove, so adding a single block scores 1 and not 2 (the block plus its
    connector). Renames: free when the labels match, field_change_cost when only a
    field changed inside the same block type, and type_change_cost when the block
    type itself changed."""

    def delete(self, node):
        return EDGE_DELETE_COST if node.node_type == "__edge__" else BLOCK_DELETE_COST

    def insert(self, node):
        return EDGE_INSERT_COST if node.node_type == "__edge__" else BLOCK_INSERT_COST

    def rename(self, n1, n2):
        if n1.name == n2.name:
            return 0.0
        if n1.node_type == "__edge__" or n2.node_type == "__edge__":
            return EDGE_CHANGE_COST
        if n1.node_type == n2.node_type:
            return FIELD_CHANGE_COST
        return TYPE_CHANGE_COST


def compute_edit_distance(ast_prev, ast_curr):
    """The actual APTED distance between two run ASTs, rounded to a whole number
    under the edge-aware cost model. 0 means the two are identical."""
    t1 = ast_to_apted_tree(ast_prev)
    t2 = ast_to_apted_tree(ast_curr)
    return int(round(APTED(t1, t2, VexConfig()).compute_edit_distance()))
