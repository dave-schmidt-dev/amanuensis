"""Tests for ``universe_check``."""

from __future__ import annotations

from amanuensis.schemas import Atom
from amanuensis.validators import universe_check


def test_universe_check_passes_when_source_known(atom: Atom) -> None:
    result = universe_check(atom, known_source_ids={atom.source_id, "src-other"})
    assert result.passed is True
    assert result.validator == "universe_check"
    assert result.subject_id == atom.id
    assert result.reason == ""


def test_universe_check_fails_when_source_unknown(atom: Atom) -> None:
    result = universe_check(atom, known_source_ids={"src-other"})
    assert result.passed is False
    assert result.validator == "universe_check"
    assert "not in known sources" in result.reason
    assert atom.source_id in result.reason
    assert result.subject_id == atom.id


def test_universe_check_fails_on_empty_universe(atom: Atom) -> None:
    result = universe_check(atom, known_source_ids=set())
    assert result.passed is False
    assert "not in known sources" in result.reason
