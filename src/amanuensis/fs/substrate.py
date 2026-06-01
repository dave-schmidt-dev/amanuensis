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
from typing import TYPE_CHECKING, Any, ClassVar, Literal

if TYPE_CHECKING:
    from amanuensis.vocabulary.entity_registry import EntityVocabulary

import yaml

from amanuensis.schemas import (
    Atom,
    Clarification,
    CrossDocRelation,
    CrossDocRelationSupersede,
    Entity,
    EntitySupersede,
    IterationDirective,
    ProvenanceRecord,
    Relation,
    Resolution,
    ResolutionSupersede,
    SourceMirrorManifest,
    Vocabulary,
    compute_id,
)

from ._atomic import atomic_write_text
from ._errors import (
    CrossSourceConstraintViolation,
    MappingVocabularyAlreadyPinned,
    MutationOfImmutableRecord,
    ResolutionDuplicateTriple,
    SharedEntityGateViolation,
    SubstrateIdMismatch,
    SubstrateInvalidId,
    SubstrateMarkerMissing,
    SubstrateNotFound,
    SubstrateSnapshotConflict,
    SubstrateSnapshotCorrupt,
    SupersedeChainTooDeep,
    SupersedeCycleDetected,
)
from ._serialize import (
    parse_atom_md,
    parse_cross_doc_relation_supersede_yaml,
    parse_cross_doc_relation_yaml,
    parse_entity_md,
    parse_entity_supersede_yaml,
    parse_provenance_yaml,
    parse_resolution_supersede_yaml,
    parse_resolution_yaml,
    serialize_atom_md,
    serialize_clarification_md,
    serialize_cross_doc_relation_supersede_yaml,
    serialize_cross_doc_relation_yaml,
    serialize_entity_md,
    serialize_entity_supersede_yaml,
    serialize_iteration_md,
    serialize_resolution_supersede_yaml,
    serialize_resolution_yaml,
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

        # Auto-migrate v1 Clarification records to v2 (PM-3). The scan is
        # bytes-cheap: glob for c-*.md and substring-check for
        # 'schema_version: 1'. Only if any match do we invoke the full
        # migration script (which re-parses and rewrites). Import is scoped
        # inside the function to avoid hard-coupling src/ to scripts/ at
        # module load time.
        for c_md in self.root.glob("distillations/*/clarifications/*/c-*.md"):
            try:
                head = c_md.read_text()[:512]  # frontmatter is well under 512 bytes
            except OSError:
                continue
            if "schema_version: 1" in head:
                from scripts.migrate_clarifications_to_schema_v2 import (
                    migrate_workspace,
                )

                migrate_workspace(self.root)
                break  # one full migration sweep covers everything

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

    def source_mirror_root(self, source_id: str) -> Path:
        """Canonical root for a distillation's source-mirror (M3.1).

        Pure path computation; no filesystem access.
        """
        return self._distillation_root(source_id) / "source-mirror"

    def paragraph_path(self, source_id: str, paragraph_id: str) -> Path:
        """Canonical path for one paragraph .md file under source-mirror."""
        _validate_id_component(paragraph_id, label="paragraph_id")
        return self.source_mirror_root(source_id) / "paragraphs" / f"{paragraph_id}.md"

    def manifest_path(self, source_id: str) -> Path:
        """Canonical path for a distillation's source-mirror manifest."""
        return self.source_mirror_root(source_id) / "manifest.yaml"

    def entity_vocabulary_snapshot_path(self) -> Path:
        """Return the path to the active entity-vocabulary snapshot."""
        return self.root / "mappings" / "entity-vocabulary-snapshot.yaml"

    def archived_entity_vocabulary_path(self, archived_id: str) -> Path:
        """Return the path to an archived entity-vocabulary snapshot, keyed by its hash id."""
        _validate_id_component(archived_id, label="archived_id")
        return self.root / "mappings" / "entity-vocabulary-archive" / f"{archived_id}.yaml"

    # --- Identity check ----------------------------------------------

    @staticmethod
    def _require_id_matches(
        model: Atom
        | Relation
        | ProvenanceRecord
        | Clarification
        | IterationDirective
        | SourceMirrorManifest
        | Entity
        | Resolution
        | ResolutionSupersede
        | EntitySupersede
        | CrossDocRelation
        | CrossDocRelationSupersede,
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

    def add_source_mirror_manifest(self, source_id: str, manifest: SourceMirrorManifest) -> Path:
        """Write a source-mirror manifest (M3.1) atomically.

        Enforces ``manifest.id == compute_id(manifest)`` and that the
        manifest's ``source_id`` matches the caller-passed ``source_id``.
        """
        if manifest.source_id != source_id:
            raise ValueError(
                f"manifest.source_id={manifest.source_id!r} does not match source_id={source_id!r}"
            )
        self._require_id_matches(manifest)
        path = self.manifest_path(source_id)
        atomic_write_text(path, serialize_yaml(manifest))
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

        M3.1 (landed): the ingest pipeline reads the on-disk snapshot
        bytes after this method returns and records their SHA-256 in
        ``source-mirror/manifest.yaml`` (``vocabulary_snapshot_sha256``).
        This method itself stays focused on the pin write and remains
        oblivious to the manifest.
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

    # --- Entity-vocabulary snapshot (Phase 2a M2) --------------------

    def snapshot_entity_vocabulary(self, vocabulary: EntityVocabulary) -> None:
        """Write the entity-vocabulary snapshot.

        Idempotent: if a snapshot file already exists with byte-identical
        content, this is a no-op (preserves write-once semantics from INV-10).
        If a snapshot exists with DIFFERENT content, raises
        ``MappingVocabularyAlreadyPinned`` (callers must use
        ``extend_entity_vocabulary_snapshot`` to evolve).

        The serialized form is ``yaml.safe_dump(vocabulary.model_dump(),
        sort_keys=False, default_flow_style=False)``.
        """
        path = self.entity_vocabulary_snapshot_path()
        serialized = yaml.safe_dump(
            vocabulary.model_dump(), sort_keys=False, default_flow_style=False
        )
        if path.is_file():
            existing_bytes = path.read_bytes()
            if existing_bytes == serialized.encode():
                return
            raise MappingVocabularyAlreadyPinned(
                f"entity-vocabulary snapshot at {path} already exists with different content; "
                "use extend_entity_vocabulary_snapshot to evolve"
            )
        atomic_write_text(path, serialized)

    def get_entity_vocabulary_snapshot(self) -> EntityVocabulary:
        """Read and return the active snapshot. Raise SubstrateNotFound if absent."""
        path = self.entity_vocabulary_snapshot_path()
        if not path.is_file():
            raise SubstrateNotFound(f"entity-vocabulary snapshot not found at {path}")
        # Lazy import to avoid circular dependency at module load.
        from amanuensis.vocabulary.entity_registry import load_entity_vocabulary

        return load_entity_vocabulary(path)

    def extend_entity_vocabulary_snapshot(self, new_vocabulary: EntityVocabulary) -> str:
        """Archive the current snapshot, write the new one. Returns the archived id.

        The archived id is the SHA-256 hex digest of the OLD snapshot's bytes
        (truncated to 16 hex chars, no prefix). Archives the current snapshot
        to ``mappings/entity-vocabulary-archive/<archived-id>.yaml`` then
        atomically writes the new snapshot.
        """
        import hashlib

        path = self.entity_vocabulary_snapshot_path()
        if not path.is_file():
            raise SubstrateNotFound(
                f"entity-vocabulary snapshot not found at {path}; "
                "call snapshot_entity_vocabulary first"
            )
        old_bytes = path.read_bytes()
        archived_id = hashlib.sha256(old_bytes).hexdigest()[:16]
        archive_path = self.archived_entity_vocabulary_path(archived_id)
        atomic_write_text(archive_path, old_bytes.decode())
        serialized = yaml.safe_dump(
            new_vocabulary.model_dump(), sort_keys=False, default_flow_style=False
        )
        atomic_write_text(path, serialized)
        return archived_id

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

    # --- T3.2: mappings/ path resolvers ----------------------------------

    @property
    def mappings_root(self) -> Path:
        """Canonical root for all mappings artifacts."""
        return self.root / "mappings"

    def entity_path(self, entity_id: str) -> Path:
        """Canonical path for a single Entity file.

        Pure path computation; no FS access.
        """
        _validate_id_component(entity_id, label="entity_id")
        return self.mappings_root / "entities" / f"{entity_id}.md"

    def resolution_path(self, resolution_id: str) -> Path:
        """Canonical path for a single Resolution file.

        Pure path computation; no FS access.
        """
        _validate_id_component(resolution_id, label="resolution_id")
        return self.mappings_root / "resolutions" / f"{resolution_id}.yaml"

    def supersede_path(self, supersede_id: str) -> Path:
        """Canonical path for a supersede record (s- or t- prefix).

        Both ResolutionSupersede (s-) and EntitySupersede (t-) live in
        the same ``supersedes/`` directory, distinguished by id prefix.
        Pure path computation; no FS access.
        """
        _validate_id_component(supersede_id, label="supersede_id")
        return self.mappings_root / "supersedes" / f"{supersede_id}.yaml"

    def mappings_provenance_path(self, provenance_id: str) -> Path:
        """Canonical path for a mappings-layer provenance record.

        Pure path computation; no FS access.
        """
        _validate_id_component(provenance_id, label="provenance_id")
        return self.mappings_root / "provenance" / f"{provenance_id}.yaml"

    def cross_doc_relation_path(self, relation_id: str) -> Path:
        """Canonical path for a single CrossDocRelation file (Phase 2b).

        ``mappings/relations/x-<hash>.yaml``. Pure path computation; no
        FS access.
        """
        _validate_id_component(relation_id, label="relation_id")
        return self.mappings_root / "relations" / f"{relation_id}.yaml"

    # --- T3.3: Entity add / get / list -----------------------------------

    def add_entity(self, entity: Entity) -> None:
        """Write an Entity atomically.

        Validates ``entity.id == compute_id(entity)``. If the canonical
        path already exists:

        - Reads and parses the on-disk record.
        - Drops volatile fields from both (``Entity._VOLATILE_FIELDS``).
        - If the canonical-form dicts are equal: no-op (idempotent).
        - If they differ: raises ``MutationOfImmutableRecord``.

        This preserves INV-13 (entities are immutable) while allowing
        safe replay of identical records (e.g. during warp cycles).
        """
        self._require_id_matches(entity)
        path = self.entity_path(entity.id)
        if path.is_file():
            existing = parse_entity_md(path.read_text(encoding="utf-8"))
            volatile = Entity._VOLATILE_FIELDS | frozenset({"id"})  # pyright: ignore[reportPrivateUsage]
            new_dump = {
                k: v for k, v in entity.model_dump(mode="python").items() if k not in volatile
            }
            old_dump = {
                k: v for k, v in existing.model_dump(mode="python").items() if k not in volatile
            }
            if new_dump == old_dump:
                return  # idempotent
            raise MutationOfImmutableRecord(
                f"Entity at {path} already exists with different non-volatile content; "
                "refusing to overwrite (INV-13)"
            )
        atomic_write_text(path, serialize_entity_md(entity))

    def get_entity(self, entity_id: str) -> Entity:
        """Read and return an Entity by its content-addressable id."""
        path = self.entity_path(entity_id)
        if not path.is_file():
            raise SubstrateNotFound(f"entity not found at {path}")
        return parse_entity_md(path.read_text(encoding="utf-8"))

    def list_entities(self) -> Iterable[Entity]:
        """Yield all Entity records in the workspace.

        Sorted lexicographically by filename for determinism. Skips
        ``.tmp.*`` writer leftovers.
        """
        entities_dir = self.mappings_root / "entities"
        if not entities_dir.is_dir():
            return
        for path in sorted(entities_dir.iterdir()):
            if not path.is_file():
                continue
            if not path.name.endswith(".md"):
                continue
            if ".tmp." in path.name:
                continue
            yield parse_entity_md(path.read_text(encoding="utf-8"))

    # --- T3.4: Resolution add / get / list -------------------------------

    def add_resolution(self, r: Resolution) -> None:
        """Write a Resolution atomically.

        Validates ``r.id == compute_id(r)``. Raises
        ``ResolutionDuplicateTriple`` if a non-superseded Resolution for
        the same ``(source_id, atom_id, operand_index)`` triple already
        exists (INV-14).
        """
        self._require_id_matches(r)
        # Duplicate-triple guard: call latest_resolution_for to find any
        # active (non-superseded) resolution for this triple. If one
        # exists, reject.
        existing = self.latest_resolution_for(r.source_id, r.atom_id, r.operand_index)
        if existing is not None and existing.id != r.id:
            raise ResolutionDuplicateTriple(
                f"A non-superseded resolution ({existing.id!r}) already exists "
                f"for triple ({r.source_id!r}, {r.atom_id!r}, {r.operand_index}); "
                "INV-14 prohibits a second active resolution for the same triple"
            )
        path = self.resolution_path(r.id)
        atomic_write_text(path, serialize_resolution_yaml(r))

    def get_resolution(self, resolution_id: str) -> Resolution:
        """Read and return a Resolution by its content-addressable id."""
        path = self.resolution_path(resolution_id)
        if not path.is_file():
            raise SubstrateNotFound(f"resolution not found at {path}")
        return parse_resolution_yaml(path.read_text(encoding="utf-8"))

    def list_resolutions(
        self,
        *,
        source_id: str | None = None,
        where_entity_id: str | None = None,
    ) -> Iterable[Resolution]:
        """Yield Resolution records, optionally filtered.

        Args:
            source_id: If given, only yield resolutions whose
                ``source_id`` field matches.
            where_entity_id: If given, only yield resolutions whose
                ``entity_id`` field matches.
        """
        resolutions_dir = self.mappings_root / "resolutions"
        if not resolutions_dir.is_dir():
            return
        for path in sorted(resolutions_dir.iterdir()):
            if not path.is_file():
                continue
            if not path.name.endswith(".yaml"):
                continue
            if ".tmp." in path.name:
                continue
            r = parse_resolution_yaml(path.read_text(encoding="utf-8"))
            if source_id is not None and r.source_id != source_id:
                continue
            if where_entity_id is not None and r.entity_id != where_entity_id:
                continue
            yield r

    # --- T3.5: Supersede add / get / list --------------------------------

    def add_resolution_supersede(self, rs: ResolutionSupersede) -> None:
        """Write a ResolutionSupersede record atomically.

        Gates enforced (mirrors Phase 2b's
        ``add_cross_doc_relation_supersede`` per cleanup-4):

        1. **Id discipline** — ``rs.id == compute_id(rs)``.
        2. **INV-13 immutability** — if the canonical path exists, reads
           the existing bytes. If byte-identical, no-op (idempotent). If
           divergent, raises ``MutationOfImmutableRecord``.
        """
        self._require_id_matches(rs)
        path = self.supersede_path(rs.id)
        serialized = serialize_resolution_supersede_yaml(rs)
        if path.is_file():
            existing_bytes = path.read_bytes()
            if existing_bytes == serialized.encode("utf-8"):
                return  # idempotent
            raise MutationOfImmutableRecord(
                f"ResolutionSupersede at {path} already exists with "
                f"different content; refusing to overwrite (INV-13)"
            )
        atomic_write_text(path, serialized)

    def get_resolution_supersede(self, supersede_id: str) -> ResolutionSupersede:
        """Read and return a ResolutionSupersede by its id."""
        path = self.supersede_path(supersede_id)
        if not path.is_file():
            raise SubstrateNotFound(f"resolution supersede not found at {path}")
        return parse_resolution_supersede_yaml(path.read_text(encoding="utf-8"))

    def add_entity_supersede(self, es: EntitySupersede) -> None:
        """Write an EntitySupersede record atomically.

        Gates enforced (mirrors Phase 2b's
        ``add_cross_doc_relation_supersede`` per cleanup-4):

        1. **Id discipline** — ``es.id == compute_id(es)``.
        2. **INV-13 immutability** — if the canonical path exists, reads
           the existing bytes. If byte-identical, no-op (idempotent). If
           divergent, raises ``MutationOfImmutableRecord``.
        """
        self._require_id_matches(es)
        path = self.supersede_path(es.id)
        serialized = serialize_entity_supersede_yaml(es)
        if path.is_file():
            existing_bytes = path.read_bytes()
            if existing_bytes == serialized.encode("utf-8"):
                return  # idempotent
            raise MutationOfImmutableRecord(
                f"EntitySupersede at {path} already exists with "
                f"different content; refusing to overwrite (INV-13)"
            )
        atomic_write_text(path, serialized)

    def get_entity_supersede(self, supersede_id: str) -> EntitySupersede:
        """Read and return an EntitySupersede by its id."""
        path = self.supersede_path(supersede_id)
        if not path.is_file():
            raise SubstrateNotFound(f"entity supersede not found at {path}")
        return parse_entity_supersede_yaml(path.read_text(encoding="utf-8"))

    def list_supersedes(
        self,
        *,
        kind: Literal["resolution", "entity", "cross-doc-relation"] | None = None,
    ) -> Iterable[ResolutionSupersede | EntitySupersede | CrossDocRelationSupersede]:
        """Yield supersede records from the mixed ``supersedes/`` directory.

        Distinguishes record type by id prefix:
        - ``s-`` prefix → ``ResolutionSupersede``
        - ``t-`` prefix → ``EntitySupersede``
        - ``v-`` prefix → ``CrossDocRelationSupersede`` (Phase 2b)

        Args:
            kind: If ``"resolution"``, yield only ResolutionSupersede.
                If ``"entity"``, yield only EntitySupersede.
                If ``"cross-doc-relation"``, yield only
                CrossDocRelationSupersede (Phase 2b cleanup-1).
                If ``None``, yield all.
        """
        supersedes_dir = self.mappings_root / "supersedes"
        if not supersedes_dir.is_dir():
            return
        for path in sorted(supersedes_dir.iterdir()):
            if not path.is_file():
                continue
            if not path.name.endswith(".yaml"):
                continue
            if ".tmp." in path.name:
                continue
            stem = path.stem  # filename without .yaml
            if stem.startswith("s-"):
                if kind is not None and kind != "resolution":
                    continue
                yield parse_resolution_supersede_yaml(path.read_text(encoding="utf-8"))
            elif stem.startswith("t-"):
                if kind is not None and kind != "entity":
                    continue
                yield parse_entity_supersede_yaml(path.read_text(encoding="utf-8"))
            elif stem.startswith("v-"):
                if kind is not None and kind != "cross-doc-relation":
                    continue
                yield parse_cross_doc_relation_supersede_yaml(path.read_text(encoding="utf-8"))
            # Unknown prefix: skip silently (forward-compat)

    # --- T3.6: supersede-chain walkers with cycle guard ------------------

    def latest_entity_for(
        self,
        entity_id: str,
        max_depth: int = 256,
    ) -> Entity:
        """Walk the EntitySupersede chain and return the terminal Entity.

        Starting from ``entity_id``, follows EntitySupersede records
        (``superseded_entity_id`` → ``replacement_entity_id``) until no
        further supersede exists for the current id.

        Args:
            entity_id: Starting entity id (prefix ``e-``).
            max_depth: Maximum chain depth before raising
                ``SupersedeChainTooDeep``.

        Returns:
            The terminal (latest non-superseded) ``Entity``.

        Raises:
            SubstrateNotFound: if any entity in the chain does not exist.
            SupersedeCycleDetected: if the chain contains a cycle.
            SupersedeChainTooDeep: if the chain exceeds ``max_depth``.
        """
        visited: set[str] = set()
        current_id = entity_id
        depth = 0
        # Build a lookup: superseded_entity_id → replacement_entity_id
        # We scan all entity supersedes once up front, then walk.
        supersede_map: dict[str, str] = {}
        for record in self.list_supersedes(kind="entity"):
            if isinstance(record, EntitySupersede):
                supersede_map[record.superseded_entity_id] = record.replacement_entity_id
        while True:
            if current_id in visited:
                raise SupersedeCycleDetected(f"Supersede cycle detected at entity {current_id!r}")
            visited.add(current_id)
            if depth > max_depth:
                raise SupersedeChainTooDeep(
                    f"Supersede chain exceeded max_depth={max_depth} (started from {entity_id!r})"
                )
            next_id = supersede_map.get(current_id)
            if next_id is None:
                # Terminal — return the actual entity.
                return self.get_entity(current_id)
            current_id = next_id
            depth += 1

    def latest_resolution_for(
        self,
        source_id: str,
        atom_id: str,
        operand_index: int,
        max_depth: int = 256,
    ) -> Resolution | None:
        """Find the latest non-superseded Resolution for a triple.

        Scans all resolutions for the given ``(source_id, atom_id,
        operand_index)`` triple, then follows ResolutionSupersede chains
        to find the terminal (non-superseded) resolution. Returns ``None``
        if no resolution for the triple exists.

        Args:
            source_id: Source document id.
            atom_id: Atom id.
            operand_index: Zero-indexed operand position.
            max_depth: Maximum supersede-chain depth.

        Returns:
            The terminal ``Resolution`` or ``None`` if the triple has no
            resolution.

        Raises:
            SupersedeCycleDetected: if the supersede chain contains a cycle.
            SupersedeChainTooDeep: if the chain exceeds ``max_depth``.
        """
        # Build supersede map: superseded_resolution_id → replacement_resolution_id
        supersede_map: dict[str, str] = {}
        for record in self.list_supersedes(kind="resolution"):
            if isinstance(record, ResolutionSupersede):
                supersede_map[record.superseded_resolution_id] = record.replacement_resolution_id

        # Collect all resolutions for this triple.
        candidates = [
            r
            for r in self.list_resolutions(source_id=source_id)
            if r.atom_id == atom_id and r.operand_index == operand_index
        ]
        if not candidates:
            return None

        # Superseded resolution ids (those that appear as a key in supersede_map)
        superseded_ids: set[str] = set(supersede_map.keys())

        # Walk from any candidate that is NOT superseded as the entry point.
        # In a well-formed chain, at most one root resolution exists.
        roots = [c for c in candidates if c.id not in superseded_ids]
        if not roots:
            # All candidates are superseded; find the terminal by walking.
            # Start from the "youngest" replacement.
            start = candidates[0]
        else:
            start = roots[0]

        # Walk the supersede chain from start.id.
        current_id = start.id
        visited: set[str] = set()
        depth = 0
        while True:
            if current_id in visited:
                raise SupersedeCycleDetected(
                    f"Supersede cycle detected at resolution {current_id!r}"
                )
            visited.add(current_id)
            if depth > max_depth:
                raise SupersedeChainTooDeep(
                    f"Supersede chain exceeded max_depth={max_depth} "
                    f"(started from triple ({source_id!r}, {atom_id!r}, "
                    f"{operand_index}))"
                )
            next_id = supersede_map.get(current_id)
            if next_id is None:
                # Terminal — check if a resolution with this id is on disk.
                try:
                    return self.get_resolution(current_id)
                except SubstrateNotFound:
                    return None
            current_id = next_id
            depth += 1

    # --- T3.7: Phase-1-promised enumerators ------------------------------

    def list_distillations(self) -> Iterable[str]:
        """Yield source_ids of all distillations in the workspace.

        Scans the ``distillations/`` directory and yields the name of
        each subdirectory (which is the source_id). Sorted
        lexicographically for determinism.
        """
        distillations_dir = self.root / "distillations"
        if not distillations_dir.is_dir():
            return
        for path in sorted(distillations_dir.iterdir()):
            if path.is_dir():
                yield path.name

    def list_relations(self, source_id: str) -> Iterable[Relation]:
        """Yield all Relation records for a given source_id.

        Scans ``distillations/<source_id>/relations/`` and parses each
        ``.yaml`` file. Sorted lexicographically by filename.
        """
        relations_dir = self._distillation_root(source_id) / "relations"
        if not relations_dir.is_dir():
            return
        for path in sorted(relations_dir.iterdir()):
            if not path.is_file():
                continue
            if not path.name.endswith(".yaml"):
                continue
            if ".tmp." in path.name:
                continue
            from ._serialize import parse_relation_yaml  # avoid re-import cycle risk

            yield parse_relation_yaml(path.read_text(encoding="utf-8"))

    def list_clarifications(
        self,
        *,
        status: Literal["open", "resolved"] | None = None,
        kind: str | None = None,
    ) -> Iterable[Clarification]:
        """Yield Clarification records across all distillations.

        Scans ``distillations/*/clarifications/{open,resolved}/`` for
        ``c-*.md`` files. Filters by ``status`` and/or ``kind`` if
        provided.

        Args:
            status: ``"open"``, ``"resolved"``, or ``None`` for both.
            kind: Clarification kind string or ``None`` for all kinds.
        """
        from ._serialize import parse_clarification_md

        distillations_dir = self.root / "distillations"
        if not distillations_dir.is_dir():
            return

        buckets: list[str]
        if status == "open":
            buckets = ["open"]
        elif status == "resolved":
            buckets = ["resolved"]
        else:
            buckets = ["open", "resolved"]

        for src_dir in sorted(distillations_dir.iterdir()):
            if not src_dir.is_dir():
                continue
            for bucket in buckets:
                bucket_dir = src_dir / "clarifications" / bucket
                if not bucket_dir.is_dir():
                    continue
                for path in sorted(bucket_dir.iterdir()):
                    if not path.is_file():
                        continue
                    if not path.name.endswith(".md"):
                        continue
                    if ".tmp." in path.name:
                        continue
                    clarification = parse_clarification_md(path.read_text(encoding="utf-8"))
                    if kind is not None and clarification.kind != kind:
                        continue
                    yield clarification

    # --- T3.8: ensure_mappings_readme (CV-4) -----------------------------

    _MAPPINGS_README_MARKER: ClassVar[str] = "<!-- amanuensis-generated: do not edit -->"

    _MAPPINGS_SUBDIR_DESCRIPTIONS: ClassVar[dict[str, str]] = {
        "entities": (
            "Canonical cross-document entities. "
            "Each file is ``e-<hash>.md`` (YAML frontmatter + optional notes body)."
        ),
        "resolutions": (
            "Resolution records joining operand-refs to canonical entities. "
            "Each file is ``j-<hash>.yaml``."
        ),
        "supersedes": (
            "Supersede records (corrections). "
            "``s-<hash>.yaml`` = ResolutionSupersede; "
            "``t-<hash>.yaml`` = EntitySupersede. "
            "Both kinds live in this directory."
        ),
        "provenance": ("Mappings-layer provenance records. Each file is ``p-<hash>.yaml``."),
        "vocabulary-history": (
            "Archived entity-vocabulary snapshots. "
            "Each file is ``<archived-id>.yaml`` where the id is the "
            "SHA-256 of the superseded snapshot bytes (first 16 hex chars)."
        ),
    }

    def ensure_mappings_readme(self) -> None:
        """Write README files for the ``mappings/`` directory tree.

        Writes ``mappings/README.md`` and a README.md in each of the
        five standard subdirectories. Content is deterministic (byte-
        identical on every call), satisfying CV-4's idempotency
        requirement.

        Existing files are overwritten only if content would change;
        atomic_write_text ensures readers never see torn content.
        """
        marker = self._MAPPINGS_README_MARKER

        # Parent README
        parent_readme = (
            f"{marker}\n\n"
            "# mappings/\n\n"
            "Workspace-level entity mappings produced by Phase 2a.\n\n"
            "## Subdirectories\n\n"
            "| Directory | Contents |\n"
            "| --- | --- |\n"
        )
        for subdir, desc in self._MAPPINGS_SUBDIR_DESCRIPTIONS.items():
            parent_readme += f"| `{subdir}/` | {desc} |\n"

        parent_path = self.mappings_root / "README.md"
        atomic_write_text(parent_path, parent_readme)

        # Per-subdirectory READMEs
        for subdir, desc in self._MAPPINGS_SUBDIR_DESCRIPTIONS.items():
            content = f"{marker}\n\n# mappings/{subdir}/\n\n{desc}\n"
            subdir_path = self.mappings_root / subdir / "README.md"
            atomic_write_text(subdir_path, content)

    # --- Phase 2b: cross-doc relation IO (M2) -----------------------------

    def _has_resolution(self, source_id: str, atom_id: str, entity_id: str) -> bool:
        """Return True if any Resolution joins ``(source_id, atom_id, *)`` to ``entity_id``.

        The comparison is supersede-chain aware: each candidate
        Resolution's ``entity_id`` is walked via ``latest_entity_for`` and
        the terminus is compared against ``entity_id``. This covers the
        case where the original Resolution pointed to an Entity ``E_v1``
        that has since been superseded by ``E_v2`` — the cross-doc
        relation may legitimately reference ``E_v2``'s id even though no
        Resolution literally names it.

        Missing entities in the chain (e.g. an orphaned resolution whose
        ``entity_id`` has no on-disk Entity) are silently skipped: the
        caller's job is to drive the gate, not diagnose dangling state.
        """
        for res in self.list_resolutions(source_id=source_id):
            if res.atom_id != atom_id:
                continue
            try:
                chain_terminus = self.latest_entity_for(res.entity_id)
            except SubstrateNotFound:
                # Resolution references an entity that no longer exists;
                # cannot use this resolution to ground a shared-entity claim.
                continue
            if chain_terminus.id == entity_id:
                return True
        return False

    def add_cross_doc_relation(self, rel: CrossDocRelation) -> None:
        """Write a CrossDocRelation atomically.

        Gates enforced (in order):

        1. **Cross-source constraint** — refuses ``from_source_id ==
           to_source_id``. Intra-source edges belong in Phase 1
           ``Relation`` records under ``distillations/<src>/relations/``,
           not the workspace-level ``mappings/relations/`` directory.
        2. **INV-15 shared-entity gate** — ``shared_entities`` must be
           non-empty, every listed entity must exist in
           ``mappings/entities/`` (chain-walked to its terminus via
           ``latest_entity_for``), and the terminus id must be resolved
           by BOTH endpoint atoms via Phase 2a ``Resolution`` records.
        3. **Id discipline** — ``rel.id == compute_id(rel)`` (INV-8 path-
           as-truth).
        4. **INV-13 immutability** — if the canonical path exists, reads
           and parses the on-disk record. If the canonical-form bytes are
           byte-identical, this is a no-op (idempotent). If they differ,
           raises ``MutationOfImmutableRecord``.

        Lands the file at ``mappings/relations/<rel.id>.yaml`` via the
        atomic-write helper (write-to-tmp-then-rename).
        """
        # Gate 1: cross-source constraint — checked BEFORE id verification
        # so callers with malformed-but-id-matching records still get the
        # semantic error rather than a content-hash mismatch.
        if rel.from_source_id == rel.to_source_id:
            raise CrossSourceConstraintViolation(
                f"CrossDocRelation {rel.id}: from_source_id and to_source_id "
                f"are both {rel.from_source_id!r}; cross-doc relations must "
                f"span two distinct distillations"
            )
        # Gate 2: INV-15 shared-entity gate — checked BEFORE id discipline
        # so semantic violations surface even if the id is well-formed.
        if not rel.shared_entities:
            raise SharedEntityGateViolation(
                f"CrossDocRelation {rel.id}: shared_entities is empty; "
                "INV-15 requires at least one resolved shared entity"
            )
        for entity_id in rel.shared_entities:
            try:
                terminus = self.latest_entity_for(entity_id)
            except SubstrateNotFound as exc:
                raise SharedEntityGateViolation(
                    f"CrossDocRelation {rel.id}: shared entity {entity_id!r} "
                    "not found in mappings/entities/ (INV-15)"
                ) from exc
            canonical_entity_id = terminus.id
            if not self._has_resolution(rel.from_source_id, rel.from_atom_id, canonical_entity_id):
                raise SharedEntityGateViolation(
                    f"CrossDocRelation {rel.id}: from endpoint "
                    f"({rel.from_source_id}/{rel.from_atom_id}) does not "
                    f"resolve to {entity_id!r} (INV-15)"
                )
            if not self._has_resolution(rel.to_source_id, rel.to_atom_id, canonical_entity_id):
                raise SharedEntityGateViolation(
                    f"CrossDocRelation {rel.id}: to endpoint "
                    f"({rel.to_source_id}/{rel.to_atom_id}) does not "
                    f"resolve to {entity_id!r} (INV-15)"
                )
        # Gate 3: id discipline
        self._require_id_matches(rel)
        # Gate 3: INV-13 immutability via byte-identical compare of the
        # canonical serialization. CrossDocRelation has volatile fields
        # (``provenance_id``), but the canonical serializer dumps the
        # whole model — divergent volatile content STILL counts as a
        # mismatch here (idempotent re-write of an identical record is
        # the only sanctioned path). Phase 2a's Entity allows volatile-
        # only differences because its body is markdown with volatile
        # frontmatter; CrossDocRelation is pure YAML so we treat any
        # byte drift as a divergence.
        path = self.cross_doc_relation_path(rel.id)
        serialized = serialize_cross_doc_relation_yaml(rel)
        if path.is_file():
            existing_bytes = path.read_bytes()
            if existing_bytes == serialized.encode("utf-8"):
                return  # idempotent
            raise MutationOfImmutableRecord(
                f"CrossDocRelation at {path} already exists with different "
                f"content; refusing to overwrite (INV-13)"
            )
        atomic_write_text(path, serialized)

    def _load_cross_doc_relation(self, path: Path) -> CrossDocRelation:
        """Read and parse a CrossDocRelation from a single ``x-*.yaml`` path."""
        return parse_cross_doc_relation_yaml(path.read_text(encoding="utf-8"))

    def get_cross_doc_relation(self, relation_id: str) -> CrossDocRelation:
        """Load a single CrossDocRelation by id.

        Public counterpart to ``_load_cross_doc_relation``, exposed so
        callers (web routes, CLI) can fetch a single record by id
        without reaching into the private path helper. Mirrors the
        Phase 2a accessor pattern (``get_entity``, ``get_resolution``).

        Args:
            relation_id: CrossDocRelation id (``x-`` prefix).

        Raises:
            SubstrateNotFound: if no ``x-<id>.yaml`` exists.
        """
        path = self.cross_doc_relation_path(relation_id)
        if not path.is_file():
            raise SubstrateNotFound(f"cross-doc relation not found at {path}")
        return self._load_cross_doc_relation(path)

    def list_cross_doc_relations(
        self,
        *,
        kind: Literal["supports", "attacks", "undercuts"] | None = None,
        from_source: str | None = None,
        to_source: str | None = None,
        touching_source: str | None = None,
        shared_entity: str | None = None,
    ) -> Iterable[CrossDocRelation]:
        """Yield CrossDocRelation records, optionally filtered.

        Walks ``mappings/relations/`` and parses every ``x-*.yaml``.
        Skips ``.tmp.*`` writer leftovers (defense against torn writes
        per Phase 1 convention). Order is lexicographic by id
        (deterministic across runs / platforms).

        All filter kwargs compose with **AND** semantics; ``None`` means
        "do not filter on this dimension". Filter semantics:

        - ``kind``: exact match against ``rel.kind``.
        - ``from_source``: exact match against ``rel.from_source_id``.
        - ``to_source``: exact match against ``rel.to_source_id``.
        - ``touching_source``: matches if EITHER endpoint matches
          (``from_source_id`` OR ``to_source_id``). Use this when the
          caller cares about every edge incident to a source.
        - ``shared_entity``: matches if the given entity id appears in
          ``rel.shared_entities``.

        Args:
            kind: One of ``"supports" | "attacks" | "undercuts"``, or
                ``None`` for any kind.
            from_source: If set, only yield edges originating from this
                source id.
            to_source: If set, only yield edges terminating at this
                source id.
            touching_source: If set, yield edges where this source id
                appears at EITHER endpoint.
            shared_entity: If set, yield edges whose ``shared_entities``
                list contains this entity id.
        """
        relations_dir = self.mappings_root / "relations"
        if not relations_dir.is_dir():
            return
        for path in sorted(relations_dir.iterdir()):
            if not path.is_file():
                continue
            if not path.name.endswith(".yaml"):
                continue
            if ".tmp." in path.name:
                continue
            # Only x-*.yaml files are cross-doc relations; sibling
            # README.md or other files don't belong here, but be
            # defensive against future co-tenants.
            if not path.name.startswith("x-"):
                continue
            rel = self._load_cross_doc_relation(path)
            if kind is not None and rel.kind != kind:
                continue
            if from_source is not None and rel.from_source_id != from_source:
                continue
            if to_source is not None and rel.to_source_id != to_source:
                continue
            if touching_source is not None and (
                rel.from_source_id != touching_source and rel.to_source_id != touching_source
            ):
                continue
            if shared_entity is not None and shared_entity not in rel.shared_entities:
                continue
            yield rel

    def add_cross_doc_relation_supersede(self, sup: CrossDocRelationSupersede) -> None:
        """Write a CrossDocRelationSupersede record atomically.

        Mirrors ``add_resolution_supersede`` / ``add_entity_supersede``.
        Lands under ``mappings/supersedes/<sup.id>.yaml`` — the same
        shared directory used by Phase 2a's ``s-`` (ResolutionSupersede)
        and ``t-`` (EntitySupersede) records. Records are distinguished
        by id-prefix and by the ``kind`` discriminator on the record
        itself (``"cross-doc-relation"`` here, ``"resolution"`` /
        ``"entity"`` for Phase 2a).

        Gates enforced:

        1. **Id discipline** — ``sup.id == compute_id(sup)``.
        2. **INV-13 immutability** — if the canonical path exists, reads
           the existing bytes. If byte-identical, no-op (idempotent). If
           divergent, raises ``MutationOfImmutableRecord``.
        """
        self._require_id_matches(sup)
        path = self.supersede_path(sup.id)
        serialized = serialize_cross_doc_relation_supersede_yaml(sup)
        if path.is_file():
            existing_bytes = path.read_bytes()
            if existing_bytes == serialized.encode("utf-8"):
                return  # idempotent
            raise MutationOfImmutableRecord(
                f"CrossDocRelationSupersede at {path} already exists with "
                f"different content; refusing to overwrite (INV-13)"
            )
        atomic_write_text(path, serialized)

    def get_cross_doc_relation_supersede(self, supersede_id: str) -> CrossDocRelationSupersede:
        """Read and return a CrossDocRelationSupersede by its id."""
        path = self.supersede_path(supersede_id)
        if not path.is_file():
            raise SubstrateNotFound(f"cross-doc relation supersede not found at {path}")
        return parse_cross_doc_relation_supersede_yaml(path.read_text(encoding="utf-8"))

    def latest_cross_doc_relation_for(
        self,
        relation_id: str,
        max_depth: int = 256,
    ) -> CrossDocRelation | None:
        """Walk the CrossDocRelationSupersede chain and return the terminal record.

        Starting from ``relation_id``, follows
        ``CrossDocRelationSupersede`` records (``supersedes_id`` →
        ``superseded_by_id``) until no further supersede exists. Returns
        the terminal ``CrossDocRelation`` if it can be loaded, else
        ``None``.

        The supersede directory ``mappings/supersedes/`` is shared with
        Phase 2a's ``s-*`` (ResolutionSupersede) and ``t-*``
        (EntitySupersede) records. We glob ``v-*.yaml`` so neighbouring
        kinds are filtered out at the filesystem layer rather than at
        parse time.

        Args:
            relation_id: Starting cross-doc relation id (``x-`` prefix).
            max_depth: Maximum chain depth before raising
                ``SupersedeChainTooDeep``.

        Returns:
            The terminal ``CrossDocRelation``, or ``None`` if no
            cross-doc relation exists at ``relation_id`` (and no
            supersede record points away from it).

        Raises:
            SupersedeCycleDetected: if the chain contains a cycle.
            SupersedeChainTooDeep: if the chain exceeds ``max_depth``.
        """
        # Build supersede map: supersedes_id → superseded_by_id, restricted
        # to ``v-`` records (cross-doc relation kind). The list_supersedes
        # dispatch handles directory existence + kind filtering — Phase 2b
        # cleanup-1 consolidated this from a direct ``glob("v-*.yaml")``.
        supersede_map: dict[str, str] = {}
        for record in self.list_supersedes(kind="cross-doc-relation"):
            if not isinstance(record, CrossDocRelationSupersede):
                continue  # type-narrowing for Pyright; runtime is already filtered
            supersede_map[record.supersedes_id] = record.superseded_by_id

        # Walk the chain from relation_id.
        visited: set[str] = set()
        current_id = relation_id
        depth = 0
        while True:
            if current_id in visited:
                raise SupersedeCycleDetected(
                    f"Supersede cycle detected at cross-doc relation {current_id!r}"
                )
            visited.add(current_id)
            if depth > max_depth:
                raise SupersedeChainTooDeep(
                    f"Supersede chain exceeded max_depth={max_depth} (started from {relation_id!r})"
                )
            next_id = supersede_map.get(current_id)
            if next_id is None:
                # Terminal — try to load the underlying relation. Absence
                # means the id was never written; return None to mirror
                # ``latest_resolution_for``.
                path = self.cross_doc_relation_path(current_id)
                if not path.is_file():
                    return None
                return self._load_cross_doc_relation(path)
            current_id = next_id
            depth += 1
