"""
One-time (re-runnable) generator for tools/qualitative_task_registry.py.

Phase 1B - builds the static A-U qualitative task registry by:
  1. Parsing Navrist_Qualitative_Framework.md's fixed-width table (column
     offsets measured directly off its own header/separator row: ID [2:19],
     Title [20:43], Primary Source [44:128], Formula/Matrix [129:171],
     Visualization [172:195] - verified against
     "  ID                Title                   Primary Source /..." and
     its "----- ----- -----" separator line).
  2. Introspecting tools/qualitative_engine.py's actual source text (regex
     over source, not a live import - importing would pull in every scoring
     dependency just to build a registry) to find which canonical IDs have
     a real compute_* handler, and which of those persist to
     qualitative_values via write_qualitative() vs. are derived rollups
     that only combine already-persisted children.

Run manually when the framework workbook or the engine's sub-point set
changes:
    python tools/generate_qualitative_task_registry.py

This does NOT execute at runtime/import time anywhere else in the app  - 
tools/qualitative_task_registry.py is the reviewed, checked-in output that
the batch worker/API actually import.
"""

import io
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FRAMEWORK_MD = ROOT / "Navrist_Qualitative_Framework.md"
ENGINE_PY = ROOT / "tools" / "qualitative_engine.py"
OUT_PY = ROOT / "tools" / "qualitative_task_registry.py"

# Phase 3B additive extension - the evidence/source-routing/status/
# confidence contract layered on top of the existing 17 fields. Imported
# here (not duplicated) so the registry and the modules that define these
# concepts can never drift.
from tools.qualitative_source_router import route_task
from tools.qualitative_evidence_extraction import TERMINOLOGY_ALIASES, STRUCTURED_PRIMITIVES
from tools.qualitative_evidence import EvidenceStatus, ConfidenceTier

# Uniform, architecture-wide contract objects - identical for every task by
# design (these rules are properties of the qualitative ENGINE, not of any
# individual task), so they are computed once here and repeated verbatim
# into every row rather than fabricated per task.
_STATUS_RULES = {
    "vocabulary": [s.value for s in EvidenceStatus],
    "rule": "NOT_DISCLOSED (source searched, genuinely absent) is never the same as "
            "VERIFIED_ABSENT (source explicitly states the negative). Absence of evidence "
            "is not itself negative evidence unless a task's own formula_or_matrix says so.",
}
_CONFIDENCE_RULES = {
    "tiers": [t.value for t in ConfidenceTier],
    "rule": "Confidence measures evidence STRENGTH, independent of the resulting score/status - "
            "a weak/negative finding can carry HIGH confidence, and an unresolved/unknown finding "
            "always carries LOW or UNKNOWN confidence, never inferred from the score value.",
}
_PROVENANCE_REQUIREMENTS = [
    "source_document", "source_document_type", "page_number", "section", "heading",
    "extracted_text", "evidence_date", "extraction_method", "extraction_version",
]


def _evidence_contract_for(task_row):
    """Derives `required_evidence_types`/`extraction_requirements` from the
    task's OWN title/primary_source text via the shared terminology-alias
    table - generic keyword matching, never a per-task hardcoded list.
    Returns explicit empty structures (not fabricated guesses) when no
    known concept/primitive matches yet - honest about Phase 3B's actual
    coverage (13 text concepts + 3 structured primitives), not a claim that
    every one of 364 tasks has a working extractor."""
    haystack = " ".join(filter(None, [task_row.get("title"), task_row.get("primary_source")]))
    required_evidence_types = []
    seen = set()
    for concept in TERMINOLOGY_ALIASES:
        if concept in seen:
            continue
        phrases = TERMINOLOGY_ALIASES[concept]
        if any(p in haystack.lower() for p in phrases):
            required_evidence_types.append(concept)
            seen.add(concept)
    # Structured primitives keyed by concept name too (board/committee/
    # attendance/ownership/pledge/insider) - same haystack, same generic
    # substring approach, just against a smaller keyword set inferred from
    # the primitive names themselves.
    structured_keywords = {
        "board_composition": ["board composition", "board of directors"],
        "committee_composition": ["committee composition", "committee"],
        "director_independence": ["independent director"],
        "attendance": ["attendance"],
        "insider_activity": ["insider trading", "insider activity", "regulation 7"],
        "segment_concentration_threshold": [
            "single product", "portfolio/diversified", "segment count classification",
        ],
    }
    for primitive, phrases in structured_keywords.items():
        if primitive not in required_evidence_types and any(p in haystack.lower() for p in phrases):
            required_evidence_types.append(primitive)

    # A precise structured primitive supersedes the generic text concept
    # covering the same topic for THIS task - e.g. once
    # `segment_concentration_threshold` (the real 90%-threshold rule) is
    # matched, the plain `segment_concentration` text keyword match is
    # redundant and would otherwise block migration eligibility (spec
    # section 5 - don't let an imprecise generic match stand in for the
    # real analytical rule once it exists).
    _SUPERSEDES = {"segment_concentration_threshold": "segment_concentration"}
    for structured_concept, generic_concept in _SUPERSEDES.items():
        if structured_concept in required_evidence_types and generic_concept in required_evidence_types:
            required_evidence_types.remove(generic_concept)

    extraction_requirements = {}
    for concept in required_evidence_types:
        if concept in STRUCTURED_PRIMITIVES:
            extraction_requirements[concept] = {
                "primitive": STRUCTURED_PRIMITIVES[concept], "kind": "structured",
            }
        elif concept in TERMINOLOGY_ALIASES:
            extraction_requirements[concept] = {
                "primitive": "extract_text_based_evidence", "kind": "text", "concept": concept,
            }
    return required_evidence_types, extraction_requirements

# Column offsets measured directly from the framework file's own header row
# ("  ID                Title                   Primary Source / ...") and
# its "-----" separator line - see module docstring.
COL_ID = (2, 19)
COL_TITLE = (20, 43)
COL_SOURCE = (44, 128)
COL_FORMULA = (129, 171)
COL_VIZ = (172, 195)

# A "raw" ID token this table uses (framework convention, no dot after the
# leading letter): A. numeric section uses bare numbers/letters (1, 1A, 1B);
# B-U sections use LETTER+DIGIT(.DIGIT)*[letter]? (e.g. B1, B1.1, E1, E1.1).
RAW_ID_RE = re.compile(r"^(?:\d+[A-Z]?|[A-Z]\d*(?:\.\d+)*[a-z]?)$")
SECTION_HEADER_RE = re.compile(r"^([A-Z])\.\s")


def _col(line, span):
    start, end = span
    return line[start:end].rstrip() if len(line) > start else ""


def parse_framework(path):
    """Returns a list of raw row dicts in document order:
    {"raw_id": "E1.1", "title": "...", "source": "...", "formula": "...",
     "viz": "...", "section_letter": "E", "is_section_header": False}
    Section header rows (e.g. "E. Business integrity & 'leakage' signals",
    wrapped across several lines) are collapsed into one row with
    raw_id=None and is_section_header=True.
    """
    with io.open(path, encoding="utf-8") as f:
        lines = [l.rstrip("\n") for l in f]

    rows = []
    current = None  # dict being accumulated, or None
    in_section_header = False

    def flush():
        nonlocal current
        if current is not None:
            for k in ("title", "source", "formula", "viz"):
                current[k] = " ".join(current[k].split())
            rows.append(current)
        current = None

    for line in lines:
        if not line.strip():
            # Section-header rows are NOT blank-terminated the same way
            # (their title keeps wrapping across the section-title lines
            # with no ID re-stated) - but in practice a blank line also
            # separates section headers from the first task row, so this
            # is safe to treat uniformly as "end of current record".
            flush()
            in_section_header = False
            continue

        idcol = _col(line, COL_ID)
        titlecol = _col(line, COL_TITLE)
        sourcecol = _col(line, COL_SOURCE)
        formulacol = _col(line, COL_FORMULA)
        vizcol = _col(line, COL_VIZ)

        header_m = SECTION_HEADER_RE.match(idcol + " ")
        if idcol and header_m and not RAW_ID_RE.match(idcol):
            # e.g. idcol == "A." (from "A. Company") - section header start.
            flush()
            current = {
                "raw_id": None, "title": (idcol + " " + titlecol).strip(),
                "source": "", "formula": "", "viz": "",
                "section_letter": header_m.group(1), "is_section_header": True,
            }
            in_section_header = True
            continue

        if idcol and RAW_ID_RE.match(idcol) and not in_section_header:
            flush()
            current = {
                "raw_id": idcol, "title": titlecol, "source": sourcecol,
                "formula": formulacol, "viz": vizcol,
                "section_letter": None, "is_section_header": False,
            }
            continue

        # Continuation line of whatever record is currently open.
        if current is not None:
            if in_section_header:
                current["title"] += " " + (idcol + " " + titlecol).strip()
            else:
                current["title"] += " " + titlecol
                current["source"] += " " + sourcecol
                current["formula"] += " " + formulacol
                current["viz"] += " " + vizcol
        # else: stray line before any record opened (e.g. table caption) - skip.

    flush()
    return rows


def normalize_id(raw_id, section_letter):
    """Framework convention (E1, E1.1, 4A, 4B, 1A) -> canonical DB/engine
    convention (E.1, E.1.1, A.4.A ... ). Only touches the B-U
    letter-prefixed convention that the engine actually uses; the bare
    numeric IDs under section A (1, 1A, 2, 2A ...) are mapped onto the
    A.<n>[.<letter>] scheme the engine already uses for A (confirmed live:
    A.1, A.1.2, A.2, A.2.A, A.4, A.5, A.6 exist as real subpoint_ids).
    """
    if raw_id is None:
        return None
    m = re.match(r"^(\d+)([A-Z])?$", raw_id)
    if m:
        num, letter = m.groups()
        return f"A.{num}.{letter}" if letter else f"A.{num}"
    m = re.match(r"^([A-Z])(\d+)((?:\.\d+)*)([a-z])?$", raw_id)
    if m:
        letter, num, rest, suffix = m.groups()
        canon = f"{letter}.{num}"
        if rest:
            canon += rest
        if suffix:
            canon += suffix
        return canon
    return raw_id  # unrecognized shape - surfaced by validation, not silently dropped


def parent_of(canonical_id):
    if canonical_id is None:
        return None
    parts = canonical_id.split(".")
    if len(parts) <= 2:
        return None  # e.g. "E.1" has no parent (it *is* the section-level task)
    return ".".join(parts[:-1])


# --- Engine introspection -----------------------------------------------

# Real persisted leaf pattern: `    subpoint_id = "X.Y"` (a function-local
# variable later passed to write_qualitative(sym, subpoint_id, ...)).
PERSISTED_ASSIGN_RE = re.compile(r'^\s+subpoint_id\s*=\s*"([A-Z][^"]*)"', re.MULTILINE)

# Derived-rollup pattern: `"subpoint_id": "X.Y"` as a dict key inside a
# payload literal that combines already-computed children - these do NOT
# themselves call write_qualitative() (except C.1, flagged separately below).
DERIVED_DICT_RE = re.compile(r'"subpoint_id":\s*"([A-Z][^"]*)"', re.MULTILINE)

# Shared-helper leaf pattern (e.g. C.5.2/C.5.3 routed through
# _compute_committee_subpoint(sym, "C.5.2", ...) instead of a local
# `subpoint_id = ...` assignment).
HELPER_CALL_RE = re.compile(r'_compute_committee_subpoint\(\s*\n?\s*sym,\s*"([A-Z][^"]*)"')

FUNC_DEF_RE = re.compile(r'^def (compute_[a-zA-Z0-9_]+)\(', re.MULTILINE)

# A task is LLM-dependent if its owning function's body references the
# shared LLM call chokepoint (tools/groq_client.py:groq_chat, called via
# qualitative_engine.py's own _llm_json wrapper). groq_chat currently
# raises immediately (LLM calls disabled app-wide by explicit prior
# instruction - see groq_client.py's own docstring), so any task detected
# here is structurally implemented/persisted but NOT actually functional
# today. This is a mechanical, regeneratable signal - never a hand-
# maintained ID list - so it stays correct as new sections are built.
LLM_CALL_RE = re.compile(r'_llm_json\(|groq_chat\(')
_CALL_NAME_RE = re.compile(r'\b([a-zA-Z_][a-zA-Z0-9_]*)\(')


def _build_tools_call_graph():
    """Scans every tools/*.py module (not just qualitative_engine.py) so an
    LLM dependency reached through a helper module - e.g. A.2's
    compute_a2_competitive_moat -> tools.moat_peer_scoring.
    build_moat_rating_breakdown -> score_qualitative_evidence -> _llm_json,
    a 2-hop chain entirely outside qualitative_engine.py - is still
    detected. Returns {function_name: body_text} across all modules
    (functions are matched by bare name, not module-qualified - a small
    false-positive risk on name collisions across modules, accepted as a
    conservative safety net rather than a full import-resolution AST walk)
    plus the set of function names whose OWN body directly touches the LLM
    chokepoint."""
    import glob
    bodies = {}
    for path in glob.glob(str(ROOT / "tools" / "*.py")):
        with io.open(path, encoding="utf-8") as f:
            src = f.read()
        defs = list(re.finditer(r'^def ([a-zA-Z_][a-zA-Z0-9_]*)\(', src, re.MULTILINE))
        for i, m in enumerate(defs):
            start = m.end()
            end = defs[i + 1].start() if i + 1 < len(defs) else len(src)
            bodies.setdefault(m.group(1), src[start:end])
    direct_llm = {name for name, body in bodies.items() if LLM_CALL_RE.search(body)}
    return bodies, direct_llm


def _reaches_llm(body, bodies, direct_llm, max_depth=4):
    """BFS over bare function-name calls within `body`, up to max_depth
    hops, checking whether any reachable function's own body directly
    calls _llm_json/groq_chat."""
    seen = set()
    frontier = set(_CALL_NAME_RE.findall(body)) & set(bodies)
    depth = 0
    while frontier and depth < max_depth:
        if frontier & direct_llm:
            return True
        seen |= frontier
        next_frontier = set()
        for fn in frontier:
            next_frontier |= set(_CALL_NAME_RE.findall(bodies[fn])) & set(bodies)
        frontier = next_frontier - seen
        depth += 1
    return bool(frontier & direct_llm)


def introspect_engine(path):
    """Returns (persisted_ids: set[str], derived_ids: set[str],
    id_to_function: dict[str, str], ambiguous: dict[str, str],
    llm_dependent_ids: set[str])."""
    with io.open(path, encoding="utf-8") as f:
        src = f.read()

    persisted = set(m.group(1) for m in PERSISTED_ASSIGN_RE.finditer(src))
    persisted |= set(m.group(1) for m in HELPER_CALL_RE.finditer(src))
    derived = set(m.group(1) for m in DERIVED_DICT_RE.finditer(src)) - persisted

    # C.1's aggregate function contains BOTH a "subpoint_id": "C.1" dict
    # literal AND a literal write_qualitative(sym, "C.1", payload,
    # "NOT_FOUND") call on one failure branch - genuinely ambiguous
    # (partially persisted, not on every path). Do not silently resolve
    # this either way; surface it.
    ambiguous = {}
    if re.search(r'write_qualitative\(\s*sym,\s*"C\.1"', src):
        ambiguous["C.1"] = (
            "compute_c1_promoter_shareholding calls write_qualitative(sym, 'C.1', ...) "
            "on a NOT_FOUND branch only, but is otherwise a derived rollup like B.1-F.1 "
            "that does not persist on its normal path. Treated as derived (not "
            "batch-enabled) for Phase 1B; flag for manual review."
        )

    # Map each top-level `def compute_X(...)` to the subpoint_id(s) that
    # appear textually within its body (up to the next top-level def).
    tools_bodies, tools_direct_llm = _build_tools_call_graph()

    defs = list(FUNC_DEF_RE.finditer(src))
    id_to_function = {}
    llm_dependent = set()
    for i, m in enumerate(defs):
        start = m.end()
        end = defs[i + 1].start() if i + 1 < len(defs) else len(src)
        body = src[start:end]
        ids_here = set(mm.group(1) for mm in PERSISTED_ASSIGN_RE.finditer("def x(" + body))
        ids_here |= set(mm.group(1) for mm in HELPER_CALL_RE.finditer(body))
        ids_here |= set(mm.group(1) for mm in DERIVED_DICT_RE.finditer(body))
        for sid in ids_here:
            id_to_function.setdefault(sid, m.group(1))
        # Direct same-function check first (cheap, catches qualitative_
        # engine.py's own _llm_json calls) OR the cross-module transitive
        # BFS (catches e.g. A.2's 2-hop chain through moat_peer_scoring.py).
        if LLM_CALL_RE.search(body) or _reaches_llm(body, tools_bodies, tools_direct_llm):
            llm_dependent.update(ids_here)

    return persisted, derived, id_to_function, ambiguous, llm_dependent


# --- Build + validate ------------------------------------------------------

def build_registry():
    raw_rows = parse_framework(FRAMEWORK_MD)
    persisted_ids, derived_ids, id_to_function, ambiguous, llm_dependent_ids = introspect_engine(ENGINE_PY)

    tasks = []
    current_section = None
    seen_canonical = {}
    normalization_collisions = []

    for row in raw_rows:
        if row["is_section_header"]:
            current_section = row["section_letter"]
            continue
        canonical = normalize_id(row["raw_id"], current_section)
        # "defined" = has at least a title. Parent/section-level rows (e.g.
        # A.1, B.2, E.1 itself) legitimately carry only a title - source/
        # formula/viz live on their subtasks - so requiring all four fields
        # would misclassify normal parents as spec gaps. A genuinely blank
        # row (no title at all, e.g. B.1, E.1.2) has title == "".
        defined = bool(row["title"].strip())
        has_any_field = bool(row["title"].strip() or row["source"].strip() or row["formula"].strip())
        implemented = canonical in id_to_function
        persisted = canonical in persisted_ids
        derived = canonical in derived_ids
        llm_dependent = canonical in llm_dependent_ids
        # batch_enabled is the single eligibility flag the batch worker
        # trusts directly - defined ∧ implemented ∧ persisted ∧ ¬derived ∧
        # ¬llm_dependent. Never a hand-maintained ID list: llm_dependent is
        # itself mechanically detected (LLM_CALL_RE) above, so this stays
        # correct as new sections are implemented or the LLM is re-enabled.
        batch_enabled = implemented and persisted and not derived and not llm_dependent

        if canonical in seen_canonical:
            normalization_collisions.append((canonical, seen_canonical[canonical], row["raw_id"]))
        else:
            seen_canonical[canonical] = row["raw_id"]

        task_row = {
            "task_id": canonical,
            "raw_framework_id": row["raw_id"],
            "parent_id": parent_of(canonical),
            "section": current_section,
            "title": row["title"].strip() or None,
            "primary_source": row["source"].strip() or None,
            "formula_or_matrix": row["formula"].strip() or None,
            "visualization_rule": row["viz"].strip() or None,
            "defined": defined,
            "implemented": implemented,
            "persisted": persisted,
            "derived_rollup": derived,
            "llm_dependent": llm_dependent,
            "batch_enabled": batch_enabled,
            "compute_fn": f"tools.qualitative_engine.{id_to_function[canonical]}" if implemented else None,
            "ambiguous_note": ambiguous.get(canonical),
            "enabled": batch_enabled,
        }

        # Phase 3B additive contract fields - derived generically from this
        # row's own title/primary_source text (never per-task hardcoded),
        # plus the uniform architecture-wide status/confidence/provenance
        # contract (identical for every task by design - see module header).
        routing = route_task(task_row)
        required_evidence_types, extraction_requirements = _evidence_contract_for(task_row)
        task_row["preferred_sources"] = routing["preferred_sources"]
        task_row["fallback_sources"] = routing["fallback_sources"]
        task_row["required_evidence_types"] = required_evidence_types
        task_row["extraction_requirements"] = extraction_requirements
        task_row["status_rules"] = _STATUS_RULES
        task_row["confidence_rules"] = _CONFIDENCE_RULES
        task_row["provenance_requirements"] = _PROVENANCE_REQUIREMENTS

        tasks.append(task_row)

    return tasks, normalization_collisions, ambiguous


def validate(tasks, normalization_collisions):
    issues = {
        "duplicate_canonical_ids": [t for t in normalization_collisions],
        "orphan_children": [],
        "wholly_blank_framework_rows": [],
        "leaf_tasks_missing_source_and_formula": [],
        "persisted_without_handler": [],
        "batch_enabled_without_persistence": [],
    }
    by_id = {t["task_id"]: t for t in tasks}
    for t in tasks:
        if t["parent_id"] and t["parent_id"] not in by_id:
            issues["orphan_children"].append(t["task_id"])
        if not t["title"] and not t["primary_source"] and not t["formula_or_matrix"]:
            issues["wholly_blank_framework_rows"].append(t["task_id"])
        elif t["parent_id"] is not None and t["title"] and not t["primary_source"] and not t["formula_or_matrix"]:
            # Has a title (so a real leaf task was intended) but no
            # sourcing/scoring rule at all - a genuine spec gap worth a
            # human look, distinct from a normal title-only parent row.
            issues["leaf_tasks_missing_source_and_formula"].append(t["task_id"])
        if t["persisted"] and not t["compute_fn"]:
            issues["persisted_without_handler"].append(t["task_id"])
        if t["batch_enabled"] and not t["persisted"]:
            issues["batch_enabled_without_persistence"].append(t["task_id"])
    return issues


def render_python(tasks, ambiguous):
    lines = []
    lines.append('"""')
    lines.append("Static, reviewed A-U qualitative task registry.")
    lines.append("")
    lines.append("GENERATED by tools/generate_qualitative_task_registry.py from")
    lines.append("Navrist_Qualitative_Framework.md + tools/qualitative_engine.py.")
    lines.append("Do not hand-edit generated fields without re-running the generator or")
    lines.append("you will silently diverge from the framework/engine source of truth.")
    lines.append("")
    lines.append("Canonical ID convention: LETTER.NUMBER[.NUMBER][.SUFFIX] (e.g. 'E.1.1'),")
    lines.append("matching db/001_schema.sql's qualitative_values.subpoint_id and")
    lines.append("tools/qualitative_engine.py's subpoint_id literals - NOT the framework")
    lines.append("workbook's own 'E1.1' convention, which is preserved per-row as")
    lines.append("raw_framework_id for traceability.")
    lines.append('"""')
    lines.append("")
    if ambiguous:
        lines.append("# Known ambiguous cases surfaced by the generator (not silently resolved):")
        for k, v in ambiguous.items():
            lines.append(f"#   {k}: {v}")
        lines.append("")
    lines.append("TASK_REGISTRY = [")
    for t in tasks:
        lines.append("    {")
        for k in ("task_id", "raw_framework_id", "parent_id", "section", "title",
                  "primary_source", "formula_or_matrix", "visualization_rule",
                  "defined", "implemented", "persisted", "derived_rollup", "llm_dependent",
                  "batch_enabled", "compute_fn", "ambiguous_note", "enabled",
                  # Phase 3B additive contract fields:
                  "preferred_sources", "fallback_sources", "required_evidence_types",
                  "extraction_requirements", "status_rules", "confidence_rules",
                  "provenance_requirements"):
            lines.append(f"        {k!r}: {t[k]!r},")
        lines.append("    },")
    lines.append("]")
    lines.append("")
    lines.append("TASK_BY_ID = {t['task_id']: t for t in TASK_REGISTRY}")
    lines.append("")
    return "\n".join(lines)


if __name__ == "__main__":
    tasks, collisions, ambiguous = build_registry()
    issues = validate(tasks, collisions)
    print(f"[generate_qualitative_task_registry] parsed {len(tasks)} framework rows")
    for k, v in issues.items():
        print(f"[generate_qualitative_task_registry] {k}: {len(v)}", v[:10] if v else "")
    OUT_PY.write_text(render_python(tasks, ambiguous), encoding="utf-8")
    print(f"[generate_qualitative_task_registry] wrote {OUT_PY}")
