"""MODEL B - GRU sequence forecaster, pure numpy (PyTorch is blocked by this machine's Application
Control policy). A genuinely different family from Model A: it consumes the last L=24 bars as a
sequence of scale-free channels instead of engineered tabular features.

Per horizon h: a direction logit (BCE) + 7 quantiles of the vol-normalised return (pinball loss),
trained jointly (shared recurrent trunk, direct heads - no recursion, no predicted bar is ever fed back).
Early stopping uses the LAST sessions of the training window (never the calibration/test blocks).
Hyperparameters fixed a priori.
"""
import numpy as np

from . import config
from .models_base import CalibratedForecaster, QUANTS, sigma_of

L = config.SEQ_LEN
H = 32
CHANNELS = ["ret1_z", "body_z", "wup_z", "wdn_z", "range_z", "logrelvol", "relvol_known", "rsi", "ema21_z", "slot_sin", "slot_cos", "vwap_z"]
STATIC = ["log_rvrel", "session_progress", "trend_slope20", "m15_rsi", "h1_rsi", "ema9_21_z"]
CLIP = 6.0


def _sig(x):
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30, 30)))


def build_channels(M):
    """Per-row scale-free channels (N, C) and static vector (N, S). Only same-row (causal) columns."""
    s = M["rv36"].values.astype(float)
    s = np.where(s > 0, s, np.nan)
    rel = M["rel_vol"].values.astype(float)
    ch = np.column_stack([
        M["ret1"] / s, M["body"] / s, M["wick_up"] / s, M["wick_dn"] / s, M["range"] / s,
        np.log(np.where(rel > 0, rel, np.nan)), (~np.isnan(rel)).astype(float),
        M["rsi14"] / 100.0 - 0.5, M["ema21_dist"] / s, M["slot_sin"], M["slot_cos"], M["vwap_dist"] / s])
    ch = np.nan_to_num(np.clip(ch, -CLIP, CLIP), nan=0.0)        # unknown -> 0 *with* a known/unknown mask channel for volume
    st = np.column_stack([np.log(np.clip(M["rv36_rel"].values.astype(float), 0.05, 20)), M["session_progress"],
                          M["trend_slope20"] / 0.08, M["m15_rsi"] / 100 - 0.5, M["h1_rsi"] / 100 - 0.5, M["ema9_21"] / s])
    st = np.nan_to_num(np.clip(st, -CLIP, CLIP), nan=0.0)
    return ch.astype(np.float32), st.astype(np.float32)


class GRUNet:
    def __init__(self, c_in, s_in, n_out, hidden=H, seed=0):
        r = np.random.default_rng(seed)
        self.H = hidden
        g = lambda *sh, sc=0.15: (r.standard_normal(sh) * sc).astype(np.float32)
        self.p = {"Wx": g(c_in, 3 * hidden), "Uzr": g(hidden, 2 * hidden), "Un": g(hidden, hidden),
                  "b": np.zeros(3 * hidden, np.float32), "Wo": g(hidden + s_in, n_out, sc=0.1), "bo": np.zeros(n_out, np.float32)}

    def forward(self, X, S):
        p, Hd = self.p, self.H
        B, T, _ = X.shape
        h = np.zeros((B, Hd), np.float32)
        cache = {"X": X, "S": S, "h": [h], "z": [], "r": [], "n": []}
        A = X @ p["Wx"] + p["b"]                                    # (B,T,3H) all steps at once
        for t in range(T):
            a = A[:, t]
            zr = h @ p["Uzr"]
            z = _sig(a[:, :Hd] + zr[:, :Hd]); r = _sig(a[:, Hd:2 * Hd] + zr[:, Hd:])
            n = np.tanh(a[:, 2 * Hd:] + (r * h) @ p["Un"])
            h = (1 - z) * n + z * h
            cache["h"].append(h); cache["z"].append(z); cache["r"].append(r); cache["n"].append(n)
        feat = np.concatenate([h, S], axis=1)
        cache["feat"] = feat
        return feat @ p["Wo"] + p["bo"], cache

    def backward(self, dout, cache):
        p, Hd = self.p, self.H
        g = {k: np.zeros_like(v) for k, v in p.items()}
        feat = cache["feat"]
        g["Wo"] = feat.T @ dout; g["bo"] = dout.sum(0)
        dh = (dout @ p["Wo"].T)[:, :Hd]
        X = cache["X"]; T = X.shape[1]
        dA = np.zeros((X.shape[0], T, 3 * Hd), np.float32)
        for t in range(T - 1, -1, -1):
            h_prev, z, r, n = cache["h"][t], cache["z"][t], cache["r"][t], cache["n"][t]
            dn = dh * (1 - z); dz = dh * (h_prev - n); dh_prev = dh * z
            dn_pre = dn * (1 - n * n); dz_pre = dz * z * (1 - z)
            drh = dn_pre @ p["Un"].T
            g["Un"] += (r * h_prev).T @ dn_pre
            dr_pre = (drh * h_prev) * r * (1 - r); dh_prev = dh_prev + drh * r
            dg = np.concatenate([dz_pre, dr_pre], axis=1)
            g["Uzr"] += h_prev.T @ dg; dh_prev = dh_prev + dg @ p["Uzr"].T
            dA[:, t] = np.concatenate([dz_pre, dr_pre, dn_pre], axis=1)
            dh = dh_prev
        g["Wx"] = np.einsum("btc,btk->ck", X, dA); g["b"] = dA.sum((0, 1))
        return g


def loss_and_grad(net, X, S, yup, yq, nh, quants):
    """yup: (B,nh) in {0,1,nan}; yq: (B,nh) normalised returns (nan = no label)."""
    out, cache = net.forward(X, S)
    B = X.shape[0]
    dout = np.zeros_like(out)
    loss = 0.0
    nq = len(quants)
    for h in range(nh):
        m = ~np.isnan(yup[:, h])
        if m.any():
            p = _sig(out[m, h]); y = yup[m, h]
            loss += -np.mean(y * np.log(np.clip(p, 1e-6, 1)) + (1 - y) * np.log(np.clip(1 - p, 1e-6, 1)))
            dout[m, h] = (p - y) / m.sum()
        mq = ~np.isnan(yq[:, h])
        if mq.any():
            for j, q in enumerate(quants):
                col = nh + h * nq + j
                d = yq[mq, h] - out[mq, col]
                loss += np.mean(np.maximum(q * d, (q - 1) * d))
                dout[mq, col] = np.where(d > 0, -q, 1 - q) / mq.sum()
    return loss, net.backward(dout, cache), cache


class Adam:
    def __init__(self, params, lr=3e-3):
        self.lr, self.t = lr, 0
        self.m = {k: np.zeros_like(v) for k, v in params.items()}
        self.v = {k: np.zeros_like(v) for k, v in params.items()}

    def step(self, params, grads, clip=5.0):
        gn = np.sqrt(sum(float((g ** 2).sum()) for g in grads.values()))
        sc = min(1.0, clip / (gn + 1e-9))
        self.t += 1
        for k in params:
            g = grads[k] * sc
            self.m[k] = 0.9 * self.m[k] + 0.1 * g
            self.v[k] = 0.999 * self.v[k] + 0.001 * g * g
            mh, vh = self.m[k] / (1 - 0.9 ** self.t), self.v[k] / (1 - 0.999 ** self.t)
            params[k] -= (self.lr * mh / (np.sqrt(vh) + 1e-8)).astype(params[k].dtype)


class GRUForecaster(CalibratedForecaster):
    family = "gru_numpy"

    def __init__(self, feature_cols, horizons=(1, 2, 3, 4, 5), epochs=12, batch=512, stride=2, val_sessions=15, seed=3):
        super().__init__(feature_cols, horizons)
        self.epochs, self.batch, self.stride, self.val_sessions, self.seed = epochs, batch, stride, val_sessions, seed
        self.net = None
        self.attached = False

    def attach(self, M):
        """Precompute channels for the whole pooled matrix M (row labels must equal positions)."""
        self.ch, self.st = build_channels(M)
        sym, pos, seg = M["symbol"].values, M["seg_pos"].values, M["seg"].values
        ok = np.zeros(len(M), bool)
        ok[L - 1:] = (sym[L - 1:] == sym[:-(L - 1)]) & (seg[L - 1:] == seg[:-(L - 1)]) & ((pos[L - 1:] - pos[:-(L - 1)]) == L - 1)
        self.seq_ok = ok
        self.attached = True
        return self

    def _batch(self, rows):
        offs = np.arange(-(L - 1), 1)
        idx = rows[:, None] + offs[None, :]
        return self.ch[idx], self.st[rows]

    def _targets(self, df):
        sig = sigma_of(df)
        yup = np.column_stack([df[f"y_up_{h}"].values for h in self.horizons]).astype(np.float32)
        yq = np.column_stack([df[f"y_ret_{h}"].values / sig for h in self.horizons]).astype(np.float32)
        return yup, yq

    def fit_core(self, train):
        assert self.attached, "call attach(M) first"
        sess = np.array(sorted(train["session"].unique()))
        val_set = set(sess[-self.val_sessions:])
        tr = train[~train["session"].isin(val_set)]
        va = train[train["session"].isin(val_set)]
        tr = tr[self.seq_ok[tr.index.values]].iloc[:: self.stride]
        va = va[self.seq_ok[va.index.values]]
        nh = len(self.horizons)
        self.net = GRUNet(len(CHANNELS), len(STATIC), nh + nh * len(QUANTS), seed=self.seed)
        opt = Adam(self.net.p)
        rng = np.random.default_rng(self.seed)
        ytr_up, ytr_q = self._targets(tr); yva_up, yva_q = self._targets(va)
        rows_tr, rows_va = tr.index.values, va.index.values
        best, best_p, bad = np.inf, None, 0
        for ep in range(self.epochs):
            perm = rng.permutation(len(rows_tr))
            for i in range(0, len(perm), self.batch):
                b = perm[i:i + self.batch]
                X, S = self._batch(rows_tr[b])
                _, g, _ = loss_and_grad(self.net, X, S, ytr_up[b], ytr_q[b], nh, QUANTS)
                opt.step(self.net.p, g)
            vl = 0.0; nb = 0
            for i in range(0, len(rows_va), 2048):
                X, S = self._batch(rows_va[i:i + 2048])
                l, _, _ = loss_and_grad(self.net, X, S, yva_up[i:i + 2048], yva_q[i:i + 2048], nh, QUANTS)
                vl += l; nb += 1
            vl /= max(nb, 1)
            if vl < best - 1e-4:
                best, best_p, bad = vl, {k: v.copy() for k, v in self.net.p.items()}, 0
            else:
                bad += 1
                if bad >= 3:
                    break
        if best_p is not None:
            self.net.p = best_p
        self.best_val = best

    def _raw(self, df):
        nh, nq = len(self.horizons), len(QUANTS)
        rows = df.index.values
        ok = self.seq_ok[rows]
        out = np.full((len(rows), nh + nh * nq), np.nan, np.float32)
        good = np.where(ok)[0]
        for i in range(0, len(good), 4096):
            sel = good[i:i + 4096]
            X, S = self._batch(rows[sel])
            out[sel], _ = self.net.forward(X, S)
        res = {}
        for hi, h in enumerate(self.horizons):
            q = np.sort(np.vstack([out[:, nh + hi * nq + j] for j in range(nq)]), axis=0)
            res[h] = {"p_up": _sig(out[:, hi]), "q": {qq: q[j] for j, qq in enumerate(QUANTS)}}
        return res
