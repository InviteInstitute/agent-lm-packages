"""The OI-21 attachment ground-truth ledger as executable tripwires.

Every reviewer-run probe (P-series 2026-08-19, M-series 2026-08-21) is
encoded against `state_active_attachment_clearance` with the card's model:
magnet-point near-contact, blade gap 75 (bracket [68,82)), hitch gap 40
(bracket [31,52)). A model or card change that breaks a probe result fails
here by name.
"""
from __future__ import annotations

import math
from types import SimpleNamespace

import pytest

from goal_strategy.indicators import (
    EvalContext,
    state_active_attachment_clearance,
)

CARD = {
    "objects": {
        "plow": {
            "attachment": {
                "reference": "magnet_point",
                "structures": {
                    "blade": {"rect_mm": {"center": [158.9, 1317.9],
                                          "width": 292, "height": 106},
                              "attach_gap_mm": 75},
                    "hitch": {"point_mm": [163, 1169], "attach_gap_mm": 40},
                },
                "marginal_band_mm": 15,
            }
        }
    }
}
MOUNT = 66.5
NORTH, EAST, WEST = 90.0, 0.0, 180.0   # math-convention headings


def _ctx(path):
    sim = SimpleNamespace(path=path, magnet_fires_at_step=0)
    return EvalContext(
        program_id="probe", playground="castle_crashers", card=CARD,
        context=SimpleNamespace(objects={},
                                sensor_specs={"magnet": {"mount_forward_mm": MOUNT}}),
        block_families={}, code_facts=None, full_sim=sim, scored_sim=sim,
        playground_params=None, boundary_exceeded=False, boundary_exit_step=None)


def _step(step, x, y, heading):
    return SimpleNamespace(step=step, x=x, y=y, heading=heading)


def _margin(path):
    res = state_active_attachment_clearance(_ctx(path),
                                            {"object": "plow", "state": "magnet_active"})
    return res


# ── static P-series (east-approach parks and facing variants, 2026-08-19) ──

def test_p2b_static_facing_attaches_via_hitch():
    # centre (163,1100) facing north: magnet 2.5mm from the hitch
    res = _margin([_step(0, 163, 1100, NORTH)])
    assert res.value < 0


def test_p7_static_facing_fails():
    # centre (163,1050): magnet 52.5 from hitch (>40), 148.5 from blade (>75)
    res = _margin([_step(0, 163, 1050, NORTH)])
    assert res.value > 0


def test_p_ladder_passes():
    # westward passes at graded y: magnet traces the lane. NO/NO/YES/YES/YES/YES
    for y, attaches in ((1000, False), (1100, False), (1200, True),
                       (1249, True), (1285, True), (1350, True)):
        path = [_step(0, 900, y, WEST), _step(1, -200, y, WEST)]
        res = _margin(path)
        assert (res.value <= 0) == attaches, f"P-ladder y={y}: margin {res.value}"


# ── M-series (north side + gating, 2026-08-21) ──

def test_m1_pass_150_north_fails():
    path = [_step(0, 500, 1468, WEST), _step(1, -300, 1468, WEST)]
    assert _margin(path).value > 0


def test_m2_pass_242_north_fails():
    path = [_step(0, 500, 1560, WEST), _step(1, -300, 1560, WEST)]
    assert _margin(path).value > 0


def test_m3_rear_contact_does_not_attach():
    # reverse south facing north: tail ~1mm off the blade, magnet 134.5 away.
    # The magnet point's TRAVEL is a north-facing segment from y=1560 down.
    path = [_step(0, 163, 1560, NORTH), _step(1, 164, 1439, NORTH)]
    assert _margin(path).value > 0


def test_m3b_turn_swings_magnet_into_attach():
    # after M3: turn north->east swings the magnet gap 134.5 -> 68 (<75)
    path = [_step(0, 164, 1439, NORTH), _step(1, 164, 1439, EAST)]
    assert _margin(path).value < 0


def test_m3c_turn_at_82mm_gap_fails():
    path = [_step(0, 163, 1453, NORTH), _step(1, 163, 1453, EAST)]
    assert _margin(path).value > 0


# ── corpus ground truth ──

def test_c032_step4_diagonal_clips_blade():
    # the observed second-drive attach: segment (840,1034)->(-26,1534)
    # crosses the blade's east corner region
    h = math.degrees(math.atan2(500.0, -866.0))
    path = [_step(0, 840.4, 1033.8, h), _step(1, -25.7, 1533.8, h)]
    assert _margin(path).value <= 0


def test_c031_east_pass_attaches():
    # final drive (329,1111)->(347,1311): magnet lane ~32mm east of the blade
    h = math.degrees(math.atan2(199.3, 17.4))
    path = [_step(0, 329.3, 1111.5, h), _step(1, 346.7, 1310.8, h)]
    assert _margin(path).value < 0


# ── machinery ──

def test_marginal_band_flags_boundary_cases():
    # a turn ending with the magnet 78mm off the blade: margin +3, in-band
    path = [_step(0, 163, 1449, NORTH), _step(1, 163, 1449, EAST)]
    res = _margin(path)   # gap 78 -> margin +3, inside the band
    assert 0 < res.value <= 15
    assert "attachment_boundary_marginal" in res.flags


def test_never_armed_is_meaningful_absence():
    sim = SimpleNamespace(path=[_step(0, 163, 1100, NORTH)], magnet_fires_at_step=None)
    ctx = _ctx([])
    ctx = EvalContext(**{**ctx.__dict__, "full_sim": sim, "scored_sim": sim})
    res = state_active_attachment_clearance(ctx, {"object": "plow", "state": "magnet_active"})
    assert res.value is None and not res.abstained


def test_missing_attachment_block_abstains():
    ctx = _ctx([_step(0, 163, 1100, NORTH)])
    res = state_active_attachment_clearance(ctx, {"object": "rock", "state": "magnet_active"})
    assert res.abstained and res.abstain_reason == "no_attachment_model"
