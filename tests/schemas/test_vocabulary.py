"""Tests for the Vocabulary / VocabularyEntry / OperandTypeSchema models.

Coverage (one test per requirement, three models):

- Round-trip: build → ``model_dump()`` → reconstruct → equal
- Required-field enforcement (missing ``name`` on Vocabulary;
  missing ``predicate`` on VocabularyEntry; missing ``name`` on
  OperandTypeSchema)
- Literal discriminator: invalid ``kind`` on OperandTypeSchema raises
- ``extra="forbid"`` rejects unknown fields on each model
- ``OperandTypeSchema.required`` defaults to ``True``
- ``VocabularyEntry.aliases`` defaults to ``[]``
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import ValidationError

from amanuensis.schemas import (
    OperandTypeSchema,
    Vocabulary,
    VocabularyEntry,
)

# --- Vocabulary -------------------------------------------------------


def test_vocabulary_round_trip(vocabulary: Vocabulary) -> None:
    dump = vocabulary.model_dump()
    rebuilt = Vocabulary(**dump)
    assert rebuilt == vocabulary


def test_vocabulary_missing_required_field_raises(
    vocabulary_payload: dict[str, Any],
) -> None:
    vocabulary_payload.pop("name")
    with pytest.raises(ValidationError) as exc:
        Vocabulary(**vocabulary_payload)
    errors = exc.value.errors()
    assert any(err["loc"] == ("name",) and err["type"] == "missing" for err in errors)


def test_vocabulary_extra_field_forbidden(vocabulary_payload: dict[str, Any]) -> None:
    vocabulary_payload["unexpected"] = "nope"
    with pytest.raises(ValidationError) as exc:
        Vocabulary(**vocabulary_payload)
    assert any(err["type"] == "extra_forbidden" for err in exc.value.errors())


# --- VocabularyEntry --------------------------------------------------


def test_vocabulary_entry_round_trip(vocabulary_entry: VocabularyEntry) -> None:
    dump = vocabulary_entry.model_dump()
    rebuilt = VocabularyEntry(**dump)
    assert rebuilt == vocabulary_entry


def test_vocabulary_entry_missing_required_predicate_raises(
    vocabulary_entry_payload: dict[str, Any],
) -> None:
    vocabulary_entry_payload.pop("predicate")
    with pytest.raises(ValidationError) as exc:
        VocabularyEntry(**vocabulary_entry_payload)
    errors = exc.value.errors()
    assert any(err["loc"] == ("predicate",) and err["type"] == "missing" for err in errors)


def test_vocabulary_entry_extra_field_forbidden(
    vocabulary_entry_payload: dict[str, Any],
) -> None:
    vocabulary_entry_payload["unexpected"] = "nope"
    with pytest.raises(ValidationError) as exc:
        VocabularyEntry(**vocabulary_entry_payload)
    assert any(err["type"] == "extra_forbidden" for err in exc.value.errors())


def test_vocabulary_entry_aliases_default_empty(
    vocabulary_entry_payload: dict[str, Any],
) -> None:
    vocabulary_entry_payload.pop("aliases")
    entry = VocabularyEntry(**vocabulary_entry_payload)
    assert entry.aliases == []


# --- OperandTypeSchema ------------------------------------------------


def test_operand_type_schema_round_trip(
    operand_type_schema: OperandTypeSchema,
) -> None:
    dump = operand_type_schema.model_dump()
    rebuilt = OperandTypeSchema(**dump)
    assert rebuilt == operand_type_schema


def test_operand_type_schema_missing_required_name_raises() -> None:
    with pytest.raises(ValidationError) as exc:
        OperandTypeSchema(kind="entity")  # type: ignore[call-arg]
    errors = exc.value.errors()
    assert any(err["loc"] == ("name",) and err["type"] == "missing" for err in errors)


def test_operand_type_schema_invalid_kind_literal_raises() -> None:
    with pytest.raises(ValidationError) as exc:
        OperandTypeSchema(name="payer", kind="vehicle")  # type: ignore[arg-type]
    errors = exc.value.errors()
    assert any(err["loc"] == ("kind",) and err["type"] == "literal_error" for err in errors)


def test_operand_type_schema_extra_field_forbidden() -> None:
    with pytest.raises(ValidationError) as exc:
        OperandTypeSchema(name="payer", kind="entity", unexpected="nope")  # type: ignore[call-arg]
    assert any(err["type"] == "extra_forbidden" for err in exc.value.errors())


def test_operand_type_schema_required_defaults_true() -> None:
    schema = OperandTypeSchema(name="payer", kind="entity")
    assert schema.required is True
