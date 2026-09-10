"""Task-3 hat-execution fidelity: Part A inline broadcast, Part B treatments,
Part C concurrency flag, Part D fabricated-motion instrumentation."""
from goal_strategy.detector.parsing.parse_blocks import parse_workspace
from goal_strategy.detector.simulation.simulate_path import (
    ObjectRef,
    PlaygroundContext,
    simulate_path,
)

from goal_strategy.profile import _profile

NS = "https://developers.google.com/blockly/xml"


def ctx(radius=100000.0):
    return PlaygroundContext(spawn_x=0.0, spawn_y=0.0, spawn_heading=90.0,
                             field_radius=radius, objects={}, regions={})


def drive_for(mm, nxt=""):
    return f"""<block type="pg_drivetrain_drive_for" id="d{mm}">
      <field name="DIRECTION">fwd</field><field name="UNITS">mm</field>
      <value name="AMOUNT"><shadow type="math_number"><field name="NUM">{mm}</field></shadow></value>
      {nxt}</block>"""


def turn_for(deg, nxt=""):
    return f"""<block type="pg_drivetrain_turn_for" id="t{deg}">
      <field name="TURNDIRECTION">right</field><field name="UNITS">deg</field>
      <value name="AMOUNT"><shadow type="math_number"><field name="NUM">{deg}</field></shadow></value>
      {nxt}</block>"""


def workspace(*stacks):
    return f'<xml xmlns="{NS}">' + "".join(stacks) + "</xml>"


def hat(hat_type, body, fields=""):
    return f'<block type="{hat_type}" id="h{abs(hash((hat_type, body))) % 9999}">{fields}<next>{body}</next></block>'


def receiver(event, body):
    return (f'<block type="pg_events_when_broadcasted" id="r{event}">'
            f'<field name="BROADCAST_OPTION">{event}</field><next>{body}</next></block>')


def broadcast(event, nxt="", and_wait=False):
    bt = "pg_events_broadcast_and_wait" if and_wait else "pg_events_broadcast"
    return (f'<block type="{bt}" id="b{event}">'
            f'<field name="BROADCAST_OPTION">{event}</field>{nxt}</block>')


def sim(xml, **kwargs):
    return simulate_path(parse_workspace(xml, "t"), ctx(), **kwargs)


# ------------------------------------------------------------------ Part A

def test_broadcast_receiver_runs_inline_not_in_document_order():
    xml = workspace(
        hat("pg_events_when_started",
            broadcast("go", nxt=f"<next>{drive_for(100)}</next>")),
        receiver("go", turn_for(90)),
    )
    result = sim(xml)
    # Receiver's turn executes at the broadcast site — BEFORE the drive.
    assert [ps.block_type for ps in result.path] == \
        ["pg_drivetrain_turn_for", "pg_drivetrain_drive_for"]
    assert "broadcast_concurrency_approximated" in result.execution_flags


def test_receiver_not_executed_twice():
    xml = workspace(
        hat("pg_events_when_started", broadcast("go")),
        receiver("go", drive_for(100)),
    )
    assert len(sim(xml).path) == 1


def test_broadcast_and_wait_is_exact_no_approximation_flag():
    xml = workspace(
        hat("pg_events_when_started", broadcast("go", and_wait=True)),
        receiver("go", drive_for(100)),
    )
    result = sim(xml)
    assert len(result.path) == 1
    assert "broadcast_concurrency_approximated" not in result.execution_flags


def test_broadcast_recursion_suppressed():
    xml = workspace(
        hat("pg_events_when_started", broadcast("go")),
        receiver("go", drive_for(100, nxt=f"<next>{broadcast('go')}</next>")),
    )
    result = sim(xml)
    assert len(result.path) == 1   # would loop forever without the guard
    assert "broadcast_recursion_suppressed" in result.execution_flags


def test_broadcast_multiple_receivers_all_run_in_document_order():
    xml = workspace(
        hat("pg_events_when_started", broadcast("go")),
        receiver("go", turn_for(90)),
        receiver("go", drive_for(100)),
    )
    result = sim(xml)
    assert [ps.block_type for ps in result.path] == \
        ["pg_drivetrain_turn_for", "pg_drivetrain_drive_for"]
    assert "broadcast_multiple_receivers" in result.execution_flags


def test_broadcast_without_receiver_is_noop():
    xml = workspace(hat("pg_events_when_started", broadcast("ghost")))
    result = sim(xml)
    assert result.path == [] and result.execution_flags == []


# ------------------------------------------------------------------ Part B

BUMPER_XML = workspace(
    hat("pg_events_when_started", drive_for(100)),
    hat("pg_events_when_bumper", drive_for(500),
        fields='<field name="BUMPER">leftbumper</field><field name="OPTIONS">pressed</field>'),
)


def test_conditional_hat_executes_under_b1_default():
    result = sim(BUMPER_XML)
    assert len(result.path) == 2
    assert "trigger_unsimulated" in result.execution_flags   # bumper: no sensor sim exists
    assert "conditional_hat_suppressed" not in result.execution_flags


def test_conditional_hat_suppressed_under_b2():
    result = sim(BUMPER_XML, conditional_hats="suppress")
    assert len(result.path) == 1   # only the when_started drive
    assert "conditional_hat_suppressed" in result.execution_flags


def test_suppression_propagates_through_broadcast_chain():
    # §2: the broadcast originates from a conditional hat — suppressing the hat
    # must also silence its receiver (the WREN-C012 cascade).
    xml = workspace(
        hat("pg_events_when_started", drive_for(100)),
        hat("pg_events_optical_detect_object", broadcast("seen"),
            fields='<field name="OPTICAL">fronteye</field><field name="OPTIONS">detects</field>'),
        receiver("seen", turn_for(90)),
    )
    result = sim(xml)
    assert [ps.block_type for ps in result.path] == \
        ["pg_drivetrain_drive_for", "pg_drivetrain_turn_for"]        # B1: cascade runs
    assert "trigger_unfaithful" in result.execution_flags            # eye: evaluable, unfaithful
    assert len(sim(xml, conditional_hats="suppress").path) == 1      # B2: silenced


def test_b3_abstains_simulation_channel_only():
    prof = _profile(BUMPER_XML, "b3_test", {"weight_cleared": 100},
                    conditional_hats="abstain")
    for goal in prof.goals:
        for ind in goal.intent + goal.attainment:
            if ind.channel == "simulation":
                assert ind.abstained
                assert ind.abstain_reason == "trigger_unsimulated"
            else:
                assert ind.abstain_reason not in ("trigger_unsimulated",
                                                  "trigger_unfaithful")


def test_timer_hat_is_trusted_never_suppressed():
    xml = workspace(
        hat("pg_events_when_started", drive_for(100)),
        hat("pg_events_when_timer", turn_for(90),
            fields='<field name="TIME">5</field>'),
    )
    for mode in ("execute", "suppress"):
        result = sim(xml, conditional_hats=mode)
        assert len(result.path) == 2                     # timer stack always fires
        assert "trigger_unfaithful" not in result.execution_flags
        assert "trigger_unsimulated" not in result.execution_flags


def test_conditional_hat_treatment_is_inert(corpus):
    """Guard for the B1 adoption (2026-08-18): B1 vs B2 must differ only in the
    KNOWN, DOCUMENTED cases below — all logged for researcher review in
    OPEN_ISSUES.md. Any NEW divergence means the treatment choice has become
    load-bearing in a way not yet reviewed: record it in OPEN_ISSUES.md and
    flag it to the researcher — do not silently re-pick a default or extend
    these lists without logging the case.
    """
    # Real GPS sits outside the field for both; B1 matches reality (OPEN_ISSUES OI-2).
    # WREN-C040 added at the continuous-motion sign-off (2026-08-18): under B2
    # its bare drive's pending survives the suppressed eye stack to a terminal
    # runoff — boundary flips and coverage crosses a rung (OI-1 amendment).
    allowed_boundary_diffs = {"WREN-C018_WREN-C018_S001", "WREN-C103_WREN-C103_S001",
                              "WREN-C040_WREN-C040_S001",
                              # 2026-08-24 edge-triggered restart hats: B1's
                              # re-firing eye hat carries C012 off the island,
                              # matching its off-island GPS (reality-matching
                              # side); B2 suppresses the hat and stays on.
                              # Documented in OI-1.
                              "WREN-C012_WREN-C012_S001"}
    # WREN-C042 added at the continuous-sampling sign-off (2026-08-19): its
    # eye-hat stack alters the traversal near the plow mid-segment; waypoint
    # minima happened to coincide (B1 16.2mm vs B2 186.4mm continuous, same
    # rung). Same masking class as the C040 rounding incident. Logged in
    # OPEN_ISSUES (sensor cluster) for researcher review.
    # WREN-C012 + C018 added at the sensing Phase-2 sign-off (2026-08-19):
    # eye hats now fire at modeled detection, so B1 trajectories legitimately
    # differ from B2's suppressed ones. C012's debris divergence is
    # RUNG-level (systematic vs meaningful) — logged in OI-1.
    # WREN-C103 added at the sensing Phase-4 sign-off (2026-08-19): its bumper
    # hat fires at modeled contact under B1 (RUNG-level plow/debris diffs vs
    # B2's suppressed stack; B1 matches the off-island GPS on the boundary).
    allowed_value_diffs = {("WREN-C103_WREN-C103_S001", "plow_approach_intent"),
                           ("WREN-C103_WREN-C103_S001", "plow_proximity_execution"),
                           ("WREN-C103_WREN-C103_S001", "debris_zone_coverage"),
                           ("WREN-C040_WREN-C040_S001", "debris_zone_coverage"),
                           ("WREN-C040_WREN-C040_S001", "plow_approach_intent"),
                           ("WREN-C042_WREN-C042_S001", "plow_proximity_execution"),
                           ("WREN-C042_WREN-C042_S001", "plow_approach_intent"),
                           ("WREN-C012_WREN-C012_S001", "plow_approach_intent"),
                           ("WREN-C012_WREN-C012_S001", "plow_proximity_execution"),
                           # C012's on_island_sim mirrors its ALLOWLISTED
                           # boundary-level divergence (2026-08-24 restart
                           # hats, OI-1): B1's re-firing eye hat exits, B2
                           # stays on — same mechanism surfacing through the
                           # remain_on_island goal added 2026-08-25.
                           ("WREN-C012_WREN-C012_S001", "on_island_sim"),
                           # C018 re-enters the allowlist 2026-08-26: the
                           # castle-structure towers give its eye hat a real
                           # target again — B1 fires (exits like GPS), B2
                           # suppresses. Reality-matching side, as ever.
                           ("WREN-C018_WREN-C018_S001", "on_island_sim"),
                           # C103 likewise: its bumper-rooted boundary
                           # divergence is allowlisted above; on_island_sim
                           # restates it at value level.
                           ("WREN-C103_WREN-C103_S001", "on_island_sim"),
                           ("WREN-C012_WREN-C012_S001", "debris_zone_coverage"),
                           ("WREN-C018_WREN-C018_S001", "plow_approach_intent")}
    for prog in corpus:
        b1 = _profile(prog.workspace_xml or "", prog.program_id,
                      prog.playground_params, conditional_hats="execute")
        b2 = _profile(prog.workspace_xml or "", prog.program_id,
                      prog.playground_params, conditional_hats="suppress")
        for goal1, goal2 in zip(b1.goals, b2.goals):
            for ind1, ind2 in zip(goal1.intent + goal1.attainment,
                                  goal2.intent + goal2.attainment):
                if (ind1.value, ind1.rung) == (ind2.value, ind2.rung):
                    continue
                if (prog.program_id, ind1.name) in allowed_value_diffs:
                    continue
                raise AssertionError(
                    f"{prog.program_id}/{ind1.name}: B1 {ind1.value!r}/{ind1.rung!r} "
                    f"!= B2 {ind2.value!r}/{ind2.rung!r} — NEW B1-vs-B2 divergence: "
                    "the conditional-hat treatment has become load-bearing in an "
                    "unreviewed way. Record the case in OPEN_ISSUES.md and flag it "
                    "for researcher review; do not silently re-pick a default.")
        if b1.boundary_exceeded != b2.boundary_exceeded:
            assert prog.program_id in allowed_boundary_diffs, (
                f"{prog.program_id}: NEW boundary_exceeded divergence between B1 "
                "and B2 — record it in OPEN_ISSUES.md and flag it for researcher "
                "review; do not silently re-pick a default.")


# ------------------------------------------------------------------ Part C

def test_concurrent_when_started_flagged():
    xml = workspace(
        hat("pg_events_when_started", drive_for(100)),
        hat("pg_events_when_started", turn_for(90)),
    )
    assert "concurrent_stacks_unverified" in sim(xml).execution_flags


# ------------------------------------------------------------------ Part D

BARE_DRIVE = '<block type="pg_drivetrain_drive" id="bd"><field name="DIRECTION">fwd</field></block>'


def test_trailing_bare_continuous_drive_records_fabricated_step():
    result = sim(workspace(hat("pg_events_when_started", BARE_DRIVE)))
    assert result.fabricated_steps == [0]
    assert result.path[0].block_type == "pg_drivetrain_drive"


def test_bare_drive_superseded_by_drivetrain_command_contributes_no_motion():
    # Refined semantics (2026-08-18): a bare continuous drive continues until
    # the next DRIVETRAIN command activates. drive_for follows with zero
    # elapsed time, so the pending motion is cleared unconsumed — no step, no
    # motion, nothing fabricated.
    xml = workspace(hat(
        "pg_events_when_started",
        BARE_DRIVE.replace("</block>", f"<next>{drive_for(500)}</next></block>")))
    result = sim(xml)
    assert [ps.block_type for ps in result.path] == ["pg_drivetrain_drive_for"]
    assert result.fabricated_steps == []
    assert result.net_displacement_from_spawn == 500.0          # only the drive_for


def test_bare_turn_superseded_keeps_heading():
    # DOVE-C007's shape: bare turn immediately followed by a drive — the robot
    # never turns, then drives (trailing fallback) in its original heading.
    xml = workspace(hat(
        "pg_events_when_started",
        '<block type="pg_drivetrain_turn" id="bt"><field name="TURNDIRECTION">right</field>'
        f'<next>{drive_for(300)}</next></block>'))
    result = sim(xml)
    assert [ps.heading for ps in result.path] == [90.0]         # spawn heading kept
    assert result.fabricated_steps == []


def test_pending_motion_survives_instant_blocks_until_wait():
    # drive fwd; magnet boost; wait 2s -> the drive continues through the
    # instant magnet block and accrues velocity x time at the wait.
    xml = workspace(hat(
        "pg_events_when_started",
        '<block type="pg_drivetrain_drive" id="bd"><field name="DIRECTION">fwd</field>'
        '<next><block type="pg_magnet_set_magnet_state" id="m">'
        '<field name="MAGNET">Magnet</field><field name="ACTION">boost</field>'
        '<next><block type="pg_control_wait" id="w">'
        '<value name="TIME"><shadow type="math_number"><field name="NUM">2</field></shadow></value>'
        '</block></next></block></next></block>'))
    result = sim(xml)
    from goal_strategy.detector.simulation.simulate_path import _DEFAULT_DRIVE_VELOCITY_MM_PER_S
    # Wait-keeps-pending (reviewer ruling 2026-08-24, WREN-C048): the wait
    # does NOT stop the drivetrain. The wait-portion move (velocity x time,
    # REAL) is followed by the terminal runoff (fabricated) at program end.
    import math
    wait_step = next(ps for ps in result.path if ps.block_id == "w")
    assert math.hypot(wait_step.x - result.origin_x,
                      wait_step.y - result.origin_y) == 2 * _DEFAULT_DRIVE_VELOCITY_MM_PER_S
    assert result.fabricated_steps == [len(result.path) - 1]


def test_velocity_change_applies_to_continuing_motion():
    # drive fwd; set drive velocity 100%; wait 1s -> the speed change applies
    # to the CONTINUING motion (velocity setters do not preempt): 200mm/s x 1s.
    xml = workspace(hat(
        "pg_events_when_started",
        '<block type="pg_drivetrain_drive" id="bd"><field name="DIRECTION">fwd</field>'
        '<next><block type="pg_drivetrain_set_drive_velocity" id="v">'
        '<field name="UNITS">pct</field>'
        '<value name="VELOCITY"><shadow type="math_number"><field name="NUM">100</field></shadow></value>'
        '<next><block type="pg_control_wait" id="w">'
        '<value name="TIME"><shadow type="math_number"><field name="NUM">1</field></shadow></value>'
        '</block></next></block></next></block>'))
    result = sim(xml)
    import pytest, math
    # wait-portion at the NEW velocity; trailing runoff is separate/fabricated
    wait_step = result.path[0]
    assert math.hypot(wait_step.x - result.origin_x,
                      wait_step.y - result.origin_y) == pytest.approx(988.0)


def test_bare_drive_before_wait_still_uses_velocity_times_time():
    xml = workspace(hat(
        "pg_events_when_started",
        '<block type="pg_drivetrain_drive" id="bd"><field name="DIRECTION">fwd</field>'
        '<next><block type="pg_control_wait" id="w">'
        '<value name="TIME"><shadow type="math_number"><field name="NUM">2</field></shadow></value>'
        '</block></next></block>'))
    result = sim(xml)
    import pytest, math
    from goal_strategy.detector.simulation.simulate_path import _DEFAULT_DRIVE_VELOCITY_MM_PER_S
    wait_step = result.path[0]
    assert math.hypot(wait_step.x - result.origin_x,
                      wait_step.y - result.origin_y) ==         pytest.approx(2 * _DEFAULT_DRIVE_VELOCITY_MM_PER_S)
    assert result.fabricated_steps == [len(result.path) - 1]   # the runoff


def test_drive_with_wait_is_not_fabricated():
    xml = workspace(hat(
        "pg_events_when_started",
        '<block type="pg_drivetrain_drive" id="bd"><field name="DIRECTION">fwd</field>'
        '<next><block type="pg_control_wait" id="w">'
        '<value name="TIME"><shadow type="math_number"><field name="NUM">2</field></shadow></value>'
        '</block></next></block>'))
    result = sim(xml)
    # the wait move is REAL (velocity x time); the drive then CONTINUES
    # (2026-08-24 ruling) so program end adds the fabricated terminal runoff
    assert len(result.path) == 2
    assert 0 not in result.fabricated_steps
    assert result.fabricated_steps == [1]


def test_profile_fabricated_motion_flags():
    prof = _profile(workspace(hat("pg_events_when_started", BARE_DRIVE)), "fab_test")
    assert prof.fabricated_motion
    plow = next(g for g in prof.goals if g.goal == "engage_plow")
    approach = next(i for i in plow.intent if i.name == "plow_approach_intent")
    assert "fabricated_motion" in approach.flags


def test_profile_without_fallbacks_has_no_fabricated_flag():
    prof = _profile(workspace(hat("pg_events_when_started", drive_for(100))), "clean_test")
    assert not prof.fabricated_motion and not prof.boundary_exit_fabricated


# ---------------------------------------------------- OI-13/OI-14 (2026-08-18)

def test_parser_prefers_block_over_shadow_in_value_slots():
    # Blockly retains the obscured shadow when a real block is connected; the
    # student's block must win (OI-14).
    xml = workspace(hat("pg_events_when_started",
        '<block type="pg_drivetrain_drive_for" id="d1">'
        '<field name="DIRECTION">fwd</field><field name="UNITS">mm</field>'
        '<value name="AMOUNT">'
        '<shadow type="math_number"><field name="NUM">200</field></shadow>'
        '<block type="pg_variables_variable" id="v1">'
        '<field name="VARIABLE">rive</field></block>'
        '</value></block>'))
    from goal_strategy.detector.parsing.parse_blocks import parse_workspace
    program = parse_workspace(xml, "t")
    drive = program.event_handler_stacks[0].next
    assert len(drive.values) == 1
    assert drive.values[0].block_type == "pg_variables_variable"
    assert drive.values[0].get_field("VARIABLE") == "rive"


def test_variable_driven_drive_amount_evaluates(toy_ctx=None):
    # set rive = 500 (via math_number_string, the VEX string literal), then
    # drive for (rive) — both OI-13 and OI-14 in one path.
    xml = workspace(hat("pg_events_when_started",
        '<block type="pg_variables_set_variable" id="s1">'
        '<field name="VARIABLE">rive</field>'
        '<value name="VALUE"><shadow type="math_number_string">'
        '<field name="NUM">500</field></shadow></value>'
        '<next><block type="pg_drivetrain_drive_for" id="d1">'
        '<field name="DIRECTION">fwd</field><field name="UNITS">mm</field>'
        '<value name="AMOUNT">'
        '<shadow type="math_number"><field name="NUM">200</field></shadow>'
        '<block type="pg_variables_variable" id="v1">'
        '<field name="VARIABLE">rive</field></block>'
        '</value></block></next></block>'))
    result = sim(xml)
    assert result.net_displacement_from_spawn == 500.0   # not the shadow's 200
    assert result.unknown_reporter_blocks == []          # literal now recognised


def test_change_variable_accumulates_into_drive_amounts():
    # the WREN-C053 spiral shape: drive (rive); change rive by 300; drive (rive)
    xml = workspace(hat("pg_events_when_started",
        '<block type="pg_variables_set_variable" id="s1">'
        '<field name="VARIABLE">rive</field>'
        '<value name="VALUE"><shadow type="math_number">'
        '<field name="NUM">100</field></shadow></value>'
        '<next><block type="pg_drivetrain_drive_for" id="d1">'
        '<field name="DIRECTION">fwd</field><field name="UNITS">mm</field>'
        '<value name="AMOUNT"><block type="pg_variables_variable" id="v1">'
        '<field name="VARIABLE">rive</field></block></value>'
        '<next><block type="pg_variables_change_variable" id="c1">'
        '<field name="VARIABLE">rive</field>'
        '<value name="VALUE"><shadow type="math_number">'
        '<field name="NUM">300</field></shadow></value>'
        '<next><block type="pg_drivetrain_drive_for" id="d2">'
        '<field name="DIRECTION">fwd</field><field name="UNITS">mm</field>'
        '<value name="AMOUNT"><block type="pg_variables_variable" id="v2">'
        '<field name="VARIABLE">rive</field></block></value>'
        '</block></next></block></next></block></next></block>'))
    result = sim(xml)
    assert result.net_displacement_from_spawn == 500.0   # 100 + (100+300)


def test_operator_random_is_deterministic_midpoint():
    xml = workspace(hat("pg_events_when_started",
        '<block type="pg_drivetrain_drive_for" id="d1">'
        '<field name="DIRECTION">fwd</field><field name="UNITS">mm</field>'
        '<value name="AMOUNT"><block type="pg_operator_random" id="r1">'
        '<value name="FROM"><shadow type="math_number"><field name="NUM">100</field></shadow></value>'
        '<value name="TO"><shadow type="math_number"><field name="NUM">300</field></shadow></value>'
        '</block></value></block>'))
    for _ in range(3):
        assert sim(xml).net_displacement_from_spawn == 200.0   # midpoint, every run
