"""Stage-5 assembly: the delivery table (reviewer-ruled 2026-09-11)."""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
DATA = _ROOT / "data" / "ccp_run_dataset"


@pytest.fixture(scope="module")
def table(tmp_path_factory):
    if not (DATA / "stage6_rubric.csv").exists():
        pytest.skip("run dataset not present")
    from goal_strategy.profile_assembly import assemble
    out = tmp_path_factory.mktemp("s5") / "stage5_profiles.csv"
    res = assemble(DATA, out, configs_root=_ROOT)
    rows = {r["run_id"]: r for r in csv.DictReader(open(out))}
    meta = json.load(open(str(out) + ".meta.json"))
    return rows, meta, res


def test_one_row_per_corpus_run(table):
    rows, meta, res = table
    n_rungs = sum(1 for _ in csv.DictReader(open(DATA / "stage2_rungs.csv")))
    assert res["rows"] == n_rungs == len(rows)


def test_bands_match_source_and_probability_carried(table):
    rows, _, _ = table
    src = {}
    for r in csv.DictReader(open(DATA / "stage3_battery.csv")):
        if r.get("scenario") == "__goal_band__":
            src.setdefault(r["run_id"], {})[r["goal"]] = r["status"]
    import itertools
    for rid in itertools.islice(sorted(src), 0, 200, 10):
        row = rows[rid]
        assert row["clear_debris_zone__band"] == \
            src[rid]["clear_debris_zone"]
        assert row["remain_on_island__band"] == \
            src[rid]["remain_on_island"]
    some_p = [r for r in rows.values()
              if r["remain_on_island__probability"]]
    assert some_p and all(0 <= float(r["remain_on_island__probability"])
                          <= 1 for r in some_p[:50])


def test_rubric_levels_match_stage6_and_are_provisional(table):
    rows, meta, _ = table
    src = {}
    for r in csv.DictReader(open(DATA / "stage6_rubric.csv")):
        src.setdefault(r["run_id"], {})[r["dimension"]] = r["level"]
    import itertools
    for rid in itertools.islice(sorted(src), 0, 300, 30):
        for d, lvl in src[rid].items():
            assert rows[rid][f"rubric__{d}__level"] == lvl
    assert all(r["rubric_status"] == "provisional_stage2E"
               for r in list(rows.values())[:20])
    assert "recovery" in meta["rubric_caveats"]


def test_band_absence_reasons_by_route(table):
    rows, _, _ = table
    for r in rows.values():
        if r["route"] == "battery_rubric_only":
            assert r["clear_debris_zone__band"] == ""
            assert r["clear_debris_zone__band_u_reason"] == \
                "excluded_rubric_only_route"
        if r["route"] == "census_only":
            assert r["clear_debris_zone__band_u_reason"] in \
                ("no_battery_route",)


def test_meta_fingerprint_complete(table):
    _, meta, _ = table
    assert meta["claims_id"] == "castle_crashers_claims_v1"
    assert set(meta["sources"]) >= {"stage2_rungs.csv",
                                    "stage6_rubric.csv"}
    assert meta["assembly_version"]
