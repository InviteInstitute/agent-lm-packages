"""
learner_models: take a student's VEX event stream and turn it into behavioral signals
to act on. Everything in here is pure, no DB and no framework.

The main path:

  runProject events  -> compute_run_edit_distances  -> how much changed per run
  those distances    -> detect_run_triggers_by_playground -> the 4 momentary triggers
  the whole stream   -> segment_session             -> episodes (CODE/RUN/RESET + pauses)

And the 5th trigger, which is time-based instead of edit-based:

  inactive           -> detect_inactive_trigger      -> idle fire, DB left to the caller

And identity switches (casing / class changes on a tracked handle):

  detect_switches    -> the (kind, from, to) switches one event represents

Public API:
  compute_run_edit_distances, RunDistanceStream   (run_sequence)
  detect_run_triggers, detect_run_triggers_by_playground   (triggers)
  is_inactive, detect_inactive_trigger, INACTIVE_RUN_INDEX  (triggers)
  segment_session, segment_episodes, boundary_kind          (episodes)
  SessionSegmenter (incremental segment_session)            (episodes)
  cached_edit_distance, clear_cache                         (distance)
  xml_to_block_ast, extract_workspace_xml                   (ast_builder)
  detect_switches                             (switches)

Workspace rendering (compact + readable) lives in log_parser_delta_engine.

Needs the `apted` package (see requirements.txt). Everything else is stdlib.
"""
from .ast_builder import extract_workspace_xml, xml_to_block_ast
from .constants import boundary_kind
from .distance import cached_edit_distance, clear_cache
from .episodes import SessionSegmenter, segment_episodes, segment_session
from .run_sequence import RunDistanceStream, compute_run_edit_distances
from .switches import detect_switches
from .triggers import (
    INACTIVE_RUN_INDEX,
    detect_inactive_trigger,
    detect_run_triggers,
    detect_run_triggers_by_playground,
    is_inactive,
)

__all__ = [
    "INACTIVE_RUN_INDEX",
    "RunDistanceStream",
    "SessionSegmenter",
    "boundary_kind",
    "cached_edit_distance",
    "clear_cache",
    "compute_run_edit_distances",
    "detect_inactive_trigger",
    "detect_run_triggers",
    "detect_run_triggers_by_playground",
    "detect_switches",
    "extract_workspace_xml",
    "is_inactive",
    "segment_episodes",
    "segment_session",
    "xml_to_block_ast",
]
