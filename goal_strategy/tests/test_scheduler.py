"""VR-Seq Stage 2 (BUILD_SPEC §2): cooperative scheduler semantics —
interleaving, shared last-write-wins drivetrain, supersession policies,
global stop, per-thread gating. Single-stack identity is pinned separately
in test_scheduler_identity.py (gate G3)."""
from __future__ import annotations

import textwrap

import yaml

from goal_strategy.detector.parsing.parse_blocks import parse_workspace
from goal_strategy.detector.simulation.simulate_path import (
    PlaygroundContext, simulate_path,
)

from goal_strategy.tests.test_hat_execution import drive_for, turn_for, workspace

CARD = yaml.safe_load(textwrap.dedent("""
    playground_id: toy
    field_geometry: {playable_radius_mm: 60000}
    spawn_points: {default_start: {x: 0, y: 0, heading: 0}}
    robot: {width_mm: 50.8}
"""))

MAGNET = ('<block type="pg_magnet_set_magnet_state" id="m1">'
          '<field name="MAGNET">Magnet</field>'
          '<field name="ACTION">boost</field></block>')


def ctx():
    return PlaygroundContext.from_playground_card(CARD, {})


def started(sid, body):
    return (f'<block type="pg_events_when_started" id="{sid}">'
            f'<next>{body}</next></block>')


def wait_block(seconds, nxt=""):
    return (f'<block type="pg_control_wait" id="w{seconds}">'
            f'<value name="TIME"><shadow type="math_number">'
            f'<field name="NUM">{seconds}</field></shadow></value>{nxt}</block>')


def coop(xml, **kw):
    return simulate_path(parse_workspace(xml, "t"), ctx(),
                         scheduler="cooperative", **kw)


def test_same_tick_supersession_last_write_wins():
    # both threads issue *_for in the first runnable phase: B's write
    # supersedes A's before any motion commits — B's 400mm is all that runs
    xml = workspace(started("A", drive_for(1000)), started("B", drive_for(400)))
    sim = coop(xml)
    assert abs(sim.net_displacement_from_spawn - 400) < 1e-6
    # provenance counts are RESULT FIELDS, never flags (measured policy —
    # spec delta 2026-08-26): high-certainty masks must not see them
    assert sim.motions_superseded == 1
    assert sim.drivetrain_contentions >= 1
    assert "motion_superseded" not in sim.execution_flags
    assert "concurrent_stacks_unverified" not in sim.execution_flags
    assert sim.scheduler == "cooperative"


def test_wait_window_supersession_truncates_mid_flight():
    # A drives 1000mm (~2.02s at default velocity); B waits 1s then issues
    # its own drive. A's motion commits ~494mm before truncation, then B's
    # 200mm runs: total ≈ 694mm, and A resumes (its magnet fires).
    xml = workspace(
        started("A", drive_for(1000).replace(
            "</block>", f"<next>{MAGNET}</next></block>")),
        started("B", wait_block(1.0, nxt=f"<next>{drive_for(200)}</next>")))
    sim = coop(xml)
    v = 50.0 * 9.88   # default 50% velocity, calibrated mm/s per percent
    expected = v * 1.0 + 200
    assert abs(sim.net_displacement_from_spawn - expected) < 1.0
    assert sim.motions_superseded == 1
    assert sim.magnet_fires_at_step is not None      # A resumed (measured policy)


def test_truncate_and_park_kills_the_owner():
    xml = workspace(
        started("A", drive_for(1000).replace(
            "</block>", f"<next>{MAGNET}</next></block>")),
        started("B", wait_block(1.0, nxt=f"<next>{drive_for(200)}</next>")))
    sim = coop(xml, superseded_motion="truncate_and_park")
    assert sim.magnet_fires_at_step is None          # A never resumed


def test_resume_after_restores_remaining_distance():
    xml = workspace(
        started("A", drive_for(1000)),
        started("B", wait_block(1.0, nxt=f"<next>{drive_for(200)}</next>")))
    sim = coop(xml, superseded_motion="resume_after")
    # A's remaining ~506mm resumes after B's 200mm: total ≈ 1000 + 200
    assert abs(sim.net_displacement_from_spawn - 1200.0) < 1.0


def test_monitor_loop_cannot_block_the_driver():
    # the falsified-lockout shape: a forever-turn monitor beside a driver.
    # Under round-robin the driver still parks and completes; the monitor's
    # non-blocking turns supersede only between slices.
    turn = ('<block type="pg_drivetrain_turn" id="tn">'
            '<field name="TURNDIRECTION">right</field></block>')
    monitor = ('<block type="pg_control_forever" id="f1">'
               f'<statement name="SUBSTACK">{turn}</statement></block>')
    xml = workspace(started("A", drive_for(600).replace(
        "</block>", f"<next>{MAGNET}</next></block>")),
        started("B", monitor))
    sim = coop(xml)
    assert sim.magnet_fires_at_step is not None      # A finished its stack
    assert sim.motions_superseded >= 1


def test_stop_project_kills_all_threads():
    stop = '<block type="pg_control_stop_project" id="sp"/>'
    xml = workspace(
        started("A", wait_block(5.0, nxt=f"<next>{MAGNET}</next>")),
        started("B", stop))
    sim = coop(xml)
    # B stops the project in the first runnable phase: A's magnet never
    # fires and no runoff is fabricated
    assert sim.magnet_fires_at_step is None
    assert not sim.fabricated_steps


def test_gated_thread_does_not_gate_siblings():
    # A waits on a condition nothing can satisfy; B completes normally.
    cond = ('<block type="pg_sensing_bumper_pressed" id="bp">'
            '<field name="BUMPER">leftbumper</field></block>')
    wait_until = ('<block type="pg_control_wait_until" id="wu">'
                  f'<value name="CONDITION">{cond}</value></block>')
    xml = workspace(started("A", wait_until),
                    started("B", drive_for(300).replace(
                        "</block>", f"<next>{MAGNET}</next></block>")))
    sim = coop(xml)
    assert sim.magnet_fires_at_step is not None
    assert "wait_until_unmet" in sim.execution_flags
    assert abs(sim.net_displacement_from_spawn - 300) < 1e-6


def test_thread_id_tags_cooperative_steps_only():
    xml1 = workspace(started("A", drive_for(300)))
    seq = simulate_path(parse_workspace(xml1, "t"), ctx())
    assert all(ps.thread_id is None for ps in seq.path)
    xml2 = workspace(started("A", drive_for(300)),
                     started("B", turn_for(90)))
    sim = coop(xml2)
    assert any(ps.thread_id is not None for ps in sim.path)


def test_sequential_mode_keeps_legacy_flag():
    xml = workspace(started("A", drive_for(100)), started("B", drive_for(50)))
    seq = simulate_path(parse_workspace(xml, "t"), ctx())
    assert "concurrent_stacks_unverified" in seq.execution_flags
    assert seq.scheduler == "sequential"


def test_mutual_truncation_is_symmetric_and_reentrant():
    """Spec delta (2026-08-26, VR-measured): B truncates A's drive_for; A
    resumes and its next command truncates B; B resumes too — no owner
    precedence, no latching, any number of cycles. Both stacks complete."""
    a_body = drive_for(1000).replace(
        "</block>",
        f"<next>{turn_for(90)}</next></block>".replace(
            "</block></next></block>",
            f"<next>{MAGNET}</next></block></next></block>"))
    b_turn = ('<block type="pg_drivetrain_turn_for" id="bt360">'
              '<field name="TURNDIRECTION">right</field>'
              '<field name="UNITS">deg</field>'
              '<value name="AMOUNT"><shadow type="math_number">'
              '<field name="NUM">360</field></shadow></value>'
              f'<next>{drive_for(100)}</next></block>')
    xml = workspace(started("A", a_body),
                    started("B", wait_block(1.0, nxt=f"<next>{b_turn}</next>")))
    sim = coop(xml)
    v = 50.0 * 9.88
    # A drives ~1s (~494mm) until B wakes; B's turn truncates A; A's
    # turn_for truncates B; B's drive truncates A's turn; A resumes to its
    # magnet; B's 100mm drive completes. Three supersessions, both done.
    assert sim.motions_superseded == 3
    assert sim.magnet_fires_at_step is not None          # A completed
    assert abs(sim.net_displacement_from_spawn - (v * 1.0 + 100)) < 2.0

def test_thread_start_order_reverse_document():
    # same-tick contention: with reverse order, A's write is the LAST one
    # in the first phase — A's 1000mm survives instead of B's 400mm
    xml = workspace(started("A", drive_for(1000)), started("B", drive_for(400)))
    fwd = coop(xml)
    rev = coop(xml, thread_start_order="reverse_document")
    assert abs(fwd.net_displacement_from_spawn - 400) < 1e-6
    assert abs(rev.net_displacement_from_spawn - 1000) < 1e-6


def test_loop_clock_and_time_budget():
    """60Hz loop clock (measured): each otherwise-instant iteration costs one
    tick; the observed-run budget replaces the unroll caps and halts the
    program like a stop (no runoff).

    OI-28 (2026-08-28): the clock is now COOPERATIVE-ONLY — the back-edge
    tick is a time park consumed by the Sequencer, which is the one place
    that turns elapsed time into displacement. These single-stack
    assertions are unchanged from the sequential era (G3: single-stack
    cooperative is byte-identical to sequential)."""
    bump = ('<block type="pg_variables_change_variable" id="cv">'
            '<field name="VARIABLE">a</field>'
            '<value name="VALUE"><shadow type="math_number">'
            '<field name="NUM">1</field></shadow></value></block>')
    forever = ('<block type="pg_control_forever" id="f1">'
               f'<statement name="SUBSTACK">{bump}</statement></block>')
    xml = workspace(started("A", forever))
    prog = parse_workspace(xml, "t")
    # clock without budget: 20 unrolls x 1/60s
    sim = simulate_path(prog, ctx(), scheduler="cooperative",
                       loop_iteration_time_s=1 / 60)
    assert abs(sim.sim_time_s - 20 / 60) < 1e-9
    # clock + 2s budget: the cap is replaced; the clock binds at ~120 iters
    sim2 = simulate_path(prog, ctx(), scheduler="cooperative",
                         loop_iteration_time_s=1 / 60, time_budget_s=2.0)
    assert "time_budget_exhausted" in sim2.execution_flags
    assert abs(sim2.sim_time_s - 2.0) < 0.05
    assert not sim2.fabricated_steps          # budget stop => no runoff
    # iterations that consume real time are NOT double-charged
    xml3 = workspace(started("A",
        ('<block type="pg_control_repeat" id="r2">'
         '<value name="TIMES"><shadow type="math_number">'
         '<field name="NUM">2</field></shadow></value>'
         f'<statement name="SUBSTACK">{drive_for(494)}</statement></block>')))
    sim3 = simulate_path(parse_workspace(xml3, "t"), ctx(),
                         scheduler="cooperative", loop_iteration_time_s=1 / 60)
    assert abs(sim3.sim_time_s - 2 * 494 / 494.0) < 1e-6   # 1s each, no top-up


def test_rotation_time_and_cumulative_accumulator():
    """A3 rotation build (2026-08-26): turn_to_heading takes shortest-path
    time; turn_to_rotation is cumulative (multi-revolution) and takes time;
    the drive_rotation reporter returns the true accumulator."""
    def t2h(h):
        return (f'<block type="pg_drivetrain_turn_to_heading" id="th{h}">'
                f'<value name="HEADING"><shadow type="math_number">'
                f'<field name="NUM">{h}</field></shadow></value></block>')
    def t2r(rot, bid):
        return (f'<block type="pg_drivetrain_turn_to_rotation" id="{bid}">'
                f'<value name="ROTATION"><shadow type="math_number">'
                f'<field name="NUM">{rot}</field></shadow></value></block>')
    v = 50.0 * 4.16
    # spawn VEX heading 0; turn to VEX 90 = shortest path 90°
    sim = simulate_path(parse_workspace(
        workspace(started("A", t2h(90))), "t"), ctx())
    assert abs(sim.sim_time_s - 90 / v) < 1e-9
    assert abs(sim.drive_rotation_deg - 90.0) < 1e-9   # CW 90 = +90 VEX
    # cumulative: to rotation 450, then BACK to 90 (a -360 unwind)
    xml = workspace(started("A", t2r(450, "r1").replace(
        "</block>", f"<next>{t2r(90, 'r2')}</next></block>")))
    sim2 = simulate_path(parse_workspace(xml, "t"), ctx())
    assert abs(sim2.drive_rotation_deg - 90.0) < 1e-9
    assert abs(sim2.sim_time_s - (450 + 360) / v) < 1e-9
    # heading endpoint unchanged from the legacy expression
    assert abs(sim2.final_heading - ((180 - 90) % 360)) < 1e-9


def test_structures_exercised_trace():
    """A2 (2026-08-26): the sim records which loops iterated and which
    branch arms ran — the Control Structure evidence feed."""
    body = ('<block type="pg_control_if_then_else" id="if1">'
            '<value name="CONDITION"><block type="pg_sensing_bumper_pressed" '
            'id="bp"><field name="BUMPER">leftbumper</field></block></value>'
            f'<statement name="SUBSTACK">{drive_for(10)}</statement>'
            f'<statement name="SUBSTACK2">{drive_for(20)}</statement></block>')
    xml = workspace(started("A",
        ('<block type="pg_control_repeat" id="r1">'
         '<value name="TIMES"><shadow type="math_number">'
         '<field name="NUM">3</field></shadow></value>'
         f'<statement name="SUBSTACK">{body}</statement></block>')))
    sim = simulate_path(parse_workspace(xml, "t"), ctx())
    assert sim.loops_exercised == {"r1": 3}
    assert sim.branches_exercised == {"if1": ["else", "else", "else"]}


def test_zero_incidence_reporter_tripwires():
    """A3 close review (2026-08-26): the four zero-incidence reporters pin
    their semantics — position honours UNITS, heading reports the VEX/card
    convention, is_done/is_moving are cooperative-aware."""
    def rep(bt, fields=""):
        return (f'<block type="pg_variables_set_variable" id="sv">'
                f'<field name="VARIABLE">a</field>'
                f'<value name="VALUE"><block type="{bt}" id="rp">{fields}'
                f'</block></value></block>')
    from goal_strategy.detector.simulation.simulate_path import _Simulator
    probe = _Simulator(ctx())
    class FB:
        def __init__(self, bt, f): self.block_type, self._f = bt, f
        def get_field(self, n): return self._f.get(n)
        block_id = "p"; values = []
    assert probe._eval_expression(FB("pg_sensing_drive_heading", {})) == 0.0
    probe.heading = 90.0     # math 90
    assert probe._eval_expression(FB("pg_sensing_drive_heading", {})) == 90.0
    probe.heading = 180.0
    assert probe._eval_expression(FB("pg_sensing_position_angle", {})) == 0.0
    probe.x = 254.0
    assert probe._eval_expression(
        FB("pg_sensing_position", {"AXIS": "X", "UNITS": "inches"})) == 10.0
    assert probe._eval_expression(
        FB("pg_sensing_position", {"AXIS": "X"})) == 254.0
    # sequential synchronicity pins
    assert probe._eval_expression(FB("pg_sensing_drive_is_done", {})) is True
    assert probe._eval_expression(FB("pg_sensing_drive_is_moving", {})) is False


def test_is_moving_true_for_sibling_during_motion():
    # B polls is_moving into a variable while A's drive is in flight
    poll = ('<block type="pg_control_wait" id="w05">'
            '<value name="TIME"><shadow type="math_number">'
            '<field name="NUM">0.5</field></shadow></value>'
            '<next><block type="pg_variables_set_variable" id="sv">'
            '<field name="VARIABLE">moving</field>'
            '<value name="VALUE"><block type="pg_sensing_drive_is_moving" '
            'id="im"/></value></block></next></block>')
    xml = workspace(started("A", drive_for(1000)), started("B", poll))
    sim = coop(xml)
    assert bool(sim.variables.get("moving")) is True


def test_structure_trace_thread_attribution():
    """A2 thread attribution (2026-08-26): structure events carry the
    executing thread id; sequential traces carry None."""
    bump = ('<block type="pg_variables_change_variable" id="cv">'
            '<field name="VARIABLE">a</field>'
            '<value name="VALUE"><shadow type="math_number">'
            '<field name="NUM">1</field></shadow></value></block>')
    loop = ('<block type="pg_control_repeat" id="rA">'
            '<value name="TIMES"><shadow type="math_number">'
            '<field name="NUM">2</field></shadow></value>'
            f'<statement name="SUBSTACK">{bump}</statement></block>')
    xml = workspace(started("A", loop),
                    started("B", loop.replace('id="rA"', 'id="rB"')))
    sim = coop(xml)
    by_block = {}
    for tid, ev, bid, detail in sim.structure_trace:
        assert ev in ("LOOP_ITER", "BRANCH_ARM")
        by_block.setdefault(bid, set()).add(tid)
    assert by_block["rA"] == {0} and by_block["rB"] == {1}
    seq = simulate_path(parse_workspace(xml, "t"), ctx())
    assert all(tid is None for tid, *_ in seq.structure_trace)
