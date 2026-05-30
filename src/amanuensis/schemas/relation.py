"""Relation — intra-document directed edge between two Atoms.

A Relation expresses a Toulmin-style warrant connecting two atoms in
the same source mirror. Phase 1 is intra-document only; cross-document
relations are Phase 2 (Map).

Notes
-----
- ``source_id`` MUST match both atoms' ``source_id`` (INV-9). That
  cross-reference check requires a Substrate handle, so it lives in
  M1.6 (filesystem) — NOT this schema.
- ``warrant_defensibility == "contested"`` triggers an Auditor
  clarification (plan §M7.4). M1.3 only defines the schema; no
  clarification trigger is wired here.
- ``provenance_id`` is volatile for canonical-form hashing, same rule
  as Atom (see plan §4 and M1.5).
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict

from ._shared import RoleAttribution


class Relation(BaseModel):
    """Directed warrant-bearing edge between two Atoms in the same source."""

    model_config = ConfigDict(strict=True, extra="forbid")

    # Volatile fields for canonical-form hashing (see ``_hashing.py``).
    # Same rationale as ``Atom._VOLATILE_FIELDS``: PROV-O direction is
    # Activity → Entity, so the relation's outbound provenance pointer
    # is observational metadata, not identity content.
    _VOLATILE_FIELDS: ClassVar[frozenset[str]] = frozenset({"provenance_id"})

    id: str
    source_id: str
    from_atom_id: str
    to_atom_id: str
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
    provenance_id: str
    role_attributions: list[RoleAttribution]
    schema_version: int = 1
