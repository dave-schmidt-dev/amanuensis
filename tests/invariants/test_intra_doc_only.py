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
``cross-doc/``) exist at the workspace root.

The negative case (``cross_source_violation_workspace``) confirms the
gate catches a deliberately planted violation: a relation filed under
``src1`` whose ``source_id`` field names ``src2``.

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


def test_no_cross_source_relation(intra_doc_test_workspace: Path) -> None:
    """Positive: all relations reference atoms within their own source."""
    s = Substrate(intra_doc_test_workspace)
    for src in s.list_distillations():
        for rel in s.list_relations(src):
            assert rel.source_id == src
            from_atom = s.get_atom(src, rel.from_atom_id)
            assert from_atom.source_id == src
            to_atom = s.get_atom(src, rel.to_atom_id)
            assert to_atom.source_id == src


def test_no_stray_cross_doc_dirs(intra_doc_test_workspace: Path) -> None:
    """Positive: no Phase-2 cross-doc directories exist in a Phase-1 workspace."""
    assert not (intra_doc_test_workspace / "probanda").exists()
    assert not (intra_doc_test_workspace / "cross-doc").exists()


def test_deliberate_violation_caught(cross_source_violation_workspace: Path) -> None:
    """Sanity-check: the gate catches the cross-source violation we planted."""
    s = Substrate(cross_source_violation_workspace)
    with pytest.raises(AssertionError):
        for src in s.list_distillations():
            for rel in s.list_relations(src):
                assert rel.source_id == src
