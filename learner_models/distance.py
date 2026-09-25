"""
Takes two block ASTs and returns a single number: how much the code changed
between them, as a tree-edit distance.

Each AST is turned into an APTED tree and run through a VEX-specific cost model
(see VexConfig below). The result is a whole number. 0 means the two runs are
identical, and the bigger it gets the more the student rewrote. Every trigger except
inactive is defined straight off this number, so it's the load-bearing piece.
"""
import hashlib
import sys
import threading
from collections import OrderedDict, defaultdict
from apted import APTED, Config

from .constants import (
    BLOCK_DELETE_COST, BLOCK_INSERT_COST, EDGE_DELETE_COST, EDGE_INSERT_COST,
    FIELD_CHANGE_COST, TYPE_CHANGE_COST, EDGE_CHANGE_COST, MAX_DIFF_BLOCKS,
)


# The distance between two XMLs never changes, so a computed pair never goes
# stale. Keyed on the SHA1 digests of both workspace XMLs and bounded as an LRU,
# so a long-running process keeps the recent pairs (a student's last few runs are
# what gets diffed next) without growing forever. An entry is about 150 bytes.
_CACHE_MAX = 50_000
_distance_cache = OrderedDict()
_cache_lock = threading.Lock()


def clear_cache():
    """Wipe the cache. Only needed when resetting a session."""
    with _cache_lock:
        _distance_cache.clear()


def xml_digest(xml_string):
    """The cache key for one workspace XML. Callers that diff the same XML more
    than once (a run against the one before it, then the one after) can hash it
    once and pass the digest to edit_distance_for."""
    return hashlib.sha1(xml_string.encode("utf-8")).digest()


def edit_distance_for(prev_xml, curr_xml, prev_ast, curr_ast,
                      prev_digest=None, curr_digest=None):
    """The memoized distance between two workspace XMLs. prev_ast and curr_ast may
    be the ASTs themselves or zero-argument callables that build them, so a caller
    can skip parsing entirely when the pair is identical or already cached.
    Digests from xml_digest may be passed to avoid rehashing.

    Returns None when either program is bigger than MAX_DIFF_BLOCKS: the pair is
    not compared (see constants)."""
    if prev_xml == curr_xml:
        return 0
    key = (prev_digest or xml_digest(prev_xml), curr_digest or xml_digest(curr_xml))
    with _cache_lock:
        cached = _distance_cache.get(key)
        if cached is not None:
            _distance_cache.move_to_end(key)
            return cached
    prev_ast = prev_ast() if callable(prev_ast) else prev_ast
    curr_ast = curr_ast() if callable(curr_ast) else curr_ast
    if max(len(prev_ast.get("nodes", {})), len(curr_ast.get("nodes", {}))) > MAX_DIFF_BLOCKS:
        return None
    dist = compute_edit_distance(prev_ast, curr_ast)
    with _cache_lock:
        _distance_cache[key] = dist
        if len(_distance_cache) > _CACHE_MAX:
            _distance_cache.popitem(last=False)
    return dist


def cached_edit_distance(prev_xml, curr_xml, prev_ast, curr_ast):
    """Same as compute_edit_distance but memoized on the XML pair. If the two XMLs
    are byte-for-byte identical, returns 0 immediately without building a tree,
    which is the common case when a student keeps re-running without editing."""
    return edit_distance_for(prev_xml, curr_xml, prev_ast, curr_ast)


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
    can process. Children are ordered the same way every time (value, then statement,
    then next, each in its recorded order) so the distance is deterministic. When
    include_edge_nodes is on, an extra node is dropped in for every edge, which makes
    the distance care about how blocks are wired together and not just which blocks
    are present. If there's more than one root, they all hang under a fake ROOT."""
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

    def build_subtree(root_id):
        # Explicit stack instead of recursion: the tree is as deep as the
        # program is long (each next block hangs under the previous one), and
        # children are attached in the same order the recursive build used.
        def make(node_id):
            info = nodes[node_id]
            label = _make_node_label(info, include_fields=include_fields, field_keys=field_keys)
            return AptedNode(name=label, node_type=info.get("type"), fields=info.get("fields", {}))

        top = make(root_id)
        pending = [(root_id, top)]
        while pending:
            node_id, apted_node = pending.pop()
            for e in children_map.get(node_id, []):
                child = make(e["target"])
                if include_edge_nodes:
                    edge_label = (
                        e["edge_type"] if e.get("slot") is None
                        else f"{e['edge_type']}:{e['slot']}"
                    )
                    edge_node = AptedNode(name=edge_label, node_type="__edge__", fields={})
                    edge_node.add_child(child)
                    apted_node.add_child(edge_node)
                else:
                    apted_node.add_child(child)
                pending.append((e["target"], child))
        return top

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


def _tree_depth(tree):
    depth, pending = 0, [(tree, 1)]
    while pending:
        node, d = pending.pop()
        depth = max(depth, d)
        pending.extend((c, d + 1) for c in node.children)
    return depth


_recursion_lock = threading.Lock()


def _ensure_recursion_headroom(depth):
    """APTED indexes a tree recursively, one frame per level, and a program's tree
    is as deep as its longest sequence (twice that with the edge nodes). Raise the
    interpreter's limit to fit before calling it. The limit only ever goes up, so
    concurrent callers can't lower it under each other. Pure-Python frames don't
    use the C stack on Python 3.11+, so a higher limit is safe."""
    needed = 4 * depth + 1000
    with _recursion_lock:
        if sys.getrecursionlimit() < needed:
            sys.setrecursionlimit(needed)


def _signature(tree):
    """The tree's labels and shape in pre-order. Two trees with the same signature
    are identical, so their edit distance is 0."""
    out, pending = [], [tree]
    while pending:
        node = pending.pop()
        out.append((node.name, len(node.children)))
        pending.extend(reversed(node.children))
    return out


def compute_edit_distance(ast_prev, ast_curr):
    """The actual APTED distance between two run ASTs, rounded to a whole number
    under the edge-aware cost model. 0 means the two are identical.

    Identical trees return 0 without running APTED. That is common: the AST leaves
    out shadow literals, so a run that only changed a number (drive 200 -> 300)
    has a different XML but the same tree."""
    t1 = ast_to_apted_tree(ast_prev)
    t2 = ast_to_apted_tree(ast_curr)
    if _signature(t1) == _signature(t2):
        return 0
    _ensure_recursion_headroom(max(_tree_depth(t1), _tree_depth(t2)))
    return int(round(APTED(t1, t2, VexConfig()).compute_edit_distance()))
