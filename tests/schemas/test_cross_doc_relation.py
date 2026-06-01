"""Tests for the CrossDocRelation schema.

Coverage (one test per requirement):

- Round-trip: build → ``model_dump()`` → reconstruct → equal
- Minimal-valid construction
- ``extra="forbid"`` rejects unknown fields
- Empty ``shared_entities`` is accepted at the schema layer (the
  non-empty gate lives in M2 substrate, INV-15)
- Literal discriminator: invalid ``kind`` raises
- Content-addressable id stability: ``provenance_id`` is volatile;
  id changes when ``kind`` changes; ``x-`` prefix
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from amanuensis.schemas import RoleAttribution, compute_id
from amanuensis.schemas.cross_doc_relation import CrossDocRelation


@pytest.fixture
def cross_doc_relation_payload(
    role_attribution: RoleAttribution,
) -> dict[str, Any]:
    """Minimum-valid CrossDocRelation payload as constructor kwargs."""
    return {
        "id": "x-fixture00000001",
        "from_atom_id": "a-fixture0001",
        "from_source_id": "src-fixture-001",
        "to_atom_id": "a-fixture0002",
        "to_source_id": "src-fixture-002",
        "kind": "supports",
        "warrant": "Both atoms refer to the same Smith party.",
        "warrant_defensibility": "literature-backed",
        "warrant_basis": "Restatement (Second) of Contracts §1",
        "confidence": "high",
        "shared_entities": ["e-smith"],
        "provenance_id": "p-fixture-0001",
        "role_attributions": [role_attribution],
        "schema_version": 1,
    }


@pytest.fixture
def cross_doc_relation(cross_doc_relation_payload: dict[str, Any]) -> CrossDocRelation:
    return CrossDocRelation(**cross_doc_relation_payload)


def test_cross_doc_relation_round_trip(cross_doc_relation: CrossDocRelation) -> None:
    dump = cross_doc_relation.model_dump()
    rebuilt = CrossDocRelation(**dump)
    assert rebuilt == cross_doc_relation


def test_minimal_valid_cross_doc_relation(
    cross_doc_relation_payload: dict[str, Any],
) -> None:
    rel = CrossDocRelation(**cross_doc_relation_payload)
    assert rel.kind == "supports"
    assert rel.shared_entities == ["e-smith"]
    assert rel.schema_version == 1


def test_rejects_extra_field(
    cross_doc_relation_payload: dict[str, Any],
) -> None:
    cross_doc_relation_payload["extra_field"] = "nope"
    with pytest.raises(ValidationError) as exc:
        CrossDocRelation(**cross_doc_relation_payload)
    assert any(err["type"] == "extra_forbidden" for err in exc.value.errors())


def test_accepts_empty_shared_entities_at_schema_layer(
    cross_doc_relation_payload: dict[str, Any],
) -> None:
    """Schema layer ACCEPTS empty ``shared_entities``.

    The non-empty gate lives in M2 substrate IO (INV-15 enforcement
    requires a Substrate handle). This test asserts the schema does
    NOT reject the empty list on its own.
    """
    cross_doc_relation_payload["shared_entities"] = []
    rel = CrossDocRelation(**cross_doc_relation_payload)
    assert rel.shared_entities == []


def test_rejects_invalid_kind(
    cross_doc_relation_payload: dict[str, Any],
) -> None:
    cross_doc_relation_payload["kind"] = "endorses"
    with pytest.raises(ValidationError) as exc:
        CrossDocRelation(**cross_doc_relation_payload)
    assert any(err["loc"] == ("kind",) for err in exc.value.errors())


def test_id_is_stable_across_provenance_id_changes(
    cross_doc_relation_payload: dict[str, Any],
) -> None:
    """``provenance_id`` is volatile; changing it must not change ``compute_id``."""
    rel_a = CrossDocRelation(**cross_doc_relation_payload)
    cross_doc_relation_payload["provenance_id"] = "p-different-0002"
    rel_b = CrossDocRelation(**cross_doc_relation_payload)
    assert compute_id(rel_a) == compute_id(rel_b)
    assert compute_id(rel_a).startswith("x-")


def test_id_changes_when_kind_changes(
    cross_doc_relation_payload: dict[str, Any],
) -> None:
    rel_a = CrossDocRelation(**cross_doc_relation_payload)
    cross_doc_relation_payload["kind"] = "attacks"
    rel_b = CrossDocRelation(**cross_doc_relation_payload)
    assert compute_id(rel_a) != compute_id(rel_b)
