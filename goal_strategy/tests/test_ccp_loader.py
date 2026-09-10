"""Stage 0 of VALIDATION_PLAN.md — the ccp_run_dataset adapter.

Loads the full-sample run dataset, verifies the unwrapping and tagging
contracts, and runs the sanity gate: dev-corpus programs must reproduce
through the new loader. The gate's measured reality (2026-08-21): all 112
dev finals match a run's XML verbatim; 107 also match a same-run params
blob exactly; FIVE dev rows carry session-level pairings that are not
same-run pairs in the run dataset (dev extraction paired final XML with a
blob the run-linkage drops or a different run's telemetry) — named below,
documented in FINDINGS, queued for Stage-2 re-adjudication. If this set
shrinks or grows, the data changed — investigate, don't retag.
"""
from __future__ import annotations
from goal_strategy.paths import data_path

import pytest

from goal_strategy.ccp_runs import (
    PARAMS_SELF_ID,
    load_ccp_runs,
    unwrap_params,
)

# Dev rows whose (final_xml, params) pairing is NOT a same-run pair in the
# run dataset (measured 2026-08-21; see FINDINGS Stage-0 report).
CROSS_RUN_PAIRINGS = {
    "DOVE-C020_DOVE-NC020_S001",   # dev blob matches NO run in the session
    "DOVE-C046_DOVE-NCO46_S001",   # final xml only ran without telemetry
    "DOVE-C064_DOVE-NCO64_S001",   # ditto — and it is one of the 14 disagreements
    "DOVE-C074_DOVE-NCO74_S001",   # final run HAS telemetry; values differ from dev
    "WREN-C050_714982_S001",      # ditto (dev 4725/154.4s vs run 4375/69.3s)
}


@pytest.fixture(scope="module")
def runs():
    return load_ccp_runs()


@pytest.fixture(scope="module")
def dev_corpus():
    from goal_strategy.tests.helpers import load_final_code_states
    from pathlib import Path
    root = Path(__file__).resolve().parent.parent
    return load_final_code_states(str(data_path() / "final_code_states.parquet"))


def test_full_dataset_shape(runs):
    assert len(runs) == 7984
    assert len({r.student_study_id for r in runs}) == 205
    assert len({r.derived_session_id for r in runs}) == 317
    assert sum(1 for r in runs if r.playground_params) == 3978
    assert all(r.workspace_xml for r in runs)   # 100% populated at build time


def test_run_seq_contiguous_per_session(runs):
    from collections import defaultdict
    by_sess = defaultdict(list)
    for r in runs:
        by_sess[r.derived_session_id].append(r.run_seq)
    for sess, seqs in by_sess.items():
        assert seqs == list(range(1, len(seqs) + 1)), sess


def test_params_unwrapped_flat_and_self_identified(runs):
    with_params = [r for r in runs if r.playground_params]
    # flat dev-corpus shape: the fields every consumer reads
    sample = with_params[0].playground_params
    assert "weight_cleared" in sample and "parameters" not in sample
    # every blob in this dataset self-identifies with the platform's typo
    assert {r.params_playground_self_id for r in with_params} == {PARAMS_SELF_ID}
    # missing telemetry is None, never {}
    assert all(r.playground_params is None
               for r in runs if not r.playground_params)


def test_unwrap_params_contract():
    nested = '{"playground": "CasteCrasherPlus", "parameters": {"weight_cleared": 5}}'
    assert unwrap_params(nested) == ({"weight_cleared": 5}, "CasteCrasherPlus")
    flat = '{"weight_cleared": 5}'                    # dev-corpus style passthrough
    assert unwrap_params(flat) == ({"weight_cleared": 5}, None)
    assert unwrap_params(None) == (None, None)
    assert unwrap_params("") == (None, None)


def test_cohort_tags(runs):
    from collections import Counter
    c = Counter(r.cohort for r in runs)
    assert c == {"CROW/2026-04": 2849, "DOVE/2026-02": 973,
                 "WREN/2026-02": 4161, "LARK/2026-04": 1}


def test_dev_overlap_tags(runs, dev_corpus):
    tagged = [r for r in runs if r.dev_corpus_overlap]
    assert len(tagged) == 168
    from collections import Counter
    assert Counter(r.school for r in tagged) == {"DOVE": 31, "WREN": 137}


def _same_run_matches(runs, dev_corpus):
    from collections import defaultdict
    by_xml = defaultdict(list)
    for r in runs:
        by_xml[r.workspace_xml].append(r)
    matched, unmatched = {}, []
    for p in dev_corpus:
        cands = by_xml.get(p.workspace_xml, [])
        assert cands, f"{p.program_id}: dev final XML absent from run dataset"
        exact = [r for r in cands
                 if r.playground_params == p.playground_params]
        if exact:
            matched[p.program_id] = (p, exact[0])
        else:
            unmatched.append(p.program_id)
    return matched, unmatched


def test_sanity_gate_same_run_pairing(runs, dev_corpus):
    matched, unmatched = _same_run_matches(runs, dev_corpus)
    assert len(matched) == 107
    assert set(unmatched) == CROSS_RUN_PAIRINGS


def test_sanity_gate_profiles_bit_for_bit(runs, dev_corpus):
    """For matched pairs, the profile through the new loader is IDENTICAL to
    the dev-corpus profile — same xml, same params, same pure function; a
    spread subset is fully evaluated to catch any loader-shape drift (types,
    key order, None handling)."""
    from goal_strategy.profile import _profile
    matched, _ = _same_run_matches(runs, dev_corpus)
    dove = sorted(k for k in matched if matched[k][1].school == "DOVE")[:3]
    wren = sorted(k for k in matched if matched[k][1].school == "WREN")[:3]
    for pid in dove + wren:
        p, r = matched[pid]
        a = _profile(p.workspace_xml, pid, p.playground_params)
        b = _profile(r.workspace_xml, pid, r.playground_params)
        assert a == b, f"{pid}: profile differs through the ccp loader"
