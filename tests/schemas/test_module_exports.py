"""Smoke tests for ``amanuensis.schemas`` package re-exports.

Phase 2b M1 (T1.6) adds ``CrossDocRelation`` and
``CrossDocRelationSupersede`` to the root re-export surface. This test
guards against accidental removal of either name during future
refactors.
"""

from __future__ import annotations


def test_cross_doc_relation_importable_from_root_module() -> None:
    from amanuensis.schemas import CrossDocRelation, CrossDocRelationSupersede

    assert CrossDocRelation.__name__ == "CrossDocRelation"
    assert CrossDocRelationSupersede.__name__ == "CrossDocRelationSupersede"
