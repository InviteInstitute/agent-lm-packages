"""Purpose-1 goal-rollup calibration dataset (SENSOR_TESTBATTERY §4.7,
researcher plan reconciled 2026-09-01).

Assembles the calibration/reference table joining, per battery-eligible
RUN (the ruled unit — per-run rows, clustering acknowledged):

- TARGETS from the production pipeline: the sim `debris_zone_coverage`
  continuous value and its rung (the card's own cut points, applied by
  the rung sweep — never re-derived here), telemetry `weight_cleared`
  (the ruled VALIDATION quantity, not the target), and both ROI
  channels (sim rung + observed GPS off-island).
- PREDICTORS from the battery: per (scenario, check) — the measured
  value for measurement rules, pass=1 / conditional=0.5 / fail=0 for
  boolean rules, and NaN for abstentions (NEVER recoded as failure —
  plan §4), with per-scenario abstain-reason columns kept as their own
  candidate evidence.

The sample is LOOSE by ruling (Q1): no certainty gating — the fidelity
verdict and flags ride along as columns for stratification in the
descriptive review, because gating on trusted sims subselects
program types (successful engagement itself earns staleness flags).
"""
from __future__ import annotations

import csv
from pathlib import Path

from .config import configs_root
from .paths import data_path

_STATUS_SCORE = {"pass": 1.0, "conditional": 0.5, "fail": 0.0}

TARGET_COLS = ["coverage_value", "coverage_rung", "weight_cleared",
               "roi_sim_rung", "roi_observed_off", "verdict"]


def _read(path):
    with open(path) as fh:
        yield from csv.DictReader(fh)


def calibration_table(data_dir: str | None = None):
    """One row per battery-eligible run. Returns a pandas DataFrame with
    identifier, target, and wide per-(scenario, check) predictor columns
    (`<scenario>__<check>`), plus `<scenario>__abstain` reason columns
    and `<scenario>__capped` markers."""
    import pandas as pd
    d = Path(data_dir) if data_dir else data_path("ccp_run_dataset")

    # --- battery predictors, per run (identical for identical programs) ---
    batt: dict[str, dict] = {}
    for r in _read(d / "stage3_battery.csv"):
        if r["eligible"] != "True" or r["scenario"].startswith("__"):
            continue
        row = batt.setdefault(r["run_id"], {})
        key = f"{r['scenario']}__{r['check']}"
        if r["abstain_reason"]:
            row[key] = float("nan")
            row[f"{r['scenario']}__abstain"] = r["abstain_reason"]
            continue
        if r["status"] == "measured":
            row[key] = float(r["value"]) if r["value"] != "" else float("nan")
        else:
            row[key] = _STATUS_SCORE.get(r["status"], float("nan"))
        if r["capped"] == "True":
            row[f"{r['scenario']}__capped"] = True

    # --- targets ---
    rungs = {r["run_id"]: r for r in _read(d / "stage2_rungs.csv")}
    fid = {r["run_id"]: r for r in _read(d / "stage2_fidelity.csv")}

    cov_v = "clear_debris_zone__debris_zone_coverage__value"
    cov_r = "clear_debris_zone__debris_zone_coverage__rung"
    roi_r = "remain_on_island__on_island_sim__rung"

    rows = []
    for rid, preds in batt.items():
        rg = rungs.get(rid, {})
        fd = fid.get(rid, {})
        rows.append({
            "run_id": rid,
            "student": rid.split("_")[0],
            "session": rg.get("session") or "",
            "cohort": rg.get("cohort") or "",
            "has_telemetry": bool(fd),
            "coverage_value": float(rg[cov_v]) if rg.get(cov_v) else float("nan"),
            "coverage_rung": rg.get(cov_r) or "",
            "weight_cleared": (float(fd["weight_cleared"])
                               if fd.get("weight_cleared") else float("nan")),
            "roi_sim_rung": rg.get(roi_r) or "",
            "roi_observed_off": ({"True": True, "False": False}
                                 .get(fd.get("gps_off"), None)),
            "verdict": fd.get("verdict") or "",
            **preds,
        })
    df = pd.DataFrame(rows)
    return df.sort_values("run_id").reset_index(drop=True)


def predictor_columns(df) -> list:
    """The wide battery-evidence columns, excluding abstain/capped markers."""
    return [c for c in df.columns
            if "__" in c and not c.endswith(("__abstain", "__capped"))]


if __name__ == "__main__":   # pragma: no cover
    df = calibration_table()
    print(f"{len(df)} eligible runs, {len(predictor_columns(df))} predictors")
    print(df["coverage_rung"].value_counts(dropna=False))


# ---------------------------------------------------------------------- #
# Simple calibrated models (plan §5.3) — numpy-only, deliberately: ridge
# for the continuous coverage target (then the CARD's cut points), IRLS
# logistic for ROI. Coefficients stay inspectable; no new dependency.
# Abstention encoding for the model: an abstained check imputes to the
# COLUMN MEAN (uninformative) while the per-scenario abstained dummy
# carries the activation signal as its own candidate predictor (plan §4).
# ---------------------------------------------------------------------- #

def coverage_edges(playground: str = "castle_crashers") -> list:
    """The CDZ cut points, read from the goals card — never hardcoded."""
    import yaml
    with open(configs_root() / "goals" / f"{playground}.yaml") as fh:
        card = yaml.safe_load(fh)
    for goal in card.get("goals", []):
        for ind in (goal.get("indicators") or []) + \
                (goal.get("attainment") or []) + (goal.get("intent") or []):
            if ind.get("name") == "debris_zone_coverage":
                return list(ind["rungs"]["edges"])
    raise KeyError("debris_zone_coverage edges not found in goals card")


def coverage_category(value: float, edges: list) -> str:
    labels = ["negligible", "some", "meaningful", "systematic"]
    for i, e in enumerate(edges):
        if value < e:
            return labels[i]
    return labels[-1]


def _design(df, columns, transform: dict | None = None):
    """Impute (column means), standardize, prepend intercept. With
    `transform` (from a prior fit), applies THAT fit's means/mu/sd — the
    single code path for both fitting and out-of-sample scoring."""
    import pandas as pd
    X = df[columns].copy()
    if transform is None:
        means = X.mean()
        X = X.fillna(means)
        mu, sd = X.mean(), X.std(ddof=0).replace(0, 1.0)
        transform = {"impute_means": means.to_dict(),
                     "mu": mu.to_dict(), "sd": sd.to_dict()}
    else:
        X = X.fillna(pd.Series(transform["impute_means"]))
        mu = pd.Series(transform["mu"])
        sd = pd.Series(transform["sd"]).replace(0, 1.0)
    Xn = (X - mu) / sd
    Xn.insert(0, "_intercept", 1.0)
    return Xn.to_numpy(), list(Xn.columns), transform


def fit_ridge(df, columns, target: str, lam: float = 1.0):
    """Closed-form ridge on standardized predictors; returns a dict with
    coefficients (by name), the imputation means, and predictions."""
    import numpy as np
    d = df.dropna(subset=[target])
    X, names, transform = _design(d, columns)
    y = d[target].to_numpy(dtype=float)
    eye = np.eye(X.shape[1]) * lam
    eye[0, 0] = 0.0                       # never penalize the intercept
    beta = np.linalg.solve(X.T @ X + eye, X.T @ y)
    pred = X @ beta
    ss_res = float(((y - pred) ** 2).sum())
    ss_tot = float(((y - y.mean()) ** 2).sum()) or 1.0
    return {"kind": "ridge", "target": target, "lambda": lam,
            "columns": names, "coef": beta.tolist(),
            "transform": transform, "feature_columns": list(columns),
            "n": int(len(d)), "r2_insample": 1 - ss_res / ss_tot,
            "index": d.index.to_list(), "pred": pred.tolist()}


def fit_logistic(df, columns, target: str, lam: float = 1.0,
                 iters: int = 50):
    """IRLS logistic with ridge penalty; target column must be 0/1."""
    import numpy as np
    d = df.dropna(subset=[target])
    X, names, transform = _design(d, columns)
    y = d[target].to_numpy(dtype=float)
    beta = np.zeros(X.shape[1])
    eye = np.eye(X.shape[1]) * lam
    eye[0, 0] = 0.0
    for _ in range(iters):
        p = 1.0 / (1.0 + np.exp(-(X @ beta)))
        W = p * (1 - p) + 1e-9
        grad = X.T @ (y - p) - eye @ beta
        H = (X * W[:, None]).T @ X + eye
        step = np.linalg.solve(H, grad)
        beta = beta + step
        if float(np.abs(step).max()) < 1e-8:
            break
    p = 1.0 / (1.0 + np.exp(-(X @ beta)))
    acc = float(((p > 0.5) == (y > 0.5)).mean())
    return {"kind": "logistic", "target": target, "lambda": lam,
            "columns": names, "coef": beta.tolist(),
            "transform": transform, "feature_columns": list(columns),
            "n": int(len(d)), "acc_insample": acc,
            "index": d.index.to_list(), "prob": p.tolist()}


def predict(fit: dict, df):
    """Score new rows with a fitted model — the SAME design transform."""
    import numpy as np
    X, _, _ = _design(df, fit["feature_columns"],
                      transform=fit["transform"])
    raw = X @ np.array(fit["coef"])
    if fit["kind"] == "logistic":
        return 1.0 / (1.0 + np.exp(-raw))
    return raw


def grouped_cv(df, columns, target: str, kind: str = "ridge",
               group: str = "student", lam: float = 1.0, k: int = 5,
               seed: int = 7):
    """Leave-students-out CV — the clustering-aware check (Q2: per-run
    rows, students grouped). Returns out-of-fold predictions + summary."""
    import numpy as np
    d = df.dropna(subset=[target]).reset_index(drop=True)
    rng = np.random.default_rng(seed)
    groups = np.array(sorted(d[group].unique()))
    rng.shuffle(groups)
    folds = np.array_split(groups, k)
    preds = np.full(len(d), np.nan)
    fitter = fit_ridge if kind == "ridge" else fit_logistic
    for hold in folds:
        tr = d[~d[group].isin(hold)]
        te = d[d[group].isin(hold)]
        if not len(tr) or not len(te):
            continue
        fit = fitter(tr, columns, target, lam)
        preds[te.index] = predict(fit, te)
    y = d[target].to_numpy(dtype=float)
    ok = ~np.isnan(preds)
    out = {"n": int(ok.sum()), "k": k, "kind": kind,
           "pred": preds.tolist(), "index": d.index.to_list()}
    if kind == "ridge":
        ss_res = float(((y[ok] - preds[ok]) ** 2).sum())
        ss_tot = float(((y[ok] - y[ok].mean()) ** 2).sum()) or 1.0
        out["cv_r2"] = 1 - ss_res / ss_tot
    else:
        out["cv_acc"] = float(((preds[ok] > 0.5) == (y[ok] > 0.5)).mean())
    return out


def family_summary_columns(df) -> dict:
    """The parsimonious family-level representation (plan §3.4): mean of
    the PRIMARY check across a family's variants. Returns
    {new_column: source_columns}; adds the columns to df in place."""
    fams = {
        "t1_debris_field": ["t1_castle_wall"],
        "t2_boundary": ["t2a_direct", "t2b_angled", "t2c_steep"],
        "t3_block_boundary": ["t3a_generous", "t3b_extended", "t3c_offset"],
        "t4_debris_configuration": ["t4a_near_favorable", "t4b_jittered",
                                    "t4c_dispersed"],
        "t5_heading_perturbation": ["t5a_mild", "t5b_moderate", "t5c_severe"],
        "t6_reengagement": ["t6a_favorable", "t6b_shifted", "t6c_mirrored"],
        "t7_managed_clearing": ["t7a_near_favorable", "t7b_jittered",
                                "t7c_dispersed"],
    }
    added = {}
    for fam, variants in fams.items():
        for chk in ("proportion_cleared", "stays_on_island"):
            cols = [f"{v}__{chk}" for v in variants
                    if f"{v}__{chk}" in df.columns]
            if not cols:
                continue
            name = f"fam__{fam}__{chk}"
            df[name] = df[cols].mean(axis=1)
            added[name] = cols
    return added
