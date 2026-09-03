"""
Generator for `tools/qualitative_legacy_adapters.py`'s `LEGACY_AR_TEXT_SCORER_ADAPTERS`
table - mechanically scans `tools/qualitative_engine.py`'s own source for the
uniform "fetch AR text by anchors -> call one scoring-module function"
template every one of these compute_* functions follows, and emits the
(task_id -> module/function/anchors/cache_prefix) mapping as a Python
literal. Never hand-maintained - re-run when qualitative_engine.py's
compute_fn bodies change:

    python tools/extract_legacy_adapter_mapping.py

This only prints the generated dict literal to stdout for review/paste
into `qualitative_legacy_adapters.py` - it does NOT write that file
directly, so a human always reviews a diff before the adapter table
changes (same review discipline as the qualitative_task_registry.py
generator).
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ENGINE_PY = ROOT / "tools" / "qualitative_engine.py"

FUNC_RE = re.compile(r'^def (compute_[a-zA-Z0-9_]+)\(', re.MULTILINE)
TEMPLATE_RE = re.compile(
    r'from tools\.annual_report_financials import _fetch_ar_evidence_excerpts\s*\n'
    r'\s*from tools\.(\w+_scoring) import (\w+)\s*\n'
    r'\s*evidence = _fetch_ar_evidence_excerpts\(\s*\n?'
    r'\s*sym, name, (_?\w+ANCHORS), "([^"]+)"',
)
SUBPOINT_RE = re.compile(r'subpoint_id\s*=\s*"([A-Z][^"]*)"')


def extract():
    src = ENGINE_PY.read_text(encoding="utf-8")
    defs = list(FUNC_RE.finditer(src))
    matches = {}
    for i, m in enumerate(defs):
        start = m.end()
        end = defs[i + 1].start() if i + 1 < len(defs) else len(src)
        body = src[start:end]
        pm = TEMPLATE_RE.search(body)
        sm = SUBPOINT_RE.search(body)
        if pm and sm:
            module, scorefn, anchors_var, cache_prefix = pm.groups()
            matches[sm.group(1)] = {
                "compute_fn": m.group(1), "module": module, "scorefn": scorefn,
                "anchors_var": anchors_var, "cache_prefix": cache_prefix,
            }
    return matches


def render(matches):
    lines = ["LEGACY_AR_TEXT_SCORER_ADAPTERS = {"]
    for task_id in sorted(matches.keys()):
        v = matches[task_id]
        lines.append(
            f'    {task_id!r}: {{"module": {v["module"]!r}, "scorefn": {v["scorefn"]!r}, '
            f'"anchors_var": {v["anchors_var"]!r}, "cache_prefix": {v["cache_prefix"]!r}}},'
        )
    lines.append("}")
    return "\n".join(lines)


if __name__ == "__main__":
    matches = extract()
    print(f"# Found {len(matches)} task_ids matching the uniform AR-text-scorer template")
    print(render(matches))
