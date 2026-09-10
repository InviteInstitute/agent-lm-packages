"""OI-7 drivetrain lockout (built 2026-08-25) — the reviewer-probed rule:
the most recently CREATED when_started stack owns the drivetrain outright;
losers' drivetrain commands are no-ops. Precedence comes from longitudinal
snapshots (creation_order + the ccp session_snapshots adapter); absent or
unresolved precedence keeps the legacy sequential approximation and its
honest flag, byte-identically."""
from __future__ import annotations

import textwrap
from types import SimpleNamespace

from goal_strategy.detector.parsing.parse_blocks import parse_workspace
from goal_strategy.detector.simulation.simulate_path import (
    PlaygroundContext, simulate_path,
)

from goal_strategy.ccp_runs import session_snapshots, stack_precedence_map

from goal_strategy.tests.test_hat_execution import drive_for, workspace

CARD = textwrap.dedent("""
    playground_id: toy
    field_geometry: {playable_radius_mm: 60000}
    spawn_points: {default_start: {x: 0, y: 0, heading: 0}}
    robot: {width_mm: 50.8}
""")

MAGNET = ('<block type="pg_magnet_set_magnet_state" id="m1">'
          '<field name="MAGNET">Magnet</field>'
          '<field name="ACTION">boost</field></block>')


def ctx():
    import yaml
    return PlaygroundContext.from_playground_card(yaml.safe_load(CARD), {})


def two_stacks(a_body, b_body):
    return workspace(
        f'<block type="pg_events_when_started" id="hatA"><next>{a_body}</next></block>',
        f'<block type="pg_events_when_started" id="hatB"><next>{b_body}</next></block>')


def test_winner_owns_drivetrain_outright():
    # A drives 1000, B drives 400; B wins -> only B's motion happens.
    xml = two_stacks(drive_for(1000), drive_for(400))
    sim = simulate_path(parse_workspace(xml, "t"), ctx(), stack_precedence="hatB")
    assert sim.stack_lockout_winner == "hatB"
    assert abs(sim.net_displacement_from_spawn - 400) < 1e-6
    assert "concurrent_stacks_unverified" not in sim.execution_flags


def test_loser_non_drivetrain_effects_still_run():
    # loser A: drive then magnet — drive suppressed, magnet fires; the
    # drive+effect pairing carries the open timing probe's flag
    xml = two_stacks(drive_for(1000).replace("</block>",
                                             f"<next>{MAGNET}</next></block>"),
                     drive_for(400))
    sim = simulate_path(parse_workspace(xml, "t"), ctx(), stack_precedence="hatB")
    assert sim.magnet_fires_at_step is not None
    assert abs(sim.net_displacement_from_spawn - 400) < 1e-6
    assert "stack_lockout_timing_assumed" in sim.execution_flags


def test_no_precedence_is_byte_identical_legacy():
    xml = two_stacks(drive_for(1000), drive_for(400))
    legacy = simulate_path(parse_workspace(xml, "t"), ctx())
    assert "concurrent_stacks_unverified" in legacy.execution_flags
    assert legacy.stack_lockout_winner is None
    # sequential approximation sums both stacks' motion
    assert abs(legacy.net_displacement_from_spawn - 1400) < 1e-6


def test_unmatched_precedence_falls_back_with_flag():
    xml = two_stacks(drive_for(1000), drive_for(400))
    sim = simulate_path(parse_workspace(xml, "t"), ctx(),
                        stack_precedence="not_a_hat")
    assert "concurrent_stacks_unverified" in sim.execution_flags
    assert sim.stack_lockout_winner is None
    assert abs(sim.net_displacement_from_spawn - 1400) < 1e-6


def test_single_stack_ignores_precedence():
    xml = workspace('<block type="pg_events_when_started" id="hatA">'
                    f'<next>{drive_for(250)}</next></block>')
    sim = simulate_path(parse_workspace(xml, "t"), ctx(), stack_precedence="hatA")
    assert sim.stack_lockout_winner is None
    assert abs(sim.net_displacement_from_spawn - 250) < 1e-6


# ── the ccp adapter ──

def _run(session, num, seq, xml, warm=False, student="S1"):
    return SimpleNamespace(run_id=f"{session}_r{seq}", derived_session_id=session,
                           derived_session_num=num, run_seq=seq,
                           student_study_id=student, workspace_xml=xml,
                           starts_with_existing_code=warm)


def test_session_snapshots_chains_warm_starts():
    s1 = _run("S1_A", 1, 1, two_stacks(drive_for(10), drive_for(20)))
    s2 = _run("S1_B", 2, 1, two_stacks(drive_for(10), drive_for(20)), warm=True)
    cold = _run("S1_B", 2, 2, two_stacks(drive_for(10), drive_for(20)))
    runs = [s1, s2, cold]
    snaps = session_snapshots(runs, "S1_B")
    assert [k for k, _ in snaps] == [(1, 1), (2, 1), (2, 2)]   # chained back
    assert session_snapshots(runs, "S1_A") == [((1, 1), s1.workspace_xml)]
    # cold session start: no chaining
    s2.starts_with_existing_code = False
    assert [k for k, _ in session_snapshots(runs, "S1_B")] == [(2, 1), (2, 2)]


def test_stack_precedence_map_resolves_new_stack():
    # session: run 1 has only hatA; run 2 adds hatB -> hatB most recent
    one = workspace('<block type="pg_events_when_started" id="hatA">'
                    f'<next>{drive_for(100)}</next></block>')
    both = two_stacks(drive_for(100), drive_for(50))
    runs = [_run("S1_A", 1, 1, one), _run("S1_A", 1, 2, both)]
    prec = stack_precedence_map(runs)
    assert prec == {"S1_A_r2": "hatB"}   # run 1 has one stack: not mapped


def test_monitor_winner_is_gated_out():
    # the newest stack is a conditional MONITOR (drive only inside an if):
    # outside the probed configuration -> no precedence emitted (2026-08-25
    # falsification: 25 agreeing runs regressed under monitor-winner lockout)
    driver = ('<block type="pg_events_when_started" id="hatA">'
              f'<next>{drive_for(100)}</next></block>')
    monitor_body = ('<block type="pg_control_if_then" id="if1">'
                    f'<statement name="SUBSTACK">{drive_for(50)}</statement>'
                    '</block>')
    both = workspace(driver,
                     '<block type="pg_events_when_started" id="hatB">'
                     f'<next>{monitor_body}</next></block>')
    runs = [_run("S1_A", 1, 1, driver.join(['<xml xmlns="https://developers.google.com/blockly/xml">', '</xml>'])),
            _run("S1_A", 1, 2, both)]
    assert stack_precedence_map(runs) == {}   # hatB resolves but is a monitor


def test_stack_precedence_map_censored_window_unmapped():
    both = two_stacks(drive_for(100), drive_for(50))
    runs = [_run("S1_A", 1, 1, both), _run("S1_A", 1, 2, both)]
    assert stack_precedence_map(runs) == {}   # both predate the window
