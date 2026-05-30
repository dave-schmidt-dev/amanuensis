"""Tests for ``citation_ledger`` (INV-7 enforcement)."""

from __future__ import annotations

from amanuensis.schemas import Atom
from amanuensis.validators import citation_ledger
from tests.validators._types import AtomFactory


def test_citation_ledger_passes_on_well_formed_atom(atom: Atom) -> None:
    result = citation_ledger(atom)
    assert result.passed is True
    assert result.validator == "citation_ledger"
    assert result.subject_id == atom.id
    assert result.reason == ""


def test_citation_ledger_fails_on_empty_section_path(atom_factory: AtomFactory) -> None:
    bad = atom_factory(section_path=[])
    result = citation_ledger(bad)
    assert result.passed is False
    assert "section_path is empty" in result.reason
    assert result.subject_id == bad.id


def test_citation_ledger_fails_on_empty_segment(atom_factory: AtomFactory) -> None:
    bad = atom_factory(section_path=["Part II", "", "(a)"])
    result = citation_ledger(bad)
    assert result.passed is False
    assert "section_path[1] is empty" in result.reason


def test_citation_ledger_fails_on_empty_source_id(atom_factory: AtomFactory) -> None:
    bad = atom_factory(source_id="")
    result = citation_ledger(bad)
    assert result.passed is False
    assert "source_id is empty" in result.reason


def test_citation_ledger_fails_on_negative_paragraph_index(atom: Atom) -> None:
    """Post-construction-mutation defense case: Pydantic accepts any int for
    ``paragraph_index`` at construction (no ge=0 constraint), but the
    validator must reject negative values. Use ``object.__setattr__`` to
    simulate the mutation path (mirroring the ``scale_anchor`` defense).
    """
    object.__setattr__(atom, "paragraph_index", -1)
    result = citation_ledger(atom)
    assert result.passed is False
    assert "paragraph_index" in result.reason
    assert "-1" in result.reason
    assert result.subject_id == atom.id


def test_citation_ledger_fails_on_negative_char_span_start(atom: Atom) -> None:
    """Post-construction-mutation defense case: Atom's ``char_span``
    field_validator enforces ``start < end`` at construction but does not
    reject negative starts, so the validator must cover that branch.
    """
    object.__setattr__(atom, "char_span", (-1, 5))
    result = citation_ledger(atom)
    assert result.passed is False
    assert "char_span" in result.reason
    assert "negative" in result.reason
    assert result.subject_id == atom.id


def test_citation_ledger_fails_on_inverted_char_span(atom: Atom) -> None:
    """Post-construction-mutation defense case: Atom's field_validator
    enforces ``start < end`` at construction, but ``object.__setattr__``
    bypasses that. Mirrors the ``scale_anchor`` validator's stance that
    every validator must stay total over the type so the Auditor never
    raises on tampered instances.
    """
    object.__setattr__(atom, "char_span", (5, 3))
    result = citation_ledger(atom)
    assert result.passed is False
    assert "char_span" in result.reason
    assert "start must be < end" in result.reason
    assert result.subject_id == atom.id


def test_citation_ledger_fails_on_empty_char_span(atom: Atom) -> None:
    """Post-construction-mutation defense case: ``(5, 5)`` violates the
    strict ``start < end`` rule and must be caught by the symmetric
    defense (parallel to ``scale_anchor``).
    """
    object.__setattr__(atom, "char_span", (5, 5))
    result = citation_ledger(atom)
    assert result.passed is False
    assert "char_span" in result.reason
    assert "start must be < end" in result.reason
