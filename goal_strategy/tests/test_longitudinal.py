"""Longitudinal viz — pure-function tests (diff, component assembly,
outline). The Streamlit shell is exercised by hand per the plan's
verification list; everything testable without a browser is pinned here."""
from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent

from goal_strategy.viz.workspace import _block_signatures, diff_runs, workspace_html  # noqa: E402

NS = 'xmlns="https://developers.google.com/blockly/xml"'


def _xml(body: str) -> str:
    return f"<xml {NS}>{body}</xml>"


def test_diff_added_removed_changed():
    a = _xml('<block type="pg_drivetrain_drive_for" id="A">'
             '<field name="AMOUNT">100</field></block>'
             '<block type="pg_drivetrain_turn_for" id="B"/>')
    b = _xml('<block type="pg_drivetrain_drive_for" id="A">'
             '<field name="AMOUNT">250</field></block>'
             '<block type="pg_magnet_set_magnet_state" id="C"/>')
    d = diff_runs(a, b)
    assert set(d["added"]) == {"C"}
    assert set(d["removed"]) == {"B"}
    assert set(d["changed"]) == {"A"}
    old, new = d["changed"]["A"]
    assert dict(old[1])["AMOUNT"] == "100" and dict(new[1])["AMOUNT"] == "250"


def test_diff_identical_runs_is_empty():
    x = _xml('<block type="pg_drivetrain_drive" id="A"/>')
    d = diff_runs(x, x)
    assert not d["added"] and not d["removed"] and not d["changed"]


def test_diff_tolerates_empty_and_none():
    d = diff_runs("", _xml('<block type="pg_drivetrain_drive" id="A"/>'))
    assert set(d["added"]) == {"A"}
    assert diff_runs("", "") == {"added": {}, "removed": {}, "changed": {}}


def test_signatures_include_shadows_and_nested_fields():
    x = _xml('<block type="pg_control_repeat" id="L">'
             '<value name="TIMES"><shadow type="math_number" id="S">'
             '<field name="NUM">4</field></shadow></value></block>')
    sig = _block_signatures(x)
    assert set(sig) == {"L", "S"}
    assert dict(sig["S"][1])["NUM"] == "4"


def test_workspace_html_is_self_contained_and_escaped():
    html = workspace_html(_xml('<block type="pg_drivetrain_drive" id="A"/>'
                               '<block type="never_seen_block" id="Z"/>'),
                          added_ids={"A"}, changed_ids={"Z"})
    # self-contained: every <script> is inline — nothing fetched at view time
    assert "<script src=" not in html and "src='http" not in html \
        and 'src="http' not in html
    assert "defineVexBlocks" in html and "stubUnknownBlocks" in html
    assert '"10.4.3"' in html          # vendored runtime present
    assert '["A"]' in html and '["Z"]' in html
    assert "<\\/" in html or "</block>" not in html   # </ escaped inside JSON


def test_outline_rows_render_a_real_ccp_run():

    from goal_strategy.ccp_runs import load_ccp_runs
    from goal_strategy.viz import longitudinal as lg
    r = next(x for x in load_ccp_runs(tag_dev_overlap=False)
             if "procedures_call" in (x.workspace_xml or ""))
    rows = lg._outline_rows(r.workspace_xml, r.run_id)
    assert rows and any("unattached" in row["text"] for row in rows)  # orphan def visible
