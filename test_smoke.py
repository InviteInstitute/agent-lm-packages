"""Runnable smoke check for the packages. `python test_smoke.py`.
Needs `apted` (LearnerModels). Exercises the delta engine, the momentary triggers,
and the decoupled `inactive` seam."""
from datetime import datetime, timedelta, timezone

from LogParserDeltaEngine import generate_compact_prompt
from LearnerModels import detect_run_triggers, detect_inactive_trigger, INACTIVE_RUN_INDEX


def test_delta_engine_bootstraps_from_xml():
    xml = (
        '<xml>'
        '  <block type="events_whenStarted" id="hat" x="0" y="0">'
        '    <statement name="STACK"><block type="pg_drive" id="child"/></statement>'
        '  </block>'
        '  <block type="pg_turn" id="loose" x="200" y="200"/>'
        '</xml>'
    )
    prompt = generate_compact_prompt(xml)
    assert prompt is not None
    assert "whenStarted" in prompt and "drive" in prompt
    assert "[Active]" in prompt and "[Orphaned]" in prompt
    assert generate_compact_prompt(None) is None


def test_momentary_triggers_fire():
    fired = {t for (t, _i, _d) in detect_run_triggers([None, 0, 0, 0, 0, 0, 0, 20])}
    assert "wheel_spin" in fired and "explorer" in fired
    assert "resilience" in {t for (t, _i, _d) in detect_run_triggers([None, 0, 0, 0, 0, 3])}


def test_inactive_seam_is_pure():
    now = datetime.now(timezone.utc)
    idle = now - timedelta(minutes=10)          # past INACTIVE_TRIGGER_SECONDS=240
    # First fire: no prior inactive fire.
    fire = detect_inactive_trigger(idle, now=now, last_inactive_fire=None)
    assert fire is not None and fire[0] == "inactive" and fire[1] == INACTIVE_RUN_INDEX
    # Just fired -> not due for a re-alert yet.
    assert detect_inactive_trigger(idle, now=now, last_inactive_fire=(-1, now)) is None
    # Not idle -> no fire.
    assert detect_inactive_trigger(now, now=now) is None


if __name__ == "__main__":
    test_delta_engine_bootstraps_from_xml()
    test_momentary_triggers_fire()
    test_inactive_seam_is_pure()
    print("ok: LogParserDeltaEngine + LearnerModels (5 triggers) smoke test passed")
