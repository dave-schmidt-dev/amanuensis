"""Tests for ``lineage_closure``."""

from __future__ import annotations

from pathlib import Path

from amanuensis.fs import Substrate
from amanuensis.validators import lineage_closure
from tests.validators._types import AtomFactory, RelationFactory


def test_lineage_closure_passes_when_both_endpoints_exist(
    tmp_workspace: Path,
    atom_factory: AtomFactory,
    relation_factory: RelationFactory,
) -> None:
    sub = Substrate(tmp_workspace)
    a_from = atom_factory(predicate="asserts_obligation")
    a_to = atom_factory(predicate="asserts_factual_event")
    sub.add_atom(a_from.source_id, a_from)
    sub.add_atom(a_to.source_id, a_to)
    rel = relation_factory(from_atom_id=a_from.id, to_atom_id=a_to.id)
    result = lineage_closure(rel, substrate=sub)
    assert result.passed is True
    assert result.validator == "lineage_closure"
    assert result.subject_id == rel.id


def test_lineage_closure_fails_when_from_atom_missing(
    tmp_workspace: Path,
    atom_factory: AtomFactory,
    relation_factory: RelationFactory,
) -> None:
    sub = Substrate(tmp_workspace)
    a_to = atom_factory(predicate="asserts_factual_event")
    sub.add_atom(a_to.source_id, a_to)
    rel = relation_factory(from_atom_id="a-ghost000000000", to_atom_id=a_to.id)
    result = lineage_closure(rel, substrate=sub)
    assert result.passed is False
    assert "lineage_closure violation" in result.reason
    assert "from atom" in result.reason
    assert "a-ghost000000000" in result.reason


def test_lineage_closure_fails_when_to_atom_missing(
    tmp_workspace: Path,
    atom_factory: AtomFactory,
    relation_factory: RelationFactory,
) -> None:
    sub = Substrate(tmp_workspace)
    a_from = atom_factory(predicate="asserts_obligation")
    sub.add_atom(a_from.source_id, a_from)
    rel = relation_factory(from_atom_id=a_from.id, to_atom_id="a-ghost000000000")
    result = lineage_closure(rel, substrate=sub)
    assert result.passed is False
    assert "to atom" in result.reason
    assert "a-ghost000000000" in result.reason


def test_lineage_closure_first_failure_wins(
    tmp_workspace: Path,
    relation_factory: RelationFactory,
) -> None:
    # Both endpoints missing — validator reports ``from`` first.
    sub = Substrate(tmp_workspace)
    rel = relation_factory(from_atom_id="a-missing-1000000", to_atom_id="a-missing-2000000")
    result = lineage_closure(rel, substrate=sub)
    assert result.passed is False
    assert "from atom" in result.reason
    assert "a-missing-1000000" in result.reason
