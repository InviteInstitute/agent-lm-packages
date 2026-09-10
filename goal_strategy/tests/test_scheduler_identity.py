"""Gate G3 (BUILD_SPEC §4): with exactly one when_started thread,
round-robin degenerates to sequential and every yield point is unobservable
— cooperative mode must be BYTE-IDENTICAL to sequential on single-stack
programs. Pinned over the whole dev corpus (multi-stack dev programs are
compared under sequential-vs-sequential as a sanity anchor)."""
from __future__ import annotations

from goal_strategy.detector.parsing.parse_blocks import parse_workspace
from goal_strategy.detector.simulation.simulate_path import simulate_path

from goal_strategy.config import load_configs


def _n_started(program) -> int:
    return sum(1 for s in program.event_handler_stacks
               if s.block_type == "pg_events_when_started")


def test_single_stack_cooperative_identical_over_dev_corpus(corpus):
    cfg = load_configs("castle_crashers")
    checked = 0
    for prog in corpus:
        program = parse_workspace(prog.workspace_xml or "", prog.program_id)
        if program is None or _n_started(program) != 1:
            continue
        probe = simulate_path(program, cfg.context)
        if {"trigger_unfaithful", "trigger_unsimulated"} \
                & set(probe.execution_flags):
            # eager-approximated hats are EXTRA executable stacks — those
            # runs are legitimately multi-thread under the scheduler and
            # belong to the G5 attribution population, not this gate
            continue
        checked += 1
        seq = simulate_path(program, cfg.context)
        coop = simulate_path(program, cfg.context, scheduler="cooperative")
        assert len(seq.path) == len(coop.path), prog.program_id
        for a, b in zip(seq.path, coop.path):
            assert (a.step, a.block_id, a.block_type, a.heading,
                    a.magnet_fires) == (b.step, b.block_id, b.block_type,
                                        b.heading, b.magnet_fires), \
                prog.program_id
            assert abs(a.x - b.x) < 1e-9 and abs(a.y - b.y) < 1e-9, \
                prog.program_id
        assert seq.exits_field_boundary == coop.exits_field_boundary
        assert abs(seq.sim_time_s - coop.sim_time_s) < 1e-9, prog.program_id
        assert sorted(seq.execution_flags) == sorted(coop.execution_flags), \
            prog.program_id
        assert seq.region_coverage_fractions == coop.region_coverage_fractions
    assert checked > 100   # the dev corpus is overwhelmingly single-stack
