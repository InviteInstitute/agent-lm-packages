"""The online purpose-2 rubric channel (include_rubric).

Rubric is PROVISIONAL (rubric_status = provisional_stage2E). These tests pin
the contract: off by default, an opt-in provisional envelope with all six
dimensions, JSON-safe, cache-isolated, deterministic, census-decidable from
code alone, and identical between the batch and streaming paths.
"""
import json

from goal_strategy import goal_profile, goal_profiles_from_events, GoalProfileStream
from goal_strategy.tests.test_hat_execution import drive_for, turn_for, workspace
from goal_strategy.tests.test_scheduler import started


def _sensing_gated():
    """A sensing conditional gating motion inside a forever loop - exercises
    state-dependent control (CS-2) and executed state-gated motion (SMC-2)."""
    branch_true = ('<block type="pg_drivetrain_turn_for" id="t">'
                   '<field name="TURNDIRECTION">right</field><field name="UNITS">deg</field>'
                   '<value name="AMOUNT"><shadow type="math_number">'
                   '<field name="NUM">90</field></shadow></value></block>')
    branch_false = drive_for(200)
    cond = ('<block type="pg_control_if_then_else" id="if">'
            '<value name="CONDITION">'
            '<block type="pg_sensing_distance_object_distance" id="s"/></value>'
            f'<statement name="SUBSTACK">{branch_true}</statement>'
            f'<statement name="SUBSTACK2">{branch_false}</statement></block>')
    forever = (f'<block type="pg_control_forever" id="f">'
               f'<statement name="SUBSTACK">{cond}</statement></block>')
    return workspace(started('A', forever))


def _dead_reckoner():
    """A fixed repeat of drive+turn with no sensing - the economy-rule case:
    EF / TSR / Recovery are census-decided to 0, CS is 1 from the loop."""
    body = ('<block type="pg_control_repeat" id="r"><value name="TIMES">'
            '<shadow type="math_number"><field name="NUM">4</field></shadow></value>'
            '<statement name="SUBSTACK">'
            + drive_for(500, nxt=f'<next>{turn_for(90)}</next>')
            + '</statement></block>')
    return workspace(started('A', body))


_DIMENSIONS = {"environmental_feedback", "control_structure", "spatial_motion",
               "representation", "task_state_regulation", "recovery"}


def test_rubric_absent_by_default():
    result = goal_profile(_sensing_gated(), "p/s/0")
    assert "rubric" in result          # the key always exists in the envelope
    assert result["rubric"] is None    # but nothing is computed unless asked


def test_rubric_present_and_provisional():
    result = goal_profile(_sensing_gated(), "p/s/0", include_rubric=True)
    rubric = result["rubric"]
    assert rubric["provisional"] is True
    assert rubric["status"] == "provisional_stage2E"
    assert set(rubric["dimensions"]) == _DIMENSIONS
    json.dumps(result, allow_nan=False)   # strict-JSON-safe end to end


def test_sensing_gated_scores_state_dependent_levels():
    dims = goal_profile(_sensing_gated(), "p/s/0",
                        include_rubric=True)["rubric"]["dimensions"]
    # a sensing conditional evaluated inside an exercised loop is a
    # coordination relation (CS-2); the gated motion executed (SMC-2).
    assert dims["control_structure"]["level"] == "2"
    assert dims["spatial_motion"]["level"] == "2"
    assert dims["representation"]["level"] == "1"


def test_dead_reckoner_is_census_decided_from_code():
    dims = goal_profile(_dead_reckoner(), "p/s/0",
                        include_rubric=True)["rubric"]["dimensions"]
    # no live sensing -> the economy rule ASSIGNS an informative zero, with
    # the census ceiling as the fired evidence (never U).
    for dim in ("environmental_feedback", "task_state_regulation", "recovery"):
        assert dims[dim]["level"] == "0"
        assert dims[dim]["ceiling"] == 0
        assert dims[dim]["fired"] == [
            {"evidence": "census.ceiling_zero", "level": 0, "strength": "census"}]
    # the loop ran -> structured repetition
    assert dims["control_structure"]["level"] == "1"


def test_rubric_is_deterministic():
    a = goal_profile(_sensing_gated(), "p/s/0", include_rubric=True)["rubric"]
    b = goal_profile(_sensing_gated(), "p/s/other", include_rubric=True)["rubric"]
    assert a == b   # program_id is a label only; scoring must not vary


def test_rubric_cache_isolated_from_no_rubric_call():
    xml = _sensing_gated()
    warmed = goal_profile(xml, "p/s/0", include_rubric=True)
    assert warmed["rubric"] is not None
    plain = goal_profile(xml, "p/s/0")     # same xml, flag off
    assert plain["rubric"] is None         # must not inherit the cached rubric


def test_batch_and_stream_agree_on_rubric():
    xml = _sensing_gated()
    event = {"event_type": "runProject", "ts": None,
             "content": {"playground": "CastleCrasherPlus",
                         "project": {"workspace": xml}}}
    batch = goal_profiles_from_events([event], session_id="p/s",
                                      include_rubric=True)["runs"][0]
    stream = GoalProfileStream("p/s", include_rubric=True)
    online = stream.push(event)
    assert batch["rubric"] == online["rubric"]
    assert batch["rubric"] is not None
