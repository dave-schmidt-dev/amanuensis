"""Tests for the EntitySupersede schema.

Coverage (one test per requirement):

- Round-trip: build → ``model_dump()`` → reconstruct → equal
- Required-field enforcement (missing ``superseded_entity_id``)
- Literal discriminator: invalid ``kind`` raises
- ``extra="forbid"`` rejects unknown fields
- ``reason`` validator rejects empty/whitespace-only strings
- tz-naive datetime inside a nested ``RoleAttribution`` is rejected
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from pydantic import ValidationError

from amanuensis.schemas import RoleAttribution
from amanuensis.schemas.entity_supersede import EntitySupersede


@pytest.fixture
def entity_supersede_payload(
    role_attribution: RoleAttribution,
) -> dict[str, Any]:
    """Minimum-valid EntitySupersede payload as a dict (constructor kwargs)."""
    return {
        "id": "t-fixture000000000001",
        "superseded_entity_id": "e-fixture-001",
        "replacement_entity_id": "e-fixture-002",
        "reason": "merge of duplicate parties",
        "provenance_id": "p-fixture-0001",
        "role_attributions": [role_attribution],
        "schema_version": 1,
    }


@pytest.fixture
def entity_supersede(entity_supersede_payload: dict[str, Any]) -> EntitySupersede:
    return EntitySupersede(**entity_supersede_payload)


def test_entity_supersede_round_trip(entity_supersede: EntitySupersede) -> None:
    dump = entity_supersede.model_dump()
    rebuilt = EntitySupersede(**dump)
    assert rebuilt == entity_supersede


def test_entity_supersede_missing_required_field_raises(
    entity_supersede_payload: dict[str, Any],
) -> None:
    entity_supersede_payload.pop("superseded_entity_id")
    with pytest.raises(ValidationError) as exc:
        EntitySupersede(**entity_supersede_payload)
    assert any(err["loc"] == ("superseded_entity_id",) for err in exc.value.errors())


def test_entity_supersede_invalid_kind_literal_raises(
    entity_supersede_payload: dict[str, Any],
) -> None:
    entity_supersede_payload["kind"] = "invalid"
    with pytest.raises(ValidationError) as exc:
        EntitySupersede(**entity_supersede_payload)
    assert any(err["loc"] == ("kind",) for err in exc.value.errors())


def test_entity_supersede_extra_field_forbidden(
    entity_supersede_payload: dict[str, Any],
) -> None:
    entity_supersede_payload["unexpected"] = "nope"
    with pytest.raises(ValidationError) as exc:
        EntitySupersede(**entity_supersede_payload)
    assert any(err["type"] == "extra_forbidden" for err in exc.value.errors())


def test_entity_supersede_reason_must_be_non_empty(
    entity_supersede_payload: dict[str, Any],
) -> None:
    entity_supersede_payload["reason"] = ""
    with pytest.raises(ValidationError) as exc:
        EntitySupersede(**entity_supersede_payload)
    assert any("reason" in str(err["loc"]) for err in exc.value.errors())


def test_entity_supersede_reason_must_be_non_whitespace(
    entity_supersede_payload: dict[str, Any],
) -> None:
    entity_supersede_payload["reason"] = "   "
    with pytest.raises(ValidationError) as exc:
        EntitySupersede(**entity_supersede_payload)
    assert any("reason" in str(err["loc"]) for err in exc.value.errors())


def test_entity_supersede_naive_datetime_in_nested_role_attribution_rejected(
    entity_supersede_payload: dict[str, Any],
) -> None:
    # Replace the role_attribution with one whose `at` is naive (no tzinfo).
    entity_supersede_payload["role_attributions"] = [
        {
            "agent": {
                "kind": "llm",
                "identifier": "claude-opus-4-7",
                "role": "extractor",
            },
            "activity": "supervisor merged entities",
            "at": datetime(2026, 5, 29, 12, 0, 0),  # tz-naive on purpose
        }
    ]
    with pytest.raises(ValidationError) as exc:
        EntitySupersede(**entity_supersede_payload)
    assert any(err["type"] == "timezone_aware" for err in exc.value.errors())


def test_entity_supersede_kind_defaults_to_entity(
    entity_supersede_payload: dict[str, Any],
) -> None:
    entity_supersede_payload.pop("kind", None)
    es = EntitySupersede(**entity_supersede_payload)
    assert es.kind == "entity"
