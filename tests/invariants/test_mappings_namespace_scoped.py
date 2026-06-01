# pyright: reportPrivateUsage=false
"""Gate test for INV-12 (mappings/ is the home for all cross-document artifacts).

Quoting the Phase 2a design spec INV-12 verbatim:

    No cross-source artifact (entity record, resolution record,
    cross-doc relation [Phase 2b], probandum hierarchy [Phase 2c]) is
    permitted outside ``mappings/``. Per-distillation directories remain
    intra-doc.

What this gate certifies
------------------------
Three cases:

1. A clean workspace with one entity, one resolution, and one distillation
   passes: all relations in distillations/ are intra-source, and every
   resolution's source_id names an existing distillation.

2. A workspace where a relation filed under src1 references an atom from
   src2 (``from_atom_id`` belongs to src2) is detected. The gate walks
   all relations in distillations/ and fails if any endpoint atom belongs
   to a different source.

3. A workspace where a resolution references a source_id that has no
   matching distillation directory is detected. This catches the case
   where a reconcile wrote mappings/ artifacts but the corresponding
   distillation was never created.

Scope
-----
Fixture substrates are hand-built (not derived from M2.1 PDFs). Gate
lives in ``tests/invariants/`` and is wired into ``pytest -m invariants``.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from amanuensis.fs import Substrate
from amanuensis.fs._atomic import atomic_write_text
from amanuensis.fs._serialize import serialize_yaml
from amanuensis.schemas import AgentAttribution, RoleAttribution
from tests.invariants.conftest import (
    _MAPPINGS_ATOM_ID,
    _build_entity,
    _build_resolution,
)

pytestmark = pytest.mark.invariants

# Stable timestamp used in all test-local constructions.
_AT = datetime(2026, 5, 31, 12, 0, 0, tzinfo=UTC)


# ---------------------------------------------------------------------------
# Case 1: Clean workspace — all mappings in the right places
# ---------------------------------------------------------------------------


def test_mappings_namespace_clean(populated_mappings_workspace: Path) -> None:
    """Positive: a workspace with proper entity/resolution in mappings/ passes.

    Verifies:
    - Every relation in distillations/ is intra-source (from_atom and
      to_atom both belong to the relation's source_id).
    - Every resolution's source_id names an existing distillation.
    """
    s = Substrate(populated_mappings_workspace)
    distillations = set(s.list_distillations())

    # Build atom_id → source_id index across all distillations.
    atom_source: dict[str, str] = {}
    for src in distillations:
        for atom in s.list_atoms(src):
            atom_source[atom.id] = src

    # Walk distillations/ — all relations must be intra-source.
    for src in distillations:
        for rel in s.list_relations(src):
            from_src = atom_source.get(rel.from_atom_id)
            to_src = atom_source.get(rel.to_atom_id)
            assert from_src == src, (
                f"Relation {rel.id!r} filed under {src!r} but from_atom "
                f"belongs to {from_src!r} (INV-12)"
            )
            assert to_src == src, (
                f"Relation {rel.id!r} filed under {src!r} but to_atom "
                f"belongs to {to_src!r} (INV-12)"
            )

    # Walk mappings/resolutions/ — every source_id must be a known distillation.
    for res in s.list_resolutions():
        assert res.source_id in distillations, (
            f"Resolution {res.id!r} references source_id={res.source_id!r} "
            f"but no matching distillation exists (INV-12). "
            f"Known distillations: {sorted(distillations)!r}"
        )


# ---------------------------------------------------------------------------
# Case 2: Cross-source relation in distillations/ is caught
# ---------------------------------------------------------------------------


def test_mappings_cross_source_relation_caught(
    cross_doc_violation_workspace: Path,
) -> None:
    """Negative: a relation whose endpoint atom belongs to a different source is flagged.

    The fixture plants a relation under src1 whose ``from_atom_id``
    belongs to src2. The gate walk builds a cross-source atom→source
    lookup, then checks that every relation's endpoint atoms belong to
    the relation's own source. It should detect the INV-12 violation.
    """
    s = Substrate(cross_doc_violation_workspace)

    # Build atom_id → source_id index across all distillations.
    atom_source: dict[str, str] = {}
    for src in s.list_distillations():
        for atom in s.list_atoms(src):
            atom_source[atom.id] = src

    violation_found = False
    for src in s.list_distillations():
        for rel in s.list_relations(src):
            from_src = atom_source.get(rel.from_atom_id)
            to_src = atom_source.get(rel.to_atom_id)
            if from_src != src or to_src != src:
                violation_found = True
                break
        if violation_found:
            break

    assert violation_found, (
        "Expected to find a cross-source relation endpoint violation in "
        "the fixture workspace, but none was detected. "
        "The INV-12 gate failed to catch a planted violation."
    )


# ---------------------------------------------------------------------------
# Case 3: Resolution referencing a non-existent distillation is caught
# ---------------------------------------------------------------------------


def test_mappings_resolution_unknown_source_caught(tmp_path: Path) -> None:
    """Negative: a resolution whose source_id has no distillation entry is flagged.

    Builds a workspace with one entity + one resolution but does NOT create
    the matching distillation directory. The gate should flag the orphan
    resolution.
    """
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: inv12-orphan-test\n",
        encoding="utf-8",
    )
    substrate = Substrate(tmp_path)

    # Build role attribution and agent (minimal placeholders).
    agent = AgentAttribution(
        kind="llm",
        identifier="claude-opus-4-7",
        role="map-resolve",
    )
    role_attribution = RoleAttribution(
        agent=agent,
        activity="proposed",
        at=_AT,
    )

    # Build entity and resolution but do NOT create a distillation directory.
    orphan_source_id = "src-orphan-999"
    entity, entity_prov = _build_entity(role_attribution, agent)
    resolution, res_prov = _build_resolution(
        role_attribution,
        agent,
        source_id=orphan_source_id,
        atom_id=_MAPPINGS_ATOM_ID,
        entity_id=entity.id,
    )

    for prov in (entity_prov, res_prov):
        prov_path = substrate.mappings_provenance_path(prov.id)
        atomic_write_text(prov_path, serialize_yaml(prov))

    substrate.add_entity(entity)
    substrate.add_resolution(resolution)

    # Gate walk: resolution's source_id should not appear in list_distillations().
    s = Substrate(tmp_path)
    distillations = set(s.list_distillations())

    orphan_resolutions = [res for res in s.list_resolutions() if res.source_id not in distillations]
    assert len(orphan_resolutions) >= 1, (
        "Expected at least one orphan resolution (source_id not in distillations/), "
        "but the gate walk found none."
    )
    assert orphan_resolutions[0].source_id == orphan_source_id


# ---------------------------------------------------------------------------
# Phase 2b — INV-12 extended to CrossDocRelation atom references
# ---------------------------------------------------------------------------


def _walk_mappings_namespace(workspace: Path) -> None:
    """Re-run the INV-12 gate against a workspace.

    Phase 2b extension: for every CrossDocRelation under ``mappings/
    relations/``, asserts that the from/to atom files exist on disk
    (``distillations/<src>/atoms/<atom_id>.md``). Catches edges whose
    endpoints reference atom ids that were never written.

    Phase 2c extension: for every ProbandumEdge under ``mappings/
    probandum-edges/``, asserts that
    - ``parent_probandum_id`` resolves to ``mappings/probanda/<id>.md``.
    - ``child_id`` resolves to its namespace-appropriate path:
      probandum -> ``mappings/probanda/<id>.md``;
      atom -> ``distillations/<child_source_id>/atoms/<child_id>.md``;
      cross-doc-relation -> ``mappings/relations/<child_id>.yaml``.

    Catches edges whose endpoints reference ids that were never written
    (the substrate's write-time gates would normally catch this, but a
    hand-authored or tampered YAML can bypass them).
    """
    s = Substrate(workspace)
    for rel in s.list_cross_doc_relations():
        from_atom_path = s.atom_path(rel.from_source_id, rel.from_atom_id)
        if not from_atom_path.is_file():
            raise AssertionError(
                f"INV-12 violation: CrossDocRelation {rel.id!r} references "
                f"missing atom at {from_atom_path} (from endpoint)"
            )
        to_atom_path = s.atom_path(rel.to_source_id, rel.to_atom_id)
        if not to_atom_path.is_file():
            raise AssertionError(
                f"INV-12 violation: CrossDocRelation {rel.id!r} references "
                f"missing atom at {to_atom_path} (to endpoint)"
            )
    # Phase 2c extension — probandum-edge endpoint existence.
    for edge in s.list_probandum_edges():
        parent_path = s.probandum_path(edge.parent_probandum_id)
        if not parent_path.is_file():
            raise AssertionError(
                f"INV-12 violation: ProbandumEdge {edge.id!r} references missing "
                f"probandum (parent) at {parent_path}"
            )
        if edge.child_kind == "probandum":
            child_path = s.probandum_path(edge.child_id)
            if not child_path.is_file():
                raise AssertionError(
                    f"INV-12 violation: ProbandumEdge {edge.id!r} references missing "
                    f"probandum (child) at {child_path}"
                )
        elif edge.child_kind == "atom":
            # Schema guarantees child_source_id is non-None when child_kind == 'atom'.
            assert edge.child_source_id is not None
            child_atom_path = s.atom_path(edge.child_source_id, edge.child_id)
            if not child_atom_path.is_file():
                raise AssertionError(
                    f"INV-12 violation: ProbandumEdge {edge.id!r} references missing "
                    f"atom at {child_atom_path}"
                )
        elif edge.child_kind == "cross-doc-relation":
            child_xrel_path = s.cross_doc_relation_path(edge.child_id)
            if not child_xrel_path.is_file():
                raise AssertionError(
                    f"INV-12 violation: ProbandumEdge {edge.id!r} references missing "
                    f"cross-doc-relation at {child_xrel_path}"
                )


def test_cross_doc_relation_with_missing_from_atom(
    tmp_workspace_with_dangling_from_atom_ref: Path,
) -> None:
    """A CrossDocRelation whose from_atom has no on-disk record is flagged."""
    with pytest.raises(AssertionError, match="references missing atom"):
        _walk_mappings_namespace(tmp_workspace_with_dangling_from_atom_ref)


def test_cross_doc_relation_with_missing_to_atom(
    tmp_workspace_with_dangling_to_atom_ref: Path,
) -> None:
    """A CrossDocRelation whose to_atom has no on-disk record is flagged."""
    with pytest.raises(AssertionError, match="references missing atom"):
        _walk_mappings_namespace(tmp_workspace_with_dangling_to_atom_ref)


# ---------------------------------------------------------------------------
# Phase 2c — INV-12 extended to ProbandumEdge endpoint references
# ---------------------------------------------------------------------------


def test_probandum_edge_with_missing_parent(
    tmp_workspace_with_probandum_edge_dangling_parent: Path,
) -> None:
    """A ProbandumEdge whose parent has no on-disk record is flagged."""
    with pytest.raises(AssertionError, match="references missing probandum"):
        _walk_mappings_namespace(tmp_workspace_with_probandum_edge_dangling_parent)


def test_probandum_edge_with_missing_probandum_child(
    tmp_workspace_with_probandum_edge_dangling_probandum_child: Path,
) -> None:
    """A ProbandumEdge with child_kind=probandum and missing child is flagged."""
    with pytest.raises(AssertionError, match="references missing probandum"):
        _walk_mappings_namespace(tmp_workspace_with_probandum_edge_dangling_probandum_child)


def test_probandum_edge_with_missing_atom_child(
    tmp_workspace_with_probandum_edge_dangling_atom: Path,
) -> None:
    """A ProbandumEdge with child_kind=atom and missing atom file is flagged."""
    with pytest.raises(AssertionError, match="references missing atom"):
        _walk_mappings_namespace(tmp_workspace_with_probandum_edge_dangling_atom)


def test_probandum_edge_with_missing_cross_doc_relation_child(
    tmp_workspace_with_probandum_edge_dangling_xrel: Path,
) -> None:
    """A ProbandumEdge with child_kind=cross-doc-relation and missing target is flagged."""
    with pytest.raises(AssertionError, match="references missing cross-doc-relation"):
        _walk_mappings_namespace(tmp_workspace_with_probandum_edge_dangling_xrel)
