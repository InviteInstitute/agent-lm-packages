"""The §5 acceptance test: a synthetic second playground + goal card produces a
valid profile with ZERO changes to src/. Everything below is data — including the
block type strings, which are corpus vocabulary, not code."""
import textwrap

from goal_strategy.config import load_configs
from goal_strategy.profile import _profile

PLAYGROUND = textwrap.dedent("""
    playground_id: toy_arena
    field_geometry: {playable_radius_mm: 6000}
    spawn_points: {default_start: {x: 0, y: 0, heading: 0}}   # VEX 0 = math 180 = west
    robot: {width_mm: 50.8}
    field_boundary:
      polygon_mm: [[-5000, -5000], [5000, -5000], [5000, 5000], [-5000, 5000]]
    objects:
      beacon: {x: -2286, y: 0, tolerance: 100, object_type: target}
    regions:
      pad: {x_min: -2300, x_max: 0, y_min: -200, y_max: 200}
    block_families:
      magnet: [pg_magnet_set_magnet_state]
      movement: [pg_drivetrain_drive_for, pg_drivetrain_turn_for]
""")

GOALS = textwrap.dedent("""
    playground: toy_arena
    version: 1
    goals:
      - id: reach_beacon
        intent:
          - name: beacon_approach
            indicator: min_distance_to_object
            binding: {object: beacon}
            rungs:
              direction: lower_is_better
              reference: object.tolerance
              edges_as_multiples: [1.0, 2.0]
              labels: [reached, near, far]
        attainment:
          - name: beacon_engaged
            indicator: state_active_within_radius
            binding: {object: beacon, state: magnet_active}   # no zones_ref: opt-in proven
            rungs:
              direction: lower_is_better
              reference: object.tolerance
              edges_as_multiples: [1.0]
              labels: [armed_close, armed_far]
              absent_label: not_armed
      - id: cover_pad
        intent:
          - name: pad_coverage
            indicator: region_coverage
            binding: {region: pad}
            rungs:
              direction: higher_is_better
              edges: [0.01]
              labels: [low, high]
        attainment:
          - name: magic_points
            indicator: outcome_field
            binding: {field: magic_points}
            rungs:
              direction: higher_is_better
              edges: [1]
              labels: [none, some]
      - id: just_show_up
        intent:
          - name: moved_at_all
            indicator: code_movement_authored
            binding: {block_family: movement}
            rungs:
              direction: higher_is_better
              edges: [1]
              labels: [none, authored]
        attainment: []                                        # empty by design
""")

# when_started -> magnet boost -> drive forward 90in (2286mm) west onto the beacon.
XML = """<xml xmlns="https://developers.google.com/blockly/xml">
  <block type="pg_events_when_started" id="e1"><next>
    <block type="pg_magnet_set_magnet_state" id="m1">
      <field name="MAGNET">Magnet</field><field name="ACTION">boost</field>
      <next>
        <block type="pg_drivetrain_drive_for" id="d1">
          <field name="DIRECTION">fwd</field><field name="UNITS">in</field>
          <value name="AMOUNT"><shadow type="math_number" id="s1">
            <field name="NUM">90</field></shadow></value>
        </block>
      </next>
    </block>
  </next></block>
</xml>"""


def test_synthetic_playground_profiles_without_src_changes(tmp_path):
    (tmp_path / "playgrounds").mkdir()
    (tmp_path / "goals").mkdir()
    (tmp_path / "playgrounds" / "toy_arena.yaml").write_text(PLAYGROUND)
    (tmp_path / "goals" / "toy_arena.yaml").write_text(GOALS)
    load_configs.cache_clear()
    try:
        prof = _profile(XML, "synthetic_1", playground_params={"other_stat": 5},
                        playground="toy_arena", configs_dir=str(tmp_path))
    finally:
        load_configs.cache_clear()

    assert prof.playground == "toy_arena"
    assert [g.goal for g in prof.goals] == ["reach_beacon", "cover_pad", "just_show_up"]
    assert not prof.boundary_exceeded and prof.boundary_exit_step is None
    assert prof.config_version

    reach, cover, show_up = prof.goals

    approach = reach.intent[0]
    assert approach.rung == "reached" and approach.value is not None
    assert approach.rung_edges == [100.0, 200.0]     # derived from object.tolerance

    engaged = reach.attainment[0]
    assert engaged.rung == "armed_close"
    assert "simulated_attainment" in engaged.flags
    assert engaged.flags.count("simulated_attainment") == 1

    coverage = cover.intent[0]
    assert not coverage.abstained and coverage.value > 0

    points = cover.attainment[0]
    assert points.abstained and points.abstain_reason == "outcome_field_absent"
    assert points.value is None and points.rung is None

    moved = show_up.intent[0]
    assert moved.rung == "authored" and moved.value == 1
    assert show_up.attainment == []                  # empty list representable
