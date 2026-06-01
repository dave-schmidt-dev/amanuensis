"""Probandum — a proposition statement at a hierarchy level.

A ``Probandum`` is one node in a Phase 2c argument tree. The tree has an
``ultimate`` root (what the corpus is trying to prove), zero or more
``interim`` internal nodes (intermediate propositions), and ``penultimate``
nodes immediately above the atom layer. Leaves of the probandum tree
connect via ``ProbandumEdge`` records to ``Atom`` (Phase 1) or
``CrossDocRelation`` (Phase 2b) records.

Notes
-----
- ``id`` is a content-addressable hash with prefix ``p-`` (probandum).
  Phase 1's ``ProvenanceRecord`` also uses ``p-`` for an unrelated
  artifact, and they coexist because PROV records live under
  ``provenance/`` and probanda live under ``mappings/probanda/`` — the
  prefix is namespaced by directory.
- ``kind`` distinguishes the tree position (``"ultimate"``,
  ``"interim"``, ``"penultimate"``). The hierarchy invariants
  themselves (INV-16 acyclic tree, INV-17 lineage-reaches-ultimate,
  INV-18 closed Walton-scheme vocabulary, INV-19 alternatives non-empty
  for non-ultimate) are enforced by the M3/M4 substrate layer — NOT
  the schema. The schema accepts any vocabulary string for ``scheme``
  and any list (incl. empty) for ``alternatives_considered``.
- ``provenance_id`` is volatile for canonical-form hashing (PROV-O
  direction Activity -> Entity; the outbound prov pointer is not part
  of identity content).
- Strict Pydantic v2 mode + ``extra="forbid"`` is enforced via
  ``model_config``.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict

from ._shared import RoleAttribution


class Probandum(BaseModel):
    """A proposition statement at a hierarchy level in a Phase 2c argument tree."""

    model_config = ConfigDict(strict=True, extra="forbid")

    # ``provenance_id`` is volatile for canonical-form hashing (see
    # ``_hashing.py``); same rationale as Atom/Relation/Entity.
    _VOLATILE_FIELDS: ClassVar[frozenset[str]] = frozenset({"provenance_id"})

    id: str
    statement: str
    kind: Literal["ultimate", "penultimate", "interim"]
    scheme: str
    alternatives_considered: list[str]
    confidence: Literal["high", "medium", "low"]
    provenance_id: str
    role_attributions: list[RoleAttribution]
    schema_version: int = 1
