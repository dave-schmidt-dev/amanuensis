"""ProbandumEdge — supports/attacks/undercuts edge in a Phase 2c tree.

A ``ProbandumEdge`` connects a parent ``Probandum`` to a child node.
The child may itself be another ``Probandum`` (interior edge in the
hierarchy), an ``Atom`` (leaf edge into Phase 1 substrate), or a
``CrossDocRelation`` (leaf edge into Phase 2b cross-doc substrate).

Notes
-----
- ``id`` is a content-addressable hash with prefix ``q-``.
- ``child_kind`` discriminates the three target shapes. When
  ``child_kind == "atom"`` the ``child_source_id`` MUST be populated
  (atoms are source-scoped); when ``child_kind in {"probandum",
  "cross-doc-relation"}`` the ``child_source_id`` MUST be ``None``
  (probanda live in the mappings namespace; cross-doc relations span
  sources). This cross-field constraint is enforced by the
  ``_child_source_id_matches_kind`` model validator on the schema layer.
- INV-16 (acyclic tree), INV-17 (lineage reaches ``ultimate``), and the
  existence checks for the child target are M3/M4 substrate concerns,
  NOT schema concerns.
- ``warrant_defensibility == "contested"`` will (in M5) trigger a
  Map-Auditor clarification; M1 only defines the schema.
- ``provenance_id`` is volatile for canonical-form hashing (same
  rationale as Atom/Relation/Entity/CrossDocRelation).
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import BaseModel, ConfigDict, model_validator

from ._shared import RoleAttribution


class ProbandumEdge(BaseModel):
    """Directed warrant-bearing edge from a probandum to a child node."""

    model_config = ConfigDict(strict=True, extra="forbid")

    _VOLATILE_FIELDS: ClassVar[frozenset[str]] = frozenset({"provenance_id"})

    id: str
    parent_probandum_id: str
    child_id: str
    child_kind: Literal["probandum", "atom", "cross-doc-relation"]
    child_source_id: str | None
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

    @model_validator(mode="after")
    def _child_source_id_matches_kind(self) -> ProbandumEdge:
        """Enforce: ``child_source_id`` required iff ``child_kind == 'atom'``.

        Atoms are source-scoped in Phase 1, so an atom-child edge MUST
        carry the child's ``source_id``. Probandum children live in the
        mappings namespace (no source); cross-doc-relation children span
        sources by definition (the relation itself records both
        endpoints). Both of those cases MUST leave ``child_source_id``
        as ``None``.
        """
        if self.child_kind == "atom":
            if self.child_source_id is None:
                raise ValueError("child_source_id is required when child_kind == 'atom'")
        elif self.child_source_id is not None:
            raise ValueError(
                "child_source_id must be None when child_kind != 'atom' "
                f"(got child_kind={self.child_kind!r})"
            )
        return self
