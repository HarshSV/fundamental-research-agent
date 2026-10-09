"""Out-of-sample evaluation of direct multi-horizon forecasts.

`oos` is a wide frame (one row per prediction time t, test blocks only) with columns
  symbol, session, slot, regime, rv36, y_ret_h, y_up_h and, per model prefix m:
  {m}_ret_h (point forecast of ln(C_{t+h}/C_t)), {m}_pup_h, {m}_lo{50,80,95}_h, {m}_hi{50,80,95}_h
"""
import numpy as np
import pandas as pd

LEVELS = (50, 80, 95)


def _col(oos, name):
    return oos[name].values.astype(float) if name in oos else None


def score(oos, m, h, sig_col="rv36"):
    y, up, sig = oos[f"y_ret_{h}"].values, oos[f"y_up_{h}"].values, oos[sig_col].values
    ret, p = _col(oos, f"{m}_ret_{h}"), _col(oos, f"{m}_pup_{h}")
    ok = ~np.isnan(y) & ~np.isnan(ret) & (sig > 0)
    r = {"model": m, "h": h, "n": int(ok.sum())}
    if ok.sum() == 0:
        return r
    err = ret[ok] - y[ok]
    r.update(mae_bps=float(np.mean(np.abs(err)) * 1e4), rmse_bps=float(np.sqrt(np.mean(err ** 2)) * 1e4),
             nmae=float(np.mean(np.abs(err) / sig[ok])), skill_r2=float(1 - np.sum(err ** 2) / np.sum((y[ok] - 0) ** 2)))
    d = ok & ~np.isnan(up) & ~np.isnan(p)
    if d.sum():
        pred = (p[d] > 0.5).astype(float)
        yy = up[d]
        tp = np.sum((pred == 1) & (yy == 1)); fp = np.sum((pred == 1) & (yy == 0))
        fn = np.sum((pred == 0) & (yy == 1)); tn = np.sum((pred == 0) & (yy == 0))
        rec_up = tp / max(tp + fn, 1); rec_dn = tn / max(tn + fp, 1)
        pc = np.clip(p[d], 1e-6, 1 - 1e-6)
        r.update(acc=float((pred == yy).mean()), bal_acc=float((rec_up + rec_dn) / 2),
                 prec_up=float(tp / max(tp + fp, 1)), rec_up=float(rec_up),
                 brier=float(np.mean((p[d] - yy) ** 2)), logloss=float(-np.mean(yy * np.log(pc) + (1 - yy) * np.log(1 - pc))),
                 base_rate_up=float(yy.mean()), n_dir=int(d.sum()))
    for lv in LEVELS:
        lo, hi = _col(oos, f"{m}_lo{lv}_{h}"), _col(oos, f"{m}_hi{lv}_{h}")
        if lo is None:
            continue
        k = ok & ~np.isnan(lo) & ~np.isnan(hi)
        if k.sum():
            r[f"cov{lv}"] = float(((y[k] >= lo[k]) & (y[k] <= hi[k])).mean())
            r[f"width{lv}_bps"] = float(np.mean(hi[k] - lo[k]) * 1e4)
    return r


def report(oos, models, horizons=(1, 2, 3, 4, 5), sig_col="rv36"):
    return pd.DataFrame([score(oos, m, h, sig_col) for m in models for h in horizons])


def breakdown(oos, m, h, by):
    rows = []
    for key, g in oos.groupby(by):
        s = score(g.reset_index(drop=True), m, h)
        s[by] = key
        rows.append(s)
    return pd.DataFrame(rows)


def winkler(lo, hi, y, alpha):
    """Winkler/interval score (lower is better): width + (2/alpha) * miss distance. Proper for intervals."""
    return (hi - lo) + (2.0 / alpha) * (np.maximum(lo - y, 0) + np.maximum(y - hi, 0))


def paired_bootstrap(oos, m, base, h, metric="abs", B=1000, seed=0, sig_col="rv36", block_col=None):
    """Session-block bootstrap of (model - baseline) for a per-row loss. Negative = model better.
    metric: 'abs' (|ret error| / sigma), 'brier', 'err_dir' (misclassification)."""
    y, up, sig = oos[f"y_ret_{h}"].values, oos[f"y_up_{h}"].values, oos[sig_col].values
    a, b = _col(oos, f"{m}_ret_{h}"), _col(oos, f"{base}_ret_{h}")
    pa, pb = _col(oos, f"{m}_pup_{h}"), _col(oos, f"{base}_pup_{h}")
    if metric == "abs":
        ok = ~np.isnan(y) & ~np.isnan(a) & ~np.isnan(b) & (sig > 0)
        la, lb = np.abs(a - y) / sig, np.abs(b - y) / sig
    elif metric == "winkler80":
        lo_a, hi_a = _col(oos, f"{m}_lo80_{h}"), _col(oos, f"{m}_hi80_{h}")
        lo_b, hi_b = _col(oos, f"{base}_lo80_{h}"), _col(oos, f"{base}_hi80_{h}")
        ok = ~np.isnan(y) & ~np.isnan(lo_a) & ~np.isnan(lo_b) & (sig > 0)
        la, lb = winkler(lo_a, hi_a, y, 0.2) / sig, winkler(lo_b, hi_b, y, 0.2) / sig
    elif metric == "brier":
        ok = ~np.isnan(up) & ~np.isnan(pa) & ~np.isnan(pb)
        la, lb = (pa - up) ** 2, (pb - up) ** 2
    else:
        ok = ~np.isnan(up) & ~np.isnan(pa) & ~np.isnan(pb)
        la, lb = ((pa > 0.5) != (up == 1)).astype(float), ((pb > 0.5) != (up == 1)).astype(float)
    blocks = oos[block_col] if block_col else (oos["symbol"] + "|" + oos["session"])     # daily: month blocks across ALL symbols
    df = pd.DataFrame({"s": blocks.values[ok], "d": (la - lb)[ok], "a": la[ok], "b": lb[ok]})
    g = df.groupby("s").agg(d=("d", "sum"), a=("a", "sum"), b=("b", "sum"), n=("d", "size"))
    d, n = g["d"].values, g["n"].values
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(g), size=(B, len(g)))
    boot = d[idx].sum(1) / n[idx].sum(1)
    return {"model": m, "baseline": base, "h": h, "metric": metric, "mean_a": float(g["a"].sum() / n.sum()),
            "mean_b": float(g["b"].sum() / n.sum()), "diff": float(d.sum() / n.sum()),
            "ci_lo": float(np.percentile(boot, 2.5)), "ci_hi": float(np.percentile(boot, 97.5)),
            "p_better": float((boot < 0).mean()), "n": int(n.sum()), "n_blocks": int(len(g))}
