"""Out-of-sample calibration: isotonic probability calibration and conformalised quantile
regression (CQR, Romano et al. 2019). Both are FIT on the calibration block of a fold, which is
strictly after the training window and strictly before the test block."""
import json

import numpy as np

MIN_CAL = 500


class ProbCalibrator:
    """Isotonic map raw P(up) -> calibrated P(up). Identity if too little calibration data."""

    def __init__(self):
        self.iso = None

    def fit(self, p, y):
        m = ~(np.isnan(p) | np.isnan(y))
        if m.sum() < MIN_CAL or len(np.unique(y[m])) < 2:
            self.iso = None
            return self
        from sklearn.isotonic import IsotonicRegression
        self.iso = IsotonicRegression(y_min=0.01, y_max=0.99, out_of_bounds="clip").fit(p[m], y[m])
        return self

    def predict(self, p):
        if self.iso is None:
            return p
        p = np.asarray(p, float)
        out = np.full(len(p), np.nan)
        m = ~np.isnan(p)
        out[m] = self.iso.predict(p[m])
        return out


def cqr_margin(lo, hi, y, alpha):
    """Conformal margin m so that [lo - m, hi + m] has >= 1-alpha coverage on exchangeable data.
    Scores s = max(lo - y, y - hi). Returns None if the calibration set is too small."""
    m = ~(np.isnan(lo) | np.isnan(hi) | np.isnan(y))
    n = int(m.sum())
    if n < MIN_CAL:
        return None
    s = np.maximum(lo[m] - y[m], y[m] - hi[m])
    k = min(n, int(np.ceil((n + 1) * (1 - alpha))))
    return float(np.sort(s)[k - 1])


def margins_to_json(d):
    return json.dumps({str(k): v for k, v in d.items()})
