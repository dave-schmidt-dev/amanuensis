"""Clarification — open question raised by a role on a substrate artifact.

A ``Clarification`` records a single ambiguity surfaced by a role
(typically Auditor or Extractor) that requires human resolution before
downstream work can proceed. Its lifecycle is two-phase: ``open`` →
``resolved``.

Notes
-----
- ``raised_provenance_id`` is REQUIRED and points to a
  ``clarification-raised`` ``ProvenanceRecord``.
- ``resolved_provenance_id`` is OPTIONAL on creation and populated when
  the clarification transitions to ``resolved``; it points to a
  separate ``clarification-resolved`` ``ProvenanceRecord``. The
  symmetric raised/resolved provenance pair is walked by the INV-3
  completeness gate (M2.5).
- ``context_refs`` carries the atom / relation / source-span ids that
  motivated the question; M1.4 does not validate id existence.
- All datetime fields are tz-aware (``AwareDatetime``).
- Strict Pydantic v2 mode + ``extra="forbid"`` is enforced via
  ``model_config``.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict

from ._shared import AgentAttribution


class Clarification(BaseModel):
    """An open or resolved question raised by a role on substrate artifacts."""

    model_config = ConfigDict(strict=True, extra="forbid")

    # Volatile fields for canonical-form hashing (see ``_hashing.py``).
    # The clarification's identity is the question + raise context; the
    # open→resolved lifecycle does NOT change identity (resolution is
    # recorded via paired provenance records). ``raised_provenance_id``
    # and ``resolved_provenance_id`` are PROV-O Entity→Activity
    # pointers, same volatility rationale as Atom's provenance_id.
    _VOLATILE_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "status",
            "resolved_at",
            "resolved_by",
            "resolution",
            "raised_provenance_id",
            "resolved_provenance_id",
        }
    )

    id: str
    status: Literal["open", "resolved"]
    raised_at: AwareDatetime
    raised_by: AgentAttribution
    raised_by_activity: str
    context_refs: list[str]

    question: str
    options: list[str] | None = None

    resolved_at: AwareDatetime | None = None
    resolved_by: AgentAttribution | None = None
    resolution: str | None = None

    # Symmetric raised/resolved provenance pair (see module docstring).
    raised_provenance_id: str
    resolved_provenance_id: str | None = None

    schema_version: int = 1
