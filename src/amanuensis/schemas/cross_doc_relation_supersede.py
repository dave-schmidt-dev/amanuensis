"""CrossDocRelationSupersede — supervisor correction at the cross-doc relation level.

Correction record for a ``CrossDocRelation``. Mirror of Phase 2a's
``EntitySupersede`` / ``ResolutionSupersede`` for the new
``CrossDocRelation`` schema. Immutable; carries its own PROV-O record.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, field_validator

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
    kind: Literal["cross-doc-relation"] = "cross-doc-relation"
    reason: str
    provenance_id: str
    role_attributions: list[RoleAttribution]
    at: AwareDatetime
    schema_version: int = 1

    @field_validator("reason")
    @classmethod
    def _reason_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("reason must be non-empty")
        return v
