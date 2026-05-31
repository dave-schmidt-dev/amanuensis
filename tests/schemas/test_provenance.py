"""Tests for the ProvenanceRecord schema.

Coverage (one test per requirement):

- Round-trip: build → ``model_dump()`` → reconstruct → equal
- Required-field enforcement (missing ``entity_id``)
- Literal discriminator: invalid ``entity_type`` raises
- ``extra="forbid"`` rejects unknown fields
- tz-naive datetime on ``activity_started_at`` is rejected
- All nine ``entity_type`` Literal values accepted (including the three
  ``source-mirror-*`` values added during external review)
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from amanuensis.schemas import AgentAttribution, ProvenanceRecord


def test_provenance_round_trip(provenance: ProvenanceRecord) -> None:
    dump = provenance.model_dump()
    rebuilt = ProvenanceRecord(**dump)
    assert rebuilt == provenance


def test_provenance_missing_required_field_raises(
    provenance_payload: dict[str, Any],
) -> None:
    provenance_payload.pop("entity_id")
    with pytest.raises(ValidationError) as exc:
        ProvenanceRecord(**provenance_payload)
    errors = exc.value.errors()
    assert any(err["loc"] == ("entity_id",) and err["type"] == "missing" for err in errors)


def test_provenance_invalid_entity_type_literal_raises(
    provenance_payload: dict[str, Any],
) -> None:
    provenance_payload["entity_type"] = "not-a-valid-type"
    with pytest.raises(ValidationError) as exc:
        ProvenanceRecord(**provenance_payload)
    errors = exc.value.errors()
    assert any(err["loc"] == ("entity_type",) and err["type"] == "literal_error" for err in errors)


def test_provenance_extra_field_forbidden(provenance_payload: dict[str, Any]) -> None:
    provenance_payload["unexpected"] = "nope"
    with pytest.raises(ValidationError) as exc:
        ProvenanceRecord(**provenance_payload)
    assert any(err["type"] == "extra_forbidden" for err in exc.value.errors())


def test_provenance_naive_datetime_rejected(provenance_payload: dict[str, Any]) -> None:
    provenance_payload["activity_started_at"] = datetime(2026, 5, 29, 12, 0, 0)  # naive
    with pytest.raises(ValidationError) as exc:
        ProvenanceRecord(**provenance_payload)
    assert any(err["type"] == "timezone_aware" for err in exc.value.errors())


@pytest.mark.parametrize(
    "entity_type",
    [
        "atom",
        "relation",
        "clarification-raised",
        "clarification-resolved",
        "iteration-issued",
        "iteration-applied",
        "source-mirror-document",
        "source-mirror-section",
        "source-mirror-paragraph",
    ],
)
def test_provenance_accepts_all_entity_types(
    provenance_payload: dict[str, Any], entity_type: str
) -> None:
    provenance_payload["entity_type"] = entity_type
    record = ProvenanceRecord(**provenance_payload)
    assert record.entity_type == entity_type


def test_prov_entity_type_entity(agent: AgentAttribution) -> None:
    now = datetime.now(UTC)
    p = ProvenanceRecord(
        id="p-0",
        entity_type="entity",
        entity_id="e-1",
        activity="map-resolve",
        activity_started_at=now,
        activity_ended_at=now,
        used_entity_ids=["a-1"],
        was_attributed_to=agent,
    )
    assert p.entity_type == "entity"


def test_prov_entity_type_resolution(agent: AgentAttribution) -> None:
    now = datetime.now(UTC)
    p = ProvenanceRecord(
        id="p-0",
        entity_type="resolution",
        entity_id="j-1",
        activity="map-resolve",
        activity_started_at=now,
        activity_ended_at=now,
        used_entity_ids=["a-1"],
        was_attributed_to=agent,
    )
    assert p.entity_type == "resolution"


def test_prov_entity_type_resolution_supersede() -> None:
    now = datetime.now(UTC)
    human_agent = AgentAttribution(kind="human", role="human_supervisor", identifier="cli")
    p = ProvenanceRecord(
        id="p-0",
        entity_type="resolution-supersede",
        entity_id="s-1",
        activity="resolution-supersede",
        activity_started_at=now,
        activity_ended_at=now,
        used_entity_ids=["j-1"],
        was_attributed_to=human_agent,
    )
    assert p.entity_type == "resolution-supersede"


def test_prov_entity_type_entity_supersede() -> None:
    now = datetime.now(UTC)
    human_agent = AgentAttribution(kind="human", role="human_supervisor", identifier="cli")
    p = ProvenanceRecord(
        id="p-0",
        entity_type="entity-supersede",
        entity_id="t-1",
        activity="entity-merge",
        activity_started_at=now,
        activity_ended_at=now,
        used_entity_ids=["e-1"],
        was_attributed_to=human_agent,
    )
    assert p.entity_type == "entity-supersede"
