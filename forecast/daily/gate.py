"""Daily promotion-gate evaluation and forecast output formatting (no UI, no API wiring in this phase).

GATE (criteria fixed in advance; same logic as the intraday gate, with MONTH-block bootstrap because daily labels overlap
and stocks are cross-correlated). For each horizon h:
  RANGE     : Winkler(80%) beats the best baseline (95% CI upper bound < 0) AND coverage within +-3 pts at 50/80/95.
  DIRECTION : Brier AND misclassification both beat the best baseline (95% CI upper bound < 0).
The output builder only emits a directional probability for horizons whose DIRECTION gate passed; otherwise the horizon
is "range only" - a missing probability is never turned into 50%.
"""
import numpy as np
import pandas as pd

from .. import evaluate

SIG = "rv20"
COV_TOL = 0.03
BASELINES = ["persistence", "recent_return", "trend", "hist_vol"]


def best_baseline(oos, h):
    r = evaluate.report(oos, BASELINES, (h,), SIG)
    return r.sort_values("nmae").iloc[0]["model"]


def daily_gate(oos, model, horizons, boot=1000):
    res = {"model": model, "horizons": {}}
    for h in horizons:
        b = best_baseline(oos, h)
        sc = evaluate.score(oos, model, h, SIG)
        w = evaluate.paired_bootstrap(oos, model, b, h, "winkler80", B=boot, sig_col=SIG, block_col="month")
        br = evaluate.paired_bootstrap(oos, model, b, h, "brier", B=boot, sig_col=SIG, block_col="month")
        er = evaluate.paired_bootstrap(oos, model, b, h, "err_dir", B=boot, sig_col=SIG, block_col="month")
        cov = {lv: sc.get(f"cov{lv}", np.nan) for lv in evaluate.LEVELS}
        cov_ok = all(abs(cov[lv] - lv / 100.0) <= COV_TOL for lv in cov)
        res["horizons"][h] = {"baseline": b, "coverage": cov, "coverage_ok": bool(cov_ok), "winkler_ci": (w["ci_lo"], w["ci_hi"]),
                              "range_validated": bool(w["ci_hi"] < 0 and cov_ok), "direction_validated": bool(br["ci_hi"] < 0 and er["ci_hi"] < 0),
                              "brier_diff": br["diff"], "err_dir_diff": er["diff"]}
    return res


def format_forecast(close, preds, direction_validated, as_of, model_version, horizons):
    """preds: {h: {'ret_med': float, 'p_up': float, 'intervals': {50|80|95: (lo, hi)}}} for ONE symbol/date (log-return units).
    Returns the horizon cards the UI will later render. Nothing is invented: missing intervals stay None."""
    out = {"as_of": as_of, "model_version": model_version, "reference_close": float(close), "horizons": []}
    for h in horizons:
        p = preds.get(h)
        if p is None:
            out["horizons"].append({"horizon_days": h, "status": "unavailable"})
            continue
        ints = {str(lv): [float(close * np.exp(lo)), float(close * np.exp(hi))] for lv, (lo, hi) in p["intervals"].items()
                if lo is not None and hi is not None and np.isfinite(lo) and np.isfinite(hi)}
        card = {"horizon_days": h, "median": float(close * np.exp(p["ret_med"])) if np.isfinite(p["ret_med"]) else None, "intervals": ints or None}
        if not ints:
            card["status"] = "unavailable"
        elif direction_validated.get(h) and np.isfinite(p["p_up"]):
            card.update(status="directional", direction_probability=float(p["p_up"]))
        else:
            card.update(status="range_only", direction_probability=None, note="Range forecast available; directional signal uncertain")
        out["horizons"].append(card)
    return out
