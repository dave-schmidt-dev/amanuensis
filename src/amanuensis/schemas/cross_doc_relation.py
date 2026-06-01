"""CrossDocRelation — cross-document directed edge between two Atoms.

A CrossDocRelation expresses a Toulmin-style warrant connecting two atoms
in DIFFERENT distillations, grounded by at least one shared canonical
entity (Phase 2a Resolution records). Phase 1's ``Relation`` covers the
intra-document case; this Phase 2b schema covers the cross-document case
and lives under ``mappings/relations/x-<hash>.yaml`` on disk.

Notes
-----
- ``from_source_id != to_source_id`` MUST hold (cross-doc requirement).
  This is a write-time gate enforced by M2 substrate IO, NOT the schema
  layer — the schema accepts any string for both fields.
- ``shared_entities`` MUST be non-empty AND every listed entity must be
  resolved by BOTH endpoints (INV-15). That cross-reference check
  requires a Substrate handle, so it lives in M2 — NOT this schema. The
  schema accepts an empty list; M2 rejects it.
- ``warrant_defensibility == "contested"`` will (in M5) trigger a
  Map-Auditor clarification; M1 only defines the schema.
- Id prefix is ``x-`` (cross-doc); ``r-`` is reserved for Phase 1
  intra-doc ``Relation``.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict

from ._shared import RoleAttribution


class CrossDocRelation(BaseModel):
    """Directed warrant-bearing edge between two Atoms in different sources."""

    model_config = ConfigDict(strict=True, extra="forbid")

    # Volatile fields for canonical-form hashing (see ``_hashing.py``).
    # Same rationale as Phase 1 ``Relation._VOLATILE_FIELDS``: PROV-O
    # direction is Activity → Entity, so the relation's outbound
    # provenance pointer is observational metadata, not identity content.
    _VOLATILE_FIELDS: ClassVar[frozenset[str]] = frozenset({"provenance_id"})

    id: str
    from_atom_id: str
    from_source_id: str
    to_atom_id: str
    to_source_id: str
    kind: Literal["supports", "attacks", "undercuts"]
    warrant: str
    warrant_defensibility: Literal[
        "literature-backed",
        "methodology-derived",
        "conventional",
        "contested",
    ]
    warrant_basis: str
    confidence: Literal["high", "medium", "low"]
    shared_entities: list[str]
    provenance_id: str
    role_attributions: list[RoleAttribution]
    schema_version: int = 1
