"""T2.3 — Substrate.add_probandum_edge + parent/child existence gates.

Covers:
- ``add_probandum_edge`` writes to ``mappings/probandum-edges/<id>.yaml``.
- Idempotent on byte-identical content (INV-13).
- Parent existence gate: ``parent_probandum_id`` must exist in
  ``mappings/probanda/``. Raises ``ParentProbandumMissing``.
- Child existence gate (per ``child_kind``):
    - ``probandum`` → ``mappings/probanda/<id>.md``
    - ``atom`` → ``distillations/<source>/atoms/<id>.md``
    - ``cross-doc-relation`` → ``mappings/relations/<id>.yaml``
  Raises ``EdgeChildMissing``.

INV-16 (no-cycle) and INV-17 (lineage) are deferred to M4 — this file
does NOT exercise them.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from amanuensis.fs import (
    EdgeChildMissing,
    ParentProbandumMissing,
    Substrate,
)
from amanuensis.fs._atomic import atomic_write_text
from amanuensis.schemas import (
    Probandum,
    ProbandumEdge,
    RoleAttribution,
    compute_id,
)


def _new(workspace: Path) -> Substrate:
    return Substrate(workspace)


def _edge(
    *,
    parent_probandum_id: str,
    child_id: str,
    child_kind: str = "probandum",
    child_source_id: str | None = None,
    role_attribution: RoleAttribution,
    **overrides: Any,
) -> ProbandumEdge:
    """Build a ProbandumEdge whose id matches ``compute_id``."""
    payload: dict[str, Any] = {
        "id": "q-" + "0" * 16,
        "parent_probandum_id": parent_probandum_id,
        "child_id": child_id,
        "child_kind": child_kind,
        "child_source_id": child_source_id,
        "kind": "supports",
        "warrant": "Child entails parent.",
        "warrant_defensibility": "conventional",
        "warrant_basis": "fixture",
        "confidence": "medium",
        "provenance_id": "p-fixture-edge-001",
        "role_attributions": [role_attribution],
        "schema_version": 1,
    }
    payload.update(overrides)
    draft = ProbandumEdge(**payload)
    payload["id"] = compute_id(draft)
    return ProbandumEdge(**payload)


def test_add_edge_writes_to_mappings(
    tmp_workspace_with_probanda: tuple[Path, Probandum, Probandum],
    role_attribution: RoleAttribution,
) -> None:
    workspace, ult, pen = tmp_workspace_with_probanda
    sub = _new(workspace)
    edge = _edge(
        parent_probandum_id=ult.id,
        child_id=pen.id,
        child_kind="probandum",
        role_attribution=role_attribution,
    )
    sub.add_probandum_edge(edge)
    path = workspace / "mappings" / "probandum-edges" / f"{edge.id}.yaml"
    assert path.is_file()


def test_add_edge_is_idempotent(
    tmp_workspace_with_probanda: tuple[Path, Probandum, Probandum],
    role_attribution: RoleAttribution,
) -> None:
    workspace, ult, pen = tmp_workspace_with_probanda
    sub = _new(workspace)
    edge = _edge(
        parent_probandum_id=ult.id,
        child_id=pen.id,
        child_kind="probandum",
        role_attribution=role_attribution,
    )
    sub.add_probandum_edge(edge)
    # Second write with identical content must not raise; exactly one file.
    sub.add_probandum_edge(edge)
    edges_dir = workspace / "mappings" / "probandum-edges"
    files = [f for f in edges_dir.iterdir() if f.is_file() and f.suffix == ".yaml"]
    assert len(files) == 1


def test_rejects_missing_parent(tmp_workspace: Path, role_attribution: RoleAttribution) -> None:
    sub = _new(tmp_workspace)
    edge = _edge(
        parent_probandum_id="p-nonexistent-aaaa",
        child_id="p-nonexistent-bbbb",
        child_kind="probandum",
        role_attribution=role_attribution,
    )
    with pytest.raises(ParentProbandumMissing):
        sub.add_probandum_edge(edge)


def test_rejects_missing_probandum_child(
    tmp_workspace_with_probanda: tuple[Path, Probandum, Probandum],
    role_attribution: RoleAttribution,
) -> None:
    workspace, ult, _pen = tmp_workspace_with_probanda
    sub = _new(workspace)
    edge = _edge(
        parent_probandum_id=ult.id,
        child_id="p-nonexistent-cccc",
        child_kind="probandum",
        role_attribution=role_attribution,
    )
    with pytest.raises(EdgeChildMissing, match="probandum"):
        sub.add_probandum_edge(edge)


def test_rejects_missing_atom_child(
    tmp_workspace_with_probanda: tuple[Path, Probandum, Probandum],
    role_attribution: RoleAttribution,
) -> None:
    workspace, ult, _pen = tmp_workspace_with_probanda
    sub = _new(workspace)
    edge = _edge(
        parent_probandum_id=ult.id,
        child_id="a-nonexistent-atom",
        child_kind="atom",
        child_source_id="src-fixture-001",
        role_attribution=role_attribution,
    )
    with pytest.raises(EdgeChildMissing, match="atom"):
        sub.add_probandum_edge(edge)


def test_rejects_missing_cross_doc_relation_child(
    tmp_workspace_with_probanda: tuple[Path, Probandum, Probandum],
    role_attribution: RoleAttribution,
) -> None:
    workspace, ult, _pen = tmp_workspace_with_probanda
    sub = _new(workspace)
    edge = _edge(
        parent_probandum_id=ult.id,
        child_id="x-nonexistent-cdr0",
        child_kind="cross-doc-relation",
        role_attribution=role_attribution,
    )
    with pytest.raises(EdgeChildMissing, match="cross-doc-relation"):
        sub.add_probandum_edge(edge)


def test_accepts_atom_child_when_atom_exists(
    tmp_workspace_with_probanda: tuple[Path, Probandum, Probandum],
    role_attribution: RoleAttribution,
) -> None:
    """Edge with child_kind=atom where the atom exists on disk passes the gate."""
    workspace, ult, _pen = tmp_workspace_with_probanda
    sub = _new(workspace)
    # Plant a placeholder atom .md file at the canonical path (we don't
    # need a real Atom — the gate only checks existence).
    atom_path = workspace / "distillations" / "src-fixture-001" / "atoms" / "a-planted-aaaa.md"
    atomic_write_text(atom_path, "---\nplaceholder: true\n---\nplanted atom\n")
    edge = _edge(
        parent_probandum_id=ult.id,
        child_id="a-planted-aaaa",
        child_kind="atom",
        child_source_id="src-fixture-001",
        role_attribution=role_attribution,
    )
    sub.add_probandum_edge(edge)
    assert (workspace / "mappings" / "probandum-edges" / f"{edge.id}.yaml").is_file()
