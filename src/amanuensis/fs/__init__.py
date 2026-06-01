"""Filesystem-as-truth layer for the amanuensis substrate.

Public surface:

- ``Substrate`` — path-as-truth class bound to a workspace root.
- ``SubstrateError`` and subclasses — typed exceptions raised by
  the substrate layer (``SubstrateMarkerMissing``,
  ``SubstrateIdMismatch``, ``SubstrateNotFound``,
  ``SubstrateInvalidId``, ``WorkspaceLockTimeout``).
- ``acquire_workspace_lock`` — workspace-level advisory flock context
  manager used by mutating CLI commands and web POST endpoints
  (plan §5). Read-only operations do NOT acquire it.

INV-1 (marker required) is enforced by ``Substrate.__init__`` AND by
``acquire_workspace_lock`` (it refuses to flock a non-workspace
directory). INV-8 (substrate is the source of truth) is enforced by
the atomic-write discipline in ``_atomic.py`` and the content-
addressable-path checks in ``Substrate.add_*``.
"""

from ._errors import (
    AchAlternativesGateViolation,
    CrossSourceConstraintViolation,
    EdgeChildMissing,
    MutationOfImmutableRecord,
    ParentProbandumMissing,
    ProbandumTreeViolation,
    ResolutionDuplicateTriple,
    SharedEntityGateViolation,
    SourceMirrorExists,
    SubstrateError,
    SubstrateIdMismatch,
    SubstrateInvalidId,
    SubstrateMarkerMissing,
    SubstrateNotFound,
    SubstrateSnapshotConflict,
    SubstrateSnapshotCorrupt,
    SupersedeChainTooDeep,
    SupersedeCycleDetected,
    WaltonSchemeGateViolation,
    WorkspaceLockTimeout,
)
from .lock import DEFAULT_TIMEOUT_SECONDS, LOCK_FILENAME, acquire_workspace_lock
from .replay_log import ReplayLog
from .substrate import Substrate

__all__ = [
    "DEFAULT_TIMEOUT_SECONDS",
    "LOCK_FILENAME",
    "AchAlternativesGateViolation",
    "CrossSourceConstraintViolation",
    "EdgeChildMissing",
    "MutationOfImmutableRecord",
    "ParentProbandumMissing",
    "ProbandumTreeViolation",
    "ReplayLog",
    "ResolutionDuplicateTriple",
    "SharedEntityGateViolation",
    "SourceMirrorExists",
    "Substrate",
    "SubstrateError",
    "SubstrateIdMismatch",
    "SubstrateInvalidId",
    "SubstrateMarkerMissing",
    "SubstrateNotFound",
    "SubstrateSnapshotConflict",
    "SubstrateSnapshotCorrupt",
    "SupersedeChainTooDeep",
    "SupersedeCycleDetected",
    "WaltonSchemeGateViolation",
    "WorkspaceLockTimeout",
    "acquire_workspace_lock",
]
