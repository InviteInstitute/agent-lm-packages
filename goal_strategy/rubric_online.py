"""Per-run purpose-2 rubric composition for the online API.

PROVISIONAL. In the source project purpose-2 ships as
``rubric_status = provisional_stage2E`` and is under active human validation
(Stage 2E). This module composes the SAME inputs the offline sweep feeds
``rubric_combiner.combine_run`` (production code evidence plus per-scenario
battery evidence), with every value turned into the text a CSV cell holds, so
the online path matches the ``stage2_code_evidence.csv`` and
``stage3_battery_evidence.csv`` semantics exactly. Callers opt in through
``include_rubric`` and must treat the levels as provisional, never as settled
per-run feedback.

The composition never re-simulates the production run: it reuses the shared
execution artifact's parsed program and simulation for the code channel, and
runs the battery once (its own designed worlds) for the scenario channel,
exactly as ``battery_sweep`` does offline.
"""
from __future__ import annotations

from .rubric_combiner import combine_run, load_claims
from .rubric_evidence import card_geometry_targets, code_evidence, code_evidence_row

RUBRIC_STATUS = "provisional_stage2E"

def _as_csv_text(row):
    """The row as the offline combiner reads it back from CSV (booleans become
    'True'/'False', None becomes '', numbers become their text)."""
    return {k: "" if v is None else str(v) for k, v in row.items()}


def _code_row(program, sim, config_version, playground, configs_dir):
    """The stage2_code_evidence row for one run (rung_sweep's writerow shape)
    plus the ceilings dict combine_run takes directly."""
    from .config import load_configs
    ce = code_evidence(program, sim)
    card = load_configs(playground, configs_dir).card
    claims = load_claims(playground, configs_dir)
    prod = _as_csv_text(code_evidence_row(
        ce, program, "", config_version, card_geometry_targets(card),
        float(claims.get("calibration_tolerance_pct") or 10.0),
        claims.get("smc_vocabulary") or {}, claims.get("smc_specificity") or {}))
    return prod, dict(ce.ceilings)


def _battery_rows(program, report, program_id, config_version,
                  playground, configs_dir):
    """Non-abstained per-scenario rubric evidence rows, and stays_on_island by
    scenario, from a battery report (run with collect_sims=True). The report is
    shared with the other online channels so the battery runs once per call."""
    from .battery_evidence import scenario_evidence
    from .battery_sweep import _evidence_row
    from .testcases import load_scenarios
    if report is None or not report.eligible:
        return [], {}
    cards = {c["scenario_id"]: c for c in load_scenarios(playground, configs_dir)}
    arts = {(a.scenario_id, a.construct): a for a in report.artifacts}
    ident = {"run_id": program_id, "cohort": "", "session": "", "run_seq": "",
             "config_version": config_version, "channel": "goal"}
    rows, stays = [], {}
    for res in report.scenarios:
        art = arts.get((res.scenario_id, res.construct))
        if art is None:
            continue
        ev = scenario_evidence(program, res, art, cards.get(res.scenario_id, {}))
        if ev.abstained:
            continue
        rows.append(_evidence_row(ident, ev))
        for chk in res.checks:
            if (chk.name == "stays_on_island" and chk.status == "measured"
                    and chk.value is not None):
                stays[res.scenario_id] = float(chk.value)
    return [_as_csv_text(r) for r in rows], stays


def rubric_dimensions(program, sim, program_id, config_version,
                      playground="castle_crashers", configs_dir=None,
                      *, report=None, workspace_xml=None):
    """[DimensionEvidence] for one run under the claims card, or None when
    there is no parsed program or no simulation to score (a rejected program
    executes nothing; rung_sweep skips the same runs). Pass `report` (a
    collect_sims battery report) to share the single battery run with the
    other online channels; otherwise a `workspace_xml` runs one here."""
    if program is None or sim is None:
        return None
    if report is None:
        from .testcases import run_battery
        report = run_battery(workspace_xml or "", program_id,
                             playground=playground, configs_dir=configs_dir,
                             collect_sims=True)
    prod, ceilings = _code_row(program, sim, config_version, playground,
                               configs_dir)
    batt_rows, stays = _battery_rows(program, report, program_id,
                                     config_version, playground, configs_dir)
    claims = load_claims(playground, configs_dir)
    return combine_run(program_id, batt_rows, prod, ceilings, claims, stays)


def rubric_to_dict(dims):
    """The provisional purpose-2 envelope for result['rubric']. Strict-JSON
    primitives only, so it composes with the rest of the serialized result."""
    if dims is None:
        return None
    return {
        "provisional": True,
        "status": RUBRIC_STATUS,
        "dimensions": {
            de.dimension: {
                "level": de.label,
                "ceiling": de.ceiling,
                "borderline": de.borderline,
                "u_reason": de.u_reason,
                "fired": [{"evidence": name, "level": level, "strength": strength}
                          for (name, level, _weight, strength) in de.fired],
                "negatives": [name for name, _level in de.negatives],
            }
            for de in dims
        },
    }
