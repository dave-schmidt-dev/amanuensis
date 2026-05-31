"""Tests for Resolution schema."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from amanuensis.schemas._shared import AgentAttribution, RoleAttribution

# DIRECT module imports — orchestrator will swap to public re-export later
from amanuensis.schemas.resolution import Resolution


def _attr() -> RoleAttribution:
    """Helper to construct a RoleAttribution for testing."""
    return RoleAttribution(
        agent=AgentAttribution(kind="llm", identifier="claude-opus-4-7", role="extractor"),
        activity="map-resolve proposed",
        at=datetime.now(UTC),
    )


def test_resolution_round_trip() -> None:
    """Test Resolution can be serialized and deserialized."""
    r = Resolution(
        id="j-0000000000000000",
        source_id="src-doc1",
        atom_id="a-0000000000000000",
        operand_index=0,
        entity_id="e-1111111111111111",
        confidence="high",
        basis="name-and-role-equivalence rule",
        provenance_id="p-deadbeefdeadbeef",
        role_attributions=[_attr()],
    )
    assert r.operand_index == 0
    rebuilt = Resolution(**r.model_dump())
    assert rebuilt == r


def test_resolution_basis_no_newline() -> None:
    """Test that basis rejects embedded newline."""
    with pytest.raises(ValidationError):
        Resolution(
            id="j-0000000000000000",
            source_id="s",
            atom_id="a-1",
            operand_index=0,
            entity_id="e-1",
            confidence="high",
            basis="line1\nline2",
            provenance_id="p-1",
            role_attributions=[_attr()],
        )


def test_resolution_basis_no_carriage_return() -> None:
    """Test that basis rejects embedded carriage return."""
    with pytest.raises(ValidationError):
        Resolution(
            id="j-0000000000000000",
            source_id="s",
            atom_id="a-1",
            operand_index=0,
            entity_id="e-1",
            confidence="high",
            basis="line1\rline2",
            provenance_id="p-1",
            role_attributions=[_attr()],
        )


def test_resolution_operand_index_non_negative() -> None:
    """Test that operand_index must be >= 0."""
    with pytest.raises(ValidationError):
        Resolution(
            id="j-0000000000000000",
            source_id="s",
            atom_id="a-1",
            operand_index=-1,
            entity_id="e-1",
            confidence="high",
            basis="ok",
            provenance_id="p-1",
            role_attributions=[_attr()],
        )


def test_resolution_required_fields() -> None:
    """Test that required fields cannot be omitted."""
    with pytest.raises(ValidationError):
        Resolution(  # type: ignore
            id="j-0000000000000000",
            source_id="src",
            atom_id="a-1",
            operand_index=0,
            entity_id="e-1",
            confidence="high",
            basis="ok",
            provenance_id="p-1",
            # missing role_attributions
        )


def test_resolution_defaults() -> None:
    """Test that optional fields have correct defaults."""
    r = Resolution(
        id="j-0000000000000000",
        source_id="src",
        atom_id="a-1",
        operand_index=0,
        entity_id="e-1",
        confidence="high",
        basis="ok",
        provenance_id="p-1",
        role_attributions=[],
    )
    assert r.schema_version == 1


def test_resolution_confidence_literal() -> None:
    """Test that confidence only accepts valid literals."""
    # Valid confidence values
    for conf in ["high", "medium", "low"]:
        r = Resolution(
            id="j-0000000000000000",
            source_id="s",
            atom_id="a-1",
            operand_index=0,
            entity_id="e-1",
            confidence=conf,  # type: ignore
            basis="ok",
            provenance_id="p-1",
            role_attributions=[_attr()],
        )
        assert r.confidence == conf

    # Invalid confidence value
    with pytest.raises(ValidationError):
        Resolution(
            id="j-0000000000000000",
            source_id="s",
            atom_id="a-1",
            operand_index=0,
            entity_id="e-1",
            confidence="contested",  # type: ignore
            basis="ok",
            provenance_id="p-1",
            role_attributions=[_attr()],
        )


def test_resolution_strict_mode() -> None:
    """Test that strict mode rejects extra fields."""
    with pytest.raises(ValidationError):
        Resolution(  # type: ignore[call-arg]
            id="j-0000000000000000",
            source_id="s",
            atom_id="a-1",
            operand_index=0,
            entity_id="e-1",
            confidence="high",
            basis="ok",
            provenance_id="p-1",
            role_attributions=[_attr()],
            unknown_field="should fail",  # type: ignore[arg-type]
        )
