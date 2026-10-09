"""Ensemble of independently-fitted, independently-evaluated models.

Weights are NOT arbitrary: for each horizon they are chosen by grid search to minimise
  * direction weight: Brier score of the blended calibrated P(up)
  * return weight   : mean pinball loss of the blended (Vincentised) quantiles
on the fold's CALIBRATION block - data strictly after the models' training window and strictly
before the test block, so weights only use information available when the ensemble would have
been assembled. The ensemble's own conformal margins are then fit on the same calibration block.

Optional regime-aware weights (one weight set per trend regime) are fit the same way; whether
they help is measured OOS (evaluate / report) - they are never assumed to.
"""
import numpy as np

from .models_base import LEVELS, QUANTS, finalize, sigma_of
from .calibration import cqr_margin

GRID = np.round(np.linspace(0, 1, 11), 2)
MIN_REGIME_N = 1500


def _pinball(q_by_level, y):
    tot, n = 0.0, 0
    for qq, pred in q_by_level.items():
        d = y - pred
        tot += np.mean(np.maximum(qq * d, (qq - 1) * d)); n += 1
    return tot / max(n, 1)


class Ensemble:
    family = "ensemble"

    def __init__(self, models, horizons=(1, 2, 3, 4, 5), regime_aware=False):
        self.models, self.names = models, list(models)
        self.sigma_col = getattr(models[self.names[0]], "sigma_col", "rv36")
        self.horizons, self.regime_aware = tuple(horizons), regime_aware
        self.w_dir, self.w_q, self.margins = {}, {}, {}
        self.regime_w = {}            # (h, regime-trend) -> (w_dir, w_q)

    def _blend(self, comps, h, wd, wq):
        names = self.names
        if len(names) == 1:
            c = comps[names[0]][h]
            return c["p_up"], c["q"]
        a, b = comps[names[0]][h], comps[names[1]][h]
        p = wd * a["p_up"] + (1 - wd) * b["p_up"]
        q = {qq: wq * a["q"][qq] + (1 - wq) * b["q"][qq] for qq in QUANTS}
        return p, q

    def _fit_weights(self, comps, cal, mask=None):
        out = {}
        sig = sigma_of(cal, self.sigma_col)
        for h in self.horizons:
            y = cal[f"y_ret_{h}"].values / sig
            yu = cal[f"y_up_{h}"].values
            ok = ~np.isnan(y)
            oku = ~np.isnan(yu)
            if mask is not None:
                ok, oku = ok & mask, oku & mask
            if len(self.names) == 1 or ok.sum() < 300:
                out[h] = (1.0, 1.0) if len(self.names) > 1 else (1.0, 1.0)
                if len(self.names) > 1:
                    out[h] = (0.5, 0.5)                    # too little data to choose: equal, not tuned
                continue
            best_d = min(GRID, key=lambda w: np.mean((self._blend(comps, h, w, 0.5)[0][oku] - yu[oku]) ** 2))
            best_q = min(GRID, key=lambda w: _pinball({qq: v[ok] for qq, v in self._blend(comps, h, 0.5, w)[1].items()}, y[ok]))
            out[h] = (float(best_d), float(best_q))
        return out

    def fit_weights(self, cal, regimes=None):
        """Models must already be fitted (and individually calibrated) on this fold's train/cal."""
        comps = {n: m.components(cal) for n, m in self.models.items()}
        w = self._fit_weights(comps, cal)
        for h in self.horizons:
            self.w_dir[h], self.w_q[h] = w[h]
        if self.regime_aware and regimes is not None:
            for reg in ("trend_up", "trend_down", "range"):
                msk = (regimes == reg).values
                if msk.sum() >= MIN_REGIME_N:
                    rw = self._fit_weights(comps, cal, msk)
                    for h in self.horizons:
                        self.regime_w[(h, reg)] = rw[h]
        self._calibrate(cal, comps, regimes)
        return self

    def _wts(self, h, regimes, n):
        wd, wq = np.full(n, self.w_dir[h]), np.full(n, self.w_q[h])
        if self.regime_aware and regimes is not None:
            for reg in ("trend_up", "trend_down", "range"):
                if (h, reg) in self.regime_w:
                    m = (regimes == reg).values
                    wd[m], wq[m] = self.regime_w[(h, reg)]
        return wd, wq

    def components(self, df, regimes=None):
        comps = {n: m.components(df) for n, m in self.models.items()}
        return self._combine(comps, df, regimes), comps

    def _combine(self, comps, df, regimes):
        res = {}
        for h in self.horizons:
            wd, wq = self._wts(h, regimes, len(df))
            p, q = self._blend(comps, h, wd, wq)
            first = comps[self.names[0]][h]
            res[h] = {"p_up": p, "p_up_raw": p, "q": q, "wup": first.get("wup"), "wdn": first.get("wdn")}
        return res

    def _calibrate(self, cal, comps, regimes):
        sig = sigma_of(cal, self.sigma_col)
        comb = self._combine(comps, cal, regimes)
        for h in self.horizons:
            y = cal[f"y_ret_{h}"].values / sig
            self.margins[h] = {lv: cqr_margin(comb[h]["q"][a], comb[h]["q"][b], y, 1 - lv / 100.0) for lv, (a, b) in LEVELS.items()}

    def predict(self, df, regimes=None):
        comb, comps = self.components(df, regimes)
        out = finalize(comb, self.margins, sigma_of(df, self.sigma_col), self.horizons)
        sig = sigma_of(df, self.sigma_col)
        for h in self.horizons:
            out[h]["per_model"] = {n: {"p_up": comps[n][h]["p_up"], "ret_med": comps[n][h]["q"][0.5] * sig} for n in self.names}
            out[h]["weights"] = {"dir": self.w_dir[h], "ret": self.w_q[h]}
        return out
