"""IterationDirective — human instruction targeting a phase's outputs.

An ``IterationDirective`` records a human-issued instruction that asks
the substrate to revise a phase's artifacts (e.g. "re-extract section
§3 with stricter qualifier discipline"). Phase 1 only issues
directives from human supervisors; ``issued_by.kind`` is conventionally
``"human"`` but this is not enforced at the schema layer.

Lifecycle is two-phase: ``issued`` (creation) → ``applied`` (after the
target phase consumes it).

Notes
-----
- ``issued_provenance_id`` is REQUIRED and points to an
  ``iteration-issued`` ``ProvenanceRecord``.
- ``applied_provenance_id`` is OPTIONAL on creation and populated when
  the directive is applied; it points to a separate
  ``iteration-applied`` ``ProvenanceRecord``. The symmetric
  issued/applied provenance pair is walked by the INV-3 completeness
  gate (M2.5).
- ``target_artifacts`` accepts atom / relation / finding ids OR path
  globs (per plan §4); both are plain strings at the schema layer.
- All datetime fields are tz-aware (``AwareDatetime``).
- Strict Pydantic v2 mode + ``extra="forbid"`` is enforced via
  ``model_config``.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict

from ._shared import AgentAttribution


class IterationDirective(BaseModel):
    """A human instruction to revise a phase's outputs."""

    model_config = ConfigDict(strict=True, extra="forbid")

    # Volatile fields for canonical-form hashing (see ``_hashing.py``).
    # The directive's identity is the instruction + issue context; the
    # issued→applied lifecycle does NOT change identity (application is
    # recorded via paired provenance records). ``issued_provenance_id``
    # and ``applied_provenance_id`` are PROV-O Entity→Activity pointers,
    # same volatility rationale as Atom's provenance_id.
    _VOLATILE_FIELDS: ClassVar[frozenset[str]] = frozenset(
        {
            "applied_at",
            "applied_by",
            "applied_outcome",
            "issued_provenance_id",
            "applied_provenance_id",
        }
    )

    id: str
    issued_at: AwareDatetime
    issued_by: AgentAttribution
    target_phase: Literal["distill", "map", "extend", "synthesize"]
    target_artifacts: list[str]
    directive: str
    rationale: str

    applied_at: AwareDatetime | None = None
    applied_by: AgentAttribution | None = None
    applied_outcome: str | None = None

    # Symmetric issued/applied provenance pair (see module docstring).
    issued_provenance_id: str
    applied_provenance_id: str | None = None

    schema_version: int = 1
