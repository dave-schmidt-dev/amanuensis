"""Smoke tests for ``amanuensis.schemas`` package re-exports.

Phase 2b M1 (T1.6) adds ``CrossDocRelation`` and
``CrossDocRelationSupersede`` to the root re-export surface.
Phase 2c M1 (T1.5) adds ``Probandum``, ``ProbandumEdge``,
``ProbandumSupersede``, ``ProbandumEdgeSupersede``. This test guards
against accidental removal of any of these names during future refactors.
"""

from __future__ import annotations


def test_cross_doc_relation_importable_from_root_module() -> None:
    from amanuensis.schemas import CrossDocRelation, CrossDocRelationSupersede

    assert CrossDocRelation.__name__ == "CrossDocRelation"
    assert CrossDocRelationSupersede.__name__ == "CrossDocRelationSupersede"


def test_probandum_importable_from_root_module() -> None:
    from amanuensis.schemas import (
        Probandum,
        ProbandumEdge,
        ProbandumEdgeSupersede,
        ProbandumSupersede,
    )

    assert Probandum.__name__ == "Probandum"
    assert ProbandumEdge.__name__ == "ProbandumEdge"
    assert ProbandumSupersede.__name__ == "ProbandumSupersede"
    assert ProbandumEdgeSupersede.__name__ == "ProbandumEdgeSupersede"
