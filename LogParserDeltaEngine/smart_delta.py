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
        self.blocks = {}         # block_id -> {type, x, y, fields}
        self.parent_map = {}     # parent_id -> [child_id, ...]
        self.orphan_status = {}  # block_id -> True if it's NOT reachable from a hat

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
            if 'shadow' not in block_type.lower():
                self.blocks[block_id] = {
                    'type': block_type,
                    'x': None,
                    'y': None,
                    'fields': {}
                }
                self.orphan_status[block_id] = True

        elif b_type == 'move':
            self._sever_from_parents(block_id)

            new_info = block_data.get('newInfo', {})

            if 'parent' in new_info:
                new_parent = new_info['parent']
                self.parent_map.setdefault(new_parent, []).append(block_id)

                # It's attached to a parent now, so its floating x/y don't mean anything.
                if block_id in self.blocks:
                    self.blocks[block_id]['x'] = None
                    self.blocks[block_id]['y'] = None

                p_orphan = self.orphan_status.get(new_parent, False)
                self.orphan_status[block_id] = p_orphan
                self._cascade_orphan(block_id, p_orphan, set())

            elif 'coordinate' in new_info:
                coord = new_info['coordinate']
                if block_id in self.blocks:
                    self.blocks[block_id]['x'] = coord.get('x')
                    self.blocks[block_id]['y'] = coord.get('y')

                self.orphan_status[block_id] = True
                self._cascade_orphan(block_id, True, set())

        elif b_type == 'delete':
            self._sever_from_parents(block_id)
            self._delete_recursive(block_id, set())

        elif b_type == 'change':
            field_name = block_data.get('name')
            new_value = block_data.get('newValue')
            if block_id in self.blocks and field_name:
                self.blocks[block_id]['fields'][field_name] = new_value

    def _sever_from_parents(self, block_id):
        keys_to_remove = []
        for p_id, children in self.parent_map.items():
            if block_id in children:
                children.remove(block_id)
                if not children:
                    keys_to_remove.append(p_id)
        for k in keys_to_remove:
            del self.parent_map[k]

    def _bootstrap_from_xml(self, content):
        """Dump whatever I have and rebuild the maps by walking the project's
        workspace XML from scratch. A block at the root is only live if it's a hat,        as I walk down, every child just inherits whatever its parent's orphan
        status was."""
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

        def traverse(node, current_parent=None):
            tag_name = node.tag.split('}')[-1]

            if tag_name == 'block':
                b_id = node.get('id')
                b_type = node.get('type', 'unknown')
                b_x = node.get('x')
                b_y = node.get('y')

                # Pull the field values off the block's own <field> children.
                fields = {}
                for child in node:
                    child_tag = child.tag.split('}')[-1]
                    if child_tag == 'field':
                        fname = child.get('name')
                        if fname:
                            fields[fname] = child.text or ''

                self.blocks[b_id] = {
                    'type': b_type,
                    'x': float(b_x) if b_x else None,
                    'y': float(b_y) if b_y else None,
                    'fields': fields
                }

                if current_parent is None:
                    # Sitting at the root: it's live only if it's a hat (event
                    # handler or procedure def). Everything else up here is orphaned.
                    is_hat = any(p in b_type for p in self.HAT_BLOCK_PATTERNS)
                    self.orphan_status[b_id] = not is_hat
                else:
                    self.orphan_status[b_id] = self.orphan_status.get(current_parent, False)
                    self.parent_map.setdefault(current_parent, []).append(b_id)

                for t in node:
                    traverse(t, b_id)

            elif tag_name == 'shadow':
                pass
            else:
                for t in node:
                    traverse(t, current_parent)

        traverse(root)

    def _cascade_orphan(self, parent_id, status, visited=None):
        if visited is None:
            visited = set()
        if parent_id in visited:
            return
        visited.add(parent_id)

        children = self.parent_map.get(parent_id, [])
        for c in children:
            self.orphan_status[c] = status
            self._cascade_orphan(c, status, visited)

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
        for c in children:
            self._delete_recursive(c, visited)

    def get_runnable_block_count(self):
        return sum(1 for b in self.blocks if not self.orphan_status.get(b, True))

    def get_total_blocks(self):
        return len(self.blocks)

    def generate_compact_prompt(self):
        """Render the workspace as compact pseudo-code the LLM can read. I split the
        root blocks into two sections, [Active] (reachable from a hat) and
        [Orphaned], and print each block with its fields, indented by how deep it
        sits. I strip the common VEX type prefixes to keep the token count down."""
        all_children = set()
        for children in self.parent_map.values():
            all_children.update(children)

        roots = [b for b in self.blocks if b not in all_children]
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

            block = self.blocks.get(block_id, {})
            name = clean_type(block.get('type', '?'))
            fields = block.get('fields', {})

            parts = [name]
            if fields:
                parts.append("(" + ",".join(f'{k}={v}' for k, v in fields.items()) + ")")

            line = " " * depth + " ".join(parts) + "\n"

            for child in self.parent_map.get(block_id, []):
                line += build_tree(child, depth + 1, visited)
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
