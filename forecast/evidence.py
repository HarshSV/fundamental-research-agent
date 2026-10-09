"""Evidence layer: which features supported / opposed the direction call (LightGBM TreeSHAP).
SHAP attributes the MODEL's output to its inputs - it does not prove causality and is used only as
a confidence/explanation signal."""
import numpy as np


def shap_evidence(gbm, df, h, top=5):
    """Returns (agree, rows): agree[i] in [0,1] = share of |SHAP| mass among the 10 largest features
    that pushes toward the side the model predicts; rows[i] = {'for': [(feature, shap)], 'against': [...]}"""
    contrib = gbm.shap(df, h)                      # (n, n_features + 1) log-odds contributions
    c = contrib[:, :-1]
    names = np.array(gbm.cols)
    pred_up = (contrib.sum(1) > 0)
    sign = np.where(pred_up, 1.0, -1.0)[:, None]
    signed = c * sign                              # positive = supports the predicted side
    order = np.argsort(-np.abs(c), axis=1)[:, :10]
    top_signed = np.take_along_axis(signed, order, axis=1)
    mass = np.abs(top_signed).sum(1)
    agree = np.where(mass > 0, np.clip(top_signed, 0, None).sum(1) / np.where(mass > 0, mass, 1), 0.5)
    rows = []
    for i in range(len(c)):
        o = np.argsort(-signed[i])
        sup = [(str(names[j]), float(signed[i, j])) for j in o[:top] if signed[i, j] > 0]
        opp = [(str(names[j]), float(signed[i, j])) for j in o[::-1][:top] if signed[i, j] < 0]
        rows.append({"for": sup, "against": opp})
    return agree, rows
