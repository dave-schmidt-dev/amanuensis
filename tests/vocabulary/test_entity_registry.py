"""Tests for the entity kind vocabulary loader."""

from __future__ import annotations

from pathlib import Path

import pytest

from amanuensis.vocabulary.entity_registry import (
    EntityVocabulary,
    EntityVocabularyError,
    load_entity_vocabulary,
)

TEMPLATE = Path(__file__).parent.parent.parent / "vocabularies" / "generic" / "entity-kinds.yaml"


def test_load_happy_path() -> None:
    """Load the template entity vocabulary file."""
    v = load_entity_vocabulary(TEMPLATE)
    assert isinstance(v, EntityVocabulary)
    assert {k.id for k in v.kinds} >= {"party", "person"}
    assert v.version == 1


def test_duplicate_kind_id_rejected(tmp_path: Path) -> None:
    """Reject vocabularies with duplicate entity kind IDs."""
    p = tmp_path / "v.yaml"
    p.write_text(
        "version: 1\n"
        "kinds:\n"
        "  - id: party\n"
        "    description: a\n"
        "    resolution_rules: [name-and-role-equivalence]\n"
        "  - id: party\n"
        "    description: b\n"
        "    resolution_rules: [name-and-role-equivalence]\n"
    )
    with pytest.raises(EntityVocabularyError):
        load_entity_vocabulary(p)


def test_missing_required_key_rejected(tmp_path: Path) -> None:
    """Reject vocabularies missing required fields."""
    p = tmp_path / "v.yaml"
    p.write_text("version: 1\n")  # missing 'kinds'
    with pytest.raises(EntityVocabularyError):
        load_entity_vocabulary(p)


def test_empty_resolution_rules_rejected(tmp_path: Path) -> None:
    """Reject entity kinds with empty resolution_rules."""
    p = tmp_path / "v.yaml"
    p.write_text(
        "version: 1\nkinds:\n  - id: party\n    description: a\n    resolution_rules: []\n"
    )
    with pytest.raises(EntityVocabularyError):
        load_entity_vocabulary(p)


def test_file_not_found_wrapped(tmp_path: Path) -> None:
    """Wrap FileNotFoundError as EntityVocabularyError."""
    p = tmp_path / "nonexistent.yaml"
    with pytest.raises(EntityVocabularyError):
        load_entity_vocabulary(p)
