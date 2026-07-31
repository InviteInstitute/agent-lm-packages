"""
LogParserDeltaEngine: take a student's VEX log stream and rebuild what their VEX
workspace looks like right now, then render it as pseudo-code. Two renderers live here:

  generate_compact_prompt          compact, token-cheap, [Active]/[Orphaned] split (LLM)
  generate_readable_text / _lines  full names, infix operators, inline values (human)

Each renderer has a _from_content variant that takes a parsed VEX log content dict
and extracts the workspace XML internally.

  from LogParserDeltaEngine import (
      smart_delta_engine, generate_compact_prompt, generate_compact_prompt_from_content,
      generate_readable_text, generate_readable_text_from_content,
      generate_readable_lines, generate_readable_lines_from_content,
  )

Stdlib only (json, xml.etree), no dependencies to install.
"""
import json

from .smart_delta import smart_delta_engine, generate_compact_prompt
from .humanize import generate_readable_text, generate_readable_lines


def _extract_workspace_xml(content):
    """Extract the workspace XML string from a parsed VEX log content dict. The
    `project` field can be a dict or a JSON string, so both are handled. Returns
    "" when there's nothing usable."""
    if not isinstance(content, dict):
        return ""
    project = content.get("project", {})
    if isinstance(project, str):
        try:
            project = json.loads(project)
        except (json.JSONDecodeError, ValueError):
            return ""
    if not isinstance(project, dict):
        return ""
    return project.get("workspace", "") or ""


def generate_compact_prompt_from_content(content):
    """One-shot compact prompt from a parsed VEX log content dict. Extracts the
    workspace XML internally. Returns None if the content has no workspace or no
    blocks."""
    xml = _extract_workspace_xml(content)
    return generate_compact_prompt(xml) if xml else None


def generate_readable_text_from_content(content):
    """One-shot readable pseudo-code from a parsed VEX log content dict. Extracts
    the workspace XML internally. Returns "" if the content has no workspace."""
    return generate_readable_text(_extract_workspace_xml(content))


def generate_readable_lines_from_content(content):
    """One-shot readable pseudo-code lines from a parsed VEX log content dict.
    Extracts the workspace XML internally. Returns [] if the content has no
    workspace."""
    return generate_readable_lines(_extract_workspace_xml(content))


__all__ = [
    "smart_delta_engine",
    "generate_compact_prompt",
    "generate_compact_prompt_from_content",
    "generate_readable_text",
    "generate_readable_text_from_content",
    "generate_readable_lines",
    "generate_readable_lines_from_content",
]
