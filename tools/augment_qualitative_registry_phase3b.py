"""
Phase 3B additive registry augmentation - deliberately NOT the same code
path as `python tools/generate_qualitative_task_registry.py`'s full
pipeline.

Why this exists: re-running `generate_qualitative_task_registry.build_registry()`
end-to-end (re-parsing Navrist_Qualitative_Framework.md + re-introspecting
the CURRENT tools/qualitative_engine.py) was tried first and produced
unexplained drift in the pre-existing fields this phase is explicitly
forbidden from changing - `implemented` dropped from 341/364 to 291/364 and
`enabled` jumped from 136/364 to 235/364 on a full regeneration, which
would have silently flipped a large number of K-U tasks to `enabled=True`
(explicitly prohibited this phase) and un-implemented 50 previously-
implemented tasks. That drift is pre-existing engine/framework-file skew
unrelated to Phase 3B and out of this phase's scope to investigate or fix
(qualitative_engine.py is frozen for this phase).

This script instead loads the CURRENTLY CHECKED-IN `TASK_REGISTRY` as-is
(all 17 original fields byte-for-byte unchanged) and appends ONLY the 7
new Phase 3B contract fields, computed from each row's own already-present
`title`/`primary_source` text - zero re-parsing of the markdown spec, zero
re-introspection of the engine, so the original fields cannot drift.

Run:
    python tools/augment_qualitative_registry_phase3b.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from tools.qualitative_task_registry import TASK_REGISTRY as OLD_REGISTRY
from tools.generate_qualitative_task_registry import (
    render_python, _evidence_contract_for, _STATUS_RULES, _CONFIDENCE_RULES, _PROVENANCE_REQUIREMENTS,
)
from tools.qualitative_source_router import route_task

OUT_PY = ROOT / "tools" / "qualitative_task_registry.py"

_ORIGINAL_FIELDS = (
    "task_id", "raw_framework_id", "parent_id", "section", "title",
    "primary_source", "formula_or_matrix", "visualization_rule",
    "defined", "implemented", "persisted", "derived_rollup", "llm_dependent",
    "batch_enabled", "compute_fn", "ambiguous_note", "enabled",
)


def augment():
    augmented = []
    for old_row in OLD_REGISTRY:
        row = {k: old_row[k] for k in _ORIGINAL_FIELDS}  # exact copy, no re-derivation
        routing = route_task(row)
        required_evidence_types, extraction_requirements = _evidence_contract_for(row)
        row["preferred_sources"] = routing["preferred_sources"]
        row["fallback_sources"] = routing["fallback_sources"]
        row["required_evidence_types"] = required_evidence_types
        row["extraction_requirements"] = extraction_requirements
        row["status_rules"] = _STATUS_RULES
        row["confidence_rules"] = _CONFIDENCE_RULES
        row["provenance_requirements"] = _PROVENANCE_REQUIREMENTS
        augmented.append(row)
    return augmented


if __name__ == "__main__":
    augmented = augment()
    assert len(augmented) == len(OLD_REGISTRY), "row count changed - aborting, not writing"
    for old_row, new_row in zip(OLD_REGISTRY, augmented):
        for f in _ORIGINAL_FIELDS:
            assert old_row[f] == new_row[f], f"original field {f!r} drifted on {old_row['task_id']} - aborting"
    ambiguous = {r["task_id"]: r["ambiguous_note"] for r in OLD_REGISTRY if r["ambiguous_note"]}
    OUT_PY.write_text(render_python(augmented, ambiguous), encoding="utf-8")
    print(f"[augment_qualitative_registry_phase3b] wrote {len(augmented)} rows to {OUT_PY} "
          f"(0 original-field changes, 7 new fields added)")
