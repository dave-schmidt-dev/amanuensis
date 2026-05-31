"""T3.7 — Phase-1-promised enumerators.

Covers:
- list_distillations yields source_ids of existing distillation dirs
- list_distillations returns empty when no distillations/ dir
- list_relations yields all Relation records for a source
- list_relations returns empty when no relations/ dir
- list_clarifications yields all clarifications across distillations
- list_clarifications filtered by status
- list_clarifications filtered by kind
- list_clarifications returns empty when no distillations
"""

from __future__ import annotations

from pathlib import Path

from amanuensis.fs import Substrate
from amanuensis.schemas import Atom, Relation, RoleAttribution
from tests.fs.conftest import SOURCE_ID


def _new(workspace: Path) -> Substrate:
    return Substrate(workspace)


# --- list_distillations ----------------------------------------------


def test_list_distillations_empty_when_no_dir(tmp_workspace: Path) -> None:
    sub = _new(tmp_workspace)
    assert list(sub.list_distillations()) == []


def test_list_distillations_yields_source_ids(
    tmp_workspace: Path,
    role_attribution: RoleAttribution,
    atom: Atom,
    relation: Relation,
) -> None:
    """Writing atoms into two distillations makes them appear in list_distillations."""
    sub = _new(tmp_workspace)
    # Use add_atom to create the distillation directories on disk.
    sub.add_atom(SOURCE_ID, atom)  # type: ignore[arg-type]
    sub.add_atom("src-fixture-002", _atom_for(sub, role_attribution, "src-fixture-002"))
    result = list(sub.list_distillations())
    assert set(result) >= {SOURCE_ID, "src-fixture-002"}


def _atom_for(sub: Substrate, role_attribution: RoleAttribution, source_id: str) -> Atom:
    """Build a minimal Atom for a given source_id with a correct hash."""
    from typing import Any

    from amanuensis.schemas import Atom, OperandRef, compute_id

    operand = OperandRef(role="subject", kind="entity", value="ent-x", type_hint=None)
    payload: dict[str, Any] = {
        "source_id": source_id,
        "section_path": ["§1"],
        "paragraph_index": 0,
        "sentence_index": None,
        "char_span": (0, 10),
        "scale_anchor": "paragraph",
        "kind": "claim",
        "predicate": "asserts_obligation",
        "operands": [operand],
        "narrative": f"Narrative for {source_id}.",
        "qualifier_level": None,
        "qualifier_basis": None,
        "provenance_id": "p-fixture00000001",
        "role_attributions": [role_attribution],
        "schema_version": 1,
        "id": "a-" + "0" * 16,
    }
    draft = Atom(**payload)
    payload["id"] = compute_id(draft)
    return Atom(**payload)


# --- list_relations --------------------------------------------------


def test_list_relations_empty_when_no_dir(tmp_workspace: Path) -> None:
    sub = _new(tmp_workspace)
    assert list(sub.list_relations(SOURCE_ID)) == []


def test_list_relations_yields_all(
    tmp_workspace: Path,
    role_attribution: RoleAttribution,
    relation: object,
) -> None:
    sub = _new(tmp_workspace)
    sub.add_relation(SOURCE_ID, relation)  # type: ignore[arg-type]
    result = list(sub.list_relations(SOURCE_ID))
    assert len(result) == 1
    assert result[0].id == relation.id  # type: ignore[union-attr]


def test_list_relations_multiple(
    tmp_workspace: Path,
    role_attribution: RoleAttribution,
    relation: object,
) -> None:
    from typing import Any

    from amanuensis.schemas import Relation, compute_id

    sub = _new(tmp_workspace)
    sub.add_relation(SOURCE_ID, relation)  # type: ignore[arg-type]

    # Build a second relation with different atom ids.
    payload: dict[str, Any] = {
        "source_id": SOURCE_ID,
        "from_atom_id": "a-fixture0003000",
        "to_atom_id": "a-fixture0004000",
        "kind": "supports",
        "warrant": "Second warrant.",
        "warrant_defensibility": "contested",
        "warrant_basis": "Other basis.",
        "confidence": "medium",
        "provenance_id": "p-fixture00000020",
        "role_attributions": [role_attribution],
        "schema_version": 1,
        "id": "r-" + "0" * 16,
    }
    draft = Relation(**payload)
    payload["id"] = compute_id(draft)
    r2 = Relation(**payload)
    sub.add_relation(SOURCE_ID, r2)

    result = list(sub.list_relations(SOURCE_ID))
    assert len(result) == 2


# --- list_clarifications ---------------------------------------------


def test_list_clarifications_empty_when_no_distillations(
    tmp_workspace: Path,
) -> None:
    sub = _new(tmp_workspace)
    assert list(sub.list_clarifications()) == []


def test_list_clarifications_yields_open(
    tmp_workspace: Path,
    clarification: object,
) -> None:
    sub = _new(tmp_workspace)
    sub.add_clarification(SOURCE_ID, clarification)  # type: ignore[arg-type]
    result = list(sub.list_clarifications())
    assert len(result) == 1
    assert result[0].id == clarification.id  # type: ignore[union-attr]


def test_list_clarifications_yields_resolved(
    tmp_workspace: Path,
    resolved_clarification: object,
) -> None:
    sub = _new(tmp_workspace)
    sub.add_clarification(SOURCE_ID, resolved_clarification)  # type: ignore[arg-type]
    result = list(sub.list_clarifications())
    assert len(result) == 1
    assert result[0].id == resolved_clarification.id  # type: ignore[union-attr]


def test_list_clarifications_both_statuses(
    tmp_workspace: Path,
    clarification: object,
    resolved_clarification: object,
) -> None:
    sub = _new(tmp_workspace)
    sub.add_clarification(SOURCE_ID, clarification)  # type: ignore[arg-type]
    sub.add_clarification(SOURCE_ID, resolved_clarification)  # type: ignore[arg-type]
    result = list(sub.list_clarifications())
    assert len(result) == 2


def test_list_clarifications_filter_status_open(
    tmp_workspace: Path,
    clarification: object,
    resolved_clarification: object,
) -> None:
    sub = _new(tmp_workspace)
    sub.add_clarification(SOURCE_ID, clarification)  # type: ignore[arg-type]
    sub.add_clarification(SOURCE_ID, resolved_clarification)  # type: ignore[arg-type]
    result = list(sub.list_clarifications(status="open"))
    assert len(result) == 1
    assert result[0].status == "open"


def test_list_clarifications_filter_status_resolved(
    tmp_workspace: Path,
    clarification: object,
    resolved_clarification: object,
) -> None:
    sub = _new(tmp_workspace)
    sub.add_clarification(SOURCE_ID, clarification)  # type: ignore[arg-type]
    sub.add_clarification(SOURCE_ID, resolved_clarification)  # type: ignore[arg-type]
    result = list(sub.list_clarifications(status="resolved"))
    assert len(result) == 1
    assert result[0].status == "resolved"


def test_list_clarifications_filter_kind(
    tmp_workspace: Path,
    clarification: object,
) -> None:
    sub = _new(tmp_workspace)
    sub.add_clarification(SOURCE_ID, clarification)  # type: ignore[arg-type]
    result_match = list(sub.list_clarifications(kind="warrant-defensibility-contested"))
    result_no_match = list(sub.list_clarifications(kind="other-kind"))
    assert len(result_match) == 1
    assert len(result_no_match) == 0


def test_list_clarifications_across_multiple_distillations(
    tmp_workspace: Path,
    clarification: object,
    role_attribution: RoleAttribution,
) -> None:
    """Clarifications from different source_ids are all yielded."""
    sub = _new(tmp_workspace)
    sub.add_clarification(SOURCE_ID, clarification)  # type: ignore[arg-type]
    # Write the same clarification object under a second source_id — the
    # Substrate accepts it (different distillation, same record id is fine
    # since the content is canonical).
    sub.add_clarification("src-fixture-002", clarification)  # type: ignore[arg-type]
    result = list(sub.list_clarifications())
    # Same clarification written under two source_ids → 2 files.
    assert len(result) == 2
