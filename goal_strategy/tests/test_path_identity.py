"""Path-identity test — proves the substrate copy is faithful, permanently.

Replays THIS project's simulator over all 119 programs and asserts the PathStep
sequences match the frozen reference implementation's dump
(data/frozen_paths.parquet, produced by tools/dump_frozen_paths.py) on
(x, y, heading, block_id) per step, plus sequence length and program set.

This is not a one-shot copy check: it is the baseline for the §15.1 simulator-change
taxonomy. An *additive* change keeps this test green bit-for-bit. A *population-* or
*path-changing* change is expected to break it — deliberately, one change at a time,
each with its own attribution — at which point the fixture is regenerated and the
change recorded.

Adapted for goal_strategy — full diff vs VEX_model_tracing/tests/test_path_identity.py:
  - from goal_strategy.detector.io.load_cards import load_playground_card
  - from goal_strategy.detector.io.load_inputs import load_final_code_states
  + from goal_strategy.tests.helpers import load_playground_card, load_final_code_states
  - card = load_playground_card(_ROOT / "playgrounds" / "castle_crashers.yaml")
  + card = load_playground_card(_ROOT / "configs" / "playgrounds" / "castle_crashers.yaml")
  + robot_card = load_playground_card(_ROOT / "configs" / "robot" / "vr_robot.yaml")
  + context = PlaygroundContext.from_playground_card(card, robot_card)   # was (card)
    (sensing build Phase 1, 2026-08-19 — the baseline must build contexts the
    way the pipeline does, with the shared robot card's sensor specs)
Every assertion, fixture body, and the tolerance block are byte-identical to the source.
"""
from __future__ import annotations

from goal_strategy.paths import data_path

from pathlib import Path

import pandas as pd
import pytest

_ROOT = Path(__file__).resolve().parent.parent
_FIXTURE = data_path() / "frozen_paths.parquet"

from goal_strategy.tests.helpers import load_playground_card, load_final_code_states
from goal_strategy.detector.parsing.parse_blocks import parse_workspace
from goal_strategy.detector.simulation.simulate_path import PlaygroundContext, simulate_path


@pytest.fixture(scope="module")
def frozen() -> pd.DataFrame:
    assert _FIXTURE.exists(), "run tools/dump_frozen_paths.py first"
    return pd.read_parquet(_FIXTURE)


@pytest.fixture(scope="module")
def replayed() -> pd.DataFrame:
    card = load_playground_card(_ROOT / "configs" / "playgrounds" / "castle_crashers.yaml")
    # Sensing build Phase 1 (2026-08-19): the pipeline builds contexts with the
    # shared robot card (eye offsets); the identity baseline must match it.
    robot_card = load_playground_card(_ROOT / "configs" / "robot" / "vr_robot.yaml")
    context = PlaygroundContext.from_playground_card(card, robot_card)
    programs = load_final_code_states(str(data_path() / "final_code_states.parquet"))
    rows = []
    for prog in programs:
        if not prog.workspace_xml:
            continue
        sim = simulate_path(parse_workspace(prog.workspace_xml, prog.program_id), context)
        for i, ps in enumerate(sim.path):
            rows.append({"program_id": prog.program_id, "seq": i, "step": ps.step,
                         "x": ps.x, "y": ps.y, "heading": ps.heading,
                         "block_id": ps.block_id, "block_type": ps.block_type})
    return pd.DataFrame(rows)


def test_same_program_set(frozen, replayed):
    assert set(replayed.program_id) == set(frozen.program_id)


def test_same_path_lengths(frozen, replayed):
    fl = frozen.groupby("program_id").size()
    rl = replayed.groupby("program_id").size()
    diff = {p: (int(fl[p]), int(rl[p])) for p in fl.index if fl[p] != rl.get(p, -1)}
    assert not diff, f"path lengths differ: {diff}"


# Positional tolerance, in mm. The simulator is a reconstruction (design §2.2), so fidelity
# is claimed at the scale where position means something — not at the bit.
#
# Sized deliberately between two quantities:
#   ~4e-12 mm  cross-platform libm drift in sin/cos/sqrt, accumulated over a few hundred
#              steps. Observed: 1101 steps across 20 programs differ by at most this much
#              between macOS/CPython 3.9 and Linux/CPython 3.10 on identical source.
#   ~1 mm      the smallest positional change any real path-changing fix produces
#              (F-2's spawn origin, t_tol_after_fire).
# 1e-9 sits three orders below the smallest real change and three above the noise, so the
# test still fails loudly on every change it exists to catch, and passes on every machine.
#
# The discrete fields carry NO tolerance: a heading, a block_id, a block_type, a step count
# or a program set that differs is a real divergence at any magnitude.
_POS_TOL_MM = 1e-9


def test_paths_identical_per_step(frozen, replayed):
    key = ["program_id", "seq"]
    cols = ["x", "y", "heading", "block_id"]
    m = frozen[key + cols].merge(replayed[key + cols], on=key, suffixes=("_f", "_r"))
    assert len(m) == len(frozen)
    mism = m[
        ((m.x_f - m.x_r).abs() > _POS_TOL_MM)
        | ((m.y_f - m.y_r).abs() > _POS_TOL_MM)
        | (m.heading_f != m.heading_r)
        | (m.block_id_f != m.block_id_r)
    ]
    assert mism.empty, (
        f"{len(mism)} mismatching steps across "
        f"{mism.program_id.nunique()} programs; first:\n{mism.head(5)}"
    )


def test_positional_tolerance_is_far_below_any_real_change(frozen, replayed):
    """The tolerance must never be large enough to hide a path-changing fix.

    Guards the constant itself: if someone widens _POS_TOL_MM to make a failing test pass,
    this fails first and says why.
    """
    assert _POS_TOL_MM < 1e-3, (
        "positional tolerance approaching the scale of real path changes; "
        "a path-changing simulator fix must break test_paths_identical_per_step, "
        "not be absorbed by it (design §15.1 change taxonomy)"
    )
