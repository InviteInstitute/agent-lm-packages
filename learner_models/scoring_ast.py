"""Build scoring trees with literal parameters and only when-started stacks.

The general workspace parser remains unchanged for rendering and other callers.
This root policy is structural, not a procedure-call graph analysis.
"""
import xml.etree.ElementTree as ET
from .ast_builder import xml_to_block_ast

def xml_to_parameter_ast(xml: str) -> dict:
    """Preserve reference NUM/TEXT inputs without adding shadow block costs.

    The literal extraction intentionally matches the supplied notebook, including
    its treatment of real literal blocks. Structural ordering and generated IDs
    follow the pinned iterative parser. This is parser parity, not a change to
    upstream's all-roots versus executable-only distance policy.
    """
    result = xml_to_block_ast(xml, keep_shadow=False)
    if not result['nodes']:
        return result
    root = ET.fromstring(xml)
    for element in root.iter():
        element.tag = element.tag.split('}')[-1]
    literal_types = {'math_number', 'math_whole_number', 'math_positive_number',
                     'math_number_string', 'text'}
    pending = list(reversed([e for e in root if e.tag == 'block']))
    # Visit only registered real blocks, in exactly the upstream parser's order.
    # zip against ordered AST IDs also handles XML without explicit block IDs.
    for node_id in result['nodes']:
        if not pending:
            raise ValueError('Reference literal extraction differs from structural AST traversal')
        block = pending.pop()
        for value in block:
            if value.tag != 'value':
                continue
            for child in value:
                if child.tag not in {'shadow', 'block'} or child.get('type') not in literal_types:
                    continue
                fields = {f.get('name'): (f.text or '').strip() for f in child
                          if f.tag == 'field' and f.get('name')}
                name = value.get('name')
                if 'NUM' in fields:
                    result['nodes'][node_id]['fields'][name] = fields['NUM']
                elif 'TEXT' in fields:
                    result['nodes'][node_id]['fields'][name] = fields['TEXT']
                elif fields:
                    result['nodes'][node_id]['fields'][name] = fields
        children = [child for connection in block if connection.tag in {'value', 'statement', 'next'}
                    for child in connection if child.tag == 'block']
        pending.extend(reversed(children))
    if pending:
        raise ValueError('Reference literal extraction left unregistered real blocks')
    return result


def executable_ast(ast: dict) -> dict:
    """Keep only nodes reachable from pg_events_when_started roots.

    Filter nodes and edges as well as roots, so detached blocks also do not count
    toward the size guard. Multiple start stacks are included; with no start
    root, the executable AST is empty. This matches the notebook's root policy.
    """
    roots = [node for node in ast['roots']
             if ast['nodes'][node]['type'] == 'pg_events_when_started']
    children = {}
    for edge in ast['edges']:
        children.setdefault(edge['source'], []).append(edge['target'])
    reachable = set()
    pending = list(roots)
    while pending:
        node = pending.pop()
        if node in reachable:
            continue
        reachable.add(node)
        pending.extend(children.get(node, []))
    return dict(nodes={k: v for k, v in ast['nodes'].items() if k in reachable},
                edges=[e for e in ast['edges'] if e['source'] in reachable and e['target'] in reachable],
                roots=roots)


def scoring_ast(xml: str) -> dict:
    """Return the executable, parameter-preserving scoring representation."""
    return executable_ast(xml_to_parameter_ast(xml))
