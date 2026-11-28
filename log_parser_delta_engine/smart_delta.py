"""
Renders a student's VEX workspace as compact pseudo-code for an LLM prompt.

Every VEX log event (blockCreated, blockMoved, blockChanged, blockDeleted, runProject,
...) carries the whole project, workspace XML included, in `content.project`. That
snapshot is the truth, so the renderer works from one workspace XML string rather than
replaying block deltas. The deltas in real logs are too thin to replay (a move names
the new parent but not which slot it went into, shadow blocks never get a create
event, and a session starts from a workspace nobody saw being built).

What counts as live is decided by liveness.py, the same rules the readable renderer
uses.

Stdlib only (xml.etree) by design, no external dependencies.
"""
import xml.etree.ElementTree as ET

from .liveness import (
    STATEMENT_LABELS,
    child_block,
    is_disabled,
    procedure_name,
    split_stacks,
    strip_namespaces,
    strip_platform_prefix,
    value_input,
)


def generate_compact_prompt(xml_string):
    """Render a workspace XML string as compact pseudo-code for an LLM. Returns None
    if there's no input or the workspace has no blocks.

    Top-level stacks are split into two sections, [Active] (can run, a hat stack or a
    called My Block) and [Orphaned], in document order. Every stack starts at depth 1
    and the rest of its sequence sits at depth 2, so each depth-1 line opens a new
    stack. Statement bodies and value-slot reporters indent one level under their
    block, and the next block in a sequence stays at the same depth. Each block prints
    its type and fields, with value-slot literals (the 200 in "drive 200 mm") folded
    into its fields by slot name. Disabled blocks are marked [disabled], and common VEX
    type prefixes are stripped to keep the token count down. A workspace nested past
    the interpreter's stack (hostile input, never a real program) renders as
    `[Unrenderable]`."""
    if not xml_string:
        return None
    try:
        root = ET.fromstring(xml_string)
    except (ET.ParseError, ValueError):  # ValueError: lone surrogates
        return None
    strip_namespaces(root)
    active, orphaned = split_stacks(root)
    if not active and not orphaned:
        return None
    lines = []
    try:
        for header, stacks in (("[Active]", active), ("[Orphaned]", orphaned)):
            lines.append(header)
            for top in stacks:
                _render_chain(_render_block(top, 1, lines), 2, lines)
            if not stacks:
                lines.append(" (empty)")
    except RecursionError:
        return "[Unrenderable] blocks nested too deeply"
    return "\n".join(lines)


def _render_chain(block, depth, lines):
    """Render `block` and the rest of its next chain at `depth`."""
    while block is not None:
        block = _render_block(block, depth, lines)


def _render_block(block, depth, lines):
    """Render one block with its statement bodies and value reporters one level
    deeper. Returns the next block in its sequence, or None."""
    fields = {c.get('name'): c.text or '' for c in block
              if c.tag == 'field' and c.get('name')}
    name = procedure_name(block)
    if name:
        fields['PROC'] = name
    following, bodies = None, []
    for container in block:
        if container.tag == 'next':
            child = child_block(container)
            if child is not None:
                following = child
        elif container.tag == 'statement':
            child = child_block(container)
            if child is not None:
                bodies.append((STATEMENT_LABELS.get(container.get('name')), child))
        elif container.tag == 'value':
            child = value_input(container)
            if child is None:
                continue
            if child.tag == 'shadow':
                # A slot that only holds a shadow contributes its literal to the fields.
                f = child.find('field')
                if f is not None:
                    fields[container.get('name') or 'value'] = (f.text or '').strip()
                continue
            bodies.append((None, child))
    parts = [strip_platform_prefix(block.get('type', 'unknown'))]
    if fields:
        parts.append("(" + ",".join(f'{k}={v}' for k, v in fields.items()) + ")")
    if is_disabled(block):
        parts.append("[disabled]")
    lines.append(" " * depth + " ".join(parts))
    for label, child in bodies:
        if label:
            lines.append(" " * depth + label + ":")
        _render_chain(child, depth + 1, lines)
    return following
