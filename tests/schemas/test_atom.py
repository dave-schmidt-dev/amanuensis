"""Tests for the Atom schema.

Coverage (one test per requirement):

- Round-trip: build → ``model_dump()`` → reconstruct → equal
- Required-field enforcement (missing ``source_id``)
- Literal discriminator: invalid ``kind`` raises
- ``extra="forbid"`` rejects unknown fields
- ``char_span`` ordering validator rejects ``(start >= end)``
- tz-naive datetime inside a nested ``RoleAttribution`` is rejected
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from pydantic import ValidationError

from amanuensis.schemas import Atom


def test_atom_round_trip(atom: Atom) -> None:
    dump = atom.model_dump()
    rebuilt = Atom(**dump)
    assert rebuilt == atom


def test_atom_missing_required_field_raises(atom_payload: dict[str, Any]) -> None:
    atom_payload.pop("source_id")
    with pytest.raises(ValidationError) as exc:
        Atom(**atom_payload)
    assert any(err["loc"] == ("source_id",) for err in exc.value.errors())


def test_atom_invalid_kind_literal_raises(atom_payload: dict[str, Any]) -> None:
    atom_payload["kind"] = "invalid"
    with pytest.raises(ValidationError) as exc:
        Atom(**atom_payload)
    assert any(err["loc"] == ("kind",) for err in exc.value.errors())


def test_atom_extra_field_forbidden(atom_payload: dict[str, Any]) -> None:
    atom_payload["unexpected"] = "nope"
    with pytest.raises(ValidationError) as exc:
        Atom(**atom_payload)
    assert any(err["type"] == "extra_forbidden" for err in exc.value.errors())


def test_atom_char_span_must_be_ordered(atom_payload: dict[str, Any]) -> None:
    atom_payload["char_span"] = (5, 3)
    with pytest.raises(ValidationError) as exc:
        Atom(**atom_payload)
    assert any("char_span" in str(err["loc"]) for err in exc.value.errors())


def test_atom_naive_datetime_in_nested_role_attribution_rejected(
    atom_payload: dict[str, Any],
) -> None:
    # Replace the role_attribution with one whose `at` is naive (no tzinfo).
    atom_payload["role_attributions"] = [
        {
            "agent": {
                "kind": "llm",
                "identifier": "claude-opus-4-7",
                "role": "extractor",
            },
            "activity": "proposed",
            "at": datetime(2026, 5, 29, 12, 0, 0),  # tz-naive on purpose
        }
    ]
    with pytest.raises(ValidationError) as exc:
        Atom(**atom_payload)
    assert any(err["type"] == "timezone_aware" for err in exc.value.errors())
