"""Regression pins over the 119-program corpus (spec §9).

The pinned values were computed and verified during design analysis on FULL
(untruncated) paths. If a pin fails: STOP AND REPORT — do not adjust the pin,
do not tune rungs to fit. The truncated (§6a) counterparts are computed here and
recorded in FINDINGS.md as the pipeline's operating baseline; only the sanity
relation truncated <= full is asserted for them.
"""


def _indicator(prof, goal_id, name):
    goal = next(g for g in prof.goals if g.goal == goal_id)
    return next(i for i in goal.intent + goal.attainment if i.name == name)


def _counts(profiles):
    # Near-contact attachment model (OI-21, signed off 2026-08-21):
    # the rung label armed_within_radius became attach_estimated.
    armed = [p for p in profiles
             if _indicator(p, "engage_plow", "plow_proximity_execution").rung
             == "attach_estimated"]
    return {
        "boundary_exceeded": sum(p.boundary_exceeded for p in profiles),
        "reached": sum(_indicator(p, "engage_plow", "plow_approach_intent").rung
                       == "reached" for p in profiles),
        "attach_estimated": len(armed),
        "boost": sum(_indicator(p, "engage_plow", "magnet_activation_intent").rung
                     == "boost" for p in profiles),
        "outcome_field_absent": sum(
            _indicator(p, "clear_debris_zone", "weight_cleared").abstain_reason
            == "outcome_field_absent" for p in profiles),
    }


# Design-verified full-path pins (spec §9 table).
#
# geometry_undescribed is deliberately NOT pinned (reviewer decision, 2026-08-18:
# "the wrong thing to pin"). It is still computed above and recorded in
# FINDINGS.md. Under the revised zone rule (all qualifying steps, unflagged
# described zone takes precedence) the measured value happens to equal the
# design table's 19 — see FINDINGS.md.
# boundary updated 68 -> 78 at the continuous-motion sign-off (2026-08-18):
# 13 terminal runoffs newly exit, 3 old in-loop-crawl exits vanished. reached/
# armed counts unchanged but membership swapped (WREN-C008 out, WREN-C052 in).
# Corpus filtered to 112 sessions (the seven wrong-playground sessions are
# excluded; outcome_field_absent pins at 0 as the leak guard). boundary = 63 as
# of the combined 2026-08-18 sign-off: parser shadow/literal fix (3 paths),
# measured OUTER-ring island boundary, and the any-part-on-island half-robot
# tolerance — nine annulus-grazes and four ring-only "exits" were never real.
# Velocity calibration sign-off (2026-08-19, OI-16): drive 9.88 mm/s per %,
# turn 4.16 °/s per % (measured; ~5x / ~2.7x the old guesses). The six
# wait-motion programs moved; WREN-C048 and WREN-C086 newly engage the plow
# (C048 in the stuck zone), two more boundary exits.
# OI-4 probe series sign-off (2026-08-19): the plow zones are rewritten from
# measurement — the stuck_zone did not replicate (removed per reviewer ruling;
# its pin retires with it), the 1230-1250 gap attaches, and below-anchor
# engagement requires near-contact facing the anchor.
# Continuous-sampling sign-off (2026-08-19, C031 live falsification): distance
# evidence is evaluated along path segments, not waypoints, and attachment is
# estimated uniformly within the 190mm attraction radius (the prior work's
# empirically-verified magnet_attraction_radius_mm) — zone bands and the
# below_anchor_attach_unlikely flag are removed per reviewer ruling. reached
# 48 -> 67 and armed 45 -> 59: continuous minima can only be smaller than
# waypoint samples, so mid-drive passes now credit.
# Sensing Phase-4 sign-off (2026-08-19, bumper model): WREN-C103's bumper hat
# now fires at modeled contact instead of eagerly — its stack interleaves
# mid-run, diverting the trajectory before the plow approach (B1 still exits
# the boundary, matching the off-island GPS). Its reached/armed evidence
# moves out of the §6a-scored span: reached 67 -> 66, armed 59 -> 58.
# Phase-3 distance sign-off (2026-08-19): WREN-C082's while(distance found)
# guard now evaluates — the program runs and exits the field as the real
# robot did (GPS 58m out): boundary 65 -> 66, off-island agreement 95 -> 96.
# Radius ratification (same sign-off): piece body radii MEASURED (blob areas,
# rock cross-validated, 45-55 eyeballs -> 70-72mm): WREN-C035's distance
# branches now track reality (error 2052 -> 584mm, agreement 96 -> 97 = 87%);
# C035 exits like its GPS: boundary 66 -> 67.
PINS_FULL = {
    # 70 as of the castle-structure adoption (2026-08-26): the itemised
    # vertex towers give C018's and C046's eye hats real targets — C018
    # exits like its GPS always said (disagreement RESOLVED); C046 detours
    # into the override lane (its firing tower is a PROVISIONAL NE/SE
    # coordinate — flagged in the attribution).
    "boundary_exceeded": 70,
    "reached": 66,
    "attach_estimated": 58,   # same membership as the retired armed_within_radius pin
    "boost": 70,
    "outcome_field_absent": 0,
}


def test_corpus_size(corpus):
    assert len(corpus) == 112   # 119 minus the 7 wrong-playground sessions


def test_full_path_pins(profiles_full):
    counts = _counts(profiles_full)
    mismatches = {k: (PINS_FULL[k], counts[k])
                  for k in PINS_FULL if counts[k] != PINS_FULL[k]}
    assert not mismatches, (
        f"regression pins failed (expected, measured): {mismatches} — "
        "STOP AND REPORT; do not adjust the pin (spec §9)")


def test_truncated_counts_recorded_for_findings(profiles_full, profiles_truncated):
    full = _counts(profiles_full)
    truncated = _counts(profiles_truncated)
    print(f"\nFINDINGS baseline — full: {full}")
    print(f"FINDINGS baseline — truncated (§6a): {truncated}")
    for key, value in truncated.items():
        assert value <= full[key], f"{key}: truncated {value} > full {full[key]}"


def test_boundary_scan_agrees_with_simulator_flag(corpus):
    """Sanity (not a pin): our origin-seeded polygon scan should agree with the
    simulator's own exits_field_boundary on this corpus."""
    from goal_strategy.detector.parsing.parse_blocks import parse_workspace
    from goal_strategy.detector.simulation.simulate_path import simulate_path
    from goal_strategy.config import load_configs
    from goal_strategy.profile import _find_boundary_exit

    cfg = load_configs("castle_crashers")
    polygon = cfg.card["field_boundary"]["polygon_mm"]
    disagreements = []
    for prog in corpus:
        if not prog.workspace_xml:
            continue
        program = parse_workspace(prog.workspace_xml, prog.program_id)
        if program is None:
            continue
        sim = simulate_path(program, cfg.context)
        # compare at tolerance=0: the simulator's flag is a raw point-in-polygon
        # test; profile-level classification adds the any-part-on-island
        # half-robot tolerance on top (reviewer-confirmed 2026-08-18).
        ours, _ = _find_boundary_exit(sim, polygon, tolerance=0.0)
        if ours != sim.exits_field_boundary:
            disagreements.append(prog.program_id)
    assert not disagreements, f"boundary scan disagrees on: {disagreements}"


def test_zero_incidence_conventions_stay_zero(corpus):
    """OI-3 tripwires (2026-08-19): two continuous-motion conventions have zero
    corpus incidence and are documented, not validated. If a future corpus
    exercises either, this fails loudly — the convention has become
    load-bearing and needs the OI-3 design-of-record applied for real.
    """
    from goal_strategy.detector.parsing.parse_blocks import parse_workspace
    from goal_strategy.detector.simulation.simulate_path import simulate_path
    from goal_strategy.config import load_configs

    cfg = load_configs("castle_crashers")
    trailing_turns, undercredit = [], []
    for prog in corpus:
        program = parse_workspace(prog.workspace_xml or "", prog.program_id)
        if program is None:
            continue
        sim = simulate_path(program, cfg.context)
        # trailing bare turn: a fabricated step on a bare-turn block (the 90
        # degree nominal only fires via finish_pending_motion)
        for s in sim.fabricated_steps:
            if s < len(sim.path) and sim.path[s].block_type == "pg_drivetrain_turn":
                trailing_turns.append(prog.program_id)
        # under-credit shape: loop body with a wait but no drivetrain command
        nodes = []
        def walk(n):
            while n is not None:
                nodes.append(n)
                for c in n.children:
                    walk(c)
                n = n.next
        for root in program.event_handler_stacks:
            walk(root)
        for n in nodes:
            if n.block_type in ("pg_control_forever", "pg_control_repeat",
                                "pg_control_repeat_until", "pg_control_while"):
                body = []
                for c in n.children:
                    m = c
                    while m is not None:
                        body.append(m.block_type)
                        m = m.next
                if "pg_control_wait" in body and \
                        not any(b.startswith("pg_drivetrain") for b in body):
                    undercredit.append(prog.program_id)
    assert not trailing_turns, (
        f"trailing bare turns now exist ({trailing_turns}) — the 90° nominal "
        "is load-bearing; apply the OI-3 design-of-record")
    assert not undercredit, (
        f"under-credit loop shape now exists ({set(undercredit)}) — pending "
        "motion inside these loops is under-credited; apply OI-3")
