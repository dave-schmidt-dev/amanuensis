# pyright: reportUnusedFunction=false
"""Shared fixtures for ``tests/invariants/`` gate tests.

The gate tests in this directory exercise INV-2, INV-3, INV-5, INV-9,
INV-10, INV-12, INV-13, and INV-14 on hand-built fixture substrates
(NOT the M2.1 PDFs — those are vocabulary-design fixtures, not substrate
state). The factories below mirror the patterns in
``tests/validators/conftest.py`` but are re-declared here so this
directory's tests do not implicitly depend on collection order of
``tests/validators/conftest.py``.

The ``vocabulary_subset`` fixture builds a 3-entry hand-rolled
Vocabulary used by the INV-5 "snapshot vs global" gate test: we want a
known-small snapshot whose entries are a strict subset of the vendored
generic registry so we can assert that a predicate in the global
registry but NOT in the snapshot is rejected.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal, cast

import pytest

from amanuensis.fs import Substrate
from amanuensis.fs._atomic import atomic_write_text
from amanuensis.fs._serialize import serialize_yaml
from amanuensis.schemas import (
    AgentAttribution,
    Atom,
    CrossDocRelation,
    Entity,
    EntitySupersede,
    OperandRef,
    OperandTypeSchema,
    ProvenanceRecord,
    Relation,
    Resolution,
    ResolutionSupersede,
    RoleAttribution,
    Vocabulary,
    VocabularyEntry,
    compute_id,
)

# Re-export the CLI test fixtures so the M4.4 INV-4 read-only gate test
# (``test_determinism_boundary.py``) can consume them without redefining
# substrate-setup logic. pytest's conftest discovery is directory-scoped,
# so a fixture defined in ``tests/cli/conftest.py`` is invisible to
# ``tests/invariants/`` by default; re-exporting the names here makes
# them resolvable as parameter-name lookups in this directory's tests.
from tests.cli.conftest import (
    cli_substrate,
    cli_workspace,
    planted_atom,
    planted_clarification,
)
from tests.invariants._types import MatchedAtomFactory

# Explicit re-export ledger so pyright treats the imports above as
# consumed. The fixtures are discovered by pytest by NAME (not by
# import), so the import alone is what makes them visible to tests
# under `tests/invariants/`; `__all__` signals intent to static
# analysis without changing pytest's discovery behavior.
__all__ = [
    "cli_substrate",
    "cli_workspace",
    "planted_atom",
    "planted_clarification",
]

SOURCE_ID = "src-fixture-001"


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    """Empty workspace with the amanuensis.yaml marker (INV-1)."""
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: invariants-test\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def agent() -> AgentAttribution:
    return AgentAttribution(
        kind="llm",
        identifier="claude-opus-4-7",
        role="extractor",
    )


@pytest.fixture
def role_attribution(agent: AgentAttribution) -> RoleAttribution:
    return RoleAttribution(
        agent=agent,
        activity="proposed",
        at=datetime(2026, 5, 29, 12, 0, 0, tzinfo=UTC),
    )


def _operand() -> OperandRef:
    return OperandRef(
        role="obligor",
        kind="entity",
        value="ent-acme-corp",
        type_hint=None,
    )


def _atom_payload(
    role_attribution: RoleAttribution,
    *,
    source_id: str = SOURCE_ID,
    paragraph_index: int = 0,
    char_span: tuple[int, int] = (0, 42),
    predicate: str = "asserts_obligation",
    narrative: str = "ACME shall pay the invoiced amount within 30 days.",
    provenance_id: str = "p-fixture00000001",
) -> dict[str, Any]:
    return {
        "source_id": source_id,
        "section_path": ["Part II", "§3.2", "(a)"],
        "paragraph_index": paragraph_index,
        "sentence_index": None,
        "char_span": char_span,
        "scale_anchor": "paragraph",
        "kind": "claim",
        "predicate": predicate,
        "operands": [_operand()],
        "narrative": narrative,
        "qualifier_level": None,
        "qualifier_basis": None,
        "provenance_id": provenance_id,
        "role_attributions": [role_attribution],
        "schema_version": 1,
    }


def _build_atom(payload: dict[str, Any]) -> Atom:
    payload = dict(payload)
    payload["id"] = "a-" + "0" * 16
    draft = Atom(**payload)
    payload["id"] = compute_id(draft)
    return Atom(**payload)


def _build_provenance(
    agent: AgentAttribution,
    *,
    entity_id: str,
    entity_type: str = "atom",
    source_id: str = SOURCE_ID,
) -> ProvenanceRecord:
    payload: dict[str, Any] = {
        "id": "p-" + "0" * 16,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "activity": "extract_v1",
        "activity_started_at": datetime(2026, 5, 29, 12, 0, 0, tzinfo=UTC),
        "activity_ended_at": datetime(2026, 5, 29, 12, 0, 3, tzinfo=UTC),
        "used_entity_ids": [source_id],
        "was_attributed_to": agent,
        "was_influenced_by": [],
        "schema_version": 1,
    }
    draft = ProvenanceRecord(**payload)
    payload["id"] = compute_id(draft)
    return ProvenanceRecord(**payload)


def _matched_atom_and_provenance(
    role_attribution: RoleAttribution,
    agent: AgentAttribution,
    *,
    source_id: str = SOURCE_ID,
    paragraph_index: int = 0,
    char_span: tuple[int, int] = (0, 42),
    predicate: str = "asserts_obligation",
    narrative: str = "ACME shall pay the invoiced amount within 30 days.",
) -> tuple[Atom, ProvenanceRecord]:
    """Build an Atom + matching ProvenanceRecord whose ids point at each other.

    Because both ids are content-addressable AND provenance_id is volatile
    in Atom's canonical-form hashing (see schemas/atom.py _VOLATILE_FIELDS),
    the atom's id does not depend on its provenance_id. So we can:
      1. Build a draft atom to learn its id.
      2. Build a provenance record whose entity_id = atom.id.
      3. Build the final atom with provenance_id = prov.id.
    """
    draft_atom = _build_atom(
        _atom_payload(
            role_attribution,
            source_id=source_id,
            paragraph_index=paragraph_index,
            char_span=char_span,
            predicate=predicate,
            narrative=narrative,
        )
    )
    prov = _build_provenance(agent, entity_id=draft_atom.id, source_id=source_id)
    atom = _build_atom(
        _atom_payload(
            role_attribution,
            source_id=source_id,
            paragraph_index=paragraph_index,
            char_span=char_span,
            predicate=predicate,
            narrative=narrative,
            provenance_id=prov.id,
        )
    )
    assert atom.id == draft_atom.id, "atom.id depends on volatile provenance_id (regression)"
    return atom, prov


@pytest.fixture
def matched_atom_factory(
    role_attribution: RoleAttribution, agent: AgentAttribution
) -> MatchedAtomFactory:
    """Returns a callable that builds (Atom, ProvenanceRecord) pairs.

    Each call yields a distinct atom (varied by char_span so the content
    hash differs) plus a fresh provenance record whose ``entity_id`` is
    the new atom's id. Use this to build N-atom fixture substrates.
    """

    def _make(
        *,
        source_id: str = SOURCE_ID,
        paragraph_index: int = 0,
        char_span: tuple[int, int] = (0, 42),
        predicate: str = "asserts_obligation",
        narrative: str = "ACME shall pay the invoiced amount within 30 days.",
    ) -> tuple[Atom, ProvenanceRecord]:
        return _matched_atom_and_provenance(
            role_attribution,
            agent,
            source_id=source_id,
            paragraph_index=paragraph_index,
            char_span=char_span,
            predicate=predicate,
            narrative=narrative,
        )

    return _make


def _build_relation(
    role_attribution: RoleAttribution,
    *,
    source_id: str,
    from_atom_id: str,
    to_atom_id: str,
    provenance_id: str = "p-" + "0" * 16,
) -> Relation:
    """Build a Relation with a content-addressable id."""
    payload: dict[str, Any] = {
        "id": "r-" + "0" * 16,
        "source_id": source_id,
        "from_atom_id": from_atom_id,
        "to_atom_id": to_atom_id,
        "kind": "supports",
        "warrant": "The obligation follows from the payment clause.",
        "warrant_defensibility": "conventional",
        "warrant_basis": "standard contract interpretation",
        "confidence": "high",
        "provenance_id": provenance_id,
        "role_attributions": [role_attribution],
        "schema_version": 1,
    }
    draft = Relation(**payload)
    payload["id"] = compute_id(draft)
    return Relation(**payload)


@pytest.fixture
def intra_doc_test_workspace(
    tmp_path: Path,
    role_attribution: RoleAttribution,
    agent: AgentAttribution,
) -> Path:
    """Clean workspace satisfying INV-9: one source, two atoms, one relation.

    The relation's ``source_id``, ``from_atom_id``, and ``to_atom_id`` all
    belong to the same distillation. Walking with ``list_relations`` and
    ``get_atom`` on the same ``src`` must not raise or fail any source-equality
    assertion.
    """
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text("schema_version: 1\nproject_name: inv9-clean\n", encoding="utf-8")
    substrate = Substrate(tmp_path)

    src = "src-inv9-001"
    atom_a, prov_a = _matched_atom_and_provenance(
        role_attribution, agent, source_id=src, char_span=(0, 42)
    )
    atom_b, prov_b = _matched_atom_and_provenance(
        role_attribution, agent, source_id=src, char_span=(100, 142)
    )
    for prov in (prov_a, prov_b):
        substrate.add_provenance(src, prov)
    for atom in (atom_a, atom_b):
        substrate.add_atom(src, atom)

    relation = _build_relation(
        role_attribution, source_id=src, from_atom_id=atom_a.id, to_atom_id=atom_b.id
    )
    substrate.add_relation(src, relation)
    return tmp_path


@pytest.fixture
def cross_source_violation_workspace(
    tmp_path: Path,
    role_attribution: RoleAttribution,
    agent: AgentAttribution,
) -> Path:
    """Deliberately violating workspace: a relation filed under src1 whose
    ``source_id`` field names src2.

    INV-9 requires ``rel.source_id == src`` for every relation yielded by
    ``list_relations(src)``. This fixture bypasses ``Substrate.add_relation``
    (which enforces the check) by writing the YAML file directly, so the
    gate test can confirm the assertion catches the violation.
    """
    from amanuensis.fs._serialize import serialize_yaml

    marker = tmp_path / "amanuensis.yaml"
    marker.write_text("schema_version: 1\nproject_name: inv9-violation\n", encoding="utf-8")
    substrate = Substrate(tmp_path)

    src1 = "src-inv9-v01"
    src2 = "src-inv9-v02"
    atom_a, prov_a = _matched_atom_and_provenance(
        role_attribution, agent, source_id=src1, char_span=(0, 42)
    )
    atom_b, prov_b = _matched_atom_and_provenance(
        role_attribution, agent, source_id=src2, char_span=(100, 142)
    )
    for prov, src in ((prov_a, src1), (prov_b, src2)):
        substrate.add_provenance(src, prov)
    for atom, src in ((atom_a, src1), (atom_b, src2)):
        substrate.add_atom(src, atom)

    # Build a relation that claims to belong to src2 but file it under src1.
    # This is the cross-source violation: the relation's source_id != the
    # distillation directory it lives under.
    bad_relation = _build_relation(
        role_attribution,
        source_id=src2,  # <-- wrong: filed under src1, claims src2
        from_atom_id=atom_a.id,
        to_atom_id=atom_b.id,
    )
    # Write directly, bypassing the source_id guard in add_relation.
    relation_dir = tmp_path / "distillations" / src1 / "relations"
    relation_dir.mkdir(parents=True, exist_ok=True)
    (relation_dir / f"{bad_relation.id}.yaml").write_text(
        serialize_yaml(bad_relation), encoding="utf-8"
    )
    return tmp_path


@pytest.fixture
def clean_workspace(tmp_path: Path) -> Path:
    """Workspace with amanuensis.yaml and no forbidden harness files at root.

    Used by the INV-2 gate test to confirm a clean project passes.
    """
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text("schema_version: 1\nproject_name: inv2-clean\n", encoding="utf-8")
    return tmp_path


@pytest.fixture
def workspace_with_hand_authored_readme(tmp_path: Path) -> Path:
    """Workspace where ``mappings/README.md`` lacks the generator marker.

    Simulates a hand-authored README inside the ``mappings/`` directory
    (the file exists but does NOT contain the
    ``<!-- amanuensis-generated: do not edit -->`` marker). The INV-2 gate
    test treats such a file as a violation of the "no hand-authored docs at
    harness-adjacent paths" discipline.
    """
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text("schema_version: 1\nproject_name: inv2-hand-readme\n", encoding="utf-8")
    mappings_dir = tmp_path / "mappings"
    mappings_dir.mkdir(parents=True, exist_ok=True)
    (mappings_dir / "README.md").write_text(
        "# mappings\n\nThis is a hand-authored README without the generator marker.\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def workspace_with_marker_readme(tmp_path: Path) -> Path:
    """Workspace where ``mappings/README.md`` carries the generator marker.

    Simulates a README produced by ``Substrate.ensure_mappings_readme``.
    The INV-2 gate test confirms this variant passes (marker = generator-owned).
    """
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text("schema_version: 1\nproject_name: inv2-marker-readme\n", encoding="utf-8")
    substrate = Substrate(tmp_path)
    substrate.ensure_mappings_readme()
    return tmp_path


@pytest.fixture
def vocabulary_subset() -> Vocabulary:
    """A small 3-entry vocabulary whose predicates are a STRICT SUBSET of
    the vendored generic registry (``vocabularies/generic/predicates.yaml``).

    Used by the INV-5 snapshot-vs-global gate test: a predicate that
    appears in the global registry but NOT in this subset must be rejected
    when the validator routes its lookup through the snapshot. The three
    entries (``asserts_obligation``, ``asserts_factual_event``,
    ``cites_evidence``) are all real predicates from the generic registry;
    aliases are kept minimal so the subset stays small and deliberate.
    """
    return Vocabulary(
        name="invariants-subset-v0.1",
        version="0.1.0",
        entries=[
            VocabularyEntry(
                predicate="asserts_obligation",
                aliases=["asserts_shall"],
                operand_types=[
                    OperandTypeSchema(name="obligor", kind="entity", required=True),
                ],
                qualifier_required=False,
                notes="subset for INV-5 gate test",
            ),
            VocabularyEntry(
                predicate="asserts_factual_event",
                aliases=[],
                operand_types=[],
                qualifier_required=False,
                notes="subset for INV-5 gate test",
            ),
            VocabularyEntry(
                predicate="cites_evidence",
                aliases=[],
                operand_types=[],
                qualifier_required=False,
                notes="subset for INV-5 gate test",
            ),
        ],
    )


# ---------------------------------------------------------------------------
# Phase 2a helpers — Entity / Resolution / Supersede builders
# ---------------------------------------------------------------------------

_STABLE_AT = datetime(2026, 5, 31, 12, 0, 0, tzinfo=UTC)


def _build_mappings_provenance(
    agent: AgentAttribution,
    *,
    entity_id: str,
    entity_type: str,
) -> ProvenanceRecord:
    """Build a ProvenanceRecord for a mappings-layer artifact.

    Uses a fixed timestamp so content hashes are stable across test runs.
    """
    payload: dict[str, Any] = {
        "id": "p-" + "0" * 16,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "activity": "map-resolve",
        "activity_started_at": _STABLE_AT,
        "activity_ended_at": _STABLE_AT,
        "used_entity_ids": [],
        "was_attributed_to": agent,
        "was_influenced_by": [],
        "schema_version": 1,
    }
    draft = ProvenanceRecord(**payload)
    payload["id"] = compute_id(draft)
    return ProvenanceRecord(**payload)


def _build_entity(
    role_attribution: RoleAttribution,
    agent: AgentAttribution,
    *,
    canonical_name: str = "ACME Corp",
    kind: str = "organization",
    aliases: list[str] | None = None,
) -> tuple[Entity, ProvenanceRecord]:
    """Build an Entity + matching ProvenanceRecord.

    Returns (entity, prov) where entity.provenance_id == prov.id and
    prov.entity_id == entity.id.
    """
    if aliases is None:
        aliases = []
    entity_draft = Entity(
        id="e-" + "0" * 16,
        kind=kind,
        canonical_name=canonical_name,
        aliases=aliases,
        notes=None,
        provenance_id="p-" + "0" * 16,
        role_attributions=[role_attribution],
        schema_version=1,
    )
    entity_id = compute_id(entity_draft)
    prov = _build_mappings_provenance(agent, entity_id=entity_id, entity_type="entity")
    entity = Entity(
        id=entity_id,
        kind=kind,
        canonical_name=canonical_name,
        aliases=aliases,
        notes=None,
        provenance_id=prov.id,
        role_attributions=[role_attribution],
        schema_version=1,
    )
    return entity, prov


def _build_resolution(
    role_attribution: RoleAttribution,
    agent: AgentAttribution,
    *,
    source_id: str,
    atom_id: str,
    entity_id: str,
    operand_index: int = 0,
    confidence: str = "high",
    basis: str = "name match",
) -> tuple[Resolution, ProvenanceRecord]:
    """Build a Resolution + matching ProvenanceRecord."""
    confidence_lit = cast("Literal['high', 'medium', 'low']", confidence)
    res_draft = Resolution(
        id="j-" + "0" * 16,
        source_id=source_id,
        atom_id=atom_id,
        operand_index=operand_index,
        entity_id=entity_id,
        confidence=confidence_lit,
        basis=basis,
        provenance_id="p-" + "0" * 16,
        role_attributions=[role_attribution],
        schema_version=1,
    )
    resolution_id = compute_id(res_draft)
    prov = _build_mappings_provenance(agent, entity_id=resolution_id, entity_type="resolution")
    resolution = Resolution(
        id=resolution_id,
        source_id=source_id,
        atom_id=atom_id,
        operand_index=operand_index,
        entity_id=entity_id,
        confidence=confidence_lit,
        basis=basis,
        provenance_id=prov.id,
        role_attributions=[role_attribution],
        schema_version=1,
    )
    return resolution, prov


def _build_resolution_supersede(
    role_attribution: RoleAttribution,
    agent: AgentAttribution,
    *,
    superseded_resolution_id: str,
    replacement_resolution_id: str,
    reason: str = "supervisor correction",
) -> tuple[ResolutionSupersede, ProvenanceRecord]:
    """Build a ResolutionSupersede + matching ProvenanceRecord."""
    rs_draft = ResolutionSupersede(
        id="s-" + "0" * 16,
        superseded_resolution_id=superseded_resolution_id,
        replacement_resolution_id=replacement_resolution_id,
        reason=reason,
        provenance_id="p-" + "0" * 16,
        role_attributions=[role_attribution],
        schema_version=1,
    )
    rs_id = compute_id(rs_draft)
    prov = _build_mappings_provenance(agent, entity_id=rs_id, entity_type="resolution-supersede")
    rs = ResolutionSupersede(
        id=rs_id,
        superseded_resolution_id=superseded_resolution_id,
        replacement_resolution_id=replacement_resolution_id,
        reason=reason,
        provenance_id=prov.id,
        role_attributions=[role_attribution],
        schema_version=1,
    )
    return rs, prov


def _build_entity_supersede(
    role_attribution: RoleAttribution,
    agent: AgentAttribution,
    *,
    superseded_entity_id: str,
    replacement_entity_id: str,
    reason: str = "supervisor merge",
) -> tuple[EntitySupersede, ProvenanceRecord]:
    """Build an EntitySupersede + matching ProvenanceRecord."""
    es_draft = EntitySupersede(
        id="t-" + "0" * 16,
        superseded_entity_id=superseded_entity_id,
        replacement_entity_id=replacement_entity_id,
        reason=reason,
        provenance_id="p-" + "0" * 16,
        role_attributions=[role_attribution],
        schema_version=1,
    )
    es_id = compute_id(es_draft)
    prov = _build_mappings_provenance(agent, entity_id=es_id, entity_type="entity-supersede")
    es = EntitySupersede(
        id=es_id,
        superseded_entity_id=superseded_entity_id,
        replacement_entity_id=replacement_entity_id,
        reason=reason,
        provenance_id=prov.id,
        role_attributions=[role_attribution],
        schema_version=1,
    )
    return es, prov


# ---------------------------------------------------------------------------
# Phase 2a fixture: populated_mappings_workspace (INV-12 / INV-13 / INV-3)
# ---------------------------------------------------------------------------

_MAPPINGS_SOURCE_ID = "src-mappings-001"
_MAPPINGS_ATOM_ID = "a-" + "deadbeef" * 2


@pytest.fixture
def populated_mappings_workspace(
    tmp_path: Path,
    role_attribution: RoleAttribution,
    agent: AgentAttribution,
) -> Path:
    """Workspace with one distillation, one entity, and one resolution.

    The distillation entry exists so ``list_distillations()`` returns the
    source_id. The entity and resolution are written via the canonical
    Substrate methods (so all content-addressable constraints hold).
    Provenance records are written to ``mappings/provenance/``.
    """
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: inv12-mappings\n",
        encoding="utf-8",
    )
    substrate = Substrate(tmp_path)

    # Create the distillation directory so list_distillations() returns it.
    dist_dir = tmp_path / "distillations" / _MAPPINGS_SOURCE_ID
    dist_dir.mkdir(parents=True, exist_ok=True)

    entity, entity_prov = _build_entity(role_attribution, agent)
    resolution, res_prov = _build_resolution(
        role_attribution,
        agent,
        source_id=_MAPPINGS_SOURCE_ID,
        atom_id=_MAPPINGS_ATOM_ID,
        entity_id=entity.id,
    )

    # Write provenance to mappings/provenance/.
    for prov in (entity_prov, res_prov):
        prov_path = substrate.mappings_provenance_path(prov.id)
        atomic_write_text(prov_path, serialize_yaml(prov))

    substrate.add_entity(entity)
    substrate.add_resolution(resolution)

    return tmp_path


# ---------------------------------------------------------------------------
# Phase 2a fixture: cross_doc_violation_workspace (INV-12 — endpoint mismatch)
# ---------------------------------------------------------------------------


@pytest.fixture
def cross_doc_violation_workspace(
    tmp_path: Path,
    role_attribution: RoleAttribution,
    agent: AgentAttribution,
) -> Path:
    """Workspace where a relation under src1 claims a from_atom_id from src2.

    Plants two distillations; builds an atom in each. Then writes a
    relation under src1's directory whose ``from_atom_id`` belongs to
    src2 (bypassing the add_relation guard). This violates the
    intra-doc-only invariant (INV-9) and is the namespace-scope variant
    the INV-12 gate test walks.
    """
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: inv12-xdoc-violation\n",
        encoding="utf-8",
    )
    substrate = Substrate(tmp_path)

    src1 = "src-inv12-v01"
    src2 = "src-inv12-v02"

    atom_a, prov_a = _matched_atom_and_provenance(
        role_attribution, agent, source_id=src1, char_span=(0, 42)
    )
    atom_b, prov_b = _matched_atom_and_provenance(
        role_attribution, agent, source_id=src2, char_span=(100, 142)
    )
    for prov, src in ((prov_a, src1), (prov_b, src2)):
        substrate.add_provenance(src, prov)
    for atom, src in ((atom_a, src1), (atom_b, src2)):
        substrate.add_atom(src, atom)

    # Build a relation claimed under src1 but whose from_atom belongs to src2.
    bad_relation = _build_relation(
        role_attribution,
        source_id=src1,
        from_atom_id=atom_b.id,  # atom_b belongs to src2 — mismatch
        to_atom_id=atom_a.id,
    )
    relation_dir = tmp_path / "distillations" / src1 / "relations"
    relation_dir.mkdir(parents=True, exist_ok=True)
    (relation_dir / f"{bad_relation.id}.yaml").write_text(
        serialize_yaml(bad_relation), encoding="utf-8"
    )
    return tmp_path


# ---------------------------------------------------------------------------
# Phase 2b INV-15 fixtures (M3 — invariant gate)
# ---------------------------------------------------------------------------
#
# The fixtures below build workspaces that intentionally bypass
# Substrate.add_cross_doc_relation by writing tampered YAML directly.
# Each tampered relation still satisfies content-addressability (its id is
# the hash of its on-disk content) so the substrate's id check at re-walk
# time passes — only the INV-15 gate fires.

_INV15_ENTITY_ID = "e-smith"
_INV15_FROM_SOURCE = "src-A"
_INV15_FROM_ATOM = "a-fixture0001"
_INV15_TO_SOURCE = "src-B"
_INV15_TO_ATOM = "a-fixture0002"


def _inv15_forged_entity(entity_id: str, role_attribution: RoleAttribution) -> Entity:
    """Build an Entity with a literal id (bypasses content-addressability)."""
    return Entity(
        id=entity_id,
        kind="party",
        canonical_name="Smith",
        aliases=[],
        notes=None,
        provenance_id="p-inv15-ent",
        role_attributions=[role_attribution],
        schema_version=1,
    )


def _inv15_forged_resolution(
    *,
    resolution_id: str,
    source_id: str,
    atom_id: str,
    entity_id: str,
    role_attribution: RoleAttribution,
) -> Resolution:
    """Build a Resolution with a literal id (bypasses content-addressability)."""
    return Resolution(
        id=resolution_id,
        source_id=source_id,
        atom_id=atom_id,
        operand_index=0,
        entity_id=entity_id,
        confidence="high",
        basis="fixture-planted for INV-15 invariant gate",
        provenance_id="p-inv15-res",
        role_attributions=[role_attribution],
        schema_version=1,
    )


def _inv15_plant_entity(tmp_path: Path, entity: Entity) -> None:
    from amanuensis.fs._serialize import serialize_entity_md

    path = tmp_path / "mappings" / "entities" / f"{entity.id}.md"
    atomic_write_text(path, serialize_entity_md(entity))


def _inv15_plant_resolution(tmp_path: Path, resolution: Resolution) -> None:
    from amanuensis.fs._serialize import serialize_resolution_yaml

    path = tmp_path / "mappings" / "resolutions" / f"{resolution.id}.yaml"
    atomic_write_text(path, serialize_resolution_yaml(resolution))


def _inv15_build_relation(
    role_attribution: RoleAttribution,
    *,
    shared_entities: list[str],
    from_source_id: str = _INV15_FROM_SOURCE,
    from_atom_id: str = _INV15_FROM_ATOM,
    to_source_id: str = _INV15_TO_SOURCE,
    to_atom_id: str = _INV15_TO_ATOM,
) -> CrossDocRelation:
    """Build a CrossDocRelation whose id matches ``compute_id`` for its content."""
    payload: dict[str, Any] = {
        "id": "x-" + "0" * 16,
        "from_atom_id": from_atom_id,
        "from_source_id": from_source_id,
        "to_atom_id": to_atom_id,
        "to_source_id": to_source_id,
        "kind": "supports",
        "warrant": "Both atoms refer to the same Smith party.",
        "warrant_defensibility": "conventional",
        "warrant_basis": "Naming conventions match across documents.",
        "confidence": "medium",
        "shared_entities": shared_entities,
        "provenance_id": "p-inv15-cdr",
        "role_attributions": [role_attribution],
        "schema_version": 1,
    }
    draft = CrossDocRelation(**payload)
    payload["id"] = compute_id(draft)
    return CrossDocRelation(**payload)


def _inv15_plant_cross_doc_relation(tmp_path: Path, rel: CrossDocRelation) -> None:
    """Write a CrossDocRelation YAML directly, bypassing the substrate gate."""
    from amanuensis.fs._serialize import serialize_cross_doc_relation_yaml

    path = tmp_path / "mappings" / "relations" / f"{rel.id}.yaml"
    atomic_write_text(path, serialize_cross_doc_relation_yaml(rel))


def _inv15_workspace_with_marker(tmp_path: Path, project_name: str) -> Path:
    """Create a workspace with the INV-1 marker file."""
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(
        f"schema_version: 1\nproject_name: {project_name}\n",
        encoding="utf-8",
    )
    return tmp_path


@pytest.fixture
def tmp_workspace_with_one_valid_cross_doc_relation(
    tmp_path: Path, role_attribution: RoleAttribution
) -> Path:
    """Workspace with bilateral resolutions + one valid cross-doc edge."""
    workspace = _inv15_workspace_with_marker(tmp_path, "inv15-valid")
    entity = _inv15_forged_entity(_INV15_ENTITY_ID, role_attribution)
    _inv15_plant_entity(workspace, entity)
    _inv15_plant_resolution(
        workspace,
        _inv15_forged_resolution(
            resolution_id="j-inv15-from",
            source_id=_INV15_FROM_SOURCE,
            atom_id=_INV15_FROM_ATOM,
            entity_id=_INV15_ENTITY_ID,
            role_attribution=role_attribution,
        ),
    )
    _inv15_plant_resolution(
        workspace,
        _inv15_forged_resolution(
            resolution_id="j-inv15-to",
            source_id=_INV15_TO_SOURCE,
            atom_id=_INV15_TO_ATOM,
            entity_id=_INV15_ENTITY_ID,
            role_attribution=role_attribution,
        ),
    )
    rel = _inv15_build_relation(role_attribution, shared_entities=[_INV15_ENTITY_ID])
    _inv15_plant_cross_doc_relation(workspace, rel)
    return workspace


@pytest.fixture
def tmp_workspace_with_manually_authored_empty_shared_entities(
    tmp_path: Path, role_attribution: RoleAttribution
) -> Path:
    """Workspace with a CrossDocRelation whose ``shared_entities`` is empty.

    Bilateral resolutions exist (so the only violation is the empty list).
    """
    workspace = _inv15_workspace_with_marker(tmp_path, "inv15-empty-shared")
    entity = _inv15_forged_entity(_INV15_ENTITY_ID, role_attribution)
    _inv15_plant_entity(workspace, entity)
    _inv15_plant_resolution(
        workspace,
        _inv15_forged_resolution(
            resolution_id="j-inv15-from",
            source_id=_INV15_FROM_SOURCE,
            atom_id=_INV15_FROM_ATOM,
            entity_id=_INV15_ENTITY_ID,
            role_attribution=role_attribution,
        ),
    )
    _inv15_plant_resolution(
        workspace,
        _inv15_forged_resolution(
            resolution_id="j-inv15-to",
            source_id=_INV15_TO_SOURCE,
            atom_id=_INV15_TO_ATOM,
            entity_id=_INV15_ENTITY_ID,
            role_attribution=role_attribution,
        ),
    )
    rel = _inv15_build_relation(role_attribution, shared_entities=[])
    _inv15_plant_cross_doc_relation(workspace, rel)
    return workspace


@pytest.fixture
def tmp_workspace_with_dangling_shared_entity_on_disk(
    tmp_path: Path, role_attribution: RoleAttribution
) -> Path:
    """Workspace whose CrossDocRelation references an entity with no record on disk."""
    workspace = _inv15_workspace_with_marker(tmp_path, "inv15-dangling-entity")
    # No entity records planted.
    rel = _inv15_build_relation(role_attribution, shared_entities=["e-nonexistent"])
    _inv15_plant_cross_doc_relation(workspace, rel)
    return workspace


@pytest.fixture
def tmp_workspace_with_unresolved_from_endpoint_on_disk(
    tmp_path: Path, role_attribution: RoleAttribution
) -> Path:
    """Workspace where the from-endpoint Resolution is missing."""
    workspace = _inv15_workspace_with_marker(tmp_path, "inv15-no-from-res")
    entity = _inv15_forged_entity(_INV15_ENTITY_ID, role_attribution)
    _inv15_plant_entity(workspace, entity)
    # Only the to-endpoint resolution.
    _inv15_plant_resolution(
        workspace,
        _inv15_forged_resolution(
            resolution_id="j-inv15-to",
            source_id=_INV15_TO_SOURCE,
            atom_id=_INV15_TO_ATOM,
            entity_id=_INV15_ENTITY_ID,
            role_attribution=role_attribution,
        ),
    )
    rel = _inv15_build_relation(role_attribution, shared_entities=[_INV15_ENTITY_ID])
    _inv15_plant_cross_doc_relation(workspace, rel)
    return workspace


@pytest.fixture
def tmp_workspace_with_unresolved_to_endpoint_on_disk(
    tmp_path: Path, role_attribution: RoleAttribution
) -> Path:
    """Workspace where the to-endpoint Resolution is missing (mirror)."""
    workspace = _inv15_workspace_with_marker(tmp_path, "inv15-no-to-res")
    entity = _inv15_forged_entity(_INV15_ENTITY_ID, role_attribution)
    _inv15_plant_entity(workspace, entity)
    _inv15_plant_resolution(
        workspace,
        _inv15_forged_resolution(
            resolution_id="j-inv15-from",
            source_id=_INV15_FROM_SOURCE,
            atom_id=_INV15_FROM_ATOM,
            entity_id=_INV15_ENTITY_ID,
            role_attribution=role_attribution,
        ),
    )
    rel = _inv15_build_relation(role_attribution, shared_entities=[_INV15_ENTITY_ID])
    _inv15_plant_cross_doc_relation(workspace, rel)
    return workspace


# ---------------------------------------------------------------------------
# Phase 2b INV-9 extension — cross-doc files under distillations/ rejected
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_workspace_with_cross_doc_in_wrong_place(tmp_path: Path) -> Path:
    """Workspace with a stray ``x-*.yaml`` filed under ``distillations/<src>/relations/``.

    The file's content is irrelevant — the INV-9 walker trips on the
    ``x-`` prefix in a per-distillation ``relations/`` directory (cross-
    doc edges belong in ``mappings/relations/``).
    """
    workspace = _inv15_workspace_with_marker(tmp_path, "inv9-cross-doc-misplaced")
    stray = workspace / "distillations" / "src-A" / "relations" / "x-fake000000000000.yaml"
    stray.parent.mkdir(parents=True, exist_ok=True)
    stray.write_text("# placeholder — content irrelevant to INV-9\n", encoding="utf-8")
    return workspace
