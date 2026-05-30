"""Tests for ``schema_check`` validator."""

from __future__ import annotations

from amanuensis.schemas import Atom, ProvenanceRecord
from amanuensis.validators import ValidationResult, schema_check


def test_schema_check_passes_existing_model_instance(atom: Atom) -> None:
    result = schema_check(atom, model_class=Atom)
    assert result == ValidationResult(
        passed=True, validator="schema_check", reason="", subject_id=atom.id
    )


def test_schema_check_rejects_wrong_model_instance(atom: Atom) -> None:
    # An Atom is not a ProvenanceRecord; surface this rather than passing.
    result = schema_check(atom, model_class=ProvenanceRecord)
    assert result.passed is False
    assert result.validator == "schema_check"
    assert "expected ProvenanceRecord" in result.reason
    assert result.subject_id == atom.id


def test_schema_check_passes_valid_dict_payload(atom: Atom) -> None:
    payload = atom.model_dump(mode="python")
    result = schema_check(payload, model_class=Atom)
    assert result.passed is True
    assert result.validator == "schema_check"
    assert result.subject_id == atom.id


def test_schema_check_fails_dict_missing_required_field(atom: Atom) -> None:
    payload = atom.model_dump(mode="python")
    del payload["scale_anchor"]
    result = schema_check(payload, model_class=Atom)
    assert result.passed is False
    assert result.validator == "schema_check"
    assert "scale_anchor" in result.reason
    # ``subject_id`` still resolves from the payload's ``id`` field.
    assert result.subject_id == atom.id


def test_schema_check_fails_dict_with_extra_field(atom: Atom) -> None:
    payload = atom.model_dump(mode="python")
    payload["unexpected_field"] = "rogue"
    result = schema_check(payload, model_class=Atom)
    assert result.passed is False
    assert "unexpected_field" in result.reason


def test_schema_check_subject_id_none_when_dict_lacks_id() -> None:
    result = schema_check({"foo": "bar"}, model_class=Atom)
    assert result.passed is False
    assert result.subject_id is None
