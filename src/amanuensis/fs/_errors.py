"""Typed exceptions raised by the Substrate filesystem layer.

Each exception is narrow and documents the specific failure mode it
represents. Callers can catch ``SubstrateError`` as a base if they want
to handle all substrate-layer faults uniformly.
"""

from __future__ import annotations


class SubstrateError(Exception):
    """Base class for all substrate-layer exceptions."""


class SubstrateMarkerMissing(SubstrateError):
    """Raised when constructing ``Substrate`` at a path without an
    ``amanuensis.yaml`` marker file (INV-1).

    Also raised when the workspace_root path does not exist or the marker
    exists but is not a regular file (e.g. a directory of the same name).
    """


class SubstrateIdMismatch(SubstrateError):
    """Raised when an ``add_*`` method receives a model whose ``id`` does
    not match its content-addressable hash.

    Writing a model whose declared id disagrees with ``compute_id(model)``
    would corrupt the path-as-truth invariant (INV-8): readers would
    discover an artifact at the wrong path. The substrate refuses to
    write rather than silently rehashing.
    """


class SubstrateNotFound(SubstrateError):
    """Raised when a requested artifact does not exist at the expected
    canonical path."""


class SubstrateInvalidId(SubstrateError):
    """Raised when a ``source_id`` (or other path-component id) contains
    characters that would escape the canonical directory structure
    (e.g. ``/``, ``..``, NUL).
    """


class SubstrateSnapshotConflict(SubstrateError):
    """Raised when ``snapshot_vocabulary`` is called for a source_id that
    already has a snapshot whose semantic content differs from the new
    payload.

    INV-10 pins the active vocabulary per distillation: the first snapshot
    of a given ``source-id`` is authoritative for that distillation's
    lifetime. Silent overwrite would retroactively change the meaning of
    atoms already filed under the snapshot. Idempotent re-snapshot
    (semantically equal ``Vocabulary.model_dump()``) succeeds; differing
    content raises this exception. Also raised if the existing snapshot
    on disk is unreadable / unparseable — refusing to overwrite a file we
    cannot interpret is safer than silently clobbering it.
    """


class SourceMirrorExists(SubstrateError):
    """Raised when ``ingest_pdf`` is called for a source_id whose
    source-mirror manifest already exists on disk.

    Symmetric with ``SubstrateSnapshotConflict`` (INV-10 vocabulary pin):
    a source-mirror distillation is write-once. Re-ingesting the same
    source_id with a shorter PDF would leave orphan ``p-NNNN.md`` files
    beyond the new paragraph count, and a same-length re-ingest under
    different Docling vocabulary / version would mix old and new
    paragraph bodies — both confuse any reader that walks the
    ``paragraphs/`` directory directly. The substrate refuses rather
    than silently corrupting on-disk state. To re-ingest, operators
    delete the distillation's ``source-mirror/`` directory and re-run.
    """


class SubstrateSnapshotCorrupt(SubstrateError):
    """Raised when ``get_vocabulary_snapshot`` finds the snapshot file on
    disk but cannot parse / validate it into a ``Vocabulary``.

    Distinct from ``SubstrateNotFound`` (no file) and
    ``SubstrateSnapshotConflict`` (write-time pin violation): this is a
    read-time integrity failure. Callers that want to distinguish
    "snapshot missing" from "snapshot corrupted" can catch this
    specifically; otherwise both inherit from ``SubstrateError``.
    """


class WorkspaceLockTimeout(SubstrateError):
    """Raised when ``acquire_workspace_lock`` cannot obtain the workspace
    flock within the configured timeout (plan §5).

    Carries a human-readable message naming the lock file path and the
    timeout that elapsed — the message is meant to surface to the user
    via CLI / web error output (e.g. "another amanuensis process may be
    running").
    """


class MutationOfImmutableRecord(SubstrateError):
    """Attempted to overwrite an existing substrate record with content
    that hashes to the same id but differs in non-volatile fields."""


class ResolutionDuplicateTriple(SubstrateError):
    """Attempted to add a second non-superseded Resolution for the same
    (source_id, atom_id, operand_index) triple."""


class SupersedeCycleDetected(SubstrateError):
    """Walking a supersede chain encountered an id that was already
    visited."""


class SupersedeChainTooDeep(SubstrateError):
    """Walking a supersede chain exceeded the configured max_depth."""


class MappingVocabularyAlreadyPinned(Exception):
    """Overwrite of an existing entity-vocabulary snapshot with different content."""


class CrossSourceConstraintViolation(SubstrateError, ValueError):
    """Raised when a ``CrossDocRelation`` has ``from_source_id == to_source_id``.

    Phase 2b cross-doc relations express warrants connecting atoms in
    DIFFERENT distillations. An intra-source edge belongs in the Phase 1
    ``Relation`` table (``distillations/<src>/relations/r-*.yaml``), not
    in the workspace-level ``mappings/relations/`` directory. The
    substrate refuses the write rather than silently corrupting the
    cross-source partition that downstream graph queries depend on.

    Inherits from both ``SubstrateError`` (so callers catching the
    substrate base class handle it uniformly) and ``ValueError`` (so it
    survives the natural "this is malformed input" idiom).
    """
