"""Substrate filesystem class — path-as-truth for the workspace.

A ``Substrate`` is an object bound to a workspace root directory whose
methods are the only sanctioned way to read or write substrate
artifacts. It enforces:

- **INV-1 (marker required):** construction fails unless
  ``<workspace>/amanuensis.yaml`` exists as a regular file.
- **INV-8 (substrate is the source of truth):** every write goes through
  ``atomic_write_text`` so readers never see torn content; every read
  parses the canonical on-disk form via Pydantic so callers always
  receive a validated model.
- **Content-addressable path discipline:** every ``add_*`` method
  asserts ``model.id == compute_id(model)`` before writing. The path
  the artifact lands at is derived from its id; refusing to write a
  mismatched id keeps "the path you read from is the hash of what you
  read" trivially true.

Layout (Phase 1 plan §5; see also the M1.1 reconciliation that the
substrate IS the workspace root — no ``substrate/`` wrapper):

::

    <workspace>/
      amanuensis.yaml                       (marker — required, INV-1)
      distillations/<source-id>/
        atoms/a-<hash>.md                   (frontmatter + narrative)
        relations/r-<hash>.yaml             (pure YAML)
        provenance/<prov-id>.yaml           (pure YAML; see note below)
        clarifications/open/c-<hash>.md     (frontmatter + question)
        clarifications/resolved/c-<hash>.md (moved by M7.4 on resolution)
      iterations/i-<hash>.md                (workspace-level)

Provenance filename — plan-level ambiguity resolved here. Plan §5 says
``provenance/<entity-id>.yaml (one per provenance record)``. That naming
breaks for a ``Clarification`` whose raised and resolved provenance
records share an ``entity_id`` (the clarification itself). M1.6 names
provenance files ``provenance/<prov-id>.yaml`` (the provenance record's
own content-addressable id). The inverse lookup is the ``entity_id``
field on the record. Decision is recorded here AND in HISTORY.md.

Substrate operations are pure with respect to clock and randomness:
they consult the filesystem and the model's already-computed id. M1.7
adds replay-log seq-counter writes (separate concern); M1.8 adds the
workspace flock. M1.6 has no concurrency guard beyond atomic writes.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any, ClassVar

import yaml

from amanuensis.schemas import (
    Atom,
    Clarification,
    IterationDirective,
    ProvenanceRecord,
    Relation,
    Vocabulary,
    compute_id,
)

from ._atomic import atomic_write_text
from ._errors import (
    SubstrateIdMismatch,
    SubstrateInvalidId,
    SubstrateMarkerMissing,
    SubstrateNotFound,
    SubstrateSnapshotConflict,
    SubstrateSnapshotCorrupt,
)
from ._serialize import (
    parse_atom_md,
    parse_provenance_yaml,
    serialize_atom_md,
    serialize_clarification_md,
    serialize_iteration_md,
    serialize_yaml,
)

# Conservative path-component validation. Lets through plain id-like
# strings (hashes, slugs) and rejects anything that could escape the
# canonical directory structure (path separators, parent traversal,
# embedded NULs, whitespace). Tight by default; loosen only with a
# real use case.
_VALID_ID_RE = re.compile(r"^[A-Za-z0-9_.\-]+$")


def _validate_id_component(value: str, *, label: str) -> None:
    """Reject ids whose textual form would compromise path discipline.

    Path components are not allowed to be empty, contain ``/`` or
    ``\\\\``, traverse upwards via ``..``, or carry NUL / whitespace.
    """
    if not value:
        raise SubstrateInvalidId(f"{label} must be non-empty")
    if value in (".", ".."):
        raise SubstrateInvalidId(f"{label} {value!r} is not a valid path component")
    if not _VALID_ID_RE.match(value):
        raise SubstrateInvalidId(
            f"{label} {value!r} contains characters outside [A-Za-z0-9_.-]; ids must be path-safe"
        )


def _serialize_vocabulary_snapshot(vocabulary: Vocabulary) -> str:
    """Canonical YAML serialization for vocabulary snapshots.

    Deliberately distinct from ``_serialize.serialize_yaml`` (which
    sorts keys). Vocabularies have semantically meaningful entry order
    (``entries`` is a list, and so are ``operand_types`` /
    ``aliases``); the snapshot preserves that order. Mapping keys
    within an entry are also preserved in declaration order so the
    snapshot reads like the source registry. ``mode="json"`` keeps
    every leaf JSON-friendly (datetimes, etc. — not relevant for the
    vocabulary schema today, but future-proof).
    """
    payload: dict[str, Any] = vocabulary.model_dump(mode="json")
    return yaml.safe_dump(payload, sort_keys=False, default_flow_style=False, allow_unicode=True)


class Substrate:
    """Filesystem-as-truth substrate at a workspace root.

    INV-1: refuses to construct if ``amanuensis.yaml`` marker is missing.
    INV-8: substrate is the source of truth; writes are atomic
    (write-to-tmp-then-rename); reads see consistent snapshots.

    Provenance files are keyed by the provenance record's own id
    (``<prov-id>.yaml``), not the ``entity_id``, because a
    ``Clarification``'s raised+resolved pair would otherwise collide.
    The ``entity_id`` field on the ``ProvenanceRecord`` provides the
    inverse lookup.
    """

    MARKER_FILENAME: ClassVar[str] = "amanuensis.yaml"

    def __init__(self, workspace_root: Path | str) -> None:
        root = Path(workspace_root).resolve()
        if not root.is_dir():
            raise SubstrateMarkerMissing(
                f"workspace_root {root} is not an existing directory. "
                "Use `amanuensis init` (planned M4.1) to create a workspace."
            )
        marker = root / self.MARKER_FILENAME
        if not marker.is_file():
            raise SubstrateMarkerMissing(
                f"amanuensis.yaml marker missing at {root}. "
                "Use `amanuensis init` (planned M4.1) to create a workspace."
            )
        self.root: Path = root

    # --- Path resolvers (pure path computation; no FS access) ---------

    def _distillation_root(self, source_id: str) -> Path:
        _validate_id_component(source_id, label="source_id")
        return self.root / "distillations" / source_id

    def atom_path(self, source_id: str, atom_id: str) -> Path:
        _validate_id_component(atom_id, label="atom_id")
        return self._distillation_root(source_id) / "atoms" / f"{atom_id}.md"

    def relation_path(self, source_id: str, relation_id: str) -> Path:
        _validate_id_component(relation_id, label="relation_id")
        return self._distillation_root(source_id) / "relations" / f"{relation_id}.yaml"

    def provenance_path(self, source_id: str, prov_id: str) -> Path:
        _validate_id_component(prov_id, label="prov_id")
        return self._distillation_root(source_id) / "provenance" / f"{prov_id}.yaml"

    def clarification_path(
        self,
        source_id: str,
        clarification_id: str,
        *,
        resolved: bool = False,
    ) -> Path:
        _validate_id_component(clarification_id, label="clarification_id")
        bucket = "resolved" if resolved else "open"
        return (
            self._distillation_root(source_id)
            / "clarifications"
            / bucket
            / f"{clarification_id}.md"
        )

    def iteration_path(self, iteration_id: str) -> Path:
        _validate_id_component(iteration_id, label="iteration_id")
        return self.root / "iterations" / f"{iteration_id}.md"

    def vocabulary_snapshot_path(self, source_id: str) -> Path:
        """Canonical path for the per-distillation vocabulary snapshot (INV-10).

        Pure path computation; no filesystem access. The snapshot file
        is the authoritative pin for the vocabulary used while
        extracting atoms under ``source_id``.
        """
        return self._distillation_root(source_id) / "vocabulary-snapshot.yaml"

    # --- Identity check ----------------------------------------------

    @staticmethod
    def _require_id_matches(
        model: Atom | Relation | ProvenanceRecord | Clarification | IterationDirective,
    ) -> None:
        """Refuse to write a model whose declared id != its hash."""
        expected = compute_id(model)
        if model.id != expected:
            raise SubstrateIdMismatch(
                f"{type(model).__name__}.id={model.id!r} does not match "
                f"compute_id(model)={expected!r}; refusing to write"
            )

    # --- Mutating methods (atomic write) ------------------------------

    def add_atom(self, source_id: str, atom: Atom) -> Path:
        if atom.source_id != source_id:
            raise ValueError(
                f"atom.source_id={atom.source_id!r} does not match source_id={source_id!r}"
            )
        self._require_id_matches(atom)
        path = self.atom_path(source_id, atom.id)
        atomic_write_text(path, serialize_atom_md(atom))
        return path

    def add_relation(self, source_id: str, relation: Relation) -> Path:
        if relation.source_id != source_id:
            raise ValueError(
                f"relation.source_id={relation.source_id!r} does not match source_id={source_id!r}"
            )
        self._require_id_matches(relation)
        path = self.relation_path(source_id, relation.id)
        atomic_write_text(path, serialize_yaml(relation))
        return path

    def add_provenance(self, source_id: str, prov: ProvenanceRecord) -> Path:
        # ProvenanceRecord has no ``source_id`` field — it's filed under
        # whichever distillation owns the artifact being recorded. The
        # caller passes ``source_id`` explicitly.
        self._require_id_matches(prov)
        path = self.provenance_path(source_id, prov.id)
        atomic_write_text(path, serialize_yaml(prov))
        return path

    def add_clarification(self, source_id: str, clarification: Clarification) -> Path:
        self._require_id_matches(clarification)
        resolved = clarification.status == "resolved"
        path = self.clarification_path(source_id, clarification.id, resolved=resolved)
        atomic_write_text(path, serialize_clarification_md(clarification))
        return path

    def add_iteration(self, iteration: IterationDirective) -> Path:
        self._require_id_matches(iteration)
        path = self.iteration_path(iteration.id)
        atomic_write_text(path, serialize_iteration_md(iteration))
        return path

    # --- Vocabulary snapshot (INV-10) ---------------------------------

    def snapshot_vocabulary(self, source_id: str, vocabulary: Vocabulary) -> Path:
        """Pin ``vocabulary`` as the per-distillation snapshot for ``source_id``.

        Writes the canonical YAML serialization of ``vocabulary`` to
        ``distillations/<source-id>/vocabulary-snapshot.yaml`` via the
        atomic-write helper. INV-10 makes this a write-once operation
        within a distillation: a subsequent call with the same payload
        is idempotent and silently succeeds; a call with different
        payload raises ``SubstrateSnapshotConflict`` rather than
        silently overwriting (the snapshot is the source of truth for
        every downstream validator).

        Idempotent re-snapshot is determined by *semantic* equality
        (``Vocabulary.model_dump()``), not byte equality, so
        format-level changes (PyYAML version drift, schema field
        additions with defaults) do not false-trip the conflict guard.
        If the existing snapshot file cannot be read or parsed, the
        method raises ``SubstrateSnapshotConflict`` chained from the
        underlying error — silently overwriting an unreadable pin would
        defeat INV-10.

        TODO(M3.1): record the snapshot's content hash in
        ``source-mirror/manifest.yaml`` on ingest. The manifest file
        itself is M3.1's deliverable; this method only writes the
        snapshot.
        """
        path = self.vocabulary_snapshot_path(source_id)
        if path.is_file():
            try:
                existing_vocab = Vocabulary.load(path)
            except (OSError, UnicodeDecodeError) as exc:
                raise SubstrateSnapshotConflict(
                    f"vocabulary snapshot at {path} exists but cannot be read; "
                    "refusing to overwrite an unreadable pin (INV-10)"
                ) from exc
            except Exception as exc:
                # ``Vocabulary.load`` raises ``VocabularyLoadError`` (parse,
                # schema, or structural failure). Imported lazily to avoid
                # a circular import; caught via the broad base and
                # narrowed by name to keep the chain explicit.
                from amanuensis.vocabulary.registry import VocabularyLoadError

                if isinstance(exc, VocabularyLoadError):
                    raise SubstrateSnapshotConflict(
                        f"vocabulary snapshot at {path} exists but is unparseable; "
                        "refusing to overwrite an unreadable pin (INV-10)"
                    ) from exc
                raise
            if existing_vocab.model_dump() == vocabulary.model_dump():
                return path
            raise SubstrateSnapshotConflict(
                f"vocabulary snapshot at {path} already exists with different content; "
                "INV-10 prohibits silent overwrite of a per-distillation vocabulary pin"
            )
        serialized = _serialize_vocabulary_snapshot(vocabulary)
        atomic_write_text(path, serialized)
        return path

    def get_vocabulary_snapshot(self, source_id: str) -> Vocabulary:
        """Read + validate the per-distillation vocabulary snapshot.

        Raises ``SubstrateNotFound`` if no snapshot has been written for
        ``source_id`` yet. Raises ``SubstrateSnapshotCorrupt`` if the
        snapshot file exists but cannot be parsed / validated — chained
        from the underlying ``VocabularyLoadError`` for debugging.
        Validators (M2.4) reach for this — never the global registry —
        so vocabulary edits made after ingest cannot retroactively change
        what atoms in this distillation mean.
        """
        # New typed exception ``SubstrateSnapshotCorrupt`` chosen over
        # reusing ``SubstrateSnapshotConflict`` because read-time
        # integrity failure is semantically distinct from write-time pin
        # violation; callers may want to handle them differently.
        path = self.vocabulary_snapshot_path(source_id)
        if not path.is_file():
            raise SubstrateNotFound(f"vocabulary snapshot not found at {path}")
        # Lazy import to avoid circular dependency at module load.
        from amanuensis.vocabulary.registry import VocabularyLoadError

        try:
            return Vocabulary.load(path)
        except VocabularyLoadError as exc:
            raise SubstrateSnapshotCorrupt(
                f"vocabulary snapshot at {path} could not be loaded: {exc}"
            ) from exc

    # --- Read methods -------------------------------------------------

    def get_atom(self, source_id: str, atom_id: str) -> Atom:
        path = self.atom_path(source_id, atom_id)
        if not path.is_file():
            raise SubstrateNotFound(f"atom not found at {path}")
        return parse_atom_md(path.read_text(encoding="utf-8"))

    def get_provenance(self, source_id: str, prov_id: str) -> ProvenanceRecord:
        """Read + validate a ProvenanceRecord by its own content-addressable id.

        Mirrors ``get_atom`` for the YAML-only provenance file format.
        Validators (notably ``provenance_completeness``, INV-3) reach for
        this to confirm the record exists at the canonical path and
        actually describes the atom that claims it.
        """
        path = self.provenance_path(source_id, prov_id)
        if not path.is_file():
            raise SubstrateNotFound(f"provenance not found at {path}")
        return parse_provenance_yaml(path.read_text(encoding="utf-8"))

    def list_atoms(self, source_id: str) -> Iterable[Atom]:
        """Yield all atoms in a distillation (generator; memory-efficient).

        Order is filesystem-iteration order (sorted lexicographically by
        filename for determinism). Skips any ``.tmp.*`` writer leftovers
        so a half-written sibling does not get parsed as truth.
        """
        atoms_dir = self._distillation_root(source_id) / "atoms"
        if not atoms_dir.is_dir():
            return
        for path in sorted(atoms_dir.iterdir()):
            if not path.is_file():
                continue
            name = path.name
            if not name.endswith(".md"):
                continue
            if ".tmp." in name:
                continue
            yield parse_atom_md(path.read_text(encoding="utf-8"))
