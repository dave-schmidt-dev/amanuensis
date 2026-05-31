"""Sanity test: the four new Phase 2a typed exceptions are importable from amanuensis.fs."""

from __future__ import annotations

from amanuensis.fs import (
    MutationOfImmutableRecord,
    ResolutionDuplicateTriple,
    SupersedeChainTooDeep,
    SupersedeCycleDetected,
)


def test_phase2a_errors_importable() -> None:
    for cls in (
        MutationOfImmutableRecord,
        ResolutionDuplicateTriple,
        SupersedeCycleDetected,
        SupersedeChainTooDeep,
    ):
        assert issubclass(cls, Exception)
