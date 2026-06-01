"""CrossDocRelationSupersede — supervisor correction at the cross-doc relation level.

Correction record for a ``CrossDocRelation``. Mirror of Phase 2a's
``EntitySupersede`` / ``ResolutionSupersede`` for the new
``CrossDocRelation`` schema. Immutable; carries its own PROV-O record.

Notes
-----
- ``id`` is a content-addressable hash with prefix ``v-`` (revision).
- ``supersedes_id`` and ``superseded_by_id`` are both
  ``CrossDocRelation`` ids (prefix ``x-``).
- ``reason`` is a free-form string describing the correction; the M2
  substrate layer is expected to require non-empty, but the schema
  layer does NOT enforce that (mirroring INV-13's existing pattern
  flexibility — the substrate gate is what we trust on writes).
- ``provenance_id`` is volatile for canonical-form hashing.
- ``at`` is volatile (when the supersession was authored is
  observational metadata, not identity content).
- Strict Pydantic v2 mode + ``extra="forbid"`` is enforced via
  ``model_config``.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import AwareDatetime, BaseModel, ConfigDict

from ._shared import RoleAttribution


class CrossDocRelationSupersede(BaseModel):
    """Records a supervisor correction at the cross-doc relation level.

    A ``CrossDocRelationSupersede`` carries no semantic content beyond
    the old → new pointer; the corrected ``CrossDocRelation`` is a
    separate new record. Walking the supersede chain yields the
    current cross-doc relation for a given (from, to) pair.
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    # Volatile fields dropped from canonical-form hashing. ``id`` is
    # universally dropped by the hasher and is NOT listed here.
    # ``provenance_id`` is volatile because PROV-O direction is
    # Activity → Entity, not Entity → Activity. ``at`` is volatile
    # because the timestamp is observational metadata.
    _VOLATILE_FIELDS: ClassVar[frozenset[str]] = frozenset({"provenance_id", "at"})

    id: str
    supersedes_id: str
    superseded_by_id: str
    reason: str
    provenance_id: str
    role_attributions: list[RoleAttribution]
    at: AwareDatetime
    schema_version: int = 1
