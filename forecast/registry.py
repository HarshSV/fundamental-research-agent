"""Model registry + promotion gate.

Every production forecast is traceable to a registry row: model/feature version, training data
range, training timestamp, hyperparameters, validation metrics, artifact path.

PROMOTION GATE (criteria fixed here, in advance - not tuned to make a model pass). A candidate
becomes `production` only if, on pooled walk-forward OUT-OF-SAMPLE results, for EVERY horizon h=1..5:
  RANGE   (the product's core claim):
    - Winkler(80%) interval score beats the best baseline with a 95% session-block bootstrap CI
      entirely below 0, AND
    - empirical coverage within +-3 percentage points of nominal at 50/80/95%.
  and, for the candidate overall:
    - beats the best baseline on |return error|/sigma in >= 2/3 of walk-forward folds,
    - and, if a production model exists, is not worse than it on Winkler(80%) (p_better >= 0.5).
DIRECTION is validated per horizon separately: Brier AND misclassification both beat the best baseline
with 95% CI below 0. A horizon that fails direction validation may still be shown as a range forecast,
but its directional confidence is capped (confidence engine perf component = 0).
A model failing the RANGE gate is never promoted; the API then answers NO_RELIABLE_FORECAST.
"""
import json
import os
import time

import numpy as np

from . import config, evaluate

COVERAGE_TOL = 0.03
FOLD_WIN_SHARE = 2 / 3
BASELINES = ["persistence", "recent_return", "trend"]


def _best_baseline(oos, h):
    rep = evaluate.report(oos, BASELINES, (h,))
    return rep.sort_values("nmae").iloc[0]["model"]


def promotion_gate(oos, model="ens", prod_model=None, boot=1000):
    res = {"model": model, "range_validated": {}, "direction_validated": {}, "perf_skill": {}, "details": [], "reasons": []}
    for h in config.HORIZONS:
        b = _best_baseline(oos, h)
        w = evaluate.paired_bootstrap(oos, model, b, h, "winkler80", B=boot)
        sc = evaluate.score(oos, model, h)
        cov_ok = all(abs(sc.get(f"cov{lv}", np.nan) - lv / 100.0) <= COVERAGE_TOL for lv in evaluate.LEVELS)
        res["range_validated"][h] = bool(w["ci_hi"] < 0 and cov_ok)
        br = evaluate.paired_bootstrap(oos, model, b, h, "brier", B=boot)
        er = evaluate.paired_bootstrap(oos, model, b, h, "err_dir", B=boot)
        res["direction_validated"][h] = bool(br["ci_hi"] < 0 and er["ci_hi"] < 0)
        res["perf_skill"][h] = float(max(0.0, -br["diff"] / max(br["mean_b"], 1e-9)))
        res["details"].append({"h": h, "baseline": b, "winkler": w, "brier": br, "err_dir": er, "coverage_ok": cov_ok})
        if not res["range_validated"][h]:
            res["reasons"].append(f"h={h}: range gate failed (winkler CI hi={w['ci_hi']:.4f}, coverage_ok={cov_ok})")
    # fold-level consistency on |error|/sigma
    wins = []
    for f, g in oos.groupby("fold"):
        g = g.reset_index(drop=True)
        wins.append(np.mean([evaluate.score(g, model, h)["nmae"] < evaluate.score(g, _best_baseline(oos, h), h)["nmae"]
                             for h in config.HORIZONS]))
    res["fold_win_share"] = float(np.mean(np.array(wins) > 0.5)) if wins else 0.0
    if res["fold_win_share"] < FOLD_WIN_SHARE:
        res["reasons"].append(f"fold consistency {res['fold_win_share']:.2f} < {FOLD_WIN_SHARE:.2f}")
    if prod_model is not None and prod_model in oos.columns.str.split("_").str[0].values:
        for h in config.HORIZONS:
            c = evaluate.paired_bootstrap(oos, model, prod_model, h, "winkler80", B=boot)
            if c["p_better"] < 0.5:
                res["reasons"].append(f"h={h}: not better than production model")
    res["pass"] = bool(all(res["range_validated"].values()) and not res["reasons"])
    return res


# ----------------------------------------------------------------- registry persistence
def register(con, version, family, feature_version, train_start, train_end, hyperparams, metrics, artifact_path, status="candidate", notes=None):
    with con:
        con.execute("INSERT OR REPLACE INTO model_registry VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (version, family, feature_version, train_start, train_end, int(time.time()),
                     json.dumps(hyperparams, default=str), json.dumps(metrics, default=str), artifact_path, status, None, notes))


def promote(con, version, gate):
    """Only a passing gate may promote; otherwise the model is marked rejected with the reasons."""
    if not gate["pass"]:
        with con:
            con.execute("UPDATE model_registry SET status='rejected', notes=? WHERE model_version=?",
                        (json.dumps(gate["reasons"]), version))
        return False
    with con:
        con.execute("UPDATE model_registry SET status='retired' WHERE status='production'")
        con.execute("UPDATE model_registry SET status='production', promoted_at=? WHERE model_version=?", (int(time.time()), version))
    return True


def production_model(con):
    r = con.execute("SELECT model_version,family,feature_version,train_start,train_end,trained_at,hyperparams_json,"
                    "metrics_json,artifact_path,promoted_at FROM model_registry WHERE status='production'").fetchone()
    if r is None:
        return None
    keys = ["model_version", "family", "feature_version", "train_start", "train_end", "trained_at", "hyperparams", "metrics", "artifact_path", "promoted_at"]
    d = dict(zip(keys, r))
    d["hyperparams"], d["metrics"] = json.loads(d["hyperparams"] or "{}"), json.loads(d["metrics"] or "{}")
    return d
