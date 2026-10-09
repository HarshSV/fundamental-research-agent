"""GRU backprop correctness: analytic gradients must match numerical gradients."""
import os, sys
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from forecast.models_gru import GRUNet, loss_and_grad  # noqa: E402
from forecast.models_base import QUANTS  # noqa: E402


def test_gru_gradients_match_numerical():
    rng = np.random.default_rng(0)
    B, T, C, S, nh = 6, 5, 4, 3, 2
    net = GRUNet(C, S, nh + nh * len(QUANTS), hidden=5, seed=1)
    for k in net.p:
        net.p[k] = net.p[k].astype(np.float64)
    X = rng.normal(size=(B, T, C)); St = rng.normal(size=(B, S))
    yup = rng.integers(0, 2, size=(B, nh)).astype(float); yq = rng.normal(size=(B, nh))
    yup[0, 0] = np.nan; yq[1, 1] = np.nan
    _, grads, _ = loss_and_grad(net, X, St, yup, yq, nh, QUANTS)
    eps = 1e-5
    worst = 0.0
    for k, v in net.p.items():
        flat = v.reshape(-1)
        for i in rng.choice(flat.size, size=min(6, flat.size), replace=False):
            old = flat[i]
            flat[i] = old + eps; lp, _, _ = loss_and_grad(net, X, St, yup, yq, nh, QUANTS)
            flat[i] = old - eps; lm, _, _ = loss_and_grad(net, X, St, yup, yq, nh, QUANTS)
            flat[i] = old
            num = (lp - lm) / (2 * eps)
            ana = grads[k].reshape(-1)[i]
            worst = max(worst, abs(num - ana) / max(1e-6, abs(num) + abs(ana)))
    assert worst < 1e-3, f"gradient mismatch {worst}"
