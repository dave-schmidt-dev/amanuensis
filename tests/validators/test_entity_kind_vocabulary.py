"""Tests for ``entity_kind_in_vocabulary`` (INV-12 enforcement)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from amanuensis.schemas import Entity
from amanuensis.schemas._shared import AgentAttribution, RoleAttribution
from amanuensis.validators.entity_kind_in_vocabulary import (
    EntityKindNotInSnapshot,
    entity_kind_in_vocabulary,
)
from amanuensis.vocabulary.entity_registry import EntityKind, EntityVocabulary


def _attr() -> RoleAttribution:
    """Create a fixture RoleAttribution."""
    return RoleAttribution(
        agent=AgentAttribution(kind="llm", role="extractor", identifier="claude-opus-4-7"),
        activity="extractor proposed",
        at=datetime.now(UTC),
    )


def _entity(kind: str) -> Entity:
    """Create a fixture Entity with the given kind."""
    return Entity(
        id="e-0000000000000000",
        kind=kind,
        canonical_name="X",
        provenance_id="p-deadbeefdeadbeef",
        role_attributions=[_attr()],
    )


def _vocab(kind_ids: list[str]) -> EntityVocabulary:
    """Create a fixture EntityVocabulary with the given kind IDs."""
    return EntityVocabulary(
        version=1,
        kinds=[
            EntityKind(
                id=k,
                description=f"desc {k}",
                resolution_rules=["name-and-role-equivalence"],
            )
            for k in kind_ids
        ],
    )


def test_kind_in_vocabulary_passes() -> None:
    """Validator passes when entity kind is in vocabulary."""
    result = entity_kind_in_vocabulary(_entity("party"), vocabulary=_vocab(["party", "person"]))
    assert result.passed is True
    assert result.validator == "entity_kind_in_vocabulary"
    assert result.subject_id == "e-0000000000000000"


def test_kind_not_in_vocabulary_raises() -> None:
    """Validator raises EntityKindNotInSnapshot when kind is absent."""
    with pytest.raises(EntityKindNotInSnapshot) as exc_info:
        entity_kind_in_vocabulary(_entity("not-a-kind"), vocabulary=_vocab(["party"]))
    assert "not-a-kind" in str(exc_info.value)
    assert "party" in str(exc_info.value)


def test_empty_vocabulary_raises() -> None:
    """Validator raises when vocabulary has no matching kind."""
    with pytest.raises(EntityKindNotInSnapshot):
        entity_kind_in_vocabulary(_entity("party"), vocabulary=_vocab(["unrelated-kind"]))


def test_multiple_kinds_error_message_includes_all() -> None:
    """Error message lists all valid kinds sorted."""
    with pytest.raises(EntityKindNotInSnapshot) as exc_info:
        entity_kind_in_vocabulary(
            _entity("invalid"),
            vocabulary=_vocab(["zebra", "apple", "monkey"]),
        )
    msg = str(exc_info.value)
    assert "invalid" in msg
    # Check that kinds are sorted in the error message
    assert msg.index("apple") < msg.index("monkey") < msg.index("zebra")
