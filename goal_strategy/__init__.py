"""goal_strategy — lightweight goal-recognition pipeline.

One function is the product: profile(workspace_xml, program_id, ...) -> GoalProfile.
"""
from .profile import GoalEvidence, GoalProfile, Indicator, profile

__all__ = ["profile", "GoalProfile", "GoalEvidence", "Indicator"]

from .adapter import (
    goal_profile, goal_profile_from_content, goal_profile_from_run_event,
    goal_profiles_from_events,
)
from .streaming import GoalProfileStream
from .serialize import profile_to_dict, PIPELINE_VERSION

__all__ += ["goal_profile", "goal_profile_from_content", "goal_profile_from_run_event",
            "goal_profiles_from_events", "GoalProfileStream", "profile_to_dict", "PIPELINE_VERSION"]
