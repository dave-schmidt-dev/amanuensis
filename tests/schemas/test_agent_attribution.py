"""Tests for AgentAttribution schema validation.

Verifies Phase 2a map roles and backward compatibility with Phase 1 roles.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from amanuensis.schemas._shared import AgentAttribution


def test_map_resolve_role_accepted() -> None:
    """Verify 'map-resolve' role is accepted in AgentAttribution."""
    a = AgentAttribution(kind="llm", role="map-resolve", identifier="claude-opus-4-7")
    assert a.role == "map-resolve"


def test_map_audit_role_accepted() -> None:
    """Verify 'map-audit' role is accepted in AgentAttribution."""
    a = AgentAttribution(kind="llm", role="map-audit", identifier="claude-opus-4-7")
    assert a.role == "map-audit"


def test_phase1_extractor_role_still_validates() -> None:
    """Verify Phase 1 'extractor' role still validates (backward compatibility - R11)."""
    a = AgentAttribution(kind="llm", role="extractor", identifier="claude-opus-4-7")
    assert a.role == "extractor"


def test_phase1_auditor_role_still_validates() -> None:
    """Verify Phase 1 'auditor' role still validates (backward compatibility - R11)."""
    a = AgentAttribution(kind="llm", role="auditor", identifier="claude-opus-4-7")
    assert a.role == "auditor"


def test_phase1_contrarian_role_still_validates() -> None:
    """Verify Phase 1 'contrarian' role still validates (backward compatibility - R11)."""
    a = AgentAttribution(kind="llm", role="contrarian", identifier="claude-opus-4-7")
    assert a.role == "contrarian"


def test_phase1_constructive_role_still_validates() -> None:
    """Verify Phase 1 'constructive' role still validates (backward compatibility - R11)."""
    a = AgentAttribution(kind="llm", role="constructive", identifier="claude-opus-4-7")
    assert a.role == "constructive"


def test_phase1_premortem_role_still_validates() -> None:
    """Verify Phase 1 'premortem' role still validates (backward compatibility - R11)."""
    a = AgentAttribution(kind="llm", role="premortem", identifier="claude-opus-4-7")
    assert a.role == "premortem"


def test_phase1_human_supervisor_role_still_validates() -> None:
    """Verify Phase 1 'human_supervisor' role still validates (backward compatibility - R11)."""
    a = AgentAttribution(kind="llm", role="human_supervisor", identifier="alice")
    assert a.role == "human_supervisor"


def test_unknown_role_rejected() -> None:
    """Verify unknown role values are rejected with ValidationError."""
    with pytest.raises(ValidationError):
        AgentAttribution(kind="llm", role="not-a-real-role", identifier="claude")  # type: ignore[arg-type]


def test_human_kind_with_map_resolve() -> None:
    """Verify 'map-resolve' role works with 'human' kind."""
    a = AgentAttribution(kind="human", role="map-resolve", identifier="alice")
    assert a.role == "map-resolve"
    assert a.kind == "human"


def test_human_kind_with_map_audit() -> None:
    """Verify 'map-audit' role works with 'human' kind."""
    a = AgentAttribution(kind="human", role="map-audit", identifier="bob")
    assert a.role == "map-audit"
    assert a.kind == "human"
