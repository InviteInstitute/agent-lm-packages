"""Stack creation-order recovery from longitudinal workspace snapshots (OI-7).

The arbitration rule (reviewer probe, 2026-08-21): when concurrent
`when started` stacks contend for the drivetrain, the MOST RECENTLY CREATED
stack takes precedence — deterministic, independent of selection state and
later edits. The workspace XML carries no timestamps, so creation order is
recovered longitudinally: the first snapshot in which a top-level stack's
block id appears. Block ids are stable across edits; a pasted or re-created
stack receives a fresh id, which is CORRECT under the rule (re-creation is
creation).

This module is deliberately upstream-agnostic: it takes an ordered sequence
of (run_seq, workspace_xml) for ONE session and knows nothing about how the
snapshots are stored. When the fuller validation-stage sample arrives, an
adapter maps its schema onto `recover_creation_order`; nothing here changes.

Honesty rules (no silent guesses — every ambiguity is a named reason):
- Stacks already present in the window's FIRST snapshot predate observation:
  their relative order is unknown (``window_censored``, generation 0).
- Stacks first appearing in the SAME snapshot were created in the same
  between-runs edit interval: relative order unknown (a tie within their
  generation).
- A stack id that disappears and later returns (undo resurrection restores
  the same id) is ambiguous: its creation may count from first appearance or
  from resurrection. Precedence is resolved only when BOTH interpretations
  agree on the winner.
"""
from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence, Tuple


def _top_level_blocks(workspace_xml: str) -> "list[tuple[str, str]]":
    """(block_id, block_type) for each top-level block, document order.

    Namespace-agnostic; blocks without an id attribute are skipped (they
    cannot be tracked across snapshots).
    """
    root = ET.fromstring(workspace_xml)
    out = []
    for el in root:
        tag = el.tag.rsplit("}", 1)[-1]
        if tag != "block":
            continue
        block_id = el.get("id")
        if block_id:
            out.append((block_id, el.get("type") or ""))
    return out


@dataclass(frozen=True)
class StackAppearance:
    block_id: str
    block_type: str
    first_seen_run: object          # run_seq of first appearance
    generation: int                 # 0 = window-opening snapshot (censored)
    window_censored: bool           # True when generation == 0
    reappeared: bool                # id vanished from a snapshot, then returned
    last_return_run: object         # run_seq where current presence began
    last_return_generation: int     # generation index of that return


@dataclass(frozen=True)
class CreationOrderResult:
    appearances: Tuple[StackAppearance, ...]
    generations: Tuple[frozenset, ...]   # block-id groups, oldest first

    def appearance(self, block_id: str) -> Optional[StackAppearance]:
        for a in self.appearances:
            if a.block_id == block_id:
                return a
        return None


@dataclass(frozen=True)
class PrecedenceResolution:
    winner: Optional[str]
    reason: str
    # "resolved" | "single_candidate" | "window_censored" | "tied_generation"
    # | "reappearance_ambiguous" | "unknown_candidates" | "no_candidates"


def recover_creation_order(
    snapshots: Iterable[Tuple[object, Optional[str]]],
) -> CreationOrderResult:
    """Derive stack creation order for one session.

    ``snapshots``: (run_seq, workspace_xml) in chronological order. Entries
    with empty/None xml are skipped (a failed capture is not evidence of
    deletion). Unparseable xml raises — a live parse failure is a parser
    gap, not student noise (the OI-14 lesson).
    """
    first_seen: dict = {}          # id -> (run_seq, generation)
    block_types: dict = {}
    reappeared: set = set()
    last_return: dict = {}         # id -> (run_seq, generation)
    previously_present: set = set()
    generations: list = []
    gen_index = -1

    for run_seq, xml_text in snapshots:
        if not xml_text:
            continue
        blocks = _top_level_blocks(xml_text)
        present = {bid for bid, _ in blocks}
        new_ids = [bid for bid, _ in blocks if bid not in first_seen]
        if new_ids:
            gen_index += 1
            generations.append(frozenset(new_ids))
            for bid, btype in blocks:
                if bid in new_ids:
                    first_seen[bid] = (run_seq, gen_index)
                    last_return[bid] = (run_seq, gen_index)
                    block_types[bid] = btype
        returned = sorted(
            bid for bid in present
            if bid in first_seen
            and bid not in previously_present
            and bid not in new_ids
        )
        if returned:
            # known ids, absent last snapshot, present again: resurrections.
            # All events within one between-runs interval have unknown
            # relative order, so resurrections SHARE the snapshot's
            # generation: the new-ids generation when one was opened, else a
            # fresh slot of their own (later than every prior generation).
            if not new_ids:
                gen_index += 1
                generations.append(frozenset(returned))
            for bid in returned:
                reappeared.add(bid)
                last_return[bid] = (run_seq, gen_index)
        previously_present = present

    appearances = tuple(
        sorted(
            (
                StackAppearance(
                    block_id=bid,
                    block_type=block_types[bid],
                    first_seen_run=first_seen[bid][0],
                    generation=first_seen[bid][1],
                    window_censored=first_seen[bid][1] == 0,
                    reappeared=bid in reappeared,
                    last_return_run=last_return[bid][0],
                    last_return_generation=last_return[bid][1],
                )
                for bid in first_seen
            ),
            key=lambda a: (a.generation, a.block_id),
        )
    )
    return CreationOrderResult(appearances=appearances,
                               generations=tuple(generations))


def _latest(result: CreationOrderResult, candidates: Sequence[str],
            key: str) -> Tuple[Optional[str], str]:
    """Winner among candidates under one creation-time interpretation."""
    apps = [result.appearance(c) for c in candidates]
    ranked = sorted(apps, key=lambda a: getattr(a, key), reverse=True)
    top = ranked[0]
    top_gen = getattr(top, key)
    tied = [a for a in ranked if getattr(a, key) == top_gen]
    if len(tied) > 1:
        if top_gen == 0:
            return None, "window_censored"
        return None, "tied_generation"
    return top.block_id, "resolved"


def resolve_precedence(
    result: CreationOrderResult, candidate_ids: Sequence[str]
) -> PrecedenceResolution:
    """Most-recently-created winner among ``candidate_ids``, or a named
    reason why precedence cannot be resolved. Resolution requires the
    first-seen and resurrection interpretations of any reappeared stack to
    AGREE on the winner."""
    if not candidate_ids:
        return PrecedenceResolution(None, "no_candidates")
    unknown = [c for c in candidate_ids if result.appearance(c) is None]
    if unknown:
        return PrecedenceResolution(None, "unknown_candidates")
    if len(candidate_ids) == 1:
        return PrecedenceResolution(candidate_ids[0], "single_candidate")

    w_first, r_first = _latest(result, candidate_ids, "generation")
    if any(result.appearance(c).reappeared for c in candidate_ids):
        w_res, r_res = _latest(result, candidate_ids, "last_return_generation")
        if w_first is not None and w_first == w_res:
            return PrecedenceResolution(w_first, "resolved")
        if w_first is None and w_res is None:
            # both interpretations agree there is no winner; surface the
            # shared reason, or the generic tie when the labels differ
            return PrecedenceResolution(
                None, r_first if r_first == r_res else "tied_generation")
        return PrecedenceResolution(None, "reappearance_ambiguous")
    return PrecedenceResolution(w_first, r_first)
