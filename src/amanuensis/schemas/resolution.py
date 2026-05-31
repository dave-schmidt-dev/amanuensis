"""Resolution — one immutable join between an operand-ref and a canonical entity.

The unit of cross-document joinable evidence. Two non-superseded
resolutions for the same (source_id, atom_id, operand_index) triple
cannot coexist (INV-14). Corrections go through ResolutionSupersede (§4.4).

Notes
-----
- ``id`` is a content-addressable hash of normalized resolution content
  excluding ``provenance_id`` (the provenance pointer is "volatile"
  for canonical-form hashing — see plan §4 and M1.5).
- Strict Pydantic v2 mode + ``extra="forbid"`` is enforced via
  ``model_config``.
- The ``basis`` field is one-line only (no embedded newlines or
  carriage returns).
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ._shared import RoleAttribution


class Resolution(BaseModel):
    """One immutable join: (source, atom, operand-index) → entity.

    The unit of cross-document joinable evidence. Two non-superseded
    resolutions for the same triple cannot coexist (INV-14). Corrections
    go through ResolutionSupersede (§4.4).
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    # Volatile fields dropped from canonical-form hashing (see
    # ``_hashing.py``). ``id`` is universally dropped by the hasher and
    # is NOT listed here. ``provenance_id`` is volatile because PROV-O
    # direction is Activity → Entity, not Entity → Activity; resolution
    # identity is the resolution content, the provenance record exists
    # to record what happened to it.
    _VOLATILE_FIELDS: ClassVar[frozenset[str]] = frozenset({"provenance_id"})

    id: str = Field(
        ...,
        description="``j-<16 hex chars>``; content-addressable (join).",
    )
    source_id: str
    atom_id: str
    operand_index: int = Field(
        ...,
        ge=0,
        description=(
            "Zero-indexed into the referenced atom's ``operands`` list. "
            "Validator ``resolution_triple_exists`` (M2) certifies the "
            "index is in range against the referenced atom."
        ),
    )
    entity_id: str
    confidence: Literal["high", "medium", "low"]
    basis: str = Field(
        ...,
        description=(
            "One-line rationale: which resolution-rule fired, or "
            "supervisor reason. Audit-readable; not re-parsed by code."
        ),
    )
    provenance_id: str
    role_attributions: list[RoleAttribution]
    schema_version: int = 1

    @field_validator("basis")
    @classmethod
    def _basis_one_line(cls, v: str) -> str:
        if any(ch in v for ch in ("\n", "\r")):
            raise ValueError("basis must be one line (no embedded newlines or carriage returns)")
        if not v.strip():
            raise ValueError("basis must be non-empty")
        return v
