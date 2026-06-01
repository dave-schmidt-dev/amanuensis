"""Tests for the ProbandumEdge schema.

Coverage (one test per requirement):

- Minimal-valid construction with probandum child (no source_id)
- Minimal-valid construction with atom child (source_id required)
- ``child_source_id`` cross-field validator:
    - REQUIRED when ``child_kind == "atom"``
    - FORBIDDEN when ``child_kind != "atom"``
- ``extra="forbid"`` rejects unknown fields
- Literal discriminator: invalid ``kind`` raises
- Content-addressable id stability: ``provenance_id`` is volatile;
  id has the ``q-`` prefix
- Round-trip: build -> ``model_dump()`` -> reconstruct -> equal
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from amanuensis.schemas import RoleAttribution, compute_id
from amanuensis.schemas.probandum_edge import ProbandumEdge


@pytest.fixture
def probandum_edge_payload(
    role_attribution: RoleAttribution,
) -> dict[str, Any]:
    """Minimum-valid ProbandumEdge payload (probandum-to-probandum)."""
    return {
        "id": "q-fixture00000001",
        "parent_probandum_id": "p-parent000000001",
        "child_id": "p-child0000000001",
        "child_kind": "probandum",
        "child_source_id": None,
        "kind": "supports",
        "warrant": "Child proposition entails the parent.",
        "warrant_defensibility": "literature-backed",
        "warrant_basis": "Restatement (Second) of Contracts §1",
        "confidence": "high",
        "provenance_id": "p-fixture-prov-0001",
        "role_attributions": [role_attribution],
        "schema_version": 1,
    }


def test_minimal_valid_edge_probandum_child(
    probandum_edge_payload: dict[str, Any],
) -> None:
    edge = ProbandumEdge(**probandum_edge_payload)
    assert edge.child_kind == "probandum"
    assert edge.child_source_id is None
    assert edge.kind == "supports"
    assert edge.schema_version == 1


def test_minimal_valid_edge_atom_child(
    probandum_edge_payload: dict[str, Any],
) -> None:
    probandum_edge_payload["child_kind"] = "atom"
    probandum_edge_payload["child_id"] = "a-atom0000000001"
    probandum_edge_payload["child_source_id"] = "src-A"
    edge = ProbandumEdge(**probandum_edge_payload)
    assert edge.child_kind == "atom"
    assert edge.child_source_id == "src-A"


def test_rejects_atom_child_without_source_id(
    probandum_edge_payload: dict[str, Any],
) -> None:
    probandum_edge_payload["child_kind"] = "atom"
    probandum_edge_payload["child_id"] = "a-atom0000000001"
    probandum_edge_payload["child_source_id"] = None
    with pytest.raises(ValidationError) as exc:
        ProbandumEdge(**probandum_edge_payload)
    assert any(
        "child_source_id" in (err.get("msg") or "") or "child_source_id" in str(err.get("loc", ()))
        for err in exc.value.errors()
    )


def test_rejects_non_atom_child_with_source_id(
    probandum_edge_payload: dict[str, Any],
) -> None:
    probandum_edge_payload["child_kind"] = "probandum"
    probandum_edge_payload["child_source_id"] = "src-A"
    with pytest.raises(ValidationError) as exc:
        ProbandumEdge(**probandum_edge_payload)
    assert any(
        "child_source_id" in (err.get("msg") or "") or "child_source_id" in str(err.get("loc", ()))
        for err in exc.value.errors()
    )


def test_rejects_extra_field(probandum_edge_payload: dict[str, Any]) -> None:
    probandum_edge_payload["unexpected"] = "nope"
    with pytest.raises(ValidationError) as exc:
        ProbandumEdge(**probandum_edge_payload)
    assert any(err["type"] == "extra_forbidden" for err in exc.value.errors())


def test_rejects_invalid_kind(probandum_edge_payload: dict[str, Any]) -> None:
    probandum_edge_payload["kind"] = "endorses"
    with pytest.raises(ValidationError) as exc:
        ProbandumEdge(**probandum_edge_payload)
    assert any(err["loc"] == ("kind",) for err in exc.value.errors())


def test_id_starts_with_q_prefix(
    probandum_edge_payload: dict[str, Any],
) -> None:
    edge = ProbandumEdge(**probandum_edge_payload)
    assert compute_id(edge).startswith("q-")


def test_id_stable_across_provenance_id(
    probandum_edge_payload: dict[str, Any],
) -> None:
    e_a = ProbandumEdge(**probandum_edge_payload)
    probandum_edge_payload["provenance_id"] = "p-different-prov-0002"
    e_b = ProbandumEdge(**probandum_edge_payload)
    assert compute_id(e_a) == compute_id(e_b)


def test_round_trip(probandum_edge_payload: dict[str, Any]) -> None:
    edge = ProbandumEdge(**probandum_edge_payload)
    dump = edge.model_dump()
    rebuilt = ProbandumEdge(**dump)
    assert rebuilt == edge
