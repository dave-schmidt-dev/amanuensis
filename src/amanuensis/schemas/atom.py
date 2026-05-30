"""Atom — the leaf unit of distillation.

An Atom captures a single reduced-Toulmin assertion (claim / data /
qualifier / rebuttal) anchored to a specific span of a source mirror.
See Phase 1 plan §4 for the authoritative schema spec; this module
implements that spec verbatim.

Notes
-----
- ``id`` is a content-addressable hash of normalized atom content
  excluding ``provenance_id`` (the provenance pointer is "volatile"
  for canonical-form hashing — see plan §4 and M1.5). For M1.3 ``id``
  accepts any non-empty string; M1.5 implements the hashing module.
- ``predicate`` MUST be drawn from the closed vocabulary; that check
  is M2.x and not enforced here.
- Strict Pydantic v2 mode + ``extra="forbid"`` is enforced via
  ``model_config``.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ._shared import OperandRef, RoleAttribution


class Atom(BaseModel):
    """The leaf unit of distillation (reduced-Toulmin assertion)."""

    model_config = ConfigDict(strict=True, extra="forbid")

    # Volatile fields dropped from canonical-form hashing (see
    # ``_hashing.py``). ``id`` is universally dropped by the hasher and
    # is NOT listed here. ``provenance_id`` is volatile because PROV-O
    # direction is Activity → Entity, not Entity → Activity; atom
    # identity is the atom content, the provenance record exists to
    # record what happened to it.
    _VOLATILE_FIELDS: ClassVar[frozenset[str]] = frozenset({"provenance_id"})

    # --- Identity ---
    id: str = Field(
        ...,
        description="Content-addressable hash of normalized atom content; deterministic",
    )
    source_id: str
    section_path: list[str]
    paragraph_index: int
    sentence_index: int | None = None
    char_span: tuple[int, int]
    scale_anchor: Literal["sentence", "paragraph", "section", "document"]

    # --- Reduced Toulmin content ---
    kind: Literal["claim", "data", "qualifier", "rebuttal"]
    predicate: str
    operands: list[OperandRef]
    narrative: str

    # --- Qualifier (when kind allows) ---
    qualifier_level: Literal["high", "medium", "low", "contested"] | None = None
    qualifier_basis: str | None = None

    # --- Provenance (always populated, never optional) ---
    # provenance_id is volatile for canonical-form hashing (see M1.5).
    # Atom identity = atom content excluding its prov pointer.
    provenance_id: str

    # --- Audit ---
    role_attributions: list[RoleAttribution]
    schema_version: int = 1

    @field_validator("char_span")
    @classmethod
    def _char_span_ordered(cls, v: tuple[int, int]) -> tuple[int, int]:
        if not v[0] < v[1]:
            raise ValueError("char_span must be (start < end)")
        return v
