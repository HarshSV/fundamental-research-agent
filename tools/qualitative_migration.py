"""
Shared migration gate + execution-path resolver (Phase 3, final pass).

ONE place decides whether a registry task executes through the universal
`qualitative_task_engine.evaluate_task` or through its legacy
`qualitative_engine.compute_*` function - imported identically by
`tools.qualitative_batch_worker`, `tools.document_analysis_engine`'s manual-
upload orchestrator, and any future caller, so there is never a case where
the batch path and the manual-upload path disagree about which engine runs
a given task_id (spec's "no permanently duplicated API-vs-batch scoring
behaviour" requirement, extended to the manual-upload path too).
"""

from typing import Callable, Dict, Tuple


def is_migrated(task: Dict) -> bool:
    """A task is migrated when its Phase 3B evidence contract
    (`required_evidence_types`) is non-empty and entirely covered by a
    STRUCTURED primitive (governance/shareholding/insider scrapers, or the
    segment-concentration threshold rule) - i.e. every concept the task
    needs has either unambiguous structured data behind it, or a
    purpose-built interpreter preserving the task's own real analytical
    rule (spec section 5), not a generic keyword match standing in for a
    rule that was never actually encoded.

    Text-based narrative concepts (litigation, RPT, dividend policy, ...)
    are deliberately NOT included in this gate for BULK/BATCH cutover: the
    universal engine already produces an honest result for them (evidence
    found/absent/explicitly-negative, score=None - `qualitative_task_engine.
    _score_for` never fabricates a categorical/numeric conclusion from
    narrative text), but the LEGACY compute_fn for many of these tasks
    already produces a real evaluated 1-5 rubric score via its own
    task-specific scoring module. Silently replacing an existing real score
    with score=None at bulk-migration scale, without per-task verification
    against each task's actual formula_or_matrix (344 functions - not
    feasible to individually re-verify in one pass), would be a genuine
    information regression, not merely a stylistic one.

    A text concept (e.g. `auditor_qualification`) CAN have a real scorer
    wired in `qualitative_task_engine._score_for` (see its SA 700/705
    severity score, verified against C.6.3's own "unmodified = highest;
    qualifications reduce score by severity" formula text) without that
    concept being added to this gate - concept-level overlap alone is NOT
    sufficient evidence that a DIFFERENT task requiring the same evidence
    concept means the same thing. Confirmed real risk: `P.3.2` ("Audit
    Attention Score... based on materiality and recurrence") also requires
    `auditor_qualification`, but is a materially different rubric than
    C.6.3's opinion-severity rule - naively gating on concept membership
    would have auto-migrated P.3.2 onto a scorer verified for a DIFFERENT
    task's semantics, exactly the "replace precise logic with generic
    matching" failure mode this phase must avoid. Widening this gate to a
    text concept therefore requires an explicit, individually-verified
    task_id, not a concept-level rule - none are added yet; the structured-
    primitive-only gate below remains the safe default."""
    if task.get("derived_rollup") or task.get("llm_dependent"):
        return False

    # CASE A (spec decision tree): task_ids whose legacy compute_fn follows
    # the uniform AR-text-scorer template (tools/qualitative_legacy_adapters.py,
    # mechanically extracted from qualitative_engine.py's own source) - the
    # SAME fetch+score functions are called, so equivalence is guaranteed
    # by construction, not re-verified per task here.
    from tools.qualitative_legacy_adapters import (
        LEGACY_AR_TEXT_SCORER_ADAPTERS, LEGACY_TABLE_TEXT_ADAPTERS,
        LEGACY_PRIVATE_HELPER_ADAPTERS, LEGACY_RPT_EVIDENCE_ADAPTERS,
        LEGACY_GOVERNANCE_FILING_ADAPTERS,
    )
    if task["task_id"] in (set(LEGACY_AR_TEXT_SCORER_ADAPTERS) | set(LEGACY_TABLE_TEXT_ADAPTERS)
                            | set(LEGACY_PRIVATE_HELPER_ADAPTERS) | set(LEGACY_RPT_EVIDENCE_ADAPTERS)
                            | set(LEGACY_GOVERNANCE_FILING_ADAPTERS)):
        return True

    from tools.qualitative_evidence_extraction import STRUCTURED_PRIMITIVES
    scorable = set(STRUCTURED_PRIMITIVES)
    required = task.get("required_evidence_types") or []
    if not required:
        return False
    return all(concept in scorable for concept in required)


def resolve_execution_fn(task: Dict, legacy_resolver: Callable[[str], Callable]) -> Tuple[Callable, str]:
    """Returns (callable, path_label). `callable(symbol, name, force=False)
    -> payload_dict` in both cases - callers never need to know which path
    they got. `legacy_resolver(dotted_path) -> callable` is injected so
    this module doesn't need to duplicate either caller's own dotted-path
    resolution mechanism (`qualitative_batch_worker._resolve_compute_fn` /
    the manual pipeline's own import)."""
    if is_migrated(task):
        from tools.qualitative_task_engine import evaluate_task

        def _via_universal_engine(symbol, name, force=False):
            result = evaluate_task(symbol, name, fiscal_year=None, task_id=task["task_id"], force=force)
            payload = result.to_payload()
            payload["confidence_tag"] = result.status.value
            return payload

        return _via_universal_engine, "universal_engine"
    return legacy_resolver(task["compute_fn"]), "legacy_compute_fn"
