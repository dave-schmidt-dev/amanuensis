"""Tests for the CrossDocRelationSupersede schema (Phase 2b M1).

Coverage:

- T1.4: minimal-valid construction (round-trip via attribute access);
  ``extra="forbid"`` rejects unknown fields
- T1.5: content-addressable id stability — ``at`` is volatile, ``v-`` prefix
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from amanuensis.schemas import RoleAttribution, compute_id
from amanuensis.schemas.cross_doc_relation_supersede import (
    CrossDocRelationSupersede,
)


@pytest.fixture
def cross_doc_relation_supersede_payload(
    role_attribution: RoleAttribution,
) -> dict[str, Any]:
    """Minimum-valid CrossDocRelationSupersede payload as kwargs."""
    return {
        "id": "v-fixture00000001",
        "supersedes_id": "x-old",
        "superseded_by_id": "x-new",
        "reason": "warrant tightened after supervisor review",
        "provenance_id": "p-fixture-0001",
        "role_attributions": [role_attribution],
        "at": datetime(2026, 5, 31, 12, 0, 0, tzinfo=UTC),
        "schema_version": 1,
    }


def test_minimal_supersede(
    cross_doc_relation_supersede_payload: dict[str, Any],
) -> None:
    s = CrossDocRelationSupersede(**cross_doc_relation_supersede_payload)
    assert s.supersedes_id == "x-old"
    assert s.superseded_by_id == "x-new"


def test_rejects_extra_field(
    cross_doc_relation_supersede_payload: dict[str, Any],
) -> None:
    cross_doc_relation_supersede_payload["unexpected"] = "nope"
    with pytest.raises(ValidationError) as exc:
        CrossDocRelationSupersede(**cross_doc_relation_supersede_payload)
    assert any(err["type"] == "extra_forbidden" for err in exc.value.errors())


def test_kind_discriminator_default_present(
    cross_doc_relation_supersede_payload: dict[str, Any],
) -> None:
    """``kind`` defaults to ``"cross-doc-relation"`` when not supplied."""
    cross_doc_relation_supersede_payload.pop("kind", None)
    s = CrossDocRelationSupersede(**cross_doc_relation_supersede_payload)
    assert s.kind == "cross-doc-relation"


def test_rejects_empty_reason(
    cross_doc_relation_supersede_payload: dict[str, Any],
) -> None:
    """``reason=""`` raises (mirrors Phase 2a supersede validator)."""
    cross_doc_relation_supersede_payload["reason"] = ""
    with pytest.raises(ValidationError) as exc_info:
        CrossDocRelationSupersede(**cross_doc_relation_supersede_payload)
    errors = exc_info.value.errors()
    assert any(err["loc"] == ("reason",) for err in errors)
    assert any("non-empty" in err["msg"].lower() for err in errors)


def test_rejects_whitespace_only_reason(
    cross_doc_relation_supersede_payload: dict[str, Any],
) -> None:
    """``reason="   "`` raises (validator strips before checking)."""
    cross_doc_relation_supersede_payload["reason"] = "   "
    with pytest.raises(ValidationError) as exc_info:
        CrossDocRelationSupersede(**cross_doc_relation_supersede_payload)
    errors = exc_info.value.errors()
    assert any(err["loc"] == ("reason",) for err in errors)
    assert any("non-empty" in err["msg"].lower() for err in errors)


def test_id_starts_with_v_prefix(
    cross_doc_relation_supersede_payload: dict[str, Any],
) -> None:
    s = CrossDocRelationSupersede(**cross_doc_relation_supersede_payload)
    assert compute_id(s).startswith("v-")


def test_at_is_volatile(
    cross_doc_relation_supersede_payload: dict[str, Any],
) -> None:
    """``at`` is volatile; two records identical except ``at`` hash identically."""
    s_a = CrossDocRelationSupersede(**cross_doc_relation_supersede_payload)
    cross_doc_relation_supersede_payload["at"] = datetime(2027, 1, 15, 9, 30, 0, tzinfo=UTC)
    s_b = CrossDocRelationSupersede(**cross_doc_relation_supersede_payload)
    assert compute_id(s_a) == compute_id(s_b)
