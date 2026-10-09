"""MODEL A - LightGBM direct multi-horizon forecaster (tabular engineered features).

Per horizon h (1..5), independent direct models (never recursive):
  * direction classifier on y_up_h
  * quantile regressors on the VOL-NORMALISED return y_ret_h / sigma_t at 7 quantiles
  * median regressors for the normalised upper/lower wick of the target bar
sigma_t = rv36 at prediction time (a causal feature) - no future statistic is used to normalise.
Hyperparameters are FIXED a priori (no tuning on test data).
Explanations: LightGBM's native TreeSHAP (`pred_contrib=True`); `shap` itself is unusable here
(blocked DLL) and is not required.
"""
import lightgbm as lgb
import numpy as np

from .models_base import CalibratedForecaster, QUANTS, LEVELS, sigma_of  # noqa: F401

PARAMS = dict(num_leaves=15, learning_rate=0.05, min_data_in_leaf=400, feature_fraction=0.7,
              bagging_fraction=0.7, bagging_freq=1, lambda_l2=10.0, verbose=-1, seed=7,
              deterministic=True, force_row_wise=True, num_threads=12)
ROUNDS = 120


def _train(X, y, objective, rounds=None, min_leaf=None, **extra):
    p = dict(PARAMS, objective=objective, **extra)
    if min_leaf:
        p["min_data_in_leaf"] = min_leaf
    return lgb.train(p, lgb.Dataset(X, y, free_raw_data=False), num_boost_round=rounds or ROUNDS)


class GBMForecaster(CalibratedForecaster):
    family = "lightgbm"

    def __init__(self, feature_cols, horizons=(1, 2, 3, 4, 5), train_stride=2, sigma_col="rv36", use_wicks=True,
                 rounds=None, min_leaf=None):
        super().__init__(feature_cols, horizons, sigma_col)
        self.stride, self.use_wicks = train_stride, use_wicks
        self.rounds, self.min_leaf = rounds, min_leaf
        self.clf, self.q, self.wick = {}, {}, {}

    def fit_core(self, train):
        tr = train.iloc[:: self.stride]
        Xtr = tr[self.cols].values.astype(np.float32)
        sig = sigma_of(tr, self.sigma_col)
        for h in self.horizons:
            yr, yu = tr[f"y_ret_{h}"].values / sig, tr[f"y_up_{h}"].values
            ok = ~np.isnan(yr)
            self.q[h] = {qq: _train(Xtr[ok], yr[ok], "quantile", self.rounds, self.min_leaf, alpha=qq) for qq in QUANTS}
            oku = ~np.isnan(yu)
            self.clf[h] = _train(Xtr[oku], yu[oku], "binary", self.rounds, self.min_leaf)
            self.wick[h] = {}
            for k in (("wup", "wdn") if self.use_wicks else ()):
                yw = tr[f"y_{k}_{h}"].values / sig
                okw = ~np.isnan(yw)
                self.wick[h][k] = _train(Xtr[okw], yw[okw], "quantile", self.rounds, self.min_leaf, alpha=0.5)

    def _raw(self, df):
        X = df[self.cols].values.astype(np.float32)
        out = {}
        for h in self.horizons:
            q = np.sort(np.vstack([self.q[h][qq].predict(X) for qq in QUANTS]), axis=0)   # monotone (no crossing)
            out[h] = {"p_up": self.clf[h].predict(X), "q": {qq: q[i] for i, qq in enumerate(QUANTS)}}
            if self.use_wicks:
                out[h]["wup"], out[h]["wdn"] = self.wick[h]["wup"].predict(X), self.wick[h]["wdn"].predict(X)
        return out

    def shap(self, df, h):
        """TreeSHAP contributions of the direction model for horizon h (last column = bias)."""
        return self.clf[h].predict(df[self.cols].values.astype(np.float32), pred_contrib=True)
