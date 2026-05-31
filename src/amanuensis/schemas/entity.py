"""Entity — canonical cross-document entity.

The unit of entity resolution: every operand-ref of ``kind=entity``
across the workspace resolves (via a ``Resolution`` record) to one
``Entity``. Content-addressable; immutable (INV-13). Corrections go
through ``EntitySupersede`` (see Phase 2a plan §4.5).

Notes
-----
- ``id`` is a content-addressable hash of normalized entity content
  excluding ``provenance_id`` (the provenance pointer is "volatile"
  for canonical-form hashing — see plan §4.2 and M1.5). For M1.3 ``id``
  accepts any non-empty string; M1.5 implements the hashing module.
- ``kind`` MUST be drawn from the closed entity-kind vocabulary pinned
  in ``mappings/entity-vocabulary-snapshot.yaml``. That check is M2.x
  (``EntityKindNotInSnapshot`` validator) and not enforced here at the
  schema layer.
- Strict Pydantic v2 mode + ``extra="forbid"`` is enforced via
  ``model_config``.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ._shared import RoleAttribution


class Entity(BaseModel):
    """Canonical cross-document entity.

    The unit of entity resolution: every operand-ref of ``kind=entity``
    across the workspace resolves (via a ``Resolution`` record) to one
    ``Entity``. Content-addressable; immutable (INV-13). Corrections go
    through ``EntitySupersede`` (§4.5).
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    # ``provenance_id`` is volatile for the same reason it is on
    # Atom/Relation (Activity → Entity is the PROV-O direction).
    _VOLATILE_FIELDS: ClassVar[frozenset[str]] = frozenset({"provenance_id"})

    # --- Identity ---
    id: str = Field(
        ...,
        description="``e-<16 hex chars>``; content-addressable.",
    )

    # --- Entity classification ---
    kind: str = Field(
        ...,
        description=(
            "Entity kind — MUST be the ``id`` of an entry in the "
            "mapping's ``entity-vocabulary-snapshot.yaml``. Closed-vocab "
            "check is the M2 validator (INV-12)."
        ),
    )

    # --- Canonical form ---
    canonical_name: str = Field(
        ...,
        description="Canonical surface form; must be non-empty after strip.",
    )
    aliases: list[str] = Field(
        default_factory=list,
        description="Surface forms seen across the corpus.",
    )
    notes: str | None = Field(
        default=None,
        description="Supervisor-authored disambiguation text (markdown).",
    )

    # --- Provenance (always populated, never optional) ---
    # provenance_id is volatile for canonical-form hashing (see M1.5).
    # Entity identity = entity content excluding its prov pointer.
    provenance_id: str

    # --- Audit ---
    role_attributions: list[RoleAttribution]
    schema_version: int = 1

    @field_validator("canonical_name")
    @classmethod
    def _non_empty_canonical(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("canonical_name must be non-empty")
        return v

    @field_validator("kind")
    @classmethod
    def _non_empty_kind(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("kind must be non-empty")
        return v
