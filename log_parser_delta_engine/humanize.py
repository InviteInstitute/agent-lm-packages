"""
Turns a VEX workspace into a readable program listing.

This is display only. It parses the XML by itself and never touches ast_builder.py or
the edit-distance path, so nothing in here can accidentally move a trigger signal. The
reason it exists: the alert views show block types but not their parameters, and the
parameters are often the whole point (how far a student actually drives, say). Those
numbers sit in `<value>` shadow slots that the distance parser throws away, so they
are preserved here instead.

The rendering rule is one idea, applied recursively:
  * statement / next children go on their own stacked, indented lines (loop and if
    bodies)
  * value children get rendered inline into the parent (conditions, sensor reads,
    math), because a reporter drops into a socket, it doesn't sit in the stack

Live code comes first, one stack after another with a blank line between them (separate
stacks run side by side, not one after the other). Stacks that can never run (not
under a hat, or an uncalled My Block) follow under ORPHAN_HEADER, indented, so they
can't be read as the next steps of the program. What counts as live is decided by
liveness.py, the same rules the compact renderer uses. A disabled block stays where
it is, marked "(disabled)".

Block names come from vex_blocks.json (VEX's own mapping, with blocks + robots + python
merged). If a block isn't in there, a name is derived from its type (platform prefix
dropped, underscores to spaces), so a stale mapping never breaks the listing, it only
makes it rougher until someone refreshes the file.
"""
import json
import os
import xml.etree.ElementTree as ET

from .liveness import (
    PROCEDURE_CALL,
    PROCEDURE_DEFINITION,
    STATEMENT_LABELS,
    child_block,
    is_disabled,
    next_block,
    procedure_label,
    split_stacks,
    strip_namespaces,
    strip_platform_prefix,
    value_input,
)

_MAP_PATH = os.path.join(os.path.dirname(__file__), "vex_blocks.json")

# Block type to display name, loaded once at import. The mapping's sections are
# merged with blocks winning over robots over python when a type appears in more
# than one.
_NAMES = {}
try:
    _raw = json.load(open(_MAP_PATH, encoding="utf-8"))
    for _section in ("python", "robots", "blocks"):     # blocks last so it wins
        for _t, _info in (_raw.get(_section) or {}).items():
            _NAMES[_t] = (_info or {}).get("full_name", _t)
except (OSError, ValueError):
    _NAMES = {}

# A few fixes so enum fields read like words instead of tokens. Anything not
# listed passes straight through. The goal is "name + params", not real English.
_ENUM = {"fwd": "forward", "rev": "reverse", "pct": "%"}

# Operators that read best infix: type -> (operator field, [operand value slots]).
_INFIX = {
    "pg_operator_comparison": ("COMPARISON", ["NUM1", "NUM2"]),
    "pg_operator_and_or": ("CHECK", ["OPERAND1", "OPERAND2"]),
    "pg_operator_math": ("MATH", ["NUM1", "NUM2"]),
}

# Heads the section of stacks that can never run.
ORPHAN_HEADER = "not connected (won't run):"

def _name(t):
    if t in _NAMES:
        return _NAMES[t]
    return strip_platform_prefix(t).replace("_", " ")


def _tidy(v):
    return _ENUM.get(v, v)


def _field(block, name):
    for c in block:
        if c.tag == "field" and c.attrib.get("name") == name:
            return (c.text or "").strip()
    return ""


def _value(block, slot_name):
    """Render one named <value> slot of `block` inline, whether it's a literal or a
    reporter block."""
    for v in block.findall("value"):
        if v.attrib.get("name") == slot_name:
            return _value_str(v)
    return ""


def _value_str(value_elem):
    """Render a <value> element: the connected reporter block if there is one (it
    covers the slot's shadow default, which Blockly still writes out first), else the
    shadow's literal."""
    inp = value_input(value_elem)
    if inp is None:
        return ""
    if inp.tag == "block":
        return _expr(inp)                          # nested reporter, recurse
    f = inp.find("field")
    return (f.text or "").strip() if f is not None else ""


def _is_reporter(block):
    """Operators only ever plug into a socket. At the top level they are loose
    reporters and read best as the expression they compute."""
    t = block.attrib.get("type", "")
    return t in _INFIX or t.startswith("pg_operator_")


def _expr(block):
    """Render a reporter block as an inline expression."""
    t = block.attrib.get("type", "")
    if t in _INFIX:                                # A < B , A and B , A + B
        field, slots = _INFIX[t]
        op = _tidy(_field(block, field))
        return "(" + f" {op} ".join(_value(block, s) for s in slots) + ")"
    if t.startswith("argument_reporter"):          # a My Block parameter
        return _field(block, "VALUE")
    if t == "pg_operator_not":                     # not X
        return f"(not {_value(block, 'OPERAND')})"
    if t == "pg_operator_range":                   # A < x < B
        return (f"({_value(block, 'NUM1')} {_field(block, 'COMPARISON1')} "
                f"{_value(block, 'NUM2')} {_field(block, 'COMPARISON2')} "
                f"{_value(block, 'NUM3')})")
    # Anything else: name, then its own fields, then its value slots (recursed).
    # This is the catch-all that stops an operator or sensor from quietly losing
    # its inputs when no special case exists for it.
    fields = [_tidy(_field(block, c.attrib["name"]))
              for c in block if c.tag == "field" and c.attrib.get("name")]
    # one render per slot: rendering it again to test it was 2^depth on nesting
    rendered = [(v.attrib.get('name', '').lower(), _value_str(v)) for v in block.findall("value")]
    vals = [f"{name} {text}" for name, text in rendered if text]
    tail = " ".join(p for p in fields + vals if p)
    return _name(t) + (f" {tail}" if tail else "")


def _line(block):
    """The one-line label for a stackable block: name, then fields, then value
    literals. Mutator fields are hidden, since those are just VEX plumbing
    (things like `anddontwait_mutator`) and mean nothing to a reader. My Blocks read
    as `define <name>` and `call <name>`, arguments filled in."""
    t = block.attrib.get("type", "")
    if t == PROCEDURE_DEFINITION:
        return "define " + procedure_label(block)
    if t == PROCEDURE_CALL:
        return "call " + procedure_label(block, lambda slot: _value(block, slot))
    fields = [_tidy(_field(block, c.attrib["name"]))
              for c in block
              if c.tag == "field" and c.attrib.get("name")
              and not c.attrib["name"].endswith("_mutator")
              and (c.text or "").strip()]
    vals = []
    for v in block.findall("value"):
        slot = v.attrib.get("name", "")
        txt = _value_str(v)
        if txt:
            # A CONDITION reads fine on its own, every other slot keeps its name so
            # there's some context for what the value is.
            vals.append(txt if slot == "CONDITION" else f"{slot.lower()} {txt}")
    tail = ", ".join(p for p in [", ".join(fields)] + vals if p)
    return f"{_name(block.attrib.get('type', ''))}" + (f" {tail}" if tail else "")


def _walk(block, depth, out):
    """Append one line per stackable block of the chain starting at `block`: the block,
    then its statement bodies one level deeper, then the next block at the same depth."""
    while block is not None:
        mark = " (disabled)" if is_disabled(block) else ""
        out.append("  " * depth + _line(block) + mark)
        for child in block:
            if child.tag == "statement":
                body = child_block(child)
                if body is None:
                    continue
                label = STATEMENT_LABELS.get(child.attrib.get("name"))
                if label:
                    out.append("  " * depth + label + ":")
                _walk(body, depth + 1, out)
        block = next_block(block)


def _stack(top, depth, out):
    if _is_reporter(top):
        mark = " (disabled)" if is_disabled(top) else ""
        out.append("  " * depth + _expr(top) + mark)
    else:
        _walk(top, depth, out)


def generate_readable_lines(xml_string):
    """Parse a workspace XML string into a list of readable lines, one per stackable
    block, indented to show the loop and if nesting. Live stacks come first, separated
    by a blank line; stacks that can never run follow under ORPHAN_HEADER, indented one
    level. Empty or broken input returns [] instead of raising, so a caller can always
    treat this as best-effort."""
    if not xml_string:
        return []
    try:
        root = ET.fromstring(xml_string)
    except (ET.ParseError, ValueError):  # ValueError: lone surrogates
        return []
    strip_namespaces(root)
    try:
        return _render(*split_stacks(root))
    except RecursionError:   # nested past the stack: hostile, not a real program
        return []


def _render(active, orphaned):
    out = []
    for i, top in enumerate(active):
        if i:
            out.append("")
        _stack(top, 0, out)
    if orphaned:
        if out:
            out.append("")
        out.append(ORPHAN_HEADER)
        for i, top in enumerate(orphaned):
            if i:
                out.append("")
            _stack(top, 1, out)
    return out


def generate_readable_text(xml_string):
    """Same as generate_readable_lines but joined into one string. Returns "" when
    there's nothing to show."""
    return "\n".join(generate_readable_lines(xml_string))

