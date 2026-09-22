"""Phase-5 harness tests: scenario overlays, check rules, push model,
eligibility, and the goal-mapping roll-up.

The three synthetic programs pin the harness's core distinction (reviewer
design): a RESPONSIVE pusher (bumper-gated) passes detects; a BLIND sweeper
clears the piece but fails detects — clearing without sensing is visible as
exactly that; an INERT program fails everything.
"""
from __future__ import annotations

import pytest

from pathlib import Path

from goal_strategy.testcases import run_battery

_ROOT = Path(__file__).resolve().parent.parent

RESPONSIVE_PUSHER = """<xml xmlns="https://developers.google.com/blockly/xml">
<block type="pg_events_when_started" id="h1"><next>
<block type="pg_drivetrain_drive" id="d1"><field name="DIRECTION">fwd</field><next>
<block type="pg_control_wait_until" id="w1">
  <value name="CONDITION"><block type="pg_sensing_bumper" id="b1">
    <field name="BUMPER">leftbumper</field></block></value><next>
<block type="pg_drivetrain_drive_for" id="d2"><field name="DIRECTION">fwd</field>
  <field name="UNITS">mm</field>
  <value name="AMOUNT"><shadow type="math_number" id="s2"><field name="NUM">2500</field></shadow></value>
</block></next></block></next></block></next></block></xml>"""

# The if-bumper check runs FIRST (so under Option A the piece materializes
# ahead of the robot at spawn), then a blind 3000mm sweep plows through it.
# The check itself never alters the trajectory: clearing is accidental.
BLIND_SWEEPER_REAL = """<xml xmlns="https://developers.google.com/blockly/xml">
<block type="pg_events_when_started" id="h1"><next>
<block type="pg_control_if_then" id="i1">
  <value name="CONDITION"><block type="pg_sensing_bumper" id="b1">
    <field name="BUMPER">leftbumper</field></block></value>
  <statement name="DO"><block type="pg_drivetrain_stop" id="st1"/></statement><next>
<block type="pg_drivetrain_drive_for" id="d1"><field name="DIRECTION">fwd</field>
  <field name="UNITS">mm</field>
  <value name="AMOUNT"><shadow type="math_number" id="s1"><field name="NUM">3000</field></shadow></value>
</block></next></block></next></block></xml>"""

INERT_SENSOR_PROGRAM = """<xml xmlns="https://developers.google.com/blockly/xml">
<block type="pg_events_when_started" id="h1"><next>
<block type="pg_control_if_then" id="i1">
  <value name="CONDITION"><block type="pg_sensing_bumper" id="b1">
    <field name="BUMPER">leftbumper</field></block></value>
  <statement name="DO"><block type="pg_drivetrain_drive_for" id="d1">
    <field name="DIRECTION">fwd</field><field name="UNITS">mm</field>
    <value name="AMOUNT"><shadow type="math_number" id="s1">
    <field name="NUM">500</field></shadow></value></block></statement>
</block></next></block></xml>"""

DOWN_EYE_ONLY = """<xml xmlns="https://developers.google.com/blockly/xml">
<block type="pg_events_when_started" id="h1"><next>
<block type="pg_control_wait_until" id="w1">
  <value name="CONDITION"><block type="pg_sensing_optical_color" id="e1">
    <field name="OPTICAL">downeye</field><field name="COLORS">red</field></block></value>
</block></next></block></xml>"""


def _scenario(report, sid):
    return next(s for s in report.scenarios if s.scenario_id == sid)


def _check(scenario, name):
    return next(c for c in scenario.checks if c.name == name)


@pytest.fixture(scope="module")
def responsive():
    return run_battery(RESPONSIVE_PUSHER, "responsive-pusher")


# The edge_handling / two_pieces_reset cards were RETIRED (reviewer,
# 2026-09-01) — the boundary family supersedes them. Their card CONTENT
# survives here as synthetic test-only cards because they carry the only
# coverage of two live harness mechanisms: `requires:` credit gating and
# Option A relative placement with per-construct variants.
_SYN_REQUIRES_CARD = """\
scenario_id: syn_requires_gate
description: synthetic — pins the `requires:` credit gate (was edge_handling).
goal: [clear_debris_zone, remain_on_island]
testcase_physics: {push_model: kinematic, loop_unroll: 60, clear_extension_fraction: 0.55,
                    loop_clock_hz: 60, time_budget_s: 60, invariance_budget_s: 30}
pieces:
  test_piece: {x: -1500, y: 49, body_radius_mm: 55}
checks:
  - {name: detects,         rule: behavioral_divergence, divergence_mm: 100, facet: object_detection}
  - {name: pushes_off,      rule: pieces_cleared, requires: detects, count: 1, facet: push_execution,
     progress_annotation: could_clear_if_run}
  - {name: stays_on_island, rule: on_island, facet: edge_failure_handling,
     goal: remain_on_island}
"""
_SYN_RELATIVE_CARD = """\
scenario_id: syn_relative_reset
description: synthetic — pins Option A relative placement (was two_pieces_reset).
goal: clear_debris_zone
testcase_physics: {push_model: kinematic, loop_unroll: 60, clear_extension_fraction: 0.55,
                    loop_clock_hz: 60, time_budget_s: 60, invariance_budget_s: 30}
pieces:
  test_piece_1: {relative: {ahead_mm: 600, bearing_deg: 0},  body_radius_mm: 55}
  test_piece_2: {relative: {ahead_mm: 600, bearing_deg: 90}, body_radius_mm: 55}
checks:
  - {name: detects,        rule: behavioral_divergence, divergence_mm: 100, facet: object_detection}
  - {name: pushes_off,     rule: pieces_cleared, requires: detects, count: 1, facet: push_execution,
     progress_annotation: could_clear_if_run}
  - {name: resets_to_next, rule: pieces_cleared, requires: detects, count: 2, facet: repeat_acquisition,
     progress_annotation: could_reacquire_if_run}
"""


@pytest.fixture(scope="module")
def syn_configs(tmp_path_factory):
    import shutil
    dst = tmp_path_factory.mktemp("syn") / "configs"
    shutil.copytree(_ROOT / "configs", dst)
    tdir = dst / "testcases" / "castle_crashers"
    for f in tdir.glob("*.yaml"):
        if not f.name.startswith("_"):
            f.unlink()
    (tdir / "syn_requires_gate.yaml").write_text(_SYN_REQUIRES_CARD)
    (tdir / "syn_relative_reset.yaml").write_text(_SYN_RELATIVE_CARD)
    return str(dst)


@pytest.fixture(scope="module")
def responsive_syn(syn_configs):
    return run_battery(RESPONSIVE_PUSHER, "responsive-pusher",
                       configs_dir=syn_configs)


def test_responsive_pusher_detects_and_clears_on_t4a(responsive):
    # piece_ahead retired 2026-08-28; t4a_near_favorable is its replacement
    # (a real castle position 1.2 deg off the westward spawn axis).
    t4a = _scenario(responsive, "t4a_near_favorable")
    assert _check(t4a, "detects").status == "pass"
    assert _check(t4a, "proportion_engaged").value == pytest.approx(1 / 3)
    assert _check(t4a, "proportion_cleared").value == pytest.approx(1 / 3)


def test_blind_sweeper_gets_no_accidental_credit(syn_configs):
    """Reviewer ruling 2026-08-19 — accidental clearing is not evidence.
    The `requires:` gate is a live harness mechanism; its card coverage
    moved to the synthetic cards when edge_handling / two_pieces_reset
    retired (2026-09-01)."""
    report = run_battery(BLIND_SWEEPER_REAL, "blind-sweeper",
                         configs_dir=syn_configs)
    two = _scenario(report, "syn_relative_reset")
    assert _check(two, "detects").status == "fail"
    push = _check(two, "pushes_off")
    assert push.status == "fail"
    assert "accidental" in (push.detail or "")


def test_measurement_cards_cannot_gate_accidental_clearing(responsive):
    """The counterpart, stated explicitly so it is never mistaken for a
    regression: `requires:` OVERWRITES a check's status with "fail", which
    would destroy a measurement's value — so it is structurally
    incompatible with the observation-true rules and appears on no T1/T4/T5
    card. A blind sweeper therefore DOES score proportion_cleared there;
    its lack of responsivity shows in `detects` (weighted 0.1 in the
    rollup), not by zeroing the measurement."""
    report = run_battery(BLIND_SWEEPER_REAL, "blind-sweeper")
    t4a = _scenario(report, "t4a_near_favorable")
    assert _check(t4a, "detects").status == "fail"
    assert _check(t4a, "proportion_cleared").value > 0
    assert all("requires" not in (c.detail or "") for c in t4a.checks)


def test_inert_sensor_program_scores_nothing():
    report = run_battery(INERT_SENSOR_PROGRAM, "inert")
    t4a = _scenario(report, "t4a_near_favorable")
    assert _check(t4a, "detects").status == "fail"
    assert _check(t4a, "proportion_engaged").value == 0.0
    assert _check(t4a, "proportion_cleared").value == 0.0
    # stays_on_island is encounter-based (2026-09-01): a program that
    # never approaches an edge has NO ROI evidence — abstain, never a
    # trivial pass for standing still
    island = _check(t4a, "stays_on_island")
    assert island.abstained and island.abstain_reason == "encounter_not_reached"


def test_down_eye_only_program_is_ineligible():
    # Red-line sensing is already sim-evidenced — the battery adds nothing
    # (reviewer ruling): not eligible.
    report = run_battery(DOWN_EYE_ONLY, "down-eye-only")
    assert report.eligible is False
    assert report.scenarios == ()


def test_two_piece_reset_distinguishes_single_clear(responsive_syn):
    two = _scenario(responsive_syn, "syn_relative_reset")
    # The straight-line pusher clears the first piece but never reacquires
    # the off-axis second piece.
    assert _check(two, "pushes_off").status == "pass"
    assert _check(two, "resets_to_next").status != "pass"


def test_goal_mapping_rolls_up_facets(responsive, responsive_syn):
    mapping = responsive.goal_mapping.get("clear_debris_zone", {})
    assert mapping.get("object_detection") == "pass"
    # push_execution / repeat_acquisition left the PRODUCTION mapping with
    # the legacy boolean cards (retired 2026-09-01) — the T-families carry
    # those facets as MEASUREMENTS, which stay out of the ranked mapping.
    assert "push_execution" not in mapping
    assert "repeat_acquisition" not in mapping
    # `object_pursuit` left the battery with the piece_* cards (2026-08-28).
    assert "object_pursuit" not in mapping
    # the boolean facet roll-up itself stays pinned via the synthetic cards
    syn = responsive_syn.goal_mapping.get("clear_debris_zone", {})
    assert syn.get("push_execution") == "pass"
    assert "repeat_acquisition" in syn


def test_multi_goal_card_routes_check_evidence(responsive):
    # Multi-goal routing (2026-08-27), retargeted to t1_castle_wall when
    # edge_handling retired (2026-09-01): clearing checks feed
    # clear_debris_zone (the primary) while stays_on_island carries its
    # own goal and rolls up under remain_on_island — not the primary.
    # stays_on_island became a MEASUREMENT (2026-09-01), so its facet
    # stays out of the ranked goal_mapping entirely — routing is asserted
    # on the check's own goal attribution instead.
    assert "edge_failure_handling" not in \
        responsive.goal_mapping.get("remain_on_island", {})
    assert "edge_failure_handling" not in \
        responsive.goal_mapping.get("clear_debris_zone", {})
    t1 = _scenario(responsive, "t1_castle_wall")
    assert t1.goal == "clear_debris_zone"            # primary, first-listed
    assert _check(t1, "stays_on_island").goal == "remain_on_island"
    assert _check(t1, "detects").goal == "clear_debris_zone"


def test_t1_castle_wall_measurement_checks(responsive):
    # T1 redesign (2026-08-28): a single castle-wall test — 28 tower-sized
    # pieces on the original outer-wall hexagon, spacing <= 250mm vs the
    # 125.4mm pin, so any sweep crossing the wall line contacts a piece.
    # Checks are observation-true measurements; detects leads them as
    # informational responsivity evidence (never a credit gate); and
    # stays_on_island routes to remain_on_island.
    t1 = [s for s in responsive.scenarios if s.family == "t1_debris_field"]
    assert [s.scenario_id for s in t1] == ["t1_castle_wall"]
    s = t1[0]
    assert s.construct == "static"
    assert [c.name for c in s.checks] == [
        "detects", "proportion_engaged", "proportion_cleared",
        "stays_on_island"]
    for name in ("proportion_engaged", "proportion_cleared"):
        c = _check(s, name)
        assert c.status == "measured"
        assert c.value is not None and 0.0 <= c.value <= 1.0
    # guaranteed wall contact: the westbound bumper pusher crosses the
    # east wall — it must detect, engage, and clear at least one piece
    assert _check(s, "detects").status == "pass"
    assert _check(s, "proportion_engaged").value >= 1 / 28 - 1e-9
    assert _check(s, "proportion_cleared").value >= 1 / 28 - 1e-9
    island = _check(s, "stays_on_island")
    assert island.goal == "remain_on_island"
    # measured joined with the encounter redesign (2026-09-01); abstained
    # with the boundary family (Phase 1)
    assert island.status == "measured" or island.abstained
    if island.status == "measured":
        assert 0.0 <= island.value <= 1.0
    # measurements stay out of the best-status facet roll-up
    for facets in responsive.goal_mapping.values():
        assert "measured" not in facets.values()


def test_banded_rollup_integration(responsive):
    """Banded rollup v2 (§4.8 fully ruled 2026-09-04) end to end on a
    real report: both goals present; a scored goal carries a ruled band
    + flat score, an evidence-free goal reads U with a sub-tag (D3(b) —
    the resolution of the old 0-vs-U provisional pin)."""
    from goal_strategy.battery_rollup import (
        banded_rollup, load_rollup_card)
    card = load_rollup_card("castle_crashers")
    bands = banded_rollup(responsive, card, probabilities=False)
    assert set(bands) == {"clear_debris_zone", "remain_on_island"}
    cdz_names = [r["band"] for r in card["goals"]["clear_debris_zone"]["rungs"]]
    roi_names = [r["band"] for r in card["goals"]["remain_on_island"]["rungs"]]
    for goal, gb in bands.items():
        names = cdz_names if goal == "clear_debris_zone" else roi_names
        if gb.indeterminate:
            assert gb.band is None and gb.score is None
            assert gb.label.startswith("U/")
        else:
            assert gb.band in names
            assert 0.0 <= gb.score <= 1.0
            assert gb.n_valid > 0
    # the responsive pusher clears somewhere — CDZ must be scored
    assert not bands["clear_debris_zone"].indeterminate


def test_battery_uses_push_model_only_in_scenarios(responsive):
    # Sanity: the main profile pipeline still never clears pieces — the push
    # switch lives only in scenario cards.
    from goal_strategy.config import load_configs
    cfg = load_configs("castle_crashers")
    assert cfg.context.testcase_physics == {}


# --------------------------------- Option A: sequential-goal isolation

# Phase 1 of the code pursues a different goal (drive north 800, turn to
# face west); only THEN does the bumper-gated clearing code engage. Under
# Option A the piece materializes when the bumper is first consulted —
# ahead of the robot's pose AT THAT MOMENT, not ahead of spawn.
SEQUENTIAL_CLEARER = """<xml xmlns="https://developers.google.com/blockly/xml">
<block type="pg_events_when_started" id="h1"><next>
<block type="pg_drivetrain_turn_for" id="t0"><field name="TURNDIRECTION">right</field>
  <value name="AMOUNT"><shadow type="math_number" id="s0"><field name="NUM">90</field></shadow></value><next>
<block type="pg_drivetrain_drive_for" id="d0"><field name="DIRECTION">fwd</field>
  <field name="UNITS">mm</field>
  <value name="AMOUNT"><shadow type="math_number" id="s1"><field name="NUM">800</field></shadow></value><next>
<block type="pg_drivetrain_turn_for" id="t1"><field name="TURNDIRECTION">left</field>
  <value name="AMOUNT"><shadow type="math_number" id="s2"><field name="NUM">90</field></shadow></value><next>
<block type="pg_drivetrain_drive" id="d1"><field name="DIRECTION">fwd</field><next>
<block type="pg_control_wait_until" id="w1">
  <value name="CONDITION"><block type="pg_sensing_bumper" id="b1">
    <field name="BUMPER">leftbumper</field></block></value><next>
<block type="pg_drivetrain_drive_for" id="d2"><field name="DIRECTION">fwd</field>
  <field name="UNITS">mm</field>
  <value name="AMOUNT"><shadow type="math_number" id="s3"><field name="NUM">2500</field></shadow></value>
</block></next></block></next></block></next></block></next></block></next></block></next></block></xml>"""


def test_sequential_goal_piece_materializes_at_phase_two(syn_configs):
    report = run_battery(SEQUENTIAL_CLEARER, "sequential-clearer",
                         configs_dir=syn_configs)
    # syn_relative_reset keeps Option A (late materialization,
    # per-construct variants) exercised now that every relative-placement
    # production card has retired (piece_* 2026-08-28; two_pieces_reset
    # 2026-09-01 — the boundary family stages pieces via world events).
    two = _scenario(report, "syn_relative_reset")
    # Phase 1 ran uncontaminated; the clearing phase still earns credit.
    assert _check(two, "detects").status == "pass"
    assert _check(two, "pushes_off").status == "pass"
    assert two.construct.startswith("pg_sensing_bumper")


def test_spawn_override_merges_rather_than_replacing():
    """T5 blocker (2026-08-28): a card declaring only `heading:` must
    inherit the canonical x/y. _scenario_card replaced default_start
    wholesale, which dropped the position — unexercised until T5 because
    no production scenario had used `spawn:`."""
    from goal_strategy.config import _load_yaml
    from goal_strategy.testcases import _scenario_card
    base = _load_yaml(_ROOT / "configs" / "playgrounds" / "castle_crashers.yaml")
    canon = base["spawn_points"]["default_start"]

    heading_only = _scenario_card(base, {"spawn": {"heading": 270}},
                                  with_pieces=False)["spawn_points"]["default_start"]
    assert heading_only["heading"] == 270
    assert (heading_only["x"], heading_only["y"]) == (canon["x"], canon["y"])

    full = _scenario_card(base, {"spawn": {"x": -100, "y": 200, "heading": 90}},
                          with_pieces=False)["spawn_points"]["default_start"]
    assert (full["x"], full["y"], full["heading"]) == (-100, 200, 90)

    # no spawn key at all: untouched
    none = _scenario_card(base, {}, with_pieces=False)["spawn_points"]["default_start"]
    assert (none["x"], none["y"]) == (canon["x"], canon["y"])


def test_t5_heading_family(responsive):
    """T5 reuses T1's world unchanged and varies ONLY the spawn heading,
    so evidence variables stay directly comparable across the
    perturbation."""
    t5 = [s for s in responsive.scenarios
          if s.family == "t5_heading_perturbation"]
    assert sorted(s.scenario_id for s in t5) == \
        ["t5a_mild", "t5b_moderate", "t5c_severe"]
    t1 = next(s for s in responsive.scenarios if s.family == "t1_debris_field")
    for s in t5:
        assert s.construct == "static"
        # identical check list to T1 — the comparison is the whole point
        assert [c.name for c in s.checks] == [c.name for c in t1.checks]
        for name in ("proportion_engaged", "proportion_cleared"):
            c = _check(s, name)
            assert c.status == "measured" and 0.0 <= c.value <= 1.0
        island = _check(s, "stays_on_island")
        assert island.goal == "remain_on_island"
        assert island.status == "measured" or island.abstained
        if island.status == "measured":
            assert 0.0 <= island.value <= 1.0


def test_t5_cards_share_t1_world_and_differ_only_in_heading():
    from goal_strategy.testcases import load_scenarios
    by_id = {s["scenario_id"]: s for s in load_scenarios("castle_crashers")}
    t1 = by_id["t1_castle_wall"]
    for sid, heading in (("t5a_mild", 330), ("t5b_moderate", 270),
                         ("t5c_severe", 180)):
        card = by_id[sid]
        assert card["pieces"] == t1["pieces"], "T5 must reuse T1's world"
        assert card["testcase_physics"] == t1["testcase_physics"]
        assert card["goal"] == t1["goal"]
        assert card["applies"] == t1["applies"]
        assert card["spawn"] == {"heading": heading}
        assert all("requires" not in c for c in card["checks"])


def test_rollup_card_is_banded_v2():
    """The v1 vocabulary is RETIRED (D2(a) 2026-09-04): no contributions,
    weights, pass_score or levels anywhere in the card — the ruled shape
    is check + rungs (+ sparse_min_valid). The old T5-exclusion worry
    died with the levels machinery: under the FLAT ruling every valid
    test contributes equally, T5 included, and a structurally-hard
    variant simply lowers the mean it honestly lowers."""
    import json
    from goal_strategy.battery_rollup import load_rollup_card
    card = load_rollup_card("castle_crashers")
    dumped = json.dumps(card)
    for v1_word in ("contributions", "pass_score", "robust_min_fraction",
                    "conditional_credit"):
        assert v1_word not in dumped
    for goal, spec in card["goals"].items():
        assert spec["check"] and spec["rungs"]


def test_t4_debris_configuration_family(responsive):
    """T4 replaces the retired piece_* cards: same canonical spawn, only
    the DEBRIS CONFIGURATION varies, so the family reads generalisation
    of clearing behaviour rather than start dependence (that is T5)."""
    t4 = [s for s in responsive.scenarios
          if s.family == "t4_debris_configuration"]
    assert sorted(s.scenario_id for s in t4) == \
        ["t4a_near_favorable", "t4b_jittered", "t4c_dispersed"]
    t1 = next(s for s in responsive.scenarios if s.family == "t1_debris_field")
    for s in t4:
        assert s.construct == "static"          # absolute placements
        assert [c.name for c in s.checks] == [c.name for c in t1.checks]
        for name in ("proportion_engaged", "proportion_cleared"):
            c = _check(s, name)
            assert c.status == "measured" and 0.0 <= c.value <= 1.0
        assert _check(s, "stays_on_island").goal == "remain_on_island"


def test_t4_placements_match_their_declared_geometry():
    """The card headers make geometric claims; pin them against the real
    playground polygons so a later edit cannot quietly falsify them."""
    from goal_strategy.detector.simulation.simulate_path import (
        _point_in_convex_polygon)
    from goal_strategy.config import _load_yaml
    from goal_strategy.testcases import load_scenarios
    card = _load_yaml(_ROOT / "configs" / "playgrounds" / "castle_crashers.yaml")
    zone = [tuple(v) for v in card["regions"]["debris_zone"]["polygon_mm"]]
    island = [tuple(v) for v in card["field_boundary"]["polygon_mm"]]
    castle = {(p["x"], p["y"]) for p in
              card["objects"]["castle_debris"]["pieces"].values()}
    by_id = {s["scenario_id"]: s for s in load_scenarios("castle_crashers")}
    spawn = card["spawn_points"]["default_start"]

    def pts(sid):
        return [(p["x"], p["y"]) for p in by_id[sid]["pieces"].values()]

    # T4a: real castle positions, all inside the zone
    a = pts("t4a_near_favorable")
    assert all(p in castle for p in a), "T4a must use REAL castle positions"
    assert all(_point_in_convex_polygon(x, y, zone) for x, y in a)
    # T4b: inside the zone but OFF the castle geometry
    b = pts("t4b_jittered")
    assert all(_point_in_convex_polygon(x, y, zone) for x, y in b)
    assert not any(p in castle for p in b), "T4b must be off castle positions"
    # T4c: outside the zone, still on the island, one directly BEHIND spawn
    c = pts("t4c_dispersed")
    assert all(not _point_in_convex_polygon(x, y, zone) for x, y in c)
    assert all(_point_in_convex_polygon(x, y, island) for x, y in c)
    assert any(x > spawn["x"] and abs(y - spawn["y"]) < 100 for x, y in c), \
        "T4c must place one block directly behind the spawn"
    # every family: no piece can pin two neighbours in one push
    import math
    for sid in ("t4a_near_favorable", "t4b_jittered", "t4c_dispersed"):
        p = pts(sid)
        seps = [math.hypot(p[i][0] - p[j][0], p[i][1] - p[j][1])
                for i in range(len(p)) for j in range(i + 1, len(p))]
        assert min(seps) >= 350, f"{sid} pieces too close: {min(seps):.0f}mm"


def test_retired_piece_cards_are_gone():
    from goal_strategy.testcases import load_scenarios
    ids = {s["scenario_id"] for s in load_scenarios("castle_crashers")}
    assert not any(i.startswith("piece_") for i in ids)
    assert {"t4a_near_favorable", "t4b_jittered", "t4c_dispersed"} <= ids


def test_random_draws_are_paired_across_a_scenarios_two_runs():
    """A battery scenario compares a BASELINE run against a with-pieces run;
    `detects` is that path divergence. If a program's `choose random` block
    drew different values in the two runs, the divergence would measure OUR
    sampling instead of the program's response to the pieces. Seeding on the
    program id makes the two runs draw the same sequence, so a program whose
    behaviour the pieces do not change shows ZERO divergence (2026-08-28)."""
    random_forever = """<xml xmlns="https://developers.google.com/blockly/xml">
<block type="pg_events_when_started" id="h1"><next>
<block type="pg_control_forever" id="f1"><statement name="SUBSTACK">
<block type="pg_drivetrain_turn_for" id="t1"><field name="TURNDIRECTION">right</field>
  <value name="AMOUNT"><block type="pg_operator_random" id="r1">
    <value name="FROM"><shadow type="math_number"><field name="NUM">60</field></shadow></value>
    <value name="TO"><shadow type="math_number"><field name="NUM">120</field></shadow></value>
  </block></value><next>
<block type="pg_sensing_bumper" id="b1"><field name="BUMPER">leftbumper</field></block>
</next></block></statement></block></next></block></xml>"""
    report = run_battery(random_forever, "paired-rng", collect_sims=True)
    assert report.eligible, "needs a sensing block to be battery-eligible"
    checked = 0
    for art in report.artifacts:
        # the draws must line up run-for-run
        assert art.baseline.nondeterministic_draws == art.sim.nondeterministic_draws
        assert "nondeterministic_variable" in art.sim.execution_flags
        if art.baseline.nondeterministic_draws:
            checked += 1
    assert checked, "the fixture must actually exercise the random block"
