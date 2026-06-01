"""Tests for the CrossDocRelation schema (Phase 2b M1).

Coverage grows across tasks:

- T1.1: minimal-valid construction
- T1.2: rejection cases — extra-field, invalid-kind; empty
  ``shared_entities`` is accepted at the schema layer (the non-empty
  gate lives in M2 substrate, INV-15)
- T1.3: content-addressable id stability — ``provenance_id`` is volatile;
  id changes when ``kind`` changes; ``x-`` prefix
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from amanuensis.schemas import RoleAttribution
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


def test_rejects_empty_shared_entities_via_explicit_validator(
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
