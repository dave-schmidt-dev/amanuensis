"""Tests for ``provenance_completeness`` (INV-3 enforcement)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from amanuensis.fs import Substrate
from amanuensis.schemas import (
    AgentAttribution,
    Atom,
    ProvenanceRecord,
    compute_id,
)
from amanuensis.validators import provenance_completeness
from tests.validators._types import AtomFactory, ProvenanceFactory


def _atom_with_provenance(
    atom_factory: AtomFactory,
    provenance_factory: ProvenanceFactory,
) -> tuple[Atom, ProvenanceRecord]:
    """Construct an Atom + matching ProvenanceRecord whose ids agree."""
    # Build a draft atom to learn its id, then build the matching prov
    # record (entity_id = atom.id), then rebuild the atom with the prov
    # record's id as its provenance_id. Two passes are needed because
    # both ids are content-addressable and reference each other.
    draft_atom = atom_factory()
    prov = provenance_factory(entity_id=draft_atom.id)
    atom = atom_factory(provenance_id=prov.id)
    # The atom's id depends on its content, not on provenance_id (which
    # is in _VOLATILE_FIELDS), so draft_atom.id == atom.id. Re-build the
    # prov record bound to the (stable) atom id.
    prov = provenance_factory(entity_id=atom.id)
    return atom, prov


def test_provenance_completeness_passes_on_matched_record(
    tmp_workspace: Path,
    atom_factory: AtomFactory,
    provenance_factory: ProvenanceFactory,
) -> None:
    sub = Substrate(tmp_workspace)
    atom, prov = _atom_with_provenance(atom_factory, provenance_factory)
    sub.add_provenance(atom.source_id, prov)
    result = provenance_completeness(atom, substrate=sub)
    assert result.passed is True
    assert result.validator == "provenance_completeness"
    assert result.subject_id == atom.id


def test_provenance_completeness_fails_when_record_missing(
    tmp_workspace: Path,
    atom_factory: AtomFactory,
    provenance_factory: ProvenanceFactory,
) -> None:
    sub = Substrate(tmp_workspace)
    atom, _ = _atom_with_provenance(atom_factory, provenance_factory)
    # No add_provenance — file is absent.
    result = provenance_completeness(atom, substrate=sub)
    assert result.passed is False
    assert "INV-3 violation" in result.reason
    assert "not found" in result.reason


def test_provenance_completeness_fails_on_entity_id_mismatch(
    tmp_workspace: Path,
    agent: AgentAttribution,
    atom_factory: AtomFactory,
) -> None:
    sub = Substrate(tmp_workspace)
    # Build a provenance record whose entity_id points at a DIFFERENT atom.
    payload: dict[str, Any] = {
        "id": "p-" + "0" * 16,
        "entity_type": "atom",
        "entity_id": "a-some-other-atom",
        "activity": "extract_v1",
        "activity_started_at": datetime(2026, 5, 29, 12, 0, 0, tzinfo=UTC),
        "activity_ended_at": datetime(2026, 5, 29, 12, 0, 3, tzinfo=UTC),
        "used_entity_ids": ["src-fixture-001"],
        "was_attributed_to": agent,
        "was_influenced_by": [],
        "schema_version": 1,
    }
    draft = ProvenanceRecord(**payload)
    payload["id"] = compute_id(draft)
    mismatched_prov = ProvenanceRecord(**payload)
    atom = atom_factory(provenance_id=mismatched_prov.id)
    sub.add_provenance(atom.source_id, mismatched_prov)
    result = provenance_completeness(atom, substrate=sub)
    assert result.passed is False
    assert "entity_id" in result.reason
    assert "does not match" in result.reason
    assert result.subject_id == atom.id


def test_provenance_completeness_fails_on_empty_provenance_id(
    tmp_workspace: Path,
    atom_factory: AtomFactory,
) -> None:
    sub = Substrate(tmp_workspace)
    # An empty provenance_id is rejected by Pydantic? No — Atom only
    # requires non-empty via field semantics, not a min_length constraint.
    # Confirm: build with empty string by way of out-of-band mutation if
    # Pydantic refuses. Try direct construction first.
    a = atom_factory()
    object.__setattr__(a, "provenance_id", "")
    result = provenance_completeness(a, substrate=sub)
    assert result.passed is False
    assert "provenance_id is empty" in result.reason


def test_provenance_completeness_fails_on_corrupt_yaml(
    tmp_workspace: Path,
    atom_factory: AtomFactory,
    provenance_factory: ProvenanceFactory,
) -> None:
    """If a provenance file on disk is unparseable YAML, the validator must
    report a graceful failure rather than raise. This is what lets an
    Auditor walk the substrate without crashing on the first bad file.
    """
    sub = Substrate(tmp_workspace)
    atom, prov = _atom_with_provenance(atom_factory, provenance_factory)
    # Place a valid record first so the parent directory exists, then
    # clobber the file in place with non-YAML garbage.
    sub.add_provenance(atom.source_id, prov)
    path = sub.provenance_path(atom.source_id, atom.provenance_id)
    path.write_text("::: not valid yaml :::\n\t- [unbalanced", encoding="utf-8")
    result = provenance_completeness(atom, substrate=sub)
    assert result.passed is False
    assert result.validator == "provenance_completeness"
    assert result.subject_id == atom.id
    assert "failed to load" in result.reason


def test_provenance_completeness_fails_on_schema_invalid_yaml(
    tmp_workspace: Path,
    atom_factory: AtomFactory,
    provenance_factory: ProvenanceFactory,
) -> None:
    """Parses as YAML but fails ProvenanceRecord schema validation — the
    validator must still degrade gracefully and report INV-3 violation.
    """
    sub = Substrate(tmp_workspace)
    atom, prov = _atom_with_provenance(atom_factory, provenance_factory)
    sub.add_provenance(atom.source_id, prov)
    path = sub.provenance_path(atom.source_id, atom.provenance_id)
    # Valid YAML, missing most required fields → pydantic.ValidationError.
    path.write_text(
        "id: p-abc\nentity_id: wrong-shape\n",
        encoding="utf-8",
    )
    result = provenance_completeness(atom, substrate=sub)
    assert result.passed is False
    assert result.validator == "provenance_completeness"
    assert result.subject_id == atom.id
    assert "failed to load" in result.reason
    assert "schema violation" in result.reason
