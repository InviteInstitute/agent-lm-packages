"""Purpose-1 BANDED goal rollup (v2 — the §4.8 fully-ruled spec,
2026-09-04). Supersedes the v1 weighted-mean capability levels, RETIRED
by ruling D2(a); the per-check evidence rows remain the durable
artifact, and this layer stays deliberately replaceable.

The ruled pipeline per goal (rulings G-b/G-d 2026-09-03, rungs + D1-D5
2026-09-04 — SENSOR_TESTBATTERY §4.8 carries the audit trail):

    flat score  = mean of the goal's check over VALID (non-abstained)
                  tests; abstention shrinks the denominator, never
                  zeroes. CDZ = clearing ONLY; ROI = encounter-survival
                  ONLY (no engagement, no detection — D1(b)).
    band        = the score cut into the card's ruled rungs.
    U           = every contributing check abstained -> no band; the
                  dominant abstain reason rides as a sub-tag (D3(b):
                  U/test_not_activated and U/encounter_not_reached are
                  behaviorally different signatures).
    certainty   = "full" minus demotions: sparse_evidence (valid tests
                  below the card's sparse_min_valid) and
                  budget_sensitive (the band moves between the two
                  duration budgets — D4(a): primary band KEPT).
    P(ROI)      = the calibrated family logistic where the artifact is
                  on disk; band-vs-model disagreement is a surfaced
                  flag, never a silent average (D5(a)).

Every cut/threshold lives in _rollup.yaml (YAML-only discipline).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from .config import _DEFAULT_CONFIGS_DIR, _load_yaml


@dataclass(frozen=True)
class GoalBand:
    goal: str
    band: str | None               # None when indeterminate (U)
    score: float | None            # flat mean over valid tests
    n_valid: int
    n_abstained: int
    # indicator-vocabulary name (2026-09-05): the test channel's entry in
    # the goal__indicator__* naming (cleared_proportion_tests /
    # on_island_tests), card-declared.
    indicator: str = ""
    indeterminate: bool = False
    abstain_subtag: str = ""       # dominant reason when U (D3(b))
    certainty: str = "full"        # "full" | "reduced"
    certainty_reasons: tuple = ()  # e.g. ("sparse_evidence",)
    probability: float | None = None   # calibrated P (ROI only)
    flags: tuple = ()              # e.g. ("band_model_disagreement",)

    @property
    def label(self) -> str:
        if self.indeterminate:
            return f"U/{self.abstain_subtag or 'no_evidence'}"
        return self.band or ""


def load_rollup_card(playground: str, configs_dir: str | None = None) -> dict:
    path = (Path(configs_dir or _DEFAULT_CONFIGS_DIR) / "testcases"
            / playground / "_rollup.yaml")
    return _load_yaml(path) if path.exists() else {}


def _band_for(score: float, rungs: list) -> str:
    for rung in rungs:                       # card order: highest first
        if score >= float(rung["min"]) - 1e-12:
            return str(rung["band"])
    return str(rungs[-1]["band"])


def _goal_checks(report, check_name: str):
    """Every (scenario, check) result carrying the goal's ruled check."""
    out = []
    for s in report.scenarios:
        for c in s.checks:
            if c.name == check_name:
                out.append((s, c))
    return out


def _flat_score(report, check_name: str):
    """(score, n_valid, n_abstained, subtag): the ruled flat mean."""
    vals, reasons = [], []
    for _s, c in _goal_checks(report, check_name):
        if c.abstained:
            reasons.append(c.abstain_reason or "unknown")
        elif c.value is not None:
            vals.append(float(c.value))
    if not vals:
        subtag = ""
        if reasons:
            top = max(set(reasons), key=reasons.count)
            subtag = top if reasons.count(top) * 2 >= len(reasons) else "mixed"
        return None, 0, len(reasons), subtag
    return sum(vals) / len(vals), len(vals), len(reasons), ""


def _family_island_means(report) -> dict:
    """fam__{family}__stays_on_island means from a report — the feature
    row for the calibrated ROI logistic (matches goal_calibration's
    family-summary columns)."""
    acc: dict = {}
    for s in report.scenarios:
        for c in s.checks:
            if c.name == "stays_on_island" and not c.abstained \
                    and c.value is not None:
                acc.setdefault(s.family, []).append(float(c.value))
    return {f"fam__{fam}__stays_on_island": sum(v) / len(v)
            for fam, v in acc.items()}


def roi_probability(report, playground: str = "castle_crashers",
                    artifact_path: str | None = None) -> float | None:
    """Calibrated P(remain_on_island) from the on-disk candidate model;
    None when the artifact (or pandas) is unavailable."""
    try:
        import pandas as pd
        from .goal_calibration import predict
        path = Path(artifact_path) if artifact_path else (
            Path(_DEFAULT_CONFIGS_DIR).parent / "data" / "ccp_run_dataset"
            / "purpose1_calibration.json")
        if not path.exists():
            return None
        art = json.loads(path.read_text())
        fit = art.get("roi")
        if not fit:
            return None
        row = _family_island_means(report)
        import numpy as np
        df = pd.DataFrame([{c: row.get(c, np.nan)
                            for c in fit["feature_columns"]}], dtype=float)
        return float(predict(fit, df)[0])
    except Exception:
        return None


def banded_rollup(report, card: dict, probabilities: bool = True,
                  playground: str = "castle_crashers") -> dict:
    """{goal: GoalBand} for one battery report under the ruled spec."""
    out = {}
    for goal, spec in (card.get("goals") or {}).items():
        score, n_valid, n_abst, subtag = _flat_score(report, spec["check"])
        if score is None:
            out[goal] = GoalBand(goal=goal,
                                 indicator=str(spec.get("indicator") or ""),
                                 band=None, score=None,
                                 n_valid=0, n_abstained=n_abst,
                                 indeterminate=True, abstain_subtag=subtag)
            continue
        band = _band_for(score, spec["rungs"])
        reasons = []
        if n_valid < int(spec.get("sparse_min_valid") or 0):
            reasons.append("sparse_evidence")
        prob = None
        flags = []
        if probabilities and spec.get("calibrated_model"):
            prob = roi_probability(report, playground)
            if prob is not None:
                # D5(a): disagreement between the top/bottom band and the
                # calibrated claim is surfaced, never averaged away.
                top = spec["rungs"][0]["band"]
                bottom = spec["rungs"][-1]["band"]
                if (band == top and prob < 0.5) or \
                        (band == bottom and prob >= 0.5):
                    flags.append("band_model_disagreement")
        out[goal] = GoalBand(goal=goal,
                             indicator=str(spec.get("indicator") or ""),
                             band=band, score=score,
                             n_valid=n_valid, n_abstained=n_abst,
                             certainty="reduced" if reasons else "full",
                             certainty_reasons=tuple(reasons),
                             probability=prob, flags=tuple(flags))
    return out


def banded_invariant(reports, card: dict,
                     playground: str = "castle_crashers") -> dict:
    """The D4(a) two-budget guard: bands from the PRIMARY budget, with a
    `budget_sensitive` certainty demotion wherever the band moves under
    the invariance budget. Never U (the v1 semantics, retired)."""
    primary = banded_rollup(reports[0], card, playground=playground)
    if len(reports) < 2:
        return primary
    alt = banded_rollup(reports[1], card, probabilities=False,
                        playground=playground)
    out = {}
    for goal, gb in primary.items():
        other = alt.get(goal)
        if (gb.band is not None and other is not None
                and other.band is not None and other.band != gb.band):
            from dataclasses import replace
            out[goal] = replace(
                gb, certainty="reduced",
                certainty_reasons=gb.certainty_reasons + ("budget_sensitive",))
        else:
            out[goal] = gb
    return out
