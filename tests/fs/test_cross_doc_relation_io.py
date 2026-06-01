"""T2 — Substrate cross-doc relation IO (Phase 2b M2).

Covers:
- ``add_cross_doc_relation`` writes to ``mappings/relations/<id>.yaml``
- Cross-source constraint: ``from_source_id != to_source_id`` (T2.1 gate)
- Idempotency on byte-identical content
- ``MutationOfImmutableRecord`` on tampered on-disk content (INV-13)

INV-15 (shared-entity gate) is M3 territory — these tests deliberately do
NOT exercise INV-15.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from amanuensis.fs import (
    CrossSourceConstraintViolation,
    MutationOfImmutableRecord,
    Substrate,
)
from amanuensis.schemas import (
    CrossDocRelation,
    RoleAttribution,
    compute_id,
)


def _new(workspace: Path) -> Substrate:
    return Substrate(workspace)


def _rel_payload(role_attribution: RoleAttribution, **overrides: Any) -> dict[str, Any]:
    """Minimum-valid CrossDocRelation kwargs (id placeholder; caller fixes)."""
    payload: dict[str, Any] = {
        "id": "x-" + "0" * 16,
        "from_atom_id": "a-fixture0001",
        "from_source_id": "src-A",
        "to_atom_id": "a-fixture0002",
        "to_source_id": "src-B",
        "kind": "supports",
        "warrant": "Both atoms refer to the same Smith party.",
        "warrant_defensibility": "conventional",
        "warrant_basis": "Naming conventions match across documents.",
        "confidence": "medium",
        "shared_entities": ["e-smith"],
        "provenance_id": "p-fixture-cdr-001",
        "role_attributions": [role_attribution],
        "schema_version": 1,
    }
    payload.update(overrides)
    return payload


def _rel(role_attribution: RoleAttribution, **overrides: Any) -> CrossDocRelation:
    """Build a CrossDocRelation whose id matches ``compute_id``."""
    payload = _rel_payload(role_attribution, **overrides)
    draft = CrossDocRelation(**payload)
    payload["id"] = compute_id(draft)
    return CrossDocRelation(**payload)


# --- T2.1: happy-path write ------------------------------------------


def test_add_cross_doc_relation_writes_to_mappings_relations(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    sub = _new(tmp_workspace)
    rel = _rel(role_attribution)
    sub.add_cross_doc_relation(rel)
    path = tmp_workspace / "mappings" / "relations" / f"{rel.id}.yaml"
    assert path.is_file()


# --- T2.2: idempotency + immutability + cross-source rejection -------


def test_add_cross_doc_relation_is_idempotent(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    sub = _new(tmp_workspace)
    rel = _rel(role_attribution)
    sub.add_cross_doc_relation(rel)
    # Second write with identical content must not raise; exactly one file
    # must exist on disk.
    sub.add_cross_doc_relation(rel)
    relations_dir = tmp_workspace / "mappings" / "relations"
    files = [p for p in relations_dir.iterdir() if p.is_file() and p.suffix == ".yaml"]
    assert len(files) == 1


def test_add_cross_doc_relation_raises_on_diverging_content(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    """Tampered on-disk content at the same path triggers INV-13."""
    sub = _new(tmp_workspace)
    rel = _rel(role_attribution)
    sub.add_cross_doc_relation(rel)
    path = tmp_workspace / "mappings" / "relations" / f"{rel.id}.yaml"
    # Append a manual edit so existing bytes diverge from canonical form.
    path.write_text(path.read_text(encoding="utf-8") + "# manual edit\n", encoding="utf-8")
    with pytest.raises(MutationOfImmutableRecord):
        sub.add_cross_doc_relation(rel)


def test_rejects_intra_source(tmp_workspace: Path, role_attribution: RoleAttribution) -> None:
    """from_source_id == to_source_id → CrossSourceConstraintViolation."""
    sub = _new(tmp_workspace)
    rel = _rel(role_attribution, to_source_id="src-A")  # same as from_source_id
    with pytest.raises(CrossSourceConstraintViolation):
        sub.add_cross_doc_relation(rel)
