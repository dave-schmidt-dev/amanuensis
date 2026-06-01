"""Tests for the ProbandumSupersede schema.

Coverage (one test per requirement):

- Minimal-valid construction
- ``extra="forbid"`` rejects unknown fields
- ``reason`` validator rejects empty / whitespace-only strings
- Content-addressable id stability:
    - ``at`` is volatile (changing it does not change ``compute_id``)
    - ``u-`` prefix
- Round-trip: build -> ``model_dump()`` -> reconstruct -> equal
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from amanuensis.schemas import RoleAttribution, compute_id
from amanuensis.schemas.probandum_supersede import ProbandumSupersede


@pytest.fixture
def probandum_supersede_payload(
    role_attribution: RoleAttribution,
) -> dict[str, Any]:
    """Minimum-valid ProbandumSupersede payload."""
    return {
        "id": "u-fixture00000001",
        "supersedes_id": "p-old0000000001",
        "superseded_by_id": "p-new0000000001",
        "reason": "Statement refined after supervisor review.",
        "provenance_id": "p-fixture-prov-0001",
        "role_attributions": [role_attribution],
        "at": datetime(2026, 5, 31, 12, 0, 0, tzinfo=UTC),
        "schema_version": 1,
    }


def test_minimal_supersede(
    probandum_supersede_payload: dict[str, Any],
) -> None:
    s = ProbandumSupersede(**probandum_supersede_payload)
    assert s.supersedes_id == "p-old0000000001"
    assert s.superseded_by_id == "p-new0000000001"
    assert s.kind == "probandum"


def test_rejects_extra_field(
    probandum_supersede_payload: dict[str, Any],
) -> None:
    probandum_supersede_payload["unexpected"] = "nope"
    with pytest.raises(ValidationError) as exc:
        ProbandumSupersede(**probandum_supersede_payload)
    assert any(err["type"] == "extra_forbidden" for err in exc.value.errors())


def test_rejects_empty_reason(
    probandum_supersede_payload: dict[str, Any],
) -> None:
    probandum_supersede_payload["reason"] = ""
    with pytest.raises(ValidationError) as exc_info:
        ProbandumSupersede(**probandum_supersede_payload)
    errors = exc_info.value.errors()
    assert any(err["loc"] == ("reason",) for err in errors)
    assert any("non-empty" in err["msg"].lower() for err in errors)


def test_rejects_whitespace_only_reason(
    probandum_supersede_payload: dict[str, Any],
) -> None:
    probandum_supersede_payload["reason"] = "   "
    with pytest.raises(ValidationError) as exc_info:
        ProbandumSupersede(**probandum_supersede_payload)
    errors = exc_info.value.errors()
    assert any(err["loc"] == ("reason",) for err in errors)
    assert any("non-empty" in err["msg"].lower() for err in errors)


def test_id_starts_with_u_prefix(
    probandum_supersede_payload: dict[str, Any],
) -> None:
    s = ProbandumSupersede(**probandum_supersede_payload)
    assert compute_id(s).startswith("u-")


def test_at_is_volatile(
    probandum_supersede_payload: dict[str, Any],
) -> None:
    """``at`` is volatile; two records identical except ``at`` hash identically."""
    s_a = ProbandumSupersede(**probandum_supersede_payload)
    probandum_supersede_payload["at"] = datetime(2027, 1, 15, 9, 30, 0, tzinfo=UTC)
    s_b = ProbandumSupersede(**probandum_supersede_payload)
    assert compute_id(s_a) == compute_id(s_b)


def test_round_trip(
    probandum_supersede_payload: dict[str, Any],
) -> None:
    s = ProbandumSupersede(**probandum_supersede_payload)
    dump = s.model_dump()
    rebuilt = ProbandumSupersede(**dump)
    assert rebuilt == s
