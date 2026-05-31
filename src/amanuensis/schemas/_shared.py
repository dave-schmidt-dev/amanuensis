"""Shared schema types used by Atom and Relation.

The underscore prefix marks this module as not part of the canonical
public reading order. Public re-exports live in
``amanuensis.schemas.__init__``.

Types defined here:

- ``AgentAttribution``: identifies an actor (human or LLM) acting in a
  specific role (extractor, auditor, etc.). Fully specified by plan §4.
- ``RoleAttribution``: records a single audit event on a substrate
  artifact (e.g. "extractor proposed at 2026-05-29T10:00:00Z"). Designed
  minimally per M1.3 task description; carries the responsible
  ``AgentAttribution`` plus activity verb and tz-aware timestamp.
- ``OperandRef``: typed reference to an entity / literal / document
  span participating in an Atom's predicate. Phase 1 deliberately keeps
  this loose so Phase 2 (Map) can normalize entity references during
  cross-document join without re-extracting.
"""

from __future__ import annotations

from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict

# Strict, no-extra config reused across this package.
_STRICT_CONFIG = ConfigDict(strict=True, extra="forbid")


class AgentAttribution(BaseModel):
    """Identifies who/what acted in a particular role.

    - ``identifier``: for humans, a user id / handle; for LLMs, the
      model id at call time (e.g. ``claude-opus-4-7``).
    - ``role``: which substrate role this agent was operating under.
    """

    model_config = _STRICT_CONFIG

    kind: Literal["human", "llm"]
    identifier: str
    role: Literal[
        "extractor",
        "auditor",
        "contrarian",
        "constructive",
        "premortem",
        "human_supervisor",
        "map-resolve",
        "map-audit",
    ]


class RoleAttribution(BaseModel):
    """Records a single audit event on a substrate artifact.

    Distinct from ``AgentAttribution``: a ``RoleAttribution`` is the
    *event* (e.g. "extractor proposed", "auditor approved"), whereas
    ``AgentAttribution`` identifies the actor.

    ``at`` is required tz-aware (``AwareDatetime``); naive datetimes
    raise ``ValidationError`` with error type ``timezone_aware``.
    Convention is ISO-8601 UTC; other tz offsets are accepted by the
    schema, callers normalize at write time.
    """

    model_config = _STRICT_CONFIG

    agent: AgentAttribution
    activity: str
    at: AwareDatetime


class OperandRef(BaseModel):
    """Typed reference to an operand participating in an Atom's predicate.

    Examples:

    - ``role="subject", kind="entity", value="ent-acme-corp"``
    - ``role="amount", kind="literal", value="50000", type_hint="money"``
    - ``role="cited", kind="doc_span", value="p3:120-185"``

    Phase 1 keeps ``value`` as a free-form string; Phase 2 (Map) will
    normalize entity references during cross-document join. ``type_hint``
    is advisory only — no validation in Phase 1.
    """

    model_config = _STRICT_CONFIG

    role: str
    kind: Literal["entity", "literal", "doc_span"]
    value: str
    type_hint: str | None = None
