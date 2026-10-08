"""Presentation layer for the 68-ratio list: user-facing labels and the 'first 13' order.

Nothing here touches a value, status, formula, input, provenance or internal id. A stored row keeps its `ratio_key` and
`sr_no`; only `label` / `display_priority` are (re)applied from the registry at read time, and the few place-names a saved
breakdown/metadata text may contain are rewritten to the current labels so an older saved row never shows a name the
dashboard no longer uses.
"""
from tools.fundamental_ratio_registry import BY_RATIO_KEY, LEGACY_LABELS

# keys of a row's `_metadata` blob whose strings are plain prose (reasons / formulas / parent names). Input NAMES (statement
# line items such as an 'Effective Tax Rate' component of ROIC) are deliberately not in this list.
_SKIP_KEYS = {"inputs", "tests", "variables", "facts"}


def _swap(text):
    if not isinstance(text, str):
        return text
    for old, new in LEGACY_LABELS.items():
        if old in text:
            text = text.replace(old, new)
    return text


def _walk(obj, skip=False):
    if isinstance(obj, str):
        return _swap(obj)
    if isinstance(obj, list):
        return [_walk(x, skip) for x in obj]
    if isinstance(obj, dict):
        return {k: (v if k in _SKIP_KEYS else _walk(v, skip)) for k, v in obj.items()}
    return obj


def apply_display_names(row):
    """Returns a copy of `row` carrying the registry's current `label` and `display_priority` (None for the other 55)."""
    spec = BY_RATIO_KEY.get(row.get("ratio_key"))
    out = dict(row)
    if spec is None:
        out["display_priority"] = None
        return out
    out["label"] = spec["label"]
    out["display_priority"] = spec.get("display_priority")
    inputs = []
    for i in row.get("inputs") or []:
        if isinstance(i, dict) and i.get("name") == "_metadata":
            i = _walk(i)
        inputs.append(i)
    if inputs:
        out["inputs"] = inputs
    return out
