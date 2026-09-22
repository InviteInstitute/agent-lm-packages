"""Battery-side rubric evidence (B-2 layers 2+3): the extracts read the
preserved scenario artifacts against card-declared episode_rules. Probed
with the same strategy archetypes the boundary cards were frozen with.
"""
from __future__ import annotations

import pytest

from goal_strategy.battery_evidence import battery_evidence

NS = 'xmlns="https://developers.google.com/blockly/xml"'


def _num(v):
    return f'<shadow type="math_number"><field name="NUM">{v}</field></shadow>'


RED = ('<block type="pg_sensing_optical_color" id="oc"><field name="OPTICAL">downeye</field>'
       '<field name="COLORS">red</field></block>')
DIST = '<block type="pg_sensing_distance_found" id="sf"><field name="DISTANCE">distance</field></block>'
NOT_DIST = f'<block type="pg_operator_not" id="nt"><value name="OPERAND">{DIST}</value></block>'


def _forever(inner):
    return ('<block type="pg_control_forever" id="f1"><statement name="SUBSTACK">'
            f'{inner}</statement></block>')


def _prog(body):
    return (f"<xml {NS}><block type=\"pg_events_when_started\" id=\"h\">"
            f"<next>{body}</next></block></xml>")


def _chain(*bs):
    xml = ""
    for b in reversed(bs):
        xml = b[:-len("</block>")] + (f"<next>{xml}</next>" if xml else "") + "</block>"
    return xml


RED_CYCLER = _prog(_forever(_chain(
    '<block type="pg_drivetrain_drive" id="dv"><field name="DIRECTION">fwd</field></block>',
    f'<block type="pg_control_wait_until" id="w1"><value name="CONDITION">{RED}</value></block>',
    ('<block type="pg_drivetrain_drive_for" id="rv"><field name="DIRECTION">rev</field>'
     f'<field name="UNITS">mm</field><value name="AMOUNT">{_num(600)}</value></block>'),
    f'<block type="pg_control_if_then" id="if1"><value name="CONDITION">{DIST}</value></block>')))

CUE_PUSHER = _prog(_forever(_chain(
    '<block type="pg_drivetrain_drive" id="dv"><field name="DIRECTION">fwd</field></block>',
    f'<block type="pg_control_wait_until" id="w1"><value name="CONDITION">{DIST}</value></block>',
    f'<block type="pg_control_wait_until" id="w2"><value name="CONDITION">{NOT_DIST}</value></block>',
    ('<block type="pg_drivetrain_drive_for" id="rv"><field name="DIRECTION">rev</field>'
     f'<field name="UNITS">mm</field><value name="AMOUNT">{_num(500)}</value></block>'))))


@pytest.fixture(scope="module")
def cycler():
    return {e.scenario_id: e for e in battery_evidence(RED_CYCLER, "cycler")}


@pytest.fixture(scope="module")
def pusher():
    return {e.scenario_id: e for e in battery_evidence(CUE_PUSHER, "pusher")}


def test_cycler_boundary_evidence(cycler):
    """The regulator: corrective response present on a fresh-encounter
    card, and the seams show boundary/retreat structure. (The repeated
    band-entry assertion moved to T7 with the 2026-09-03 restructure —
    the repeat cards are retired; T7's multi-piece tight-clear world is
    now the designed source of band>=2 evidence.)"""
    e = cycler["t2c_steep"]
    assert not e.abstained
    assert e.boundary_band_entries >= 1
    assert e.corrective_response_present is True
    assert e.code is not None and e.code.sensing_in_recurrent


def test_cycler_responds_quickly(cycler):
    e = cycler["t2a_direct"]
    assert e.response_latency_mm is not None
    # placed edge 900mm ahead: the divergence (reverse vs baseline's
    # continued drive) begins around the ring, within ~1.2m of onset
    assert e.response_latency_mm < 1600


def test_pusher_engagement_and_clear_cue(pusher):
    """The T3 cue user: engages the placed block, clears it, and acts on
    the vanish promptly (the post-clear latency is the cue-use signal)."""
    e = pusher["t3a_generous"]
    assert not e.abstained
    assert e.engagement_latency_mm is not None
    assert e.post_clear_action_latency_mm is not None
    assert e.post_clear_action_latency_mm < 600
    assert any(k == "engage" for _, k in e.behavioral_seams)
    assert any(k == "clear" for _, k in e.behavioral_seams)


# A bumper program whose contact never fires: it evaluates a sensor (so
# it is eligible and activates) but never approaches an edge — genuinely
# abstains encounter_not_reached on the boundary families after the
# intersection/assured-detection redesign made object-pursuers activate.
_STiLL = _prog(_forever(
    '<block type="pg_control_if_then" id="i1">'
    '<value name="CONDITION"><block type="pg_sensing_bumper" id="b1">'
    '<field name="BUMPER">leftbumper</field></block></value>'
    '<statement name="SUBSTACK"><block type="pg_drivetrain_turn_for" id="t1">'
    '<field name="TURNDIRECTION">right</field>'
    f'<value name="AMOUNT">{_num(10)}</value></block></statement></block>'))


def test_abstained_scenario_carries_no_extracts():
    """An abstained scenario yields an ABSTAINED evidence record — no
    fabricated latencies, no code extract (the ruled U semantics)."""
    evs = {e.scenario_id: e for e in battery_evidence(_STiLL, "still")}
    abstained = [e for e in evs.values() if e.abstained]
    assert abstained, "expected at least one abstained scenario"
    for e in abstained:
        assert e.abstain_reason
        assert e.response_latency_mm is None
        assert e.engagement_latency_mm is None
        assert e.code is None


def test_ineligible_program_yields_no_evidence():
    xml = _prog('<block type="pg_drivetrain_drive_for" id="d1">'
                '<field name="DIRECTION">fwd</field><field name="UNITS">mm</field>'
                f'<value name="AMOUNT">{_num(300)}</value></block>')
    assert battery_evidence(xml, "dead") == []


def test_family_evidence_profiles_and_shared_structure(cycler):
    from goal_strategy.battery_evidence import (
        battery_evidence, family_evidence,
    )
    from goal_strategy.testcases import run_battery
    report = run_battery(RED_CYCLER, "cycler", collect_sims=True)
    evs = battery_evidence(RED_CYCLER, "cycler")
    fams = {f.family: f for f in family_evidence(report, evs)}
    t2 = fams["t2_boundary"]
    assert set(t2.variants) == {"t2a_direct", "t2b_angled", "t2c_steep"}
    # raw per-variant outcomes preserved, no level arithmetic
    assert set(t2.outcome_profile["stays_on_island"]) == set(t2.variants)
    # the cycler's forever loop is the same exercised structure everywhere
    assert "f1" in t2.shared_structure


def test_dimension_u_map_routes_abstentions(pusher):
    """The U-map routes each scenario's abstention to every dimension its
    variables feed, and informative scenarios to `informative`. (Post the
    T6 assured-detection redesign the cue-pusher activates T6, so the
    routing is asserted structurally: every abstained scenario evidence
    lands under its dimensions' `abstained`, and at least one dimension
    has informative scenarios.)"""
    from goal_strategy.battery_evidence import (
        battery_evidence, dimension_u_map, load_evidence_registry,
    )
    evs = battery_evidence(CUE_PUSHER, "pusher")
    reg = load_evidence_registry()
    umap = dimension_u_map(evs, reg)
    abstained_scen = {e.scenario_id for e in evs if e.abstained}
    informative_scen = {e.scenario_id for e in evs if not e.abstained}
    # every abstained scenario that feeds recovery is carried as a U cell
    routed = {sid for sid, _ in umap["recovery"]["abstained"]}
    assert routed <= abstained_scen
    if abstained_scen:
        assert routed  # at least one abstention routed somewhere
    # informative scenarios populate their dimensions
    assert any(sid in informative_scen
               for sid in umap["task_state_regulation"]["informative"])


# ---- construct-separability layer (reviewer-ruled 2026-09-05) ----

def test_task_semantic_variables_on_the_pusher(pusher):
    """The cue-pusher runs full task chains: acquire/engage/clear seams
    present, task transitions counted, and the task count differs from
    the generic transition count (the separability)."""
    informative = [e for e in pusher.values() if not e.abstained]
    kinds = {k for e in informative for _, k in e.behavioral_seams}
    assert {"acquire", "engage", "clear"} <= kinds
    total_task = sum(e.task_state_triggered_transition_count
                     for e in informative)
    total_generic = sum(e.behavioral_transition_count for e in informative)
    assert total_task > 0
    assert total_task != total_generic


def test_cycler_is_recovery_heavy_tsr_light(cycler):
    """The red-cycler regulates the boundary, not task phases: its
    reassessment cycles dwarf its task transitions."""
    informative = [e for e in cycler.values() if not e.abstained]
    cycles = sum(e.correction_reassessment_cycles for e in informative)
    task = sum(e.task_state_triggered_transition_count for e in informative)
    assert cycles > task > 0 or (cycles > 0 and task == 0)


def test_registry_v2_schema():
    """Every variable has at most ONE primary dimension, a valid role,
    and non-scoring roles (validation/diagnostic/metadata, 2026-09-09)
    have no primary — they corroborate, explain, or gate, never
    establish."""
    from goal_strategy.battery_evidence import load_evidence_registry
    reg = load_evidence_registry()
    dims = set(reg["dimensions"])
    for name, var in reg["variables"].items():
        assert var.get("role") in ("indicator", "validation",
                                   "diagnostic", "metadata"), name
        prim = var.get("primary") or []
        assert len(prim) <= 1, name
        assert set(prim) <= dims and set(var.get("supporting") or []) <= dims
        if var["role"] != "indicator":
            assert prim == [], name


def test_dimension_u_map_role_buckets(pusher):
    from goal_strategy.battery_evidence import (
        dimension_u_map, load_evidence_registry)
    umap = dimension_u_map(list(pusher.values()), load_evidence_registry())
    rec = umap["recovery"]
    assert set(rec) >= {"abstained", "informative", "informative_primary",
                        "informative_supporting", "informative_validation"}
    # recovery has primary indicators (corrective/reassessment) — the
    # primary bucket must populate for a program with boundary work
    assert rec["informative_primary"]


# ---- OI-36/OI-37 (reviewer-ruled 2026-09-11): failure-scoped windows,
# signed retreats, densified scans, pre-failure detects ----

class _P:
    def __init__(self, x, y, step):
        self.x, self.y, self.step, self.heading = x, y, step, 0.0


_SQUARE = [(-1000, -1000), (1000, -1000), (1000, 1000), (-1000, 1000)]


def test_scenario_exit_step_semantics():
    from goal_strategy.battery_evidence import _scenario_exit_step
    inside = [_P(0, 0, 0), _P(500, 0, 1), _P(900, 0, 2)]
    assert _scenario_exit_step(inside, _SQUARE, 71.0, (0, 0)) is None
    # crosses out mid-segment: exit attributed to the segment START step
    out = [_P(0, 0, 0), _P(500, 0, 1), _P(2500, 0, 2)]
    assert _scenario_exit_step(out, _SQUARE, 71.0, (0, 0)) == 1
    # a transient poke within grace is NOT failure
    poke = [_P(0, 0, 0), _P(1050, 0, 1), _P(0, 0, 2)]
    assert _scenario_exit_step(poke, _SQUARE, 71.0, (0, 0)) is None


def test_prefail_divergence_chunk_faller_vs_stop_responder():
    """The C015 shape (both runs identical until they fall off) must
    NOT diverge; a stop-responder (halts on-island while the baseline
    drives on) MUST diverge via the pre-failure tail."""
    from goal_strategy.testcases import _path_divergence

    class _S:
        def __init__(self, pts):
            self.path = pts
            self.origin_x, self.origin_y = pts[0].x, pts[0].y
    # chunk faller: same 2000mm chunks, off the square by step 2 in
    # both worlds — failure timing is not detection
    a = _S([_P(0, 0, 0), _P(-2000, 0, 1), _P(-4000, 0, 2)])
    b = _S([_P(0, 0, 0), _P(-2000, 0, 1), _P(-4000, 0, 2), _P(-6000, 0, 3)])
    assert _path_divergence(a, b, polygon=_SQUARE, grace_mm=71.0) < 100
    # stop responder: scored run halts at 300mm (on-island), baseline
    # carries on to 900mm — pre-failure tail divergence
    s = _S([_P(0, 0, 0), _P(300, 0, 1)])
    t = _S([_P(0, 0, 0), _P(300, 0, 1), _P(900, 0, 2)])
    assert _path_divergence(s, t, polygon=_SQUARE, grace_mm=71.0) >= 100


def test_signed_retreat_outbound_crossing_is_not_corrective(cycler,
                                                            pusher):
    """Fixture-level pins: the healthy archetypes keep their corrective
    evidence under the signed/windowed scan (no on-island regression),
    and every scored scenario's exit step is exposed for review."""
    for evs in (cycler, pusher):
        for e in evs.values():
            if e.abstained:
                continue
            assert hasattr(e, "scenario_exit_step")
            if e.corrective_response_present:
                # a credited corrective now implies a pre-failure,
                # on-island retreat existed — cycles machinery agrees
                assert e.boundary_band_entries >= 1
