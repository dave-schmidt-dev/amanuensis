"""EntitySupersede — supervisor correction at the entity level.

Records a supervisor merge, split, or rename of canonical entities.
Immutable records; see Phase 2a plan §4.5 for the authoritative schema spec.

Notes
-----
- ``id`` is a content-addressable hash with prefix ``t-`` (tracking-id).
- ``kind`` is the discriminator, fixed to ``"entity"``.
- ``superseded_entity_id`` and ``replacement_entity_id`` are both
  entity ids (prefix ``e-...``).
- ``reason`` is a non-empty string (stripped) describing the correction.
- ``provenance_id`` is volatile for canonical-form hashing.
- Strict Pydantic v2 mode + ``extra="forbid"`` is enforced via
  ``model_config``.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ._shared import RoleAttribution


class EntitySupersede(BaseModel):
    """Records a supervisor correction at the entity level.

    Used for merges (two surface-form clusters resolved to one canonical
    entity), splits (one mis-merged entity reduced to two), and renames
    (canonical_name correction). Same shape as ``ResolutionSupersede``;
    different discriminator and different identifier semantics.
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    _VOLATILE_FIELDS: ClassVar[frozenset[str]] = frozenset({"provenance_id"})

    id: str = Field(
        ...,
        description="Content-addressable tracking id; prefix t-",
    )
    kind: Literal["entity"] = "entity"
    superseded_entity_id: str = Field(
        ...,
        description="The entity id being superseded (prefix e-)",
    )
    replacement_entity_id: str = Field(
        ...,
        description="The replacement entity id (prefix e-)",
    )
    reason: str = Field(
        ...,
        description="Non-empty reason for the supersession",
    )
    provenance_id: str
    role_attributions: list[RoleAttribution]
    schema_version: int = 1

    @field_validator("reason")
    @classmethod
    def _reason_non_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("reason must be non-empty")
        return v
