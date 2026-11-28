"""
log_parser_delta_engine: take a student's VEX workspace and render it as pseudo-code.
Two renderers live here:

  generate_compact_prompt          compact, token-cheap, [Active]/[Orphaned] split (LLM)
  generate_readable_text / _lines  full names, infix operators, inline values, live code
                                   first and orphans after (human)

Both decide what can run with liveness.py (hat stacks and the My Blocks they call).
generate_compact_prompt_from_project takes the raw `content.project` value of a VEX log
event instead of the XML.

  from log_parser_delta_engine import (
      generate_compact_prompt, generate_compact_prompt_from_project,
      generate_readable_text, generate_readable_lines,
  )

Stdlib only (json, xml.etree), no dependencies to install.
"""
from .humanize import generate_readable_lines, generate_readable_text
from .liveness import extract_workspace_xml
from .smart_delta import generate_compact_prompt


def generate_compact_prompt_from_project(project):
    """One-shot compact prompt from a raw VEX `project` value, the dict or JSON string
    stored in a log event's `content.project` field, which carries the `workspace`
    XML. Returns None if the project is empty/None or yields no blocks."""
    xml = extract_workspace_xml({"project": project})
    return generate_compact_prompt(xml) if xml else None


__all__ = [
    "generate_compact_prompt",
    "generate_compact_prompt_from_project",
    "generate_readable_text",
    "generate_readable_lines",
]
