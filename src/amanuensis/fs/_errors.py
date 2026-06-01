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


class AchAlternativesGateViolation(SubstrateError, ValueError):
    """Raised when a non-ultimate ``Probandum`` has empty ``alternatives_considered``.

    Phase 2c hierarchize requires that ``penultimate`` and ``interim``
    probanda enumerate at least one alternative hypothesis (Analysis of
    Competing Hypotheses discipline). ``ultimate`` probanda are not
    required to (they are themselves the alternatives the corpus picks
    between). The substrate refuses the write rather than letting an
    un-considered alternative ladder up the tree silently.

    Inherits from both ``SubstrateError`` (so callers catching the
    substrate base class handle it uniformly) and ``ValueError`` (so it
    survives the natural "this is malformed input" idiom).
    """


class ParentProbandumMissing(SubstrateError, ValueError):
    """Raised when a ``ProbandumEdge``'s ``parent_probandum_id`` has no
    on-disk Probandum at ``mappings/probanda/<id>.md``.

    Edges anchor against an existing parent; if the parent isn't on disk
    the substrate refuses to write rather than create a dangling ref.

    Inherits from both ``SubstrateError`` and ``ValueError``.
    """


class EdgeChildMissing(SubstrateError, ValueError):
    """Raised when a ``ProbandumEdge``'s child target has no on-disk record.

    Depending on ``child_kind`` the target lives at:
    - ``"probandum"`` → ``mappings/probanda/<id>.md``
    - ``"atom"`` → ``distillations/<source>/atoms/<id>.md``
    - ``"cross-doc-relation"`` → ``mappings/relations/<id>.yaml``

    Inherits from both ``SubstrateError`` and ``ValueError``.
    """


class WaltonSchemeGateViolation(SubstrateError, ValueError):
    """Raised when a ``Probandum``'s ``scheme`` is not in the pinned snapshot.

    Phase 2c INV-18 requires that every probandum's ``scheme`` field
    appear in the per-engagement Walton-scheme snapshot at
    ``mappings/walton-scheme-snapshot.yaml``. The substrate refuses the
    write rather than letting an unknown scheme classification land
    silently — that would let an extracted argument lookup miss its
    Walton critical-questions matrix and break the synthesis layer's
    closed-vocabulary discipline.

    Inherits from both ``SubstrateError`` (so callers catching the
    substrate base class handle it uniformly) and ``ValueError`` (so it
    survives the natural "this is malformed input" idiom).
    """


class SharedEntityGateViolation(SubstrateError, ValueError):
    """Raised when a CrossDocRelation fails the INV-15 shared-entity gate.

    Specifically: shared_entities is empty, OR a listed entity is not found
    in mappings/entities/, OR a listed entity is not resolved by one or both
    endpoint atoms (via Resolution records).

    Inherits from both ``SubstrateError`` (so callers catching the substrate
    base class handle it uniformly) and ``ValueError`` (so it survives the
    natural "this is malformed input" idiom).
    """
