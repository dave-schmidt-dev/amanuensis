"""Records a supervisor correction at the resolution level.

A ``ResolutionSupersede`` carries no semantic content beyond the
old → new pointer; the corrected resolution is a separate new
``Resolution`` record. Walking the supersede chain yields the
current resolution for a given triple.

See Phase 2a plan §4.4 for the authoritative schema spec; this module
implements that spec verbatim.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, field_validator

from ._shared import RoleAttribution


class ResolutionSupersede(BaseModel):
    """Records a supervisor correction at the resolution level.

    A ``ResolutionSupersede`` carries no semantic content beyond the
    old → new pointer; the corrected resolution is a separate new
    ``Resolution`` record. Walking the supersede chain yields the
    current resolution for a given triple.
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    # Discriminator literal; lets EntitySupersede and ResolutionSupersede
    # live in the same directory distinguished by ID prefix (filename)
    # AND by the `kind` discriminator.
    kind: Literal["resolution"] = "resolution"

    # Volatile fields dropped from canonical-form hashing. ``id`` is
    # universally dropped by the hasher and is NOT listed here.
    # ``provenance_id`` is volatile because PROV-O direction is
    # Activity → Entity, not Entity → Activity; supersede identity is
    # the relationship content, the provenance record exists to record
    # what happened to it.
    _VOLATILE_FIELDS: ClassVar[frozenset[str]] = frozenset({"provenance_id"})

    # --- Identity ---
    id: str  # ``s-<16 hex chars>``
    superseded_resolution_id: str
    replacement_resolution_id: str

    # --- Correction reason ---
    reason: str

    # --- Provenance (always populated, never optional) ---
    provenance_id: str

    # --- Audit ---
    role_attributions: list[RoleAttribution]
    schema_version: int = 1

    @field_validator("reason")
    @classmethod
    def _reason_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("reason must be non-empty")
        return v
