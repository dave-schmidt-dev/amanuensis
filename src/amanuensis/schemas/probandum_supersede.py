"""ProbandumSupersede — supervisor correction at the probandum level.

Correction record for a ``Probandum``. Mirror of Phase 2b's
``CrossDocRelationSupersede`` for the new Phase 2c ``Probandum`` schema.
Immutable; carries its own PROV-O record.

Notes
-----
- ``id`` is a content-addressable hash with prefix ``u-``.
- ``kind`` is the discriminator, fixed to ``"probandum"``.
- ``supersedes_id`` / ``superseded_by_id`` are both probandum ids
  (prefix ``p-``).
- ``reason`` is a non-empty string (stripped) describing the correction.
- ``provenance_id`` and ``at`` are volatile for canonical-form hashing.
- Strict Pydantic v2 mode + ``extra="forbid"`` is enforced via
  ``model_config``.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, field_validator

from ._shared import RoleAttribution


class ProbandumSupersede(BaseModel):
    """Records a supervisor correction at the probandum level.

    A ``ProbandumSupersede`` carries no semantic content beyond the
    old -> new pointer; the corrected ``Probandum`` is a separate new
    record. Walking the supersede chain yields the current probandum
    for a given lineage.
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    _VOLATILE_FIELDS: ClassVar[frozenset[str]] = frozenset({"provenance_id", "at"})

    id: str
    supersedes_id: str
    superseded_by_id: str
    kind: Literal["probandum"] = "probandum"
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
