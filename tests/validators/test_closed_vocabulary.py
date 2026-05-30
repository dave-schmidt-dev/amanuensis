"""Tests for ``closed_vocabulary`` (INV-5 enforcement)."""

from __future__ import annotations

from amanuensis.schemas import Vocabulary
from amanuensis.validators import closed_vocabulary
from tests.validators._types import AtomFactory


def test_closed_vocabulary_passes_on_canonical_predicate(
    atom_factory: AtomFactory, vocabulary: Vocabulary
) -> None:
    a = atom_factory(predicate="asserts_obligation")
    result = closed_vocabulary(a, vocabulary=vocabulary)
    assert result.passed is True
    assert result.validator == "closed_vocabulary"
    assert result.subject_id == a.id


def test_closed_vocabulary_passes_on_alias(
    atom_factory: AtomFactory, vocabulary: Vocabulary
) -> None:
    # ``asserts_shall`` is registered as an alias of ``asserts_obligation``.
    a = atom_factory(predicate="asserts_shall")
    result = closed_vocabulary(a, vocabulary=vocabulary)
    assert result.passed is True


def test_closed_vocabulary_fails_on_unknown_predicate(
    atom_factory: AtomFactory, vocabulary: Vocabulary
) -> None:
    a = atom_factory(predicate="not_in_registry")
    result = closed_vocabulary(a, vocabulary=vocabulary)
    assert result.passed is False
    assert "not_in_registry" in result.reason
    assert vocabulary.name in result.reason
    assert result.subject_id == a.id
