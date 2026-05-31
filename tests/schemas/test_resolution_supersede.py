"""Tests for ResolutionSupersede schema."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from amanuensis.schemas._shared import AgentAttribution, RoleAttribution
from amanuensis.schemas.resolution_supersede import ResolutionSupersede


def _attr() -> RoleAttribution:
    return RoleAttribution(
        agent=AgentAttribution(kind="human", role="human_supervisor", identifier="cli"),
        activity="supervisor superseded",
        at=datetime.now(UTC),
    )


def test_supersede_round_trip() -> None:
    """Test ResolutionSupersede round-trip serialization."""
    s = ResolutionSupersede(
        id="s-0000000000000000",
        superseded_resolution_id="j-1",
        replacement_resolution_id="j-2",
        reason="supervisor correction",
        provenance_id="p-1",
        role_attributions=[_attr()],
    )
    assert s.kind == "resolution"
    rebuilt = ResolutionSupersede(**s.model_dump())
    assert rebuilt == s


def test_supersede_kind_discriminator_default() -> None:
    """Test that kind discriminator defaults to 'resolution'."""
    s = ResolutionSupersede(
        id="s-0000000000000001",
        superseded_resolution_id="j-1",
        replacement_resolution_id="j-2",
        reason="test reason",
        provenance_id="p-1",
        role_attributions=[_attr()],
    )
    assert s.kind == "resolution"


def test_supersede_reason_non_empty() -> None:
    """Test that reason must be non-empty after strip."""
    with pytest.raises(ValidationError) as exc_info:
        ResolutionSupersede(
            id="s-0",
            superseded_resolution_id="j-1",
            replacement_resolution_id="j-2",
            reason="   ",
            provenance_id="p-1",
            role_attributions=[_attr()],
        )
    errors = exc_info.value.errors()
    assert len(errors) == 1
    assert errors[0]["loc"] == ("reason",)
    assert "non-empty" in errors[0]["msg"].lower()
