"""Tests for the Probandum schema.

Coverage (one test per requirement):

- Minimal-valid construction (ultimate kind, empty alternatives)
- ``extra="forbid"`` rejects unknown fields
- Literal discriminator: invalid ``kind`` raises (e.g. ``"leaf"``)
- Content-addressable id stability: ``provenance_id`` is volatile;
  id has the ``p-`` prefix
- Round-trip: build -> ``model_dump()`` -> reconstruct -> equal

INV-16 / INV-17 / INV-18 are enforced by the M3/M4 substrate layer,
NOT the schema layer. This test file deliberately exercises only the
schema-level shape.
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from amanuensis.schemas import RoleAttribution, compute_id
from amanuensis.schemas.probandum import Probandum


@pytest.fixture
def probandum_payload(role_attribution: RoleAttribution) -> dict[str, Any]:
    """Minimum-valid Probandum payload as constructor kwargs."""
    return {
        "id": "p-fixture00000001",
        "statement": "ACME breached the contract by failing to pay.",
        "kind": "ultimate",
        "scheme": "argument-from-expert-opinion",
        "alternatives_considered": [],
        "confidence": "high",
        "provenance_id": "p-fixture-prov-0001",
        "role_attributions": [role_attribution],
        "schema_version": 1,
    }


@pytest.fixture
def probandum(probandum_payload: dict[str, Any]) -> Probandum:
    return Probandum(**probandum_payload)


def test_minimal_valid_probandum(probandum_payload: dict[str, Any]) -> None:
    p = Probandum(**probandum_payload)
    assert p.kind == "ultimate"
    assert p.statement == "ACME breached the contract by failing to pay."
    assert p.confidence == "high"
    assert p.schema_version == 1
    assert p.alternatives_considered == []


def test_rejects_extra_field(probandum_payload: dict[str, Any]) -> None:
    probandum_payload["unexpected"] = "nope"
    with pytest.raises(ValidationError) as exc:
        Probandum(**probandum_payload)
    assert any(err["type"] == "extra_forbidden" for err in exc.value.errors())


def test_rejects_invalid_kind(probandum_payload: dict[str, Any]) -> None:
    probandum_payload["kind"] = "leaf"
    with pytest.raises(ValidationError) as exc:
        Probandum(**probandum_payload)
    assert any(err["loc"] == ("kind",) for err in exc.value.errors())


def test_id_starts_with_p_prefix(probandum: Probandum) -> None:
    assert compute_id(probandum).startswith("p-")


def test_id_stable_across_provenance_id(
    probandum_payload: dict[str, Any],
) -> None:
    """``provenance_id`` is volatile; varying it must not change ``compute_id``."""
    p_a = Probandum(**probandum_payload)
    probandum_payload["provenance_id"] = "p-different-prov-0002"
    p_b = Probandum(**probandum_payload)
    assert compute_id(p_a) == compute_id(p_b)


def test_round_trip(probandum: Probandum) -> None:
    dump = probandum.model_dump()
    rebuilt = Probandum(**dump)
    assert rebuilt == probandum
