"""The online purpose-1 goal ROLLUP channel (include_rollup).

Pins the contract: off by default; an opt-in rolled-up view of all four goals;
the two battery-banded goals match the offline banded_rollup exactly; the debris
entry carries the three enrichment signals; the derived goals read from the
profile; JSON-safe; and the battery runs ONCE even with every channel on.
"""
import json

from goal_strategy import goal_profile, goal_profiles_from_events, GoalProfileStream
from goal_strategy.battery_rollup import banded_rollup, load_rollup_card
from goal_strategy.testcases import run_battery
from goal_strategy.config import load_configs
from goal_strategy.tests.test_hat_execution import drive_for, turn_for, workspace
from goal_strategy.tests.test_scheduler import started

_GOALS = {"clear_debris_zone", "remain_on_island", "engage_plow",
          "playground_engagement"}


def _clearing_run():
    body = ('<block type="pg_control_repeat" id="r"><value name="TIMES">'
            '<shadow type="math_number"><field name="NUM">3</field></shadow></value>'
            '<statement name="SUBSTACK">'
            + drive_for(800, nxt=f'<next>{turn_for(90)}</next>')
            + '</statement></block>')
    return workspace(started('A', body))


def test_rollup_absent_by_default():
    result = goal_profile(_clearing_run(), "p/s/0", {"weight_cleared": 1200})
    assert "rollup" in result           # key always present
    assert result["rollup"] is None     # computed only on request


def test_rollup_reports_all_four_goals():
    rollup = goal_profile(_clearing_run(), "p/s/0", {"weight_cleared": 1200},
                          include_rollup=True)["rollup"]
    assert rollup["provisional"] is False
    assert set(rollup["goals"]) == _GOALS


def test_battery_goals_match_offline_banded_rollup():
    xml, params = _clearing_run(), {"weight_cleared": 1200}
    online = goal_profile(xml, "p/s/0", params, include_rollup=True)["rollup"]["goals"]
    # recompute the way the offline pipeline does, over the same battery report
    report = run_battery(xml, "p/s/0", "castle_crashers", collect_sims=True)
    bands = banded_rollup(report, load_rollup_card("castle_crashers"))
    for goal in ("clear_debris_zone", "remain_on_island"):
        off = bands[goal]
        assert online[goal]["band"] == off.band
        assert online[goal]["label"] == off.label
        assert online[goal]["certainty"] == off.certainty
        assert online[goal]["source"] == "battery"


def test_debris_entry_carries_the_three_signals():
    debris = goal_profile(_clearing_run(), "p/s/0", {"weight_cleared": 1200},
                          include_rollup=True)["rollup"]["goals"]["clear_debris_zone"]["debris"]
    assert set(debris) >= {"proportion_cleared", "zone_coverage", "weight_cleared_kg"}
    assert debris["weight_cleared_kg"] == 1200.0        # telemetry surfaced
    assert debris["zone_coverage"] is not None          # simulated coverage present


def test_derived_goals_read_from_profile():
    goals = goal_profile(_clearing_run(), "p/s/0", {"weight_cleared": 1200},
                         include_rollup=True)["rollup"]["goals"]
    assert goals["playground_engagement"]["claim"] == "engaged"   # the robot moved
    assert goals["playground_engagement"]["source"] == "profile_derived"
    assert goals["engage_plow"]["source"] == "profile_derived"
    assert "claim" in goals["engage_plow"]


def test_rollup_is_json_safe_and_deterministic():
    a = goal_profile(_clearing_run(), "p/s/0", {"weight_cleared": 1200},
                     include_rollup=True)
    json.dumps(a, allow_nan=False)
    b = goal_profile(_clearing_run(), "p/s/other", {"weight_cleared": 1200},
                     include_rollup=True)
    assert a["rollup"] == b["rollup"]   # program_id is a label only


def test_battery_runs_once_with_every_channel(monkeypatch):
    load_configs.cache_clear()          # drop any cached result for this input
    import goal_strategy.testcases as tc
    real, calls = tc.run_battery, {"n": 0}

    def counting(*args, **kwargs):
        calls["n"] += 1
        return real(*args, **kwargs)

    monkeypatch.setattr(tc, "run_battery", counting)
    result = goal_profile(_clearing_run(), "p/s/once", {"weight_cleared": 1200},
                          include_battery=True, include_rubric=True, include_rollup=True)
    assert calls["n"] == 1                       # shared across all three channels
    assert len(result["battery"]["artifacts"]) == 0   # collected sims stripped from output


def test_batch_and_stream_agree_on_rollup():
    xml = _clearing_run()
    event = {"event_type": "runProject", "ts": None,
             "content": {"playground": "CastleCrasherPlus",
                         "project": {"workspace": xml}}}
    batch = goal_profiles_from_events([event], session_id="p/s",
                                      include_rollup=True)["runs"][0]
    online = GoalProfileStream("p/s", include_rollup=True).push(event)
    assert batch["rollup"] == online["rollup"]
    assert batch["rollup"] is not None
