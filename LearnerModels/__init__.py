"""
LearnerModels: take a student's VEX event stream and turn it into behavioral signals
I can act on. Everything in here is pure, no DB and no framework.

The main path:

  runProject events  -> compute_run_edit_distances  -> how much changed per run
  those distances    -> detect_run_triggers_by_playground -> the 4 momentary triggers
  the whole stream   -> segment_session             -> episodes (CODE/RUN/RESET + pauses)

And the 5th trigger, which is time-based instead of edit-based:

  inactive           -> detect_inactive_trigger      -> idle fire, DB left to the caller

What you can import:
  compute_run_edit_distances      (run_sequence)
  detect_run_triggers, detect_run_triggers_by_playground   (triggers)
  is_inactive, detect_inactive_trigger, INACTIVE_RUN_INDEX  (triggers)
  segment_session                 (episodes)
  humanize_text                   (humanize): workspace XML into readable pseudo-code
  cached_edit_distance            (distance)

Needs the `apted` package (see requirements.txt); everything else is stdlib.
"""
from .run_sequence import compute_run_edit_distances
from .triggers import (
    detect_run_triggers, detect_run_triggers_by_playground,
    is_inactive, detect_inactive_trigger, INACTIVE_RUN_INDEX,
)
from .episodes import segment_session
from .humanize import humanize_text
from .distance import cached_edit_distance

__all__ = [
    "compute_run_edit_distances",
    "detect_run_triggers",
    "detect_run_triggers_by_playground",
    "is_inactive",
    "detect_inactive_trigger",
    "INACTIVE_RUN_INDEX",
    "segment_session",
    "humanize_text",
    "cached_edit_distance",
]
