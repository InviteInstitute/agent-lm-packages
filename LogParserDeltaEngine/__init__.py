"""
LogParserDeltaEngine: take a student's VEX log stream and rebuild what their VEX
workspace looks like right now, then render it as pseudo-code. Two renderers live here:

  generate_compact_prompt[_from_project]   compact, token-cheap, [Active]/[Orphaned] split (LLM)
  generate_readable_text / _lines          full names, infix operators, inline values (human)

  from LogParserDeltaEngine import (
      SmartDeltaEngine, generate_compact_prompt_from_project,
      generate_readable_text, generate_readable_lines,
  )

Stdlib only (json, xml.etree), no dependencies to install.
"""
from .smart_delta import SmartDeltaEngine, generate_compact_prompt_from_project
from .humanize import generate_readable_text, generate_readable_lines

__all__ = [
    "SmartDeltaEngine",
    "generate_compact_prompt_from_project",
    "generate_readable_text",
    "generate_readable_lines",
]
