"""Gate test for INV-9 (Cross-document reasoning is Phase 2's job, not Phase 1's).

Quoting INVARIANTS.md INV-9 verbatim:

    Phase 1 emits intra-document relations only. Cross-document
    entity resolution, support/attack edges spanning documents,
    probandum hierarchies spanning sources are Phase 2 (Map) outputs.

What this gate certifies
------------------------
Walks all distillations in a fixture substrate; for every relation,
asserts that ``rel.source_id`` matches the distillation it lives under.
Also asserts that no Phase-2 cross-doc directories (``probanda/``,
``cross-doc/``) exist at the workspace root, and that no cross-doc
relation YAML (``x-*.yaml``) is filed under any per-distillation
``relations/`` directory (Phase 2b extension — those edges belong in
``mappings/relations/``). Phase 2c extension: no probandum (``p-*.md``)
or probandum-edge (``q-*.yaml``) file is permitted anywhere under
``distillations/<src>/`` — probanda and edges live exclusively in
``mappings/probanda/`` and ``mappings/probandum-edges/``.

The negative cases:
- ``cross_source_violation_workspace`` — a relation filed under ``src1``
  whose ``source_id`` field names ``src2``.
- ``tmp_workspace_with_cross_doc_in_wrong_place`` — a CrossDocRelation
  YAML filed under ``distillations/<src>/relations/`` (Phase 2b extension).
- ``tmp_workspace_with_probandum_in_wrong_place`` — a Probandum ``.md``
  filed under ``distillations/<src>/`` (Phase 2c extension).
- ``tmp_workspace_with_probandum_edge_in_wrong_place`` — a ProbandumEdge
  ``.yaml`` filed under ``distillations/<src>/`` (Phase 2c extension).

Scope
-----
The fixture substrates are hand-built (not derived from the M2.1 PDFs).
This gate lives in ``tests/invariants/`` and is wired into
``pytest -m invariants``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from amanuensis.fs import Substrate

pytestmark = pytest.mark.invariants


def _walk_intra_doc_only(workspace: Path) -> None:
    """Re-run the INV-9 gate against a workspace.

    Raises ``AssertionError`` on any violation:
    - A relation under ``distillations/<src>/relations/`` whose
      ``source_id`` does not match ``src`` (or whose endpoint atoms
      belong to a different source).
    - A cross-doc relation file (``x-*.yaml``) filed under any
      per-distillation ``relations/`` directory.
    - A probandum file (``p-*.md``) filed anywhere under
      ``distillations/<src>/`` (Phase 2c extension).
    - A probandum-edge file (``q-*.yaml``) filed anywhere under
      ``distillations/<src>/`` (Phase 2c extension).
    """
    s = Substrate(workspace)
    distillations_dir = workspace / "distillations"
    # Phase 2b extension — no cross-doc relation files under distillations/.
    if distillations_dir.is_dir():
        for src_dir in distillations_dir.iterdir():
            if not src_dir.is_dir():
                continue
            relations_dir = src_dir / "relations"
            if relations_dir.is_dir():
                for path in relations_dir.iterdir():
                    if not path.is_file():
                        continue
                    if path.name.startswith("x-") and path.name.endswith(".yaml"):
                        raise AssertionError(
                            f"INV-9 violation: cross-doc relation under distillations/ "
                            f"at {path}; cross-doc edges belong in mappings/relations/"
                        )
            # Phase 2c extension — no probandum (``p-*.md``) or
            # probandum-edge (``q-*.yaml``) anywhere under distillations/.
            # Walk the source subtree recursively so stray files in any
            # nested directory (atoms/, relations/, etc.) are caught.
            for path in src_dir.rglob("*"):
                if not path.is_file():
                    continue
                if path.name.startswith("p-") and path.name.endswith(".md"):
                    raise AssertionError(
                        f"INV-9 violation: probandum under distillations/ "
                        f"at {path}; probanda belong in mappings/probanda/"
                    )
                if path.name.startswith("q-") and path.name.endswith(".yaml"):
                    raise AssertionError(
                        f"INV-9 violation: probandum-edge under distillations/ "
                        f"at {path}; probandum-edges belong in mappings/probandum-edges/"
                    )
    # Phase 1 invariant — every relation is intra-source.
    for src in s.list_distillations():
        for rel in s.list_relations(src):
            assert rel.source_id == src, (
                f"INV-9 violation: relation {rel.id!r} filed under {src!r} "
                f"but claims source_id={rel.source_id!r}"
            )
            from_atom = s.get_atom(src, rel.from_atom_id)
            assert from_atom.source_id == src
            to_atom = s.get_atom(src, rel.to_atom_id)
            assert to_atom.source_id == src


def test_no_cross_source_relation(intra_doc_test_workspace: Path) -> None:
    """Positive: all relations reference atoms within their own source."""
    _walk_intra_doc_only(intra_doc_test_workspace)


def test_no_stray_cross_doc_dirs(intra_doc_test_workspace: Path) -> None:
    """Positive: no Phase-2 cross-doc directories exist in a Phase-1 workspace."""
    assert not (intra_doc_test_workspace / "probanda").exists()
    assert not (intra_doc_test_workspace / "cross-doc").exists()


def test_deliberate_violation_caught(cross_source_violation_workspace: Path) -> None:
    """Sanity-check: the gate catches the cross-source violation we planted."""
    with pytest.raises(AssertionError):
        _walk_intra_doc_only(cross_source_violation_workspace)


def test_rejects_cross_doc_relation_file_under_distillations(
    tmp_workspace_with_cross_doc_in_wrong_place: Path,
) -> None:
    """A CrossDocRelation YAML filed under distillations/ is a violation of INV-9."""
    with pytest.raises(AssertionError, match="cross-doc relation under distillations/"):
        _walk_intra_doc_only(tmp_workspace_with_cross_doc_in_wrong_place)


def test_rejects_probandum_file_under_distillations(
    tmp_workspace_with_probandum_in_wrong_place: Path,
) -> None:
    """A Probandum (``p-*.md``) under distillations/ is a violation of INV-9.

    Phase 2c extension: probanda live exclusively in ``mappings/probanda/``;
    a stray ``p-*.md`` file under any per-distillation subtree must be
    flagged as a cross-doc artifact filed in the wrong namespace.
    """
    with pytest.raises(AssertionError, match="probandum under distillations/"):
        _walk_intra_doc_only(tmp_workspace_with_probandum_in_wrong_place)


def test_rejects_probandum_edge_file_under_distillations(
    tmp_workspace_with_probandum_edge_in_wrong_place: Path,
) -> None:
    """A ProbandumEdge (``q-*.yaml``) under distillations/ is a violation of INV-9.

    Phase 2c extension: probandum-edges live exclusively in
    ``mappings/probandum-edges/``; a stray ``q-*.yaml`` file under any
    per-distillation subtree must be flagged.
    """
    with pytest.raises(AssertionError, match="probandum-edge under distillations/"):
        _walk_intra_doc_only(tmp_workspace_with_probandum_edge_in_wrong_place)
