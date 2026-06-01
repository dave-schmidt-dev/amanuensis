"""INV-15 — cross-doc edges are grounded in shared resolved entities.

Walks every CrossDocRelation under ``mappings/relations/`` and verifies the
shared_entities clause. Catches edges that bypassed the substrate write
gate (e.g., manually edited YAML).

The helper re-runs the INV-15 gate by attempting to re-add every cross-doc
relation on disk via ``Substrate.add_cross_doc_relation`` (which enforces
the gate). For valid relations the re-add is a no-op (idempotency); for
tampered relations the gate raises ``SharedEntityGateViolation``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from amanuensis.fs import SharedEntityGateViolation, Substrate

pytestmark = pytest.mark.invariants


def test_clean_workspace_passes(
    tmp_workspace_with_one_valid_cross_doc_relation: Path,
) -> None:
    """Bilateral-resolution workspace with a single valid edge passes."""
    sub = Substrate(tmp_workspace_with_one_valid_cross_doc_relation)
    _walk_and_check(sub)  # no raise


def test_empty_shared_entities_caught(
    tmp_workspace_with_manually_authored_empty_shared_entities: Path,
) -> None:
    """A CrossDocRelation YAML with ``shared_entities: []`` is rejected."""
    sub = Substrate(tmp_workspace_with_manually_authored_empty_shared_entities)
    with pytest.raises(SharedEntityGateViolation, match="shared_entities is empty"):
        _walk_and_check(sub)


def test_missing_entity_caught(
    tmp_workspace_with_dangling_shared_entity_on_disk: Path,
) -> None:
    """A CrossDocRelation referencing an unknown entity id is rejected."""
    sub = Substrate(tmp_workspace_with_dangling_shared_entity_on_disk)
    with pytest.raises(SharedEntityGateViolation, match="not found in mappings/entities"):
        _walk_and_check(sub)


def test_missing_from_resolution_caught(
    tmp_workspace_with_unresolved_from_endpoint_on_disk: Path,
) -> None:
    """A CrossDocRelation whose from-endpoint lacks a Resolution is rejected."""
    sub = Substrate(tmp_workspace_with_unresolved_from_endpoint_on_disk)
    with pytest.raises(SharedEntityGateViolation, match=r"from endpoint .* does not resolve"):
        _walk_and_check(sub)


def test_missing_to_resolution_caught(
    tmp_workspace_with_unresolved_to_endpoint_on_disk: Path,
) -> None:
    """A CrossDocRelation whose to-endpoint lacks a Resolution is rejected."""
    sub = Substrate(tmp_workspace_with_unresolved_to_endpoint_on_disk)
    with pytest.raises(SharedEntityGateViolation, match=r"to endpoint .* does not resolve"):
        _walk_and_check(sub)


def _walk_and_check(sub: Substrate) -> None:
    """Re-run the INV-15 gate on every on-disk cross-doc relation.

    For each relation under ``mappings/relations/``, calls
    ``sub.add_cross_doc_relation(rel)`` — the substrate enforces INV-15
    on every write, so tampered records raise ``SharedEntityGateViolation``.
    Valid records hit the idempotent no-op path.
    """
    for rel in sub.list_cross_doc_relations():
        sub.add_cross_doc_relation(rel)
