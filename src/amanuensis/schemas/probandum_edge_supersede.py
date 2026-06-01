"""ProbandumEdgeSupersede — supervisor correction at the probandum-edge level.

Correction record for a ``ProbandumEdge``. Mirror of
``ProbandumSupersede`` for edge-level corrections (e.g. tightening a
warrant, flipping ``supports`` to ``attacks``). Immutable; carries its
own PROV-O record.

Notes
-----
- ``id`` is a content-addressable hash with prefix ``o-``.
- ``kind`` is the discriminator, fixed to ``"probandum-edge"``.
- ``supersedes_id`` / ``superseded_by_id`` are both probandum-edge ids
  (prefix ``q-``).
- ``reason`` is a non-empty string (stripped) describing the correction.
- ``provenance_id`` and ``at`` are volatile for canonical-form hashing.
- Strict Pydantic v2 mode + ``extra="forbid"`` is enforced via
  ``model_config``.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, field_validator

from ._shared import RoleAttribution


class ProbandumEdgeSupersede(BaseModel):
    """Records a supervisor correction at the probandum-edge level."""

    model_config = ConfigDict(strict=True, extra="forbid")

    _VOLATILE_FIELDS: ClassVar[frozenset[str]] = frozenset({"provenance_id", "at"})

    id: str
    supersedes_id: str
    superseded_by_id: str
    kind: Literal["probandum-edge"] = "probandum-edge"
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
