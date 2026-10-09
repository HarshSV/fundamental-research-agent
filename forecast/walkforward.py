"""Leakage-safe walk-forward splitting on SESSIONS (time-ordered, expanding train window).

For fold k:   train sessions < calibration sessions < test sessions   (strictly increasing dates)
- Labels never cross a session close (labels.py), so session-granular boundaries leave NO overlapping
  multi-horizon label between train/cal/test. An optional `embargo` of whole sessions is kept as extra margin.
- Everything fitted on a fold (model, probability calibration, conformal margins, baseline sign
  statistics, normalisation) uses the train/cal sessions only. The test block is only ever predicted.
- No shuffling. Folds are disjoint in their test blocks and march forward in time.
"""
import numpy as np


def make_folds(sessions, min_train=150, cal=20, test=20, embargo=1, max_folds=None):
    s = sorted(set(sessions))
    folds, start = [], min_train
    while start + embargo + cal + embargo + test <= len(s):
        tr = s[:start]
        ca = s[start + embargo: start + embargo + cal]
        te = s[start + embargo + cal + embargo: start + embargo + cal + embargo + test]
        folds.append({"train": tr, "cal": ca, "test": te})
        start += test
    return folds[-max_folds:] if max_folds else folds


def assert_no_overlap(fold):
    tr, ca, te = fold["train"], fold["cal"], fold["test"]
    assert max(tr) < min(ca) and max(ca) < min(te), "fold windows overlap in time"
    assert not (set(tr) & set(ca)) and not (set(ca) & set(te)) and not (set(tr) & set(te))
