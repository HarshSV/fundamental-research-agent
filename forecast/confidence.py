"""Dedicated confidence engine (NOT a softmax-to-confidence mapping).

Output per forecast row and horizon: level in {HIGH, MEDIUM, LOW, NO_RELIABLE_FORECAST}, a score in
[0,1], the component scores and the reasons. Thresholds are fixed a priori and then VALIDATED
out-of-sample (tier-stratified accuracy must be monotone - see report.tier_report).

Hard gates (any -> NO_RELIABLE_FORECAST, forecast withheld):
  data not usable / features invalid / model not production / validation stale / input outside the
  training distribution / horizon would cross the session end / session structure nonstandard.
Soft components (all in [0,1]):
  prob      : calibrated directional edge |p-0.5|/0.10
  agree     : all models agree on direction (p and median return signs)
  snr       : |median return| relative to the 80% interval half-width
  regime    : regime unchanged over the last bars (stability)
  evidence  : share of top-10 |SHAP| mass supporting the predicted side
  perf      : recent OOS skill vs best baseline for this horizon (0 if not better than baseline)
  data      : data-quality score
The score is a WEIGHTED GEOMETRIC MEAN, so one near-zero component (e.g. no demonstrated skill)
drags the whole score down instead of being averaged away.
"""
import numpy as np

W = {"prob": 0.25, "agree": 0.15, "snr": 0.10, "regime": 0.10, "evidence": 0.15, "perf": 0.20, "data": 0.05}
T_HIGH, T_MED, T_LOW = 0.70, 0.45, 0.25
LEVELS = np.array(["NO_RELIABLE_FORECAST", "LOW", "MEDIUM", "HIGH"])


def components(p_up, p_models, ret_models, ret_med, width80, regime_stable, shap_agree, perf_skill, data_ok):
    n = len(p_up)
    full = lambda v: np.full(n, v, float) if np.isscalar(v) else np.asarray(v, float)
    prob = np.clip(np.abs(p_up - 0.5) / 0.10, 0, 1)
    signs = [np.sign(np.asarray(pm) - 0.5) for pm in p_models] + [np.sign(np.asarray(r)) for r in ret_models]
    agree = np.all([s == signs[0] for s in signs], axis=0).astype(float) * 0.7 + 0.3 * (np.sign(p_up - 0.5) == np.sign(ret_med))
    snr = np.clip(np.abs(ret_med) / np.where(width80 > 0, width80 / 2, np.nan) / 0.10, 0, 1)
    regime = full(regime_stable)
    evidence = np.where(np.isnan(full(shap_agree)), 0.5, np.clip((full(shap_agree) - 0.5) / 0.3, 0, 1))
    perf = np.clip(full(perf_skill) / 0.004, 0, 1)
    data = full(data_ok)
    return {"prob": prob, "agree": agree, "snr": np.nan_to_num(snr, nan=0.0), "regime": regime,
            "evidence": evidence, "perf": perf, "data": data}


def score_from_components(c):
    eps = 1e-3
    logs = sum(W[k] * np.log(np.clip(c[k], eps, 1.0)) for k in W)
    return np.exp(logs / sum(W.values()))


def level_from_score(score, gated):
    lvl = np.where(score >= T_HIGH, 3, np.where(score >= T_MED, 2, np.where(score >= T_LOW, 1, 0)))
    lvl = np.where(gated, 0, lvl)
    return LEVELS[lvl]


def assess(p_up, p_models, ret_models, ret_med, width80, regime_stable, shap_agree, perf_skill, data_ok, gated=None):
    comp = components(p_up, p_models, ret_models, ret_med, width80, regime_stable, shap_agree, perf_skill, data_ok)
    score = score_from_components(comp)
    g = np.zeros(len(p_up), bool) if gated is None else np.asarray(gated, bool)
    g = g | np.isnan(p_up) | np.isnan(ret_med)
    return {"level": level_from_score(score, g), "score": np.where(g, 0.0, score), "components": comp}


def in_distribution(df, envelope, max_outside_frac=0.15):
    """Input-distribution gate. envelope = {feature: (p0.5, p99.5)} saved with the model at training time.
    Returns a bool array: True = supported, False = outside the training distribution."""
    cols = [c for c in envelope if c in df.columns]
    if not cols:
        return np.zeros(len(df), bool)
    X = df[cols].values.astype(float)
    lo = np.array([envelope[c][0] for c in cols]); hi = np.array([envelope[c][1] for c in cols])
    known = ~np.isnan(X)
    out = ((X < lo) | (X > hi)) & known
    frac = out.sum(1) / np.maximum(known.sum(1), 1)
    return frac <= max_outside_frac
