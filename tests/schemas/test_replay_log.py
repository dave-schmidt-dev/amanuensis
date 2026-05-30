"""Tests for the ReplayLogEntry schema.

Coverage (one test per requirement):

- Round-trip: build → ``model_dump()`` → reconstruct → equal
- Required-field enforcement (missing ``seq``)
- ``extra="forbid"`` rejects unknown fields
- tz-naive datetime on ``timestamp`` is rejected
- Optional token / cost fields default to ``None`` and can be populated
  (the "optional token fields" the task description emphasizes).
- Strict-mode int rejects float for ``seq``
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytest
from pydantic import ValidationError

from amanuensis.schemas import ReplayLogEntry


def test_replay_log_round_trip(replay_log_entry: ReplayLogEntry) -> None:
    dump = replay_log_entry.model_dump()
    rebuilt = ReplayLogEntry(**dump)
    assert rebuilt == replay_log_entry


def test_replay_log_missing_required_seq_raises(
    replay_log_payload: dict[str, Any],
) -> None:
    replay_log_payload.pop("seq")
    with pytest.raises(ValidationError) as exc:
        ReplayLogEntry(**replay_log_payload)
    errors = exc.value.errors()
    assert any(err["loc"] == ("seq",) and err["type"] == "missing" for err in errors)


def test_replay_log_extra_field_forbidden(replay_log_payload: dict[str, Any]) -> None:
    replay_log_payload["unexpected"] = "nope"
    with pytest.raises(ValidationError) as exc:
        ReplayLogEntry(**replay_log_payload)
    assert any(err["type"] == "extra_forbidden" for err in exc.value.errors())


def test_replay_log_naive_timestamp_rejected(replay_log_payload: dict[str, Any]) -> None:
    replay_log_payload["timestamp"] = datetime(2026, 5, 29, 12, 0, 3)  # naive
    with pytest.raises(ValidationError) as exc:
        ReplayLogEntry(**replay_log_payload)
    assert any(err["type"] == "timezone_aware" for err in exc.value.errors())


def test_replay_log_optional_token_fields_default_none(
    replay_log_payload: dict[str, Any],
) -> None:
    # Confirm payload intentionally omits the optional cost fields.
    assert "tokens_input" not in replay_log_payload
    assert "tokens_output" not in replay_log_payload
    assert "cost_estimate_cents" not in replay_log_payload

    entry = ReplayLogEntry(**replay_log_payload)
    assert entry.tokens_input is None
    assert entry.tokens_output is None
    assert entry.cost_estimate_cents is None


def test_replay_log_optional_token_fields_round_trip(
    replay_log_payload: dict[str, Any],
) -> None:
    replay_log_payload["tokens_input"] = 1234
    replay_log_payload["tokens_output"] = 567
    replay_log_payload["cost_estimate_cents"] = 0.42
    entry = ReplayLogEntry(**replay_log_payload)
    rebuilt = ReplayLogEntry(**entry.model_dump())
    assert rebuilt == entry
    assert rebuilt.tokens_input == 1234
    assert rebuilt.tokens_output == 567
    assert rebuilt.cost_estimate_cents == 0.42


def test_replay_log_strict_int_rejects_float_seq(
    replay_log_payload: dict[str, Any],
) -> None:
    replay_log_payload["seq"] = 1.5
    with pytest.raises(ValidationError) as exc:
        ReplayLogEntry(**replay_log_payload)
    assert any(err["loc"] == ("seq",) for err in exc.value.errors())
