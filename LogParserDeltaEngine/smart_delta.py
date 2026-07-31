"""
Rebuilds a student's VEX block workspace so I can see what their code actually looks
like right now.

There are two ways in: replay the create/move/delete/change events one at a time as
they stream in, or bootstrap straight from a project's saved workspace XML. Either
path lands in the same place, three flat maps: every block, who's parented to whom,
and which blocks are "orphans" (not wired up under a hat block, so they'll never run).
generate_compact_prompt turns that into a short pseudo-code listing that's cheap to hand
to an LLM.

Stdlib only (json + xml.etree) on purpose. I didn't want to pull in a dependency just
to read some XML.
"""
import json
import xml.etree.ElementTree as ET


class SmartDeltaEngine:
    # These are the "hat" blocks, the ones that can actually start a program
    # (event handlers, procedure definitions). At the top of the workspace only a
    # hat counts as live code, anything else just sitting up there is an orphan.
    HAT_BLOCK_PATTERNS = ('events_', 'procedures_definition')

    def __init__(self):
        self.blocks = {}         # block_id -> {type, x, y, fields, is_shadow}
        self.parent_map = {}     # parent_id -> [{child_id, edge_type, slot}, ...]
        self.orphan_status = {}  # block_id -> True if it's NOT reachable from a hat

    def _register_block(self, block_id, block_type, x=None, y=None, fields=None,
                        is_shadow=False):
        self.blocks[block_id] = {
            'type': block_type,
            'x': x,
            'y': y,
            'fields': fields or {},
            'is_shadow': is_shadow,
        }
        self.orphan_status[block_id] = True

    def _link(self, parent_id, child_id, edge_type, slot=None):
        self.parent_map.setdefault(parent_id, []).append(
            {'child_id': child_id, 'edge_type': edge_type, 'slot': slot}
        )

    def process_log(self, log_event):
        """Take one VEX log event and fold it into the workspace I'm tracking. A
        loadProject/newProject wipes everything and rebuilds from the project XML,
        and the block-level create/move/delete/change events just nudge the maps. If an
        event is junk or irrelevant I drop it quietly rather than blow up."""
        try:
            content = json.loads(log_event.get('content', '{}'))
        except Exception:
            return

        event_type = content.get('eventType')

        # Load or new project -> start over and rebuild straight from the XML.
        if event_type in ('loadProject', 'newProject'):
            self._bootstrap_from_xml(content)
            return

        # Anything else is a single block-level change I apply on top of what I have.
        raw_block_data = content.get('blockEventData')
        if not raw_block_data:
            return

        try:
            block_data = json.loads(raw_block_data)
        except Exception:
            return

        b_type = block_data.get('eventType')
        block_id = block_data.get('blockID')

        if not block_id:
            return

        if b_type == 'create':
            block_type = block_data.get('blockType', '')
            is_shadow = 'shadow' in block_type.lower()
            init_fields = {}
            for f in block_data.get('fields', []) or []:
                if isinstance(f, dict) and 'name' in f:
                    init_fields[f['name']] = f.get('value', '')
            self._register_block(block_id, block_type, fields=init_fields,
                                 is_shadow=is_shadow)
            self._recompute_orphans()

        elif b_type == 'move':
            self._sever_from_parents(block_id)

            new_info = block_data.get('newInfo', {})

            if 'parent' in new_info:
                new_parent = new_info['parent']
                edge_type = new_info.get('type', 'next')
                slot = new_info.get('inputName') or new_info.get('slot')
                self._link(new_parent, block_id, edge_type, slot)

                # It's attached to a parent now, so its floating x/y don't mean anything.
                if block_id in self.blocks:
                    self.blocks[block_id]['x'] = None
                    self.blocks[block_id]['y'] = None

                # If a shadow block moved into a value slot, fold its field value
                # into the parent's fields so it shows in the compact prompt.
                if (edge_type == 'value' and slot
                        and self.blocks.get(block_id, {}).get('is_shadow')
                        and new_parent in self.blocks):
                    shadow_fields = self.blocks[block_id].get('fields', {})
                    if shadow_fields:
                        parent_fields = self.blocks[new_parent]['fields']
                        for sf_name, sf_val in shadow_fields.items():
                            parent_fields[slot] = sf_val

                self._recompute_orphans()

            elif 'coordinate' in new_info:
                coord = new_info['coordinate']
                if block_id in self.blocks:
                    self.blocks[block_id]['x'] = coord.get('x')
                    self.blocks[block_id]['y'] = coord.get('y')

                self._recompute_orphans()

        elif b_type == 'delete':
            self._sever_from_parents(block_id)
            self._delete_recursive(block_id, set())
            self._recompute_orphans()

        elif b_type == 'change':
            field_name = block_data.get('name')
            new_value = block_data.get('newValue')
            if block_id in self.blocks and field_name:
                self.blocks[block_id]['fields'][field_name] = new_value
                # If this is a shadow block parented into a value slot, propagate
                # the change to the parent's folded field so the compact prompt
                # stays in sync.
                if self.blocks[block_id].get('is_shadow'):
                    for p_id, entries in self.parent_map.items():
                        for entry in entries:
                            if entry['child_id'] == block_id and entry['edge_type'] == 'value':
                                slot = entry['slot']
                                if slot and p_id in self.blocks:
                                    self.blocks[p_id]['fields'][slot] = new_value

    def _sever_from_parents(self, block_id):
        keys_to_remove = []
        for p_id, children in self.parent_map.items():
            removed = False
            for entry in list(children):
                if entry['child_id'] == block_id:
                    children.remove(entry)
                    removed = True
            if removed and not children:
                keys_to_remove.append(p_id)
        for k in keys_to_remove:
            del self.parent_map[k]

    def _bootstrap_from_xml(self, content):
        """Dump whatever I have and rebuild the maps by walking the project's
        workspace XML from scratch. A block at the root is only live if it's a hat,
        and as I walk down, every child just inherits whatever its parent's orphan
        status was. Shadow blocks inside <value> slots contribute their field values
        to the parent block's fields (e.g. the NUM on a math_number shadow becomes
        AMOUNT on the drive block that holds it), and real reporter blocks in value
        slots get tracked as children with edge_type='value'."""
        self.blocks.clear()
        self.parent_map.clear()
        self.orphan_status.clear()

        project_raw = content.get('project', '{}')
        try:
            project = json.loads(project_raw) if isinstance(project_raw, str) else project_raw
        except Exception:
            project = {}

        xml_string = project.get('workspace', '')
        if not xml_string:
            return

        try:
            root = ET.fromstring(xml_string)
        except Exception:
            return

        def _strip_ns(tag):
            return tag.split('}')[-1]

        def _extract_fields(block_elem):
            fields = {}
            for child in block_elem:
                if _strip_ns(child.tag) == 'field':
                    fname = child.get('name')
                    if fname:
                        fields[fname] = child.text or ''
            return fields

        def _extract_shadow_value(value_elem):
            """If a <value> slot holds a <shadow> with a literal field, return the
            field's text. Return None for non-literal shadows."""
            for child in value_elem:
                ctag = _strip_ns(child.tag)
                if ctag == 'shadow':
                    f = child.find('field')
                    if f is not None:
                        return (f.text or '').strip()
            return None

        def traverse(node, current_parent=None, edge_type=None, slot=None):
            tag_name = _strip_ns(node.tag)

            if tag_name == 'block':
                b_id = node.get('id') or f'gen_{len(self.blocks)}'
                b_type = node.get('type', 'unknown')
                b_x = node.get('x')
                b_y = node.get('y')
                fields = _extract_fields(node)

                self._register_block(
                    b_id, b_type,
                    x=float(b_x) if b_x else None,
                    y=float(b_y) if b_y else None,
                    fields=fields,
                )

                if current_parent is None:
                    is_hat = any(p in b_type for p in self.HAT_BLOCK_PATTERNS)
                    self.orphan_status[b_id] = not is_hat
                else:
                    self.orphan_status[b_id] = self.orphan_status.get(current_parent, False)
                    self._link(current_parent, b_id, edge_type, slot)

                for child in node:
                    child_tag = _strip_ns(child.tag)
                    if child_tag == 'value':
                        cslot = child.get('name')
                        shadow_val = _extract_shadow_value(child)
                        if shadow_val is not None:
                            self.blocks[b_id]['fields'][cslot or 'value'] = shadow_val
                        traverse(child, b_id, 'value', cslot)
                    elif child_tag in ('next', 'statement'):
                        cslot = child.get('name') if child_tag == 'statement' else None
                        traverse(child, b_id, child_tag, cslot)
                    elif child_tag == 'field':
                        pass  # already captured
                    else:
                        traverse(child, b_id, edge_type, slot)

            elif tag_name == 'shadow':
                pass  # value-slot shadows are captured into the parent's fields above

            elif tag_name == 'value':
                cslot = node.get('name')
                shadow_val = _extract_shadow_value(node)
                if shadow_val is not None and current_parent is not None:
                    self.blocks[current_parent]['fields'][cslot or 'value'] = shadow_val
                for child in node:
                    traverse(child, current_parent, 'value', cslot)

            else:
                for child in node:
                    traverse(child, current_parent, edge_type, slot)

        traverse(root)

    def _recompute_orphans(self):
        """Rebuild orphan_status from scratch by walking down from hat roots. Called
        after every delta move/delete/create so the active/orphan split stays correct
        without relying on incremental cascade logic."""
        self.orphan_status = {bid: True for bid in self.blocks}

        all_children = set()
        for entries in self.parent_map.values():
            all_children.update(e['child_id'] for e in entries)

        roots = [b for b in self.blocks if b not in all_children]
        for r in roots:
            is_hat = any(p in self.blocks[r]['type'] for p in self.HAT_BLOCK_PATTERNS)
            if not is_hat:
                continue
            visited = set()
            stack = [r]
            while stack:
                bid = stack.pop()
                if bid in visited:
                    continue
                visited.add(bid)
                self.orphan_status[bid] = False
                for entry in self.parent_map.get(bid, []):
                    stack.append(entry['child_id'])

    def _delete_recursive(self, block_id, visited=None):
        if visited is None:
            visited = set()
        if block_id in visited:
            return
        visited.add(block_id)

        if block_id in self.blocks:
            del self.blocks[block_id]
        if block_id in self.orphan_status:
            del self.orphan_status[block_id]

        children = self.parent_map.pop(block_id, [])
        for entry in children:
            self._delete_recursive(entry['child_id'], visited)

    def get_runnable_block_count(self):
        return sum(1 for b in self.blocks
                   if not self.blocks[b].get('is_shadow')
                   and not self.orphan_status.get(b, True))

    def get_total_blocks(self):
        return sum(1 for b in self.blocks if not self.blocks[b].get('is_shadow'))

    def generate_compact_prompt(self):
        """Render the workspace as compact pseudo-code the LLM can read. I split the
        root blocks into two sections, [Active] (reachable from a hat block) and
        [Orphaned], and print each block with its fields, indented by how deep it
        sits. Value-slot children (inline reporters like conditions and sensor reads)
        render indented under their parent. Next/statement children chain at the same
        or deeper indentation. I strip the common VEX type prefixes to keep the token
        count down."""
        all_children = set()
        for entries in self.parent_map.values():
            all_children.update(e['child_id'] for e in entries)

        roots = [b for b in self.blocks
                 if b not in all_children and not self.blocks[b].get('is_shadow')]
        roots.sort()

        runnable_roots = [b for b in roots if not self.orphan_status.get(b, True)]
        orphan_roots = [b for b in roots if self.orphan_status.get(b, True)]

        def clean_type(raw):
            """Drop the noisy VEX prefixes so the listing is shorter."""
            for prefix in ('pg_', 'aim_', 'mixed_'):
                if raw.startswith(prefix):
                    return raw[len(prefix):]
            return raw

        def build_tree(block_id, depth, visited=None):
            if visited is None:
                visited = set()
            if block_id in visited:
                return ""
            visited.add(block_id)

            block = self.blocks.get(block_id)
            if block is None:
                return ""
            name = clean_type(block.get('type', '?'))
            fields = block.get('fields', {})

            parts = [name]
            if fields:
                parts.append("(" + ",".join(f'{k}={v}' for k, v in fields.items()) + ")")

            line = " " * depth + " ".join(parts) + "\n"

            for entry in self.parent_map.get(block_id, []):
                child_id = entry['child_id']
                if self.blocks.get(child_id, {}).get('is_shadow'):
                    continue
                edge = entry['edge_type']
                child_depth = depth + 1 if edge == 'value' else depth + 1
                line += build_tree(child_id, child_depth, visited)
            return line

        lines = []
        lines.append("[Active]")
        if runnable_roots:
            for r in runnable_roots:
                lines.append(build_tree(r, 1).rstrip())
        else:
            lines.append(" (empty)")

        lines.append("[Orphaned]")
        if orphan_roots:
            for o in orphan_roots:
                lines.append(build_tree(o, 1).rstrip())
        else:
            lines.append(" (empty)")

        return "\n".join(lines)


def generate_compact_prompt_from_project(project_json_str):
    """Shortcut for when I just have a project blob (the `project` field off a VEX
    log) and want the prompt in one call. Spins up a fresh engine, bootstraps it,
    and hands back the rendered prompt. Gives None if there's no input or the
    project turned out to have no blocks."""
    if project_json_str is None:
        return None

    engine = SmartDeltaEngine()

    # Fake up a loadProject event so I can reuse _bootstrap_from_xml as-is.
    engine._bootstrap_from_xml({
        'eventType': 'loadProject',
        'project': project_json_str
    })

    if not engine.blocks:
        return None

    return engine.generate_compact_prompt()
