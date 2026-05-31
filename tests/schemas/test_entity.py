"""Tests for Entity schema."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from amanuensis.schemas._shared import AgentAttribution, RoleAttribution

# DIRECT module imports — orchestrator will swap to public re-export later
from amanuensis.schemas.entity import Entity


def _attr() -> RoleAttribution:
    """Helper to construct a RoleAttribution for testing."""
    return RoleAttribution(
        agent=AgentAttribution(kind="llm", identifier="claude-opus-4-7", role="extractor"),
        activity="extractor proposed",
        at=datetime.now(UTC),
    )


def test_entity_round_trip() -> None:
    """Test Entity can be serialized and deserialized."""
    e = Entity(
        id="e-0000000000000000",
        kind="party",
        canonical_name="ACME Corp",
        aliases=["ACME", "ACME Corporation"],
        notes="initial draft",
        provenance_id="p-deadbeefdeadbeef",
        role_attributions=[_attr()],
    )
    assert e.kind == "party"
    rebuilt = Entity(**e.model_dump())
    assert rebuilt == e


def test_entity_canonical_name_non_empty() -> None:
    """Test that canonical_name rejects empty-after-strip values."""
    with pytest.raises(ValidationError):
        Entity(
            id="e-0000000000000000",
            kind="party",
            canonical_name="   ",
            provenance_id="p-deadbeefdeadbeef",
            role_attributions=[_attr()],
        )


def test_entity_canonical_name_stripped() -> None:
    """Test that canonical_name is accepted when non-empty after strip."""
    e = Entity(
        id="e-0000000000000000",
        kind="party",
        canonical_name="  ACME Corp  ",
        provenance_id="p-deadbeefdeadbeef",
        role_attributions=[_attr()],
    )
    # The validator returns the original string (not stripped),
    # but accepts it because v.strip() is non-empty
    assert e.canonical_name == "  ACME Corp  "


def test_entity_required_fields() -> None:
    """Test that required fields cannot be omitted."""
    with pytest.raises(ValidationError):
        Entity(  # type: ignore
            id="e-0000000000000000",
            kind="party",
            # missing canonical_name
            provenance_id="p-deadbeefdeadbeef",
            role_attributions=[],
        )


def test_entity_defaults() -> None:
    """Test that optional fields have correct defaults."""
    e = Entity(
        id="e-0000000000000000",
        kind="party",
        canonical_name="ACME Corp",
        provenance_id="p-deadbeefdeadbeef",
        role_attributions=[],
    )
    assert e.aliases == []
    assert e.notes is None
    assert e.schema_version == 1


def test_entity_strict_mode() -> None:
    """Test that strict mode rejects extra fields."""
    with pytest.raises(ValidationError):
        data = {
            "id": "e-0000000000000000",
            "kind": "party",
            "canonical_name": "ACME Corp",
            "provenance_id": "p-deadbeefdeadbeef",
            "role_attributions": [],
            "unknown_field": "should fail",
        }
        Entity(**data)  # type: ignore
