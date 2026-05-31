# pyright: reportPrivateUsage=false
"""Gate test for INV-3 (Provenance by construction).

Quoting INVARIANTS.md INV-3 verbatim:

    Every substrate artifact (atom, relation, finding, prose span,
    clarification resolution, iteration directive) has a PROV-O record
    recording who created it, what activity, what it used, and (for LLM
    contributions) which model. Retrofitted provenance is rejected.

What this gate certifies
------------------------
Walks a hand-built fixture substrate; for every atom, runs the M2.4
``provenance_completeness`` validator and asserts it passes. The
negative cases (missing PROV file, mismatched entity_id) demonstrate
that the gate catches INV-3 violations rather than silently passing.

Phase 2a extension (IA-4, T10.4)
---------------------------------
Four parametrized cases extend the gate to ``mappings/`` artifacts:

- entity with a valid provenance record passes.
- entity whose provenance_id file is missing fails.
- resolution with a valid provenance record passes.
- resolution whose provenance_id file is missing fails.

The mappings-layer provenance lives at
``mappings/provenance/p-<hash>.yaml`` (``substrate.mappings_provenance_path``),
not in ``distillations/<src>/provenance/``. The inline walker
``_check_mappings_provenance`` covers this path.

Scope boundary
--------------
M2.5 scopes the atom walk to atoms only. INV-3 extends to relations,
clarification raised/resolved events, and iteration issued/applied
events.

TODO(M3-M9): extend ``_walk_substrate_atoms_and_validate`` (or add
``_walk_substrate_relations_and_validate`` /
``_walk_substrate_clarifications_and_validate`` /
``_walk_substrate_iterations_and_validate``) once the ingest paths for
those entities are exercised in later milestones (M3 source-mirror, M6
clarifications, M5 iterations, M7 auditor). The full INV-3 walk also
needs to cover ``substrate.list_relations`` etc., which don't exist
yet — adding them is left to the milestone that introduces the matching
write path.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from amanuensis.fs import Substrate
from amanuensis.fs._atomic import atomic_write_text
from amanuensis.fs._serialize import parse_provenance_yaml, serialize_yaml
from amanuensis.schemas import AgentAttribution, Atom, ProvenanceRecord, RoleAttribution, compute_id
from amanuensis.validators import ValidationResult, provenance_completeness
from tests.invariants._types import MatchedAtomFactory
from tests.invariants.conftest import (
    _MAPPINGS_ATOM_ID,
    _MAPPINGS_SOURCE_ID,
    _build_entity,
    _build_resolution,
)

SOURCE_ID = "src-fixture-001"


def _walk_substrate_atoms_and_validate(
    substrate: Substrate, source_id: str
) -> list[ValidationResult]:
    """Walk every atom under ``source_id``; return one ValidationResult per atom.

    This is the canonical INV-3 walk pattern an auditor would use: a
    pure traversal of the substrate that yields a uniform list of
    ``ValidationResult``s downstream code can aggregate / surface.
    """
    return [
        provenance_completeness(atom, substrate=substrate)
        for atom in substrate.list_atoms(source_id)
    ]


@pytest.mark.invariants
def test_inv3_clean_substrate_passes(
    tmp_workspace: Path, matched_atom_factory: MatchedAtomFactory
) -> None:
    """Positive: five atoms each with a matching PROV record — all pass."""
    substrate = Substrate(tmp_workspace)
    # Vary char_span across atoms so their content hashes differ; pair
    # each atom with the matching provenance record produced by the
    # factory and write both to the substrate.
    for i in range(5):
        atom, prov = matched_atom_factory(char_span=(i * 100, i * 100 + 42))
        substrate.add_provenance(SOURCE_ID, prov)
        substrate.add_atom(SOURCE_ID, atom)

    results = _walk_substrate_atoms_and_validate(substrate, SOURCE_ID)
    assert len(results) == 5
    assert all(r.passed for r in results), [r for r in results if not r.passed]
    assert all(r.validator == "provenance_completeness" for r in results)


@pytest.mark.invariants
def test_inv3_missing_provenance_fails(
    tmp_workspace: Path, matched_atom_factory: MatchedAtomFactory
) -> None:
    """Negative: an atom whose provenance_id points to a non-existent file fails."""
    substrate = Substrate(tmp_workspace)
    atom, _prov = matched_atom_factory()
    # Intentionally do NOT write the matching provenance record.
    substrate.add_atom(SOURCE_ID, atom)

    results = _walk_substrate_atoms_and_validate(substrate, SOURCE_ID)
    failures = [r for r in results if not r.passed]
    assert len(failures) == 1
    assert "INV-3 violation" in failures[0].reason
    assert "not found" in failures[0].reason
    assert failures[0].subject_id == atom.id


@pytest.mark.invariants
def test_inv3_mismatched_entity_id_fails(
    tmp_workspace: Path,
    matched_atom_factory: MatchedAtomFactory,
    agent: AgentAttribution,
) -> None:
    """Negative: a provenance record whose entity_id != atom.id is rejected.

    Build atom A; build a provenance record P whose entity_id points at a
    DIFFERENT atom id; write atom A with provenance_id = P.id. The walk
    must surface exactly one failure naming the entity_id mismatch.
    """
    substrate = Substrate(tmp_workspace)
    # Build a real "other atom" id by going through compute_id so the
    # mismatch is testably realistic (not a fabricated-looking string).
    other_atom, _other_prov = matched_atom_factory(char_span=(999, 1042))

    # Manually construct a provenance record whose entity_id points at
    # ``other_atom.id`` rather than at the atom that will claim it.
    payload: dict[str, Any] = {
        "id": "p-" + "0" * 16,
        "entity_type": "atom",
        "entity_id": other_atom.id,
        "activity": "extract_v1",
        "activity_started_at": datetime(2026, 5, 29, 12, 0, 0, tzinfo=UTC),
        "activity_ended_at": datetime(2026, 5, 29, 12, 0, 3, tzinfo=UTC),
        "used_entity_ids": [SOURCE_ID],
        "was_attributed_to": agent,
        "was_influenced_by": [],
        "schema_version": 1,
    }
    draft = ProvenanceRecord(**payload)
    payload["id"] = compute_id(draft)
    mismatched_prov = ProvenanceRecord(**payload)

    # Build the atom we WILL write, pointing at the mismatched prov record.
    atom, _ = matched_atom_factory()
    # We need atom.provenance_id = mismatched_prov.id; provenance_id is
    # volatile so atom.id is unchanged. Use object.__setattr__ to bypass
    # Pydantic's frozen-ish guard the same way M2.4's tests do.
    rebuilt_atom = _rebuild_atom_with_provenance_id(atom, mismatched_prov.id)

    substrate.add_provenance(SOURCE_ID, mismatched_prov)
    substrate.add_atom(SOURCE_ID, rebuilt_atom)

    results = _walk_substrate_atoms_and_validate(substrate, SOURCE_ID)
    failures = [r for r in results if not r.passed]
    assert len(failures) == 1
    assert "INV-3 violation" in failures[0].reason
    assert "entity_id" in failures[0].reason
    assert "does not match" in failures[0].reason
    assert failures[0].subject_id == rebuilt_atom.id


def _rebuild_atom_with_provenance_id(atom: Atom, provenance_id: str) -> Atom:
    """Rebuild ``atom`` with a different ``provenance_id``.

    Because ``provenance_id`` is volatile in Atom's canonical-form
    hashing, re-validating with the new pointer yields an Atom with the
    SAME id but a different provenance pointer. We re-validate via
    ``model_validate`` (not ``object.__setattr__``) so the resulting
    instance is structurally clean and survives downstream re-dumps.
    """
    payload = atom.model_dump()
    payload["provenance_id"] = provenance_id
    return Atom.model_validate(payload)


# ---------------------------------------------------------------------------
# Phase 2a extension — mappings/ provenance completeness (IA-4, T10.4)
# ---------------------------------------------------------------------------


def _check_mappings_provenance(
    substrate: Substrate,
    artifact_id: str,
    provenance_id: str,
) -> tuple[bool, str]:
    """Check that a mappings-layer artifact has a valid provenance record.

    Returns ``(passed, reason)`` — mirrors the shape of
    ``ValidationResult`` without importing it for this inline walker.

    A record is valid when:
    - The provenance file exists at ``mappings/provenance/<prov_id>.yaml``.
    - It parses without error.
    - Its ``entity_id`` matches ``artifact_id``.
    """
    prov_path = substrate.mappings_provenance_path(provenance_id)
    if not prov_path.is_file():
        return (
            False,
            f"INV-3 violation: mappings provenance file missing for "
            f"{artifact_id!r} (expected {prov_path})",
        )
    try:
        prov = parse_provenance_yaml(prov_path.read_text(encoding="utf-8"))
    except Exception as exc:
        return (
            False,
            f"INV-3 violation: mappings provenance for {artifact_id!r} failed to parse: {exc}",
        )
    if prov.entity_id != artifact_id:
        return (
            False,
            f"INV-3 violation: mappings provenance entity_id={prov.entity_id!r} "
            f"does not match artifact id={artifact_id!r}",
        )
    return True, ""


@pytest.mark.parametrize(
    "artifact_type,with_prov,expected_pass",
    [
        ("entity", True, True),
        ("entity", False, False),
        ("resolution", True, True),
        ("resolution", False, False),
    ],
    ids=[
        "entity-valid-prov",
        "entity-missing-prov",
        "resolution-valid-prov",
        "resolution-missing-prov",
    ],
)
@pytest.mark.invariants
def test_inv3_mappings_provenance_completeness(
    tmp_path: Path,
    role_attribution: object,
    agent: object,
    artifact_type: str,
    with_prov: bool,
    expected_pass: bool,
) -> None:
    """INV-3 gate extended to mappings/ entities and resolutions (Phase 2a IA-4).

    For each artifact type (entity, resolution) and provenance state
    (present, absent), asserts that the ``_check_mappings_provenance``
    walker returns the expected pass/fail result.
    """
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: inv3-mappings-prov\n",
        encoding="utf-8",
    )
    s = Substrate(tmp_path)

    agent_obj = AgentAttribution(
        kind="llm",
        identifier="claude-opus-4-7",
        role="map-resolve",
    )
    ra = RoleAttribution(
        agent=agent_obj,
        activity="proposed",
        at=datetime(2026, 5, 31, 12, 0, 0, tzinfo=UTC),
    )

    entity, entity_prov = _build_entity(ra, agent_obj)

    if artifact_type == "entity":
        if with_prov:
            atomic_write_text(
                s.mappings_provenance_path(entity_prov.id), serialize_yaml(entity_prov)
            )
        s.add_entity(entity)
        passed, reason = _check_mappings_provenance(s, entity.id, entity.provenance_id)
    else:
        # resolution: entity prov is always written so add_entity succeeds.
        atomic_write_text(s.mappings_provenance_path(entity_prov.id), serialize_yaml(entity_prov))
        s.add_entity(entity)

        resolution, res_prov = _build_resolution(
            ra,
            agent_obj,
            source_id=_MAPPINGS_SOURCE_ID,
            atom_id=_MAPPINGS_ATOM_ID,
            entity_id=entity.id,
        )
        if with_prov:
            atomic_write_text(s.mappings_provenance_path(res_prov.id), serialize_yaml(res_prov))
        s.add_resolution(resolution)
        passed, reason = _check_mappings_provenance(s, resolution.id, resolution.provenance_id)

    assert passed == expected_pass, (
        f"artifact_type={artifact_type!r} with_prov={with_prov}: "
        f"expected passed={expected_pass!r} but got passed={passed!r} "
        f"(reason: {reason!r})"
    )
