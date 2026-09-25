"""
Rebuilds a student's VEX block workspace to see what their code currently looks like.

Every VEX log event (blockCreated, blockMoved, blockChanged, blockDeleted, runProject,
...) carries the whole project, workspace XML included, in `content.project`. That
snapshot is the truth, so process_log rebuilds from it on every event rather than
replaying the event's block delta: the deltas in real logs are too thin to replay (a
move names the new parent but not which slot it went into, shadow blocks never get a
create event, and a session starts from a workspace nobody saw being built).

The rebuilt state is three flat maps: every block, who's parented to whom, and which
blocks are "orphans" (they can never run). What counts as live is decided by
liveness.py, the same rules the readable renderer uses. generate_compact_prompt turns
that into a short pseudo-code listing suitable for an LLM prompt.

Stdlib only (json + xml.etree) by design, no external dependencies.
"""
import json
import xml.etree.ElementTree as ET

from .liveness import (
    HAT_BLOCK_TYPES,
    child_block,
    is_disabled,
    procedure_name,
    split_stacks,
    strip_namespaces,
    value_input,
)

# Labels for statement slots, so the two sides of an if/else don't blur together.
_STMT_LABEL = {"SUBSTACK2": "else"}


class smart_delta_engine:
    # Kept for callers that read it; the hat list itself lives in liveness.py.
    HAT_BLOCK_TYPES = HAT_BLOCK_TYPES

    def __init__(self):
        self.blocks = {}         # block_id -> {type, x, y, fields, is_shadow, disabled}
        self.parent_map = {}     # parent_id -> [{child_id, edge_type, slot}, ...]
        self.orphan_status = {}  # block_id -> True if it can never run
        self.roots = []          # top-level block ids, document order
        self._workspace = None   # the XML the maps were last built from

    def process_log(self, log_event):
        """Fold one VEX log event into the tracked workspace. Any event whose content
        carries a `project` rebuilds the workspace from that project's XML (an empty
        workspace clears it). Events without a project, and anything unparseable, are
        ignored.

        Most events (menuSelect, runProject, clicks) carry the same workspace as the
        one before, so an unchanged XML string skips the rebuild."""
        content = log_event.get('content') if isinstance(log_event, dict) else None
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except ValueError:
                return
        if not isinstance(content, dict) or 'project' not in content:
            return
        project = content.get('project')
        if isinstance(project, str):
            try:
                project = json.loads(project) if project.strip() else {}
            except ValueError:
                return
        if not isinstance(project, dict):
            return
        xml_string = project.get('workspace') or ''
        if xml_string == self._workspace:
            return
        self._bootstrap_from_xml(xml_string)

    def _bootstrap_from_xml(self, xml_string):
        """Clear state and rebuild the maps from a workspace XML string. Unparseable
        XML leaves the workspace empty.

        Real reporter blocks in value slots are tracked as children with
        edge_type='value'. A slot that only holds a shadow (an inline literal like the
        200 in "drive 200 mm") contributes its value to the parent block's fields
        instead, keyed by slot name (AMOUNT=200). When a reporter is connected over a
        shadow, the reporter is the input and the covered shadow is ignored."""
        self.blocks.clear()
        self.parent_map.clear()
        self.orphan_status.clear()
        self.roots = []
        self._workspace = xml_string
        if not xml_string:
            return
        try:
            root = ET.fromstring(xml_string)
        except ET.ParseError:
            return
        strip_namespaces(root)

        active, orphaned = split_stacks(root)
        live = {id(el) for el in active}
        for top in root:
            if top.tag != 'block':
                continue
            top_id = self._add_stack(top, orphan=id(top) not in live)
            self.roots.append(top_id)

    def _add_stack(self, top, orphan):
        """Register a top-level block and everything under it. Returns its id."""
        top_id = self._register(top, orphan)
        pending = [(top, top_id)]
        while pending:
            el, el_id = pending.pop()
            for container in el:
                if container.tag == 'next':
                    child = child_block(container)
                    edge, slot = 'next', None
                elif container.tag == 'statement':
                    child = child_block(container)
                    edge, slot = 'statement', container.get('name')
                elif container.tag == 'value':
                    child = value_input(container)
                    edge, slot = 'value', container.get('name')
                    if child is not None and child.tag == 'shadow':
                        f = child.find('field')
                        if f is not None:
                            self.blocks[el_id]['fields'][slot or 'value'] = (f.text or '').strip()
                        continue
                else:
                    continue
                if child is None:
                    continue
                child_id = self._register(child, orphan)
                self.parent_map.setdefault(el_id, []).append(
                    {'child_id': child_id, 'edge_type': edge, 'slot': slot})
                pending.append((child, child_id))
        return top_id

    def _register(self, el, orphan):
        b_id = el.get('id') or f'gen_{len(self.blocks)}'
        fields = {c.get('name'): c.text or '' for c in el
                  if c.tag == 'field' and c.get('name')}
        name = procedure_name(el)
        if name:
            fields['PROC'] = name
        x, y = el.get('x'), el.get('y')
        self.blocks[b_id] = {
            'type': el.get('type', 'unknown'),
            'x': float(x) if x else None,
            'y': float(y) if y else None,
            'fields': fields,
            'is_shadow': el.tag == 'shadow',
            'disabled': is_disabled(el),
        }
        self.orphan_status[b_id] = orphan
        return b_id

    def get_runnable_block_count(self):
        """Blocks that can run: in a live stack and not disabled (nor inside a disabled
        block's bodies or slots)."""
        return len(self._runnable_ids())

    def _runnable_ids(self):
        runnable = set()
        pending = [r for r in self.roots if not self.orphan_status.get(r, True)]
        while pending:
            b_id = pending.pop()
            block = self.blocks.get(b_id)
            if block is None:
                continue
            for entry in self.parent_map.get(b_id, []):
                if entry['edge_type'] == 'next' or not block['disabled']:
                    pending.append(entry['child_id'])
            if not block['disabled'] and not block['is_shadow']:
                runnable.add(b_id)
        return runnable

    def get_total_blocks(self):
        return sum(1 for b in self.blocks.values() if not b['is_shadow'])

    def generate_compact_prompt(self):
        """Render the workspace as compact pseudo-code for an LLM. Top-level stacks are
        split into two sections, [Active] (can run: a hat stack or a called My Block)
        and [Orphaned], in document order. Every stack starts at depth 1 and the rest
        of its sequence sits at depth 2, so each depth-1 line opens a new stack.
        Statement bodies and value-slot reporters indent one level under their block;
        the next block in a sequence stays at the same depth. Each block prints its
        type and fields, disabled blocks are marked [disabled], and common VEX type
        prefixes are stripped to keep the token count down."""
        active = [r for r in self.roots if not self.orphan_status.get(r, True)]
        orphaned = [r for r in self.roots if self.orphan_status.get(r, True)]

        lines = ["[Active]"]
        for r in active:
            self._render_chain(self._render_block(r, 1, lines), 2, lines)
        if not active:
            lines.append(" (empty)")
        lines.append("[Orphaned]")
        for r in orphaned:
            self._render_chain(self._render_block(r, 1, lines), 2, lines)
        if not orphaned:
            lines.append(" (empty)")
        return "\n".join(lines)

    def _render_chain(self, block_id, depth, lines):
        """Render `block_id` and the rest of its next chain at `depth`."""
        seen = set()
        while block_id is not None and block_id not in seen:
            seen.add(block_id)
            block_id = self._render_block(block_id, depth, lines)

    def _render_block(self, block_id, depth, lines):
        """Render one block with its statement bodies and value reporters one level
        deeper. Returns the id of the next block in its sequence, or None."""
        block = self.blocks.get(block_id)
        if block is None:
            return None
        lines.append(" " * depth + _compact_line(block))
        following = None
        for entry in self.parent_map.get(block_id, []):
            if entry['edge_type'] == 'next':
                following = entry['child_id']
                continue
            label = _STMT_LABEL.get(entry['slot']) if entry['edge_type'] == 'statement' else None
            if label:
                lines.append(" " * depth + label + ":")
            self._render_chain(entry['child_id'], depth + 1, lines)
        return following


def _clean_type(raw):
    """Drop the noisy VEX prefixes so the listing is shorter."""
    for prefix in ('pg_', 'aim_', 'mixed_'):
        if raw.startswith(prefix):
            return raw[len(prefix):]
    return raw


def _compact_line(block):
    parts = [_clean_type(block.get('type', '?'))]
    fields = block.get('fields', {})
    if fields:
        parts.append("(" + ",".join(f'{k}={v}' for k, v in fields.items()) + ")")
    if block.get('disabled'):
        parts.append("[disabled]")
    return " ".join(parts)


def generate_compact_prompt(xml_string):
    """One-shot compact prompt from a workspace XML string. Returns None if there's no
    input or the workspace has no blocks."""
    if not xml_string:
        return None
    engine = smart_delta_engine()
    engine._bootstrap_from_xml(xml_string)
    if not engine.blocks:
        return None
    return engine.generate_compact_prompt()

