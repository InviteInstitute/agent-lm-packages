"""Synthetic battery for the OI-7 creation-order recovery (creation_order.py).

The fuller longitudinal sample does not exist in this repo yet (validation
stage); these tests pin the contract against synthetic snapshot sequences so
the eventual adapter has a fixed target.
"""
from __future__ import annotations

import pytest

from goal_strategy.creation_order import (
    recover_creation_order,
    resolve_precedence,
)


def _ws(*stacks: str) -> str:
    blocks = "".join(
        f'<block type="pg_events_when_started" id="{s}" x="0" y="0"/>'
        for s in stacks
    )
    return ('<xml xmlns="https://developers.google.com/blockly/xml">'
            f"{blocks}</xml>")


def test_simple_addition_orders_generations():
    r = recover_creation_order([(1, _ws("A")), (2, _ws("A", "B"))])
    assert [set(g) for g in r.generations] == [{"A"}, {"B"}]
    res = resolve_precedence(r, ["A", "B"])
    assert (res.winner, res.reason) == ("B", "resolved")


def test_window_opening_stacks_are_censored_together():
    r = recover_creation_order([(1, _ws("A", "B")), (2, _ws("A", "B"))])
    a, b = r.appearance("A"), r.appearance("B")
    assert a.window_censored and b.window_censored
    res = resolve_precedence(r, ["A", "B"])
    assert res.winner is None and res.reason == "window_censored"


def test_later_creation_beats_censored_pair():
    r = recover_creation_order(
        [(1, _ws("A", "B")), (2, _ws("A", "B")), (3, _ws("A", "B", "C"))])
    res = resolve_precedence(r, ["A", "B", "C"])
    assert (res.winner, res.reason) == ("C", "resolved")


def test_same_snapshot_tie_is_unresolved_but_beats_older():
    r = recover_creation_order([(1, _ws("A")), (2, _ws("A", "B", "C"))])
    assert resolve_precedence(r, ["B", "C"]).reason == "tied_generation"
    assert resolve_precedence(r, ["A", "B"]).winner == "B"


def test_deleted_stack_keeps_history_new_id_wins():
    # B deleted at run 3; re-created as B2 (fresh id) at run 4: B2 is the
    # most recent creation — correct under the rule (re-creation is creation).
    r = recover_creation_order(
        [(1, _ws("A")), (2, _ws("A", "B")), (3, _ws("A")), (4, _ws("A", "B2"))])
    res = resolve_precedence(r, ["A", "B2"])
    assert (res.winner, res.reason) == ("B2", "resolved")


def test_undo_resurrection_resolves_when_interpretations_agree():
    # B vanishes (run 3) and returns with the SAME id (run 4). First-seen
    # says B (gen 1 > A gen 0); resurrection says B (later still): agree -> B.
    r = recover_creation_order(
        [(1, _ws("A")), (2, _ws("A", "B")), (3, _ws("A")), (4, _ws("A", "B"))])
    assert r.appearance("B").reappeared
    res = resolve_precedence(r, ["A", "B"])
    assert (res.winner, res.reason) == ("B", "resolved")


def test_undo_resurrection_ambiguous_when_interpretations_conflict():
    # B created FIRST (run 1), A later (run 2); then B vanishes (run 3) and
    # resurrects (run 4). First-seen winner: A. Resurrection winner: B.
    r = recover_creation_order(
        [(1, _ws("B")), (2, _ws("B", "A")), (3, _ws("A")), (4, _ws("A", "B"))])
    res = resolve_precedence(r, ["A", "B"])
    assert res.winner is None and res.reason == "reappearance_ambiguous"


def test_single_candidate_trivially_resolved_even_when_censored():
    r = recover_creation_order([(1, _ws("A", "B"))])
    res = resolve_precedence(r, ["A"])
    assert (res.winner, res.reason) == ("A", "single_candidate")


def test_missing_snapshots_are_skipped_not_deletions():
    # run 2's capture failed: B present run 1 and run 3 is NOT a resurrection.
    r = recover_creation_order(
        [(1, _ws("A", "B")), (2, None), (3, _ws("A", "B"))])
    assert not r.appearance("B").reappeared


def test_unknown_and_empty_candidates():
    r = recover_creation_order([(1, _ws("A"))])
    assert resolve_precedence(r, ["A", "ZZZ"]).reason == "unknown_candidates"
    assert resolve_precedence(r, []).reason == "no_candidates"


def test_block_types_and_orphans_are_tracked():
    xml = ('<xml xmlns="https://developers.google.com/blockly/xml">'
           '<block type="pg_events_when_started" id="A" x="0" y="0"/>'
           '<block type="pg_drivetrain_drive_for" id="ORPH" x="9" y="9"/>'
           "</xml>")
    r = recover_creation_order([(1, xml)])
    assert r.appearance("A").block_type == "pg_events_when_started"
    assert r.appearance("ORPH") is not None  # consumers filter by type


def test_unparseable_snapshot_raises_not_swallowed():
    # a live parse failure is a parser gap, not student noise (OI-14 lesson)
    with pytest.raises(Exception):
        recover_creation_order([(1, "<xml><unclosed")])


def test_resurrection_ties_with_same_snapshot_new_stack():
    # B resurrects in the SAME snapshot where C is newly created: one edit
    # interval, unknown relative order -> resurrection interpretation ties,
    # first-seen says C; interpretations conflict -> ambiguous, never a guess.
    r = recover_creation_order(
        [(1, _ws("A", "B")), (2, _ws("A")), (3, _ws("A", "B", "C"))])
    res = resolve_precedence(r, ["B", "C"])
    assert res.winner is None
    assert res.reason == "reappearance_ambiguous"


def test_two_resurrections_same_snapshot_tie():
    r = recover_creation_order(
        [(1, _ws("A", "B", "C")), (2, _ws("A")), (3, _ws("A", "B", "C"))])
    res = resolve_precedence(r, ["B", "C"])
    assert res.winner is None
    # both interpretations agree the pair is tied; the shared reason surfaces
    assert res.reason in ("window_censored", "tied_generation")
