"""Tests for the IterationDirective schema.

Coverage (one test per requirement):

- Round-trip: build → ``model_dump()`` → reconstruct → equal
- Required-field enforcement (missing ``issued_provenance_id``)
- Literal discriminator: invalid ``target_phase`` raises
- ``extra="forbid"`` rejects unknown fields
- tz-naive datetime on ``issued_at`` is rejected
- ``applied_provenance_id`` is optional (omitted → valid)
- Applied-state round-trip exercises the issued/applied provenance pair
  the task description emphasizes.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from amanuensis.schemas import AgentAttribution, IterationDirective


def test_iteration_round_trip(iteration: IterationDirective) -> None:
    dump = iteration.model_dump()
    rebuilt = IterationDirective(**dump)
    assert rebuilt == iteration


def test_iteration_missing_required_issued_provenance_id_raises(
    iteration_payload: dict[str, Any],
) -> None:
    iteration_payload.pop("issued_provenance_id")
    with pytest.raises(ValidationError) as exc:
        IterationDirective(**iteration_payload)
    errors = exc.value.errors()
    assert any(
        err["loc"] == ("issued_provenance_id",) and err["type"] == "missing" for err in errors
    )


def test_iteration_invalid_target_phase_literal_raises(
    iteration_payload: dict[str, Any],
) -> None:
    iteration_payload["target_phase"] = "publish"
    with pytest.raises(ValidationError) as exc:
        IterationDirective(**iteration_payload)
    errors = exc.value.errors()
    assert any(err["loc"] == ("target_phase",) and err["type"] == "literal_error" for err in errors)


def test_iteration_extra_field_forbidden(iteration_payload: dict[str, Any]) -> None:
    iteration_payload["unexpected"] = "nope"
    with pytest.raises(ValidationError) as exc:
        IterationDirective(**iteration_payload)
    assert any(err["type"] == "extra_forbidden" for err in exc.value.errors())


def test_iteration_naive_issued_at_rejected(iteration_payload: dict[str, Any]) -> None:
    iteration_payload["issued_at"] = datetime(2026, 5, 29, 13, 0, 0)  # naive
    with pytest.raises(ValidationError) as exc:
        IterationDirective(**iteration_payload)
    assert any(err["type"] == "timezone_aware" for err in exc.value.errors())


def test_iteration_applied_provenance_id_optional(
    iteration_payload: dict[str, Any],
) -> None:
    iteration_payload.pop("applied_provenance_id")
    obj = IterationDirective(**iteration_payload)
    assert obj.applied_provenance_id is None


def test_iteration_applied_round_trip(
    iteration_payload: dict[str, Any],
    human_agent: AgentAttribution,
) -> None:
    """Applied state populates the paired applied_* fields."""
    iteration_payload["applied_at"] = datetime(2026, 5, 29, 14, 30, 0, tzinfo=UTC)
    iteration_payload["applied_by"] = human_agent
    iteration_payload["applied_outcome"] = "Re-extracted §3; 4 atoms revised."
    iteration_payload["applied_provenance_id"] = "p-fixture00000099"

    obj = IterationDirective(**iteration_payload)
    rebuilt = IterationDirective(**obj.model_dump())
    assert rebuilt == obj
    assert rebuilt.applied_provenance_id == "p-fixture00000099"
