"""Daily model candidates.

A. GBM  (forecast.models_gbm.GBMForecaster): LightGBM direct multi-horizon - direction classifier + 7 quantiles of the
   vol-normalised return, on the ~32 conservative features. Fixed hyperparameters (no tuning on test data).
B. HAR-empirical (this file): a different family. For each horizon, a HAR-style regression of log(future range) on
   log(rv10, rv20, rv60, vol_rel) gives a predicted scale; the standardised return z = y_ret / scale is summarised by
   its EMPIRICAL quantiles from the training block (fat tails and drift come from data, not an assumed Gaussian).
   P(up) is the training frequency (it has no directional view).
C. Ensemble (forecast.ensemble.Ensemble) of A and B, weights chosen on the calibration block only.
Both families are calibrated identically (isotonic P(up) + conformal CQR intervals on the fold's calibration block).
"""
import numpy as np

from ..models_base import CalibratedForecaster, QUANTS, sigma_of
from ..models_gbm import GBMForecaster

HAR_COLS = ("rv10", "rv20", "rv60", "vol_rel")


def make_gbm(fcols, horizons, rounds=100, min_leaf=300, stride=2):
    return GBMForecaster(fcols, horizons, train_stride=stride, sigma_col="rv20", use_wicks=False, rounds=rounds, min_leaf=min_leaf)


class HarEmpiricalForecaster(CalibratedForecaster):
    family = "har_empirical"

    def __init__(self, feature_cols, horizons, sigma_col="rv20"):
        super().__init__(feature_cols, horizons, sigma_col)
        self.beta, self.smear, self.qz, self.p_up = {}, {}, {}, {}

    @staticmethod
    def _X(df):
        cols = [np.log(np.clip(df[c].values.astype(float), 1e-6, None)) for c in HAR_COLS]
        return np.column_stack([np.ones(len(df))] + cols)

    def fit_core(self, train):
        X = self._X(train)
        for h in self.horizons:
            yr = train[f"y_range_{h}"].values.astype(float)
            ok = np.isfinite(yr) & (yr > 0) & np.isfinite(X).all(1)
            beta = np.linalg.lstsq(X[ok], np.log(yr[ok]), rcond=None)[0]
            resid = np.log(yr[ok]) - X[ok] @ beta
            self.beta[h], self.smear[h] = beta, float(np.mean(np.exp(resid)))
            scale = np.exp(X @ beta) * self.smear[h]
            z = train[f"y_ret_{h}"].values / scale
            zok = np.isfinite(z)
            self.qz[h] = {q: float(np.quantile(z[zok], q)) for q in QUANTS}
            up = train[f"y_up_{h}"].values
            self.p_up[h] = float(np.clip(np.nanmean(up), 0.02, 0.98))

    def _raw(self, df):
        X = self._X(df)
        sig = sigma_of(df, self.sigma_col)
        out = {}
        for h in self.horizons:
            scale = np.exp(X @ self.beta[h]) * self.smear[h]
            out[h] = {"p_up": np.full(len(df), self.p_up[h]), "q": {q: self.qz[h][q] * scale / sig for q in QUANTS}}
        return out
