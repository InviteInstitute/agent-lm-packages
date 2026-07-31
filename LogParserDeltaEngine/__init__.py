"""
LogParserDeltaEngine: take a student's VEX log stream and rebuild what their Blockly
workspace looks like right now, then render it as compact pseudo-code I can feed to
an LLM.

  from LogParserDeltaEngine import SmartDeltaEngine, generate_llm_prompt_from_project

Stdlib only (json, xml.etree), no dependencies to install.
"""
from .smart_delta import SmartDeltaEngine, generate_llm_prompt_from_project

__all__ = ["SmartDeltaEngine", "generate_llm_prompt_from_project"]
