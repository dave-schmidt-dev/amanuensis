"""ProvenanceRecord — W3C PROV-O subset for substrate artifacts.

A ``ProvenanceRecord`` captures the lineage of a single substrate entity
(an Atom, Relation, Clarification event, IterationDirective event, or
source-mirror artifact). It is the unit of evidence that satisfies INV-3
(provenance completeness) — every produced artifact references exactly
one provenance record describing the activity that created it.

Notes
-----
- ``id`` is content-addressable in M1.5; M1.4 accepts any non-empty
  string.
- ``entity_type`` is closed and includes the symmetric paired values for
  clarification / iteration lifecycle events (raised / resolved,
  issued / applied) plus the three ``source-mirror-*`` values added
  during external review so source-mirror artifacts are first-class
  provenance subjects.
- ``activity_started_at`` / ``activity_ended_at`` are tz-aware
  (``AwareDatetime``). Convention is ISO-8601 UTC.
- ``used_entity_ids`` lists the artifacts this creation drew on;
  ``was_influenced_by`` lists higher-order influences (e.g. a
  clarification or iteration directive id).
- Strict Pydantic v2 mode + ``extra="forbid"`` is enforced via
  ``model_config``.
"""

from __future__ import annotations

from typing import ClassVar, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict

from ._shared import AgentAttribution


class ProvenanceRecord(BaseModel):
    """W3C PROV-O subset describing one substrate artifact's lineage."""

    model_config = ConfigDict(strict=True, extra="forbid")

    # No volatile fields for canonical-form hashing beyond the
    # universal ``id`` drop. A provenance record IS the lifecycle
    # event — every other field is identity content. (See
    # ``_hashing.py``.)
    _VOLATILE_FIELDS: ClassVar[frozenset[str]] = frozenset()

    id: str
    entity_type: Literal[
        "atom",
        "relation",
        "clarification-raised",
        "clarification-resolved",
        "iteration-issued",
        "iteration-applied",
        "source-mirror-document",
        "source-mirror-section",
        "source-mirror-paragraph",
    ]
    entity_id: str

    activity: str
    activity_started_at: AwareDatetime
    activity_ended_at: AwareDatetime

    used_entity_ids: list[str]
    was_attributed_to: AgentAttribution
    was_influenced_by: list[str] = []

    schema_version: int = 1
