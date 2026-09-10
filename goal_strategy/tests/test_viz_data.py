"""Task-2 §B: the viz data layer (pure python — no streamlit/plotly needed).

Covers the §B5 constraints that are testable headlessly: renders for zero-step
and unparseable programs, stack grouping never flattens, receiver stacks are
annotated with their inline broadcast site, trust flags sit on stack headers,
zone bands include the undescribed regions, and the two-tier fidelity fields
are passed through (a reason, never a number, when not comparable).
"""
import json
import sys
from pathlib import Path

import pytest


from goal_strategy.viz import data as vd
from goal_strategy.viz.walkthrough import walkthrough_html


@pytest.fixture(scope="module")
def corpus_map(corpus):
    return {p.program_id: p for p in corpus}


def payload_for(corpus_map, prefix, **kw):
    prog = next(v for k, v in corpus_map.items() if k.startswith(prefix))
    return vd.walkthrough_payload(prog.program_id, prog.workspace_xml,
                                  prog.playground_params, **kw)


def test_payload_is_json_serialisable_and_complete(corpus_map):
    payload = payload_for(corpus_map, "WREN-C094")
    blob = json.loads(json.dumps(payload))
    assert blob["exit_step"] is not None
    assert blob["path"] and blob["events"]
    assert any(e["kind"] == "failure" for e in blob["events"])
    assert blob["geometry"]["boundary"] and blob["geometry"]["objects"]
    assert any(p["qualifying"] for p in blob["path"])


def test_zero_step_program_renders_with_reason(corpus_map):
    # WREN-C082 graduated at the Phase-3 distance sign-off (2026-08-19): its
    # while-guard now evaluates and it runs off-field like the real robot.
    # WREN-C024 remains a genuine zero-step program (all motion gated behind
    # an if whose modeled condition is false at spawn).
    payload = payload_for(corpus_map, "WREN-C024")
    assert payload["path"] == []
    html = walkthrough_html(payload)
    assert payload["program_id"] in html


def test_unparseable_program_renders(corpus_map):
    payload = vd.walkthrough_payload("broken", "<not xml", None)
    assert payload["parse_failed"] and payload["stacks"] == []
    assert isinstance(walkthrough_html(payload), str)


def test_stacks_never_flattened_and_receiver_inline_annotated(corpus_map):
    payload = payload_for(corpus_map, "WREN-C008")
    stacks = payload["stacks"]
    assert len(stacks) == 4                       # 2 started + 2 receivers
    receivers = [s for s in stacks if s["hat_type"] == "pg_events_when_broadcasted"]
    assert len(receivers) == 2
    inline = [s for s in receivers if "runs inline" in s["note"]]
    silent = [s for s in receivers if "no path steps" in s["note"]]
    assert len(inline) == 1 and len(silent) == 1  # Chash fires; my_event never does
    assert all(s["ordinal"] is None for s in receivers), \
        "receivers must not carry top-level ordinals"
    started = [s for s in stacks if s["hat_type"] == "pg_events_when_started"]
    assert all("concurrent_stacks_unverified" in s["trust_flags"] for s in started)


def test_untrusted_hat_flags_on_stack_headers(corpus_map):
    eye = payload_for(corpus_map, "WREN-C012")
    eye_stacks = [s for s in eye["stacks"]
                  if s["hat_type"] == "pg_events_optical_detect_object"]
    assert eye_stacks and all("trigger_unfaithful" in s["trust_flags"]
                              for s in eye_stacks)
    assert "FORCED" in eye_stacks[0]["note"]      # B1 default
    bumper = payload_for(corpus_map, "WREN-C103", treatment="suppress")
    b_stacks = [s for s in bumper["stacks"]
                if s["hat_type"] == "pg_events_when_bumper"]
    assert b_stacks and "SUPPRESSED" in b_stacks[0]["note"]
    assert "trigger_unsimulated" in b_stacks[0]["trust_flags"]


def test_orphan_stacks_grouped_and_marked(corpus_map):
    prog = next(v for v in corpus_map.values() if v.program_id.startswith("DOVE-C030"))
    payload = vd.walkthrough_payload(prog.program_id, prog.workspace_xml,
                                     prog.playground_params)
    orphans = [s for s in payload["stacks"] if s["kind"] == "orphan"]
    assert orphans and all(s["note"] == "never executed" for s in orphans)
    assert all(r["steps"] == [] for s in orphans for r in s["rows"])


def test_no_zone_bands_after_continuous_sampling_ruling(corpus_map):
    # 2026-08-19 continuous-sampling ruling (C031 live falsification):
    # attachment is estimated uniformly within the 190mm radius — no card
    # binding opts into zones_ref, so the viz must draw no zone bands.
    payload = payload_for(corpus_map, "WREN-C094")
    assert payload["geometry"]["zone_bands"] == []


def test_two_tier_fidelity_passed_through(corpus_map):
    agree = payload_for(corpus_map, "WREN-C031")   # on-island agreement program
    assert agree["fidelity"]["error_mm"] is not None
    # WREN-C082 became an off-island AGREEMENT at the Phase-3 sign-off; it
    # remains non-comparable for position (both finals off-island).
    disagree = payload_for(corpus_map, "WREN-C082")
    assert disagree["fidelity"]["error_mm"] is None
    assert disagree["fidelity"]["reason"] == "off_island_position_not_comparable"


def test_treatment_changes_payload_only_for_hat_programs(corpus_map):
    b1 = payload_for(corpus_map, "WREN-C012")
    b2 = payload_for(corpus_map, "WREN-C012", treatment="suppress")
    assert len(b1["path"]) != len(b2["path"])     # the C012 cascade is visible
    assert vd.is_conditional_hat_program(
        next(v for k, v in corpus_map.items() if k.startswith("WREN-C012")).workspace_xml,
        "x")
    plain = next(v for k, v in corpus_map.items() if k.startswith("DOVE-C001"))
    assert not vd.is_conditional_hat_program(plain.workspace_xml, plain.program_id)


def test_cohort_table_shape():
    df = vd.cohort_table()
    assert len(df) == 112   # wrong-playground sessions filtered out
    assert "engage_plow__plow_approach_intent__rung" in df.columns
    # velocity calibration sign-off (2026-08-19)
    # Phase-3 distance sign-off + radius ratification (2026-08-19): C082's
    # while-guard evaluates and C035's distance branches track reality —
    # disagreements 17 -> 15 (agreement 87%). Outcome-override ruling
    # (2026-08-19, WREN-C032): a corroborated-trajectory drift exit defers to
    # the on-island outcome — 15 -> 14, comparable 39 -> 40.
    # 12 as of the castle-structure adoption (2026-08-26): C018's eye hat
    # finally has its real target — sim exits like its GPS, the
    # longest-standing disagreement resolves (was 13; 14 before C012).
    assert (df.off_island_agreement == False).sum() == 12  # noqa: E712
    assert df.gps_final_error_mm.notna().sum() == 40


def test_walkthrough_html_self_contained(corpus_map):
    html = walkthrough_html(payload_for(corpus_map, "WREN-C008"))
    for needle in ("defineVexBlocks", "stubUnknownBlocks", "unpkg.com/blockly",
                   "broadcast_concurrency_approximated", "scrub"):
        assert needle in html
    assert "</script><script>" not in json.dumps("</script>")  # escaping sanity


def test_block_corrections_match_corpus_xml_shapes(corpus):
    """The Blockly correction definitions must declare an input/field for every
    name the corpus XML actually uses on that block type — a field_number where
    the XML has a <value> input silently drops the authored number (the bug the
    corrections exist to fix)."""
    import re
    import xml.etree.ElementTree as ET
    from collections import defaultdict

    js = (Path(__file__).resolve().parent.parent
          / "viz" / "vex_blocks_corrections.js").read_text()
    raw = js.split("/*JSON-START*/")[1].split("/*JSON-END*/")[0]
    defs = {d["type"]: d for d in json.loads(raw)}

    NS = "{https://developers.google.com/blockly/xml}"
    shapes = defaultdict(lambda: {"fields": set(), "values": set(), "stmts": set()})
    for prog in corpus:
        if not prog.workspace_xml:
            continue
        try:
            root = ET.fromstring(prog.workspace_xml)
        except ET.ParseError:
            continue
        for el in root.iter():
            if el.tag not in (f"{NS}block", f"{NS}shadow"):
                continue
            shape = shapes[el.get("type", "")]
            for child in el:
                if child.tag == f"{NS}field":
                    shape["fields"].add(child.get("name"))
                elif child.tag == f"{NS}value":
                    shape["values"].add(child.get("name"))
                elif child.tag == f"{NS}statement":
                    shape["stmts"].add(child.get("name"))

    IGNORABLE_FIELDS = {"anddontwait_mutator"}   # mutator artifact, no visual slot
    problems = []
    for block_type, definition in defs.items():
        if block_type not in shapes:
            continue
        args = definition.get("args0", [])
        declared_fields = {a["name"] for a in args if a["type"].startswith("field_")}
        declared_values = {a["name"] for a in args if a["type"] == "input_value"}
        declared_stmts = {a["name"] for a in args if a["type"] == "input_statement"}
        shape = shapes[block_type]
        missing_f = shape["fields"] - declared_fields - IGNORABLE_FIELDS
        missing_v = shape["values"] - declared_values
        missing_s = shape["stmts"] - declared_stmts
        if missing_f or missing_v or missing_s:
            problems.append(f"{block_type}: fields{sorted(missing_f)} "
                            f"values{sorted(missing_v)} stmts{sorted(missing_s)}")
        # the core bug class: a corpus <value> name declared as a field
        wrong_kind = shape["values"] & declared_fields
        if wrong_kind:
            problems.append(f"{block_type}: {sorted(wrong_kind)} declared as "
                            "field but the XML carries a value input")
    assert not problems, "\n".join(problems)


def test_walkthrough_includes_block_corrections(corpus_map):
    html = walkthrough_html(payload_for(corpus_map, "DOVE-C001"))
    assert "defineVexBlockCorrections" in html
    assert html.index("defineVexBlocks()") < html.index("defineVexBlockCorrections()")
