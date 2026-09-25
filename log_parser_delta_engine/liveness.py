"""
Which parts of a VEX workspace can actually run.

Both renderers (compact and readable) use this so they agree on what is live code and
what is an orphan. The rules:

  * A top-level stack is live when its first block is an enabled hat (HAT_BLOCK_TYPES).
    The list is explicit on purpose: broadcast and broadcast-and-wait live in the
    events category too, but they are ordinary stack blocks, so a stack that starts
    with one is detached code that never runs.
  * A My Block definition is live when live code calls it (directly, or through other
    called definitions). An uncalled definition never runs. When a name is defined
    twice, the first definition wins and the duplicate is an orphan.
  * Everything else at the top level is an orphan.
  * A disabled block never runs, and neither does anything inside its statement bodies
    or value slots, but the block after it still does (Blockly skips a disabled block
    and carries on with its next). Disabled blocks stay in the stack they belong to and
    the renderers mark them, so a reader sees them without mistaking them for live code.

goal_strategy's parser applies the same rules to its own IR, and its hat set (the
`event` class in goal_strategy/detector/data/blocks.csv) is pinned to HAT_BLOCK_TYPES by
a test.

All functions take an ElementTree with namespaces already stripped (see strip_namespaces).
"""
import json

HAT_BLOCK_TYPES = frozenset({
    "pg_events_when_started",
    "pg_events_when_broadcasted",
    "pg_events_when_bumper",
    "pg_events_when_timer",
    "pg_events_optical_detect_object",
})

PROCEDURE_DEFINITION = "procedures_definition"
PROCEDURE_CALL = "procedures_call"


def strip_namespaces(elem):
    """Drop the `{namespace}` prefix from every tag, in place. VEX workspace XML is
    namespaced (xmlns="https://developers.google.com/blockly/xml") and the procedure
    <mutation> carries an XHTML one, so lookups by bare tag need this first."""
    for el in elem.iter():
        if "}" in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    return elem


def is_disabled(block):
    """Blockly marks a disabled block with disabled="true" (older XML) or a non-empty
    disabled-reasons attribute (newer XML)."""
    return block.get("disabled") in ("true", "1") or bool(block.get("disabled-reasons"))


def child_block(container):
    """The <block> a <next> or <statement> container holds, or None."""
    for el in container:
        if el.tag == "block":
            return el
    return None


def value_input(value):
    """What a <value> slot evaluates to: the connected enabled <block> if there is one,
    otherwise the <shadow> default (which is also what a disabled connected block falls
    back to). Returns None for an empty slot."""
    for el in value:
        if el.tag == "block" and not is_disabled(el):
            return el
    for el in value:
        if el.tag == "shadow":
            return el
    return None


def next_block(block):
    for el in block:
        if el.tag == "next":
            return child_block(el)
    return None


def mutation(block):
    """The attribute dict of a procedure block's <mutation>. A call carries it as a
    direct child; a definition carries it on the procedures_prototype shadow inside its
    custom_block statement."""
    holder = block
    if block.get("type") == PROCEDURE_DEFINITION:
        holder = None
        for st in block:
            if st.tag == "statement":
                for sh in st:
                    if sh.get("type") == "procedures_prototype":
                        holder = sh
        if holder is None:
            return {}
    for el in holder:
        if el.tag == "mutation":
            return dict(el.attrib)
    return {}


def procedure_name(block):
    """The proccode a definition declares or a call invokes, or None."""
    if block.get("type") not in (PROCEDURE_DEFINITION, PROCEDURE_CALL):
        return None
    return mutation(block).get("proccode") or None


def procedure_label(block, arg_text=None):
    """Human form of a procedure's proccode, with its %s/%n/%b placeholders filled in.

    For a call, `arg_text(slot_name)` renders the argument plugged into each value slot
    (slots are named by the ids in the mutation's argumentids). For a definition, the
    placeholders become the parameter names in parentheses."""
    mut = mutation(block)
    code = mut.get("proccode") or ""
    if block.get("type") == PROCEDURE_CALL:
        ids = _json_list(mut.get("argumentids"))
        args = [arg_text(i) if arg_text else "" for i in ids]
    else:
        args = [f"({n})" for n in _json_list(mut.get("argumentnames"))]
    out, i = [], 0
    for word in code.split(" "):
        if word in ("%s", "%n", "%b"):
            out.append(args[i] if i < len(args) and args[i] else "_")
            i += 1
        else:
            out.append(word)
    return " ".join(out).strip()


def _json_list(raw):
    try:
        value = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    return [str(v) for v in value] if isinstance(value, list) else []


def executed_blocks(block):
    """Every block that runs when `block`'s stack runs: the block itself, its statement
    bodies and value inputs, and its next chain. Disabled blocks and everything inside
    them are skipped, but their next chain is followed."""
    pending = [block]
    while pending:
        el = pending.pop()
        if el is None:
            continue
        pending.append(next_block(el))
        if is_disabled(el):
            continue
        yield el
        for container in el:
            if container.tag == "statement":
                pending.append(child_block(container))
            elif container.tag == "value":
                inp = value_input(container)
                if inp is not None and inp.tag == "block":
                    pending.append(inp)


def split_stacks(root):
    """Partition the workspace's top-level blocks into (active, orphaned), each a list of
    <block> elements in document order. Active = enabled hat stacks, then the My Block
    definitions they call."""
    tops = [el for el in root if el.tag == "block"]
    hats = [el for el in tops
            if el.get("type") in HAT_BLOCK_TYPES and not is_disabled(el)]
    definitions = {}
    for el in tops:
        if el.get("type") == PROCEDURE_DEFINITION and not is_disabled(el):
            name = procedure_name(el)
            if name:
                definitions.setdefault(name, el)

    live = {id(el) for el in hats}
    pending = list(hats)
    while pending:
        for el in executed_blocks(pending.pop()):
            if el.get("type") != PROCEDURE_CALL:
                continue
            definition = definitions.get(procedure_name(el) or "")
            if definition is not None and id(definition) not in live:
                live.add(id(definition))
                pending.append(definition)

    active = [el for el in tops if id(el) in live]
    orphaned = [el for el in tops if id(el) not in live]
    return active, orphaned
