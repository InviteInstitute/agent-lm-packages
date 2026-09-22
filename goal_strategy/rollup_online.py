"""Per-run purpose-1 goal ROLLUP for the online API (the `rollup` channel).

The offline pipeline turns the battery report into banded goal claims
(`battery_rollup.banded_rollup`) and lands them in stage-3/stage-5. This module
does the same for one online run so the agent can read a rolled-up, meta-level
goal claim instead of the granular per-indicator profile and per-scenario
battery output.

Two goals are BANDED from the battery (`clear_debris_zone`,
`remain_on_island`); the debris entry is enriched with the test proportion, the
simulated zone coverage, and the telemetry weight so the near-saturated debris
band is not the only signal. The other two goals (`engage_plow`,
`playground_engagement`) have no battery channel by design, so their claim is
DERIVED transparently from the profile's own indicator rungs and labeled as
such. Nothing here re-simulates or re-runs the battery: it consumes the shared
report and the already-computed profile.
"""
from __future__ import annotations

import math

from .battery_rollup import banded_rollup, load_rollup_card


def _indicator(profile, goal_id, name):
    """The named Indicator on a profile goal, or None."""
    for goal in profile.goals:
        if goal.goal != goal_id:
            continue
        for ind in list(goal.intent) + list(goal.attainment):
            if ind.name == name:
                return ind
    return None


def _rung(profile, goal_id, name):
    ind = _indicator(profile, goal_id, name)
    return None if ind is None or ind.abstained else ind.rung


def _finite(value):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _debris_enrichment(profile):
    """The three debris/zone signals: test proportion (the band score, added by
    the caller), simulated zone coverage, and telemetry weight cleared."""
    coverage = _indicator(profile, "clear_debris_zone", "debris_zone_coverage")
    weight = _indicator(profile, "clear_debris_zone", "weight_cleared")
    out = {
        "zone_coverage": None if coverage is None or coverage.abstained
        else _finite(coverage.value),
        "zone_coverage_band": None if coverage is None or coverage.abstained
        else coverage.rung,
        "weight_cleared_kg": None if weight is None or weight.abstained
        else _finite(weight.value),
        "weight_cleared_band": None if weight is None or weight.abstained
        else weight.rung,
    }
    return out


def _engage_plow_claim(profile):
    """A transparent derivation from the plow indicators (no new scoring): the
    strongest stage the run reached toward acquiring/using the plow."""
    magnet = _rung(profile, "engage_plow", "magnet_activation_intent")
    approach = _rung(profile, "engage_plow", "plow_approach_intent")
    proximity = _rung(profile, "engage_plow", "plow_proximity_execution")
    if proximity == "attach_estimated":
        claim = "attached"
    elif magnet in ("present_not_boost", "boost"):
        claim = "armed_not_attached"
    elif approach in ("reached", "near"):
        claim = "approached_not_armed"
    elif magnet is None and approach is None and proximity is None:
        claim = "unknown"
    else:
        claim = "not_pursued"
    return {"claim": claim, "source": "profile_derived",
            "magnet": magnet, "approach": approach, "proximity": proximity}


def _engagement_claim(profile):
    moved = _rung(profile, "playground_engagement", "robot_moved")
    claim = ("engaged" if moved == "moved"
             else "not_engaged" if moved == "stationary" else "unknown")
    return {"claim": claim, "source": "profile_derived", "moved": moved}


def _band_entry(band, *, source="battery"):
    """Serialize a battery GoalBand to strict-JSON primitives."""
    return {
        "band": band.band,
        "label": band.label,
        "score": _finite(band.score),
        "certainty": band.certainty,
        "certainty_reasons": list(band.certainty_reasons),
        "n_valid": band.n_valid,
        "n_abstained": band.n_abstained,
        "probability": _finite(band.probability),
        "flags": list(band.flags),
        "indeterminate": band.indeterminate,
        "abstain_subtag": band.abstain_subtag,
        "source": source,
    }


def goal_rollup(profile, report, playground="castle_crashers", configs_dir=None):
    """The `rollup` channel dict for one run: rolled-up claims for all four
    goals. Consumes the shared battery `report` and the computed `profile`."""
    card = load_rollup_card(playground, configs_dir)
    bands = banded_rollup(report, card, playground=playground) if report else {}

    goals = {}
    # clear_debris_zone: banded from the battery, enriched with the three signals
    cdz = bands.get("clear_debris_zone")
    if cdz is not None:
        entry = _band_entry(cdz)
        enrich = _debris_enrichment(profile)
        enrich["proportion_cleared"] = entry["score"]   # the band's own score
        entry["debris"] = enrich
        goals["clear_debris_zone"] = entry

    # remain_on_island: banded from the battery
    roi = bands.get("remain_on_island")
    if roi is not None:
        goals["remain_on_island"] = _band_entry(roi)

    # the two no-battery-channel goals: derived from profile indicators
    goals["engage_plow"] = _engage_plow_claim(profile)
    goals["playground_engagement"] = _engagement_claim(profile)

    return {"provisional": False, "goals": goals}
