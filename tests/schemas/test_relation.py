"""Tests for the Relation schema.

Coverage (one test per requirement):

- Round-trip: build → ``model_dump()`` → reconstruct → equal
- Required-field enforcement (missing ``from_atom_id``)
- Literal discriminator: invalid ``warrant_defensibility`` raises
- ``extra="forbid"`` rejects unknown fields
- ``confidence`` Literal: invalid value raises
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from amanuensis.schemas import Relation


def test_relation_round_trip(relation: Relation) -> None:
    dump = relation.model_dump()
    rebuilt = Relation(**dump)
    assert rebuilt == relation


def test_relation_missing_required_field_raises(relation_payload: dict[str, Any]) -> None:
    relation_payload.pop("from_atom_id")
    with pytest.raises(ValidationError) as exc:
        Relation(**relation_payload)
    assert any(err["loc"] == ("from_atom_id",) for err in exc.value.errors())


def test_relation_invalid_warrant_defensibility_raises(
    relation_payload: dict[str, Any],
) -> None:
    relation_payload["warrant_defensibility"] = "made-up"
    with pytest.raises(ValidationError) as exc:
        Relation(**relation_payload)
    assert any(err["loc"] == ("warrant_defensibility",) for err in exc.value.errors())


def test_relation_extra_field_forbidden(relation_payload: dict[str, Any]) -> None:
    relation_payload["unexpected"] = "nope"
    with pytest.raises(ValidationError) as exc:
        Relation(**relation_payload)
    assert any(err["type"] == "extra_forbidden" for err in exc.value.errors())


def test_relation_invalid_confidence_raises(relation_payload: dict[str, Any]) -> None:
    relation_payload["confidence"] = "very-high"
    with pytest.raises(ValidationError) as exc:
        Relation(**relation_payload)
    assert any(err["loc"] == ("confidence",) for err in exc.value.errors())
