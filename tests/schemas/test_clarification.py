"""Tests for the Clarification schema.

Coverage (one test per requirement):

- Round-trip: build → ``model_dump()`` → reconstruct → equal
- Required-field enforcement (missing ``raised_provenance_id``)
- Literal discriminator: invalid ``status`` raises
- ``extra="forbid"`` rejects unknown fields
- tz-naive datetime on ``raised_at`` is rejected
- ``resolved_provenance_id`` is optional (omitted → valid)
- Resolved-state round-trip (``status="resolved"`` + populated resolved
  fields) — exercises the raised/resolved provenance pair the task
  description emphasizes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from amanuensis.schemas import AgentAttribution, Clarification


def test_clarification_round_trip(clarification: Clarification) -> None:
    dump = clarification.model_dump()
    rebuilt = Clarification(**dump)
    assert rebuilt == clarification


def test_clarification_missing_required_raised_provenance_id_raises(
    clarification_payload: dict[str, Any],
) -> None:
    clarification_payload.pop("raised_provenance_id")
    with pytest.raises(ValidationError) as exc:
        Clarification(**clarification_payload)
    errors = exc.value.errors()
    assert any(
        err["loc"] == ("raised_provenance_id",) and err["type"] == "missing" for err in errors
    )


def test_clarification_invalid_status_literal_raises(
    clarification_payload: dict[str, Any],
) -> None:
    clarification_payload["status"] = "pending"
    with pytest.raises(ValidationError) as exc:
        Clarification(**clarification_payload)
    errors = exc.value.errors()
    assert any(err["loc"] == ("status",) and err["type"] == "literal_error" for err in errors)


def test_clarification_extra_field_forbidden(
    clarification_payload: dict[str, Any],
) -> None:
    clarification_payload["unexpected"] = "nope"
    with pytest.raises(ValidationError) as exc:
        Clarification(**clarification_payload)
    assert any(err["type"] == "extra_forbidden" for err in exc.value.errors())


def test_clarification_naive_raised_at_rejected(
    clarification_payload: dict[str, Any],
) -> None:
    clarification_payload["raised_at"] = datetime(2026, 5, 29, 12, 5, 0)  # naive
    with pytest.raises(ValidationError) as exc:
        Clarification(**clarification_payload)
    assert any(err["type"] == "timezone_aware" for err in exc.value.errors())


def test_clarification_resolved_provenance_id_optional(
    clarification_payload: dict[str, Any],
) -> None:
    # Omitting resolved_provenance_id entirely is valid (status="open").
    clarification_payload.pop("resolved_provenance_id")
    obj = Clarification(**clarification_payload)
    assert obj.resolved_provenance_id is None


def test_clarification_resolved_round_trip(
    clarification_payload: dict[str, Any],
    human_agent: AgentAttribution,
) -> None:
    """Resolved state populates the paired resolved_* fields."""
    clarification_payload["status"] = "resolved"
    clarification_payload["resolved_at"] = datetime(2026, 5, 29, 14, 0, 0, tzinfo=UTC)
    clarification_payload["resolved_by"] = human_agent
    clarification_payload["resolution"] = "Parent corp."
    clarification_payload["resolved_provenance_id"] = "p-fixture00000099"

    obj = Clarification(**clarification_payload)
    rebuilt = Clarification(**obj.model_dump())
    assert rebuilt == obj
    assert rebuilt.resolved_provenance_id == "p-fixture00000099"
