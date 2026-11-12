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
    BLOCK_DELETE_COST,
    BLOCK_INSERT_COST,
    EDGE_CHANGE_COST,
    FIELD_CHANGE_COST,
    MAX_DIFF_BLOCKS,
    TYPE_CHANGE_COST,
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
    return hashlib.sha1(xml_string.encode("utf-8", "surrogatepass")).digest()


def edit_distance_for(prev_xml, curr_xml, prev_ast, curr_ast,
                      prev_digest=None, curr_digest=None, namespace="xml_to_block_ast"):
    """The memoized distance between two workspace XMLs. prev_ast and curr_ast may
    be the ASTs themselves or zero-argument callables that build them, so a caller
    can skip parsing entirely when the pair is identical or already cached.
    Digests from xml_digest may be passed to avoid rehashing.

    The cache is keyed on the XMLs, so it is only right if the ASTs are always built
    from them the same way. `namespace` names that way: pass a different one for
    ASTs built by anything other than xml_to_block_ast (run scoring passes
    "scoring_ast"), or a distance cached under one would be served for the other.

    Returns None when either program is bigger than MAX_DIFF_BLOCKS: the pair is
    not compared (see constants)."""
    if prev_xml == curr_xml:
        return 0
    key = (namespace, prev_digest or xml_digest(prev_xml), curr_digest or xml_digest(curr_xml))
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
    """One node of the tree APTED diffs. `name` is the node's whole identity, so two
    nodes with equal names are the same node and renaming one into the other is free.

    A block's name is (connection, label). connection is how it hangs off its parent:
    ("next", None), ("statement", "SUBSTACK"), ("value", "AMOUNT"), or ("top", None)
    for a stack under the workspace root. label is (block type, its sorted fields).
    Keeping both as tuples, not joined strings, means no field value a student types
    can make two different blocks look the same."""

    __slots__ = ("children", "connection", "label", "name", "node_type")

    def __init__(self, node_type, connection, label):
        self.node_type = node_type
        self.connection = connection
        self.label = label
        self.name = (connection, label)
        self.children = []


if max(EDGE_CHANGE_COST, FIELD_CHANGE_COST, TYPE_CHANGE_COST) > min(BLOCK_INSERT_COST,
                                                                   BLOCK_DELETE_COST):
    raise ValueError("a rename may not cost more than a block insert or delete (see VexConfig)")

_WORKSPACE = "__workspace__"
# A cost no real diff can reach (it is at most 2 * MAX_DIFF_BLOCKS edits of cost
# <= 1), so the two workspace roots always map onto each other.
_NEVER = 1e9


def _label(info):
    fields = info.get("fields") or {}
    return (str(info.get("type", "unknown")),
            tuple(sorted((str(k), str(v)) for k, v in fields.items())))


def ast_to_apted_tree(ast_dict):
    """Turn an AST dict ({nodes, edges, roots}) into the tree APTED diffs.

    Every tree hangs off one workspace node, however many stacks there are (none
    included), so adding a stack costs its blocks and nothing for a wrapper. A
    block's connection is part of the block's own node rather than a node of its
    own: a separate connector node would have to be free to add or remove (or
    adding one block would cost 2), and a free node lets APTED move a block into a
    loop, or from the if branch to the else branch, for nothing. Children are
    ordered value, then statement, then next, each in recorded order, so the
    distance is deterministic."""
    nodes = ast_dict.get("nodes", {})
    edges = ast_dict.get("edges", [])
    roots = ast_dict.get("roots", [])

    children_map = defaultdict(list)
    for e in edges:
        children_map[e["source"]].append(e)
    edge_priority = {"value": 0, "statement": 1, "next": 2}
    for pid in children_map:
        children_map[pid].sort(key=lambda e: (edge_priority.get(e.get("edge_type"), 9),
                                              e.get("order", 0)))

    workspace = AptedNode(_WORKSPACE, None, None)
    # Explicit stack instead of recursion: the tree is as deep as the program is
    # long (each next block hangs under the previous one).
    pending = []
    for r in roots:
        node = AptedNode(nodes[r].get("type"), ("top", None), _label(nodes[r]))
        workspace.children.append(node)
        pending.append((r, node))
    while pending:
        node_id, parent = pending.pop()
        for e in children_map.get(node_id, []):
            info = nodes[e["target"]]
            child = AptedNode(info.get("type"), (e.get("edge_type"), e.get("slot")), _label(info))
            parent.children.append(child)
            pending.append((e["target"], child))
    return workspace


class VexConfig(Config):
    """The cost model that makes the distance mean something for VEX. Inserting or
    deleting a block costs 1. Renaming one block into another costs the largest of
    the changes it covers: EDGE_CHANGE_COST when it now hangs off a different
    connection (moved into a loop, to the else branch, into another slot), and
    FIELD_CHANGE_COST when its fields changed or TYPE_CHANGE_COST when its type did.
    So moving a block is 1, swapping it for another block in place is 1, and moving
    it and changing its number is 1 too. The workspace root never changes.

    The largest, not the sum: the apted package returns distances that are not
    minimal when one rename costs more than inserting or deleting a block (found by
    the symmetry check in test_robustness, confirmed against Zhang-Shasha), so no
    rename may cost more than BLOCK_INSERT_COST or BLOCK_DELETE_COST."""

    def delete(self, node):
        return _NEVER if node.node_type == _WORKSPACE else BLOCK_DELETE_COST

    def insert(self, node):
        return _NEVER if node.node_type == _WORKSPACE else BLOCK_INSERT_COST

    def rename(self, n1, n2):
        if n1.name == n2.name:
            return 0.0
        if _WORKSPACE in (n1.node_type, n2.node_type):
            return _NEVER
        cost = EDGE_CHANGE_COST if n1.connection != n2.connection else 0.0
        if n1.label != n2.label:
            cost = max(cost, FIELD_CHANGE_COST if n1.node_type == n2.node_type
                       else TYPE_CHANGE_COST)
        return cost


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
    is as deep as its longest sequence. Raise the
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
    """The APTED distance between two ASTs under VexConfig, as a whole number (every
    cost is a whole number). 0 means the two trees are identical.

    Identical trees return 0 without running APTED. Run scoring hits this for
    workspaces that differ only in detached code (see scoring_ast)."""
    t1 = ast_to_apted_tree(ast_prev)
    t2 = ast_to_apted_tree(ast_curr)
    if _signature(t1) == _signature(t2):
        return 0
    _ensure_recursion_headroom(max(_tree_depth(t1), _tree_depth(t2)))
    return int(round(APTED(t1, t2, VexConfig()).compute_edit_distance()))
