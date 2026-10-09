"""Shared calibration/prediction logic so every model family is calibrated identically:
isotonic P(up) calibration + conformalised quantile intervals (CQR), both fit on the fold's
calibration block only. Subclasses implement fit_core() and _raw()."""
import numpy as np

from . import config
from .calibration import ProbCalibrator, cqr_margin

QUANTS = (0.025, 0.1, 0.25, 0.5, 0.75, 0.9, 0.975)
LEVELS = {50: (0.25, 0.75), 80: (0.1, 0.9), 95: (0.025, 0.975)}


def sigma_of(df, col="rv36"):
    s = df[col].values.astype(float)
    return np.where(s > 0, s, np.nan)


class CalibratedForecaster:
    family = "base"

    def __init__(self, feature_cols, horizons=config.HORIZONS, sigma_col="rv36"):
        self.cols, self.horizons, self.sigma_col = list(feature_cols), tuple(horizons), sigma_col
        self.prob_cal, self.margins = {}, {}

    # --- to implement ---
    def fit_core(self, train):
        raise NotImplementedError

    def _raw(self, df):
        """{h: {'p_up': arr, 'q': {quantile: arr in sigma units}, optional 'wup','wdn': arr in sigma units}}"""
        raise NotImplementedError

    # --- shared ---
    def fit(self, train, cal):
        self.fit_core(train)
        self._calibrate(cal)
        return self

    def _calibrate(self, cal):
        raw, sig = self._raw(cal), sigma_of(cal, self.sigma_col)
        for h in self.horizons:
            self.prob_cal[h] = ProbCalibrator().fit(raw[h]["p_up"], cal[f"y_up_{h}"].values)
            y = cal[f"y_ret_{h}"].values / sig
            self.margins[h] = {lv: cqr_margin(raw[h]["q"][a], raw[h]["q"][b], y, 1 - lv / 100.0)
                               for lv, (a, b) in LEVELS.items()}

    def components(self, df):
        """Calibrated-probability + raw normalised quantiles (inputs for the ensemble)."""
        raw = self._raw(df)
        return {h: {"p_up": self.prob_cal[h].predict(raw[h]["p_up"]), "p_up_raw": raw[h]["p_up"], "q": raw[h]["q"],
                    "wup": raw[h].get("wup"), "wdn": raw[h].get("wdn")} for h in self.horizons}

    def predict(self, df):
        """{h: dict(ret_med, p_up, intervals{level:(lo,hi) | None}, wick_up, wick_dn)} in raw log-return units."""
        comp, sig = self.components(df), sigma_of(df, self.sigma_col)
        return finalize(comp, self.margins, sig, self.horizons)


def finalize(comp, margins, sig, horizons):
    out = {}
    for h in horizons:
        c = comp[h]
        ints = {}
        for lv, (a, b) in LEVELS.items():
            m = margins[h].get(lv)
            if m is None:
                ints[lv] = None
                continue
            lo, hi = c["q"][a] - m, c["q"][b] + m
            ints[lv] = (np.minimum(lo, hi) * sig, np.maximum(lo, hi) * sig)
        out[h] = {"ret_med": c["q"][0.5] * sig, "p_up": c["p_up"], "p_up_raw": c["p_up_raw"], "intervals": ints,
                  "wick_up": None if c.get("wup") is None else np.maximum(c["wup"], 0) * sig,
                  "wick_dn": None if c.get("wdn") is None else np.maximum(c["wdn"], 0) * sig}
    return out
