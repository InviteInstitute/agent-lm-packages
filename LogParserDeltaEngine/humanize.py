"""
Turns a VEX Blockly workspace into a readable program listing.

This is display only. It parses the XML by itself and never touches ast_builder.py or
the edit-distance path, so nothing in here can accidentally move a trigger signal. The
reason it exists: the alert views show block types but not their parameters, and the
parameters are often the whole point (how far a student actually drives, say). Those
numbers sit in `<value>` shadow slots that the distance parser throws away, so I keep
them here instead.

The rendering rule is really just one idea, applied recursively:
  * statement / next children go on their own stacked, indented lines (loop and if
    bodies)
  * value children get rendered inline into the parent (conditions, sensor reads,
    math), because a reporter drops into a socket, it doesn't sit in the stack

Block names come from vex_blocks.json (VEX's own mapping, with blocks + robots + python
merged). If a block isn't in there I just print its raw type, so a stale mapping never
breaks the listing, it only makes it uglier until someone refreshes the file.
"""
import json
import os
import xml.etree.ElementTree as ET

_MAP_PATH = os.path.join(os.path.dirname(__file__), "vex_blocks.json")

# Block type to display name, loaded once at import. I merge the mapping's sections
# and let blocks win over robots over python when a type shows up in more than one.
_NAMES = {}
try:
    _raw = json.load(open(_MAP_PATH, encoding="utf-8"))
    for _section in ("python", "robots", "blocks"):     # blocks last so it wins
        for _t, _info in (_raw.get(_section) or {}).items():
            _NAMES[_t] = (_info or {}).get("full_name", _t)
except (OSError, ValueError):
    _NAMES = {}

# A few tiny fixes so enum fields read like words instead of tokens. Anything not
# listed passes straight through. I'm after "name + params" here, not real English.
_ENUM = {"fwd": "forward", "rev": "reverse", "pct": "%", "and": "and", "or": "or"}

# Operators that read best infix: type -> (operator field, [operand value slots]).
_INFIX = {
    "pg_operator_comparison": ("COMPARISON", ["NUM1", "NUM2"]),
    "pg_operator_and_or": ("CHECK", ["OPERAND1", "OPERAND2"]),
    "pg_operator_math": ("MATH", ["NUM1", "NUM2"]),
}

# Labels for statement slots. The main body doesn't need one, the only slot I label
# is the second branch of an if/else, so the "then" side and "else" side don't blur.
_STMT_LABEL = {"SUBSTACK2": "else"}


def _name(t):
    return _NAMES.get(t, t)


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
    """Render a <value> element. Either it's a shadow holding a literal, or it's a
    nested reporter block I recurse into."""
    for c in value_elem:
        if c.tag == "block":
            return _expr(c)                       # nested reporter, recurse
        if c.tag == "shadow":
            f = c.find("field")
            return (f.text or "").strip() if f is not None else ""
    return ""


def _expr(block):
    """Render a reporter block as an inline expression."""
    t = block.attrib.get("type", "")
    if t in _INFIX:                                # A < B , A and B , A + B
        field, slots = _INFIX[t]
        op = _tidy(_field(block, field))
        return "(" + f" {op} ".join(_value(block, s) for s in slots) + ")"
    if t == "pg_operator_not":                     # not X
        return f"(not {_value(block, 'OPERAND')})"
    if t == "pg_operator_range":                   # A < x < B
        return (f"({_value(block, 'NUM1')} {_field(block, 'COMPARISON1')} "
                f"{_value(block, 'NUM2')} {_field(block, 'COMPARISON2')} "
                f"{_value(block, 'NUM3')})")
    # Anything else: name, then its own fields, then its value slots (recursed).
    # This is the catch-all that stops an operator or sensor from quietly losing
    # its inputs when I don't have a special case for it.
    fields = [_tidy(_field(block, c.attrib["name"]))
              for c in block if c.tag == "field" and c.attrib.get("name")]
    vals = [f"{v.attrib.get('name', '').lower()} {_value_str(v)}"
            for v in block.findall("value") if _value_str(v)]
    tail = " ".join(p for p in fields + vals if p)
    return _name(t) + (f" {tail}" if tail else "")


def _line(block):
    """The one-line label for a stackable block: name, then fields, then value
    literals. I hide the mutator fields, since those are just Blockly plumbing
    (things like `anddontwait_mutator`) and mean nothing to a reader."""
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


def _strip_ns(elem):
    if "}" in elem.tag:
        elem.tag = elem.tag.split("}", 1)[1]
    for child in elem:
        _strip_ns(child)


def generate_readable_lines(xml_string):
    """Parse a workspace XML string into a list of readable lines, one per stackable
    block, indented to show the loop and if nesting. Empty or broken input gives back
    [] instead of raising, so a caller can always treat this as best-effort."""
    if not xml_string:
        return []
    try:
        root = ET.fromstring(xml_string)
    except ET.ParseError:
        return []
    _strip_ns(root)

    out = []

    def walk(block, depth):
        out.append("  " * depth + _line(block))
        for child in block:
            if child.tag == "statement":
                label = _STMT_LABEL.get(child.attrib.get("name"))
                if label:
                    out.append("  " * depth + label + ":")
                for nb in child.findall("block"):
                    walk(nb, depth + 1)
            elif child.tag == "next":
                for nb in child.findall("block"):
                    walk(nb, depth)          # next just chains on, so keep the depth

    for block in root:
        if block.tag == "block":
            walk(block, 0)
    return out


def generate_readable_text(xml_string):
    """Same thing as generate_readable_lines but joined into one string. Gives back "" when
    there's nothing to show."""
    return "\n".join(generate_readable_lines(xml_string))


if __name__ == "__main__":
    # A quick self-check so the recursion and the infix rendering can't quietly rot
    # on me. Covers a literal number, an if/else, and a deeply nested condition.
    demo = (
        '<xml>'
        '<block type="pg_events_when_started"><next>'
        '  <block type="pg_drivetrain_drive_for">'
        '    <field name="DIRECTION">fwd</field><field name="UNITS">mm</field>'
        '    <field name="anddontwait_mutator">false</field>'
        '    <value name="AMOUNT"><shadow type="math_number"><field name="NUM">200</field></shadow></value>'
        '  <next>'
        '    <block type="pg_control_if_then_else">'
        '      <value name="CONDITION"><block type="pg_operator_not"><value name="OPERAND">'
        '        <block type="pg_operator_and_or"><field name="CHECK">and</field>'
        '          <value name="OPERAND1"><block type="pg_operator_comparison"><field name="COMPARISON">&lt;</field>'
        '            <value name="NUM1"><block type="pg_sensing_distance_distance"><field name="DISTANCE">frontdistance</field></block></value>'
        '            <value name="NUM2"><shadow type="math_number"><field name="NUM">200</field></shadow></value></block></value>'
        '          <value name="OPERAND2"><block type="pg_sensing_optical_near_object"><field name="OPTICAL">fronteye</field></block></value>'
        '        </block></value></block></value>'
        '      <statement name="SUBSTACK"><block type="pg_drivetrain_drive"><field name="DIRECTION">fwd</field></block></statement>'
        '      <statement name="SUBSTACK2"><block type="pg_drivetrain_stop_driving"/></statement>'
        '    </block></next></block>'
        '</next></block></xml>'
    )
    lines = generate_readable_lines(demo)
    print("\n".join(lines))
    assert any("200" in ln for ln in lines), "value-slot number was dropped"
    assert any("else:" == ln.strip() for ln in lines), "if/else branch not labeled"
    assert any("not (" in ln and "and" in ln and "< 200" in ln for ln in lines), \
        "nested condition not rendered"
    print("\nself-check OK")
