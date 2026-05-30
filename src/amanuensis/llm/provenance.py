"""PROV-O writer specialised for the LLM-call boundary (M5.2).

:func:`write_llm_provenance` builds a :class:`ProvenanceRecord` whose
``was_attributed_to`` carries ``kind="llm"`` and the model identifier
that produced the artefact, computes the record's content-addressable
id, and persists it via :meth:`amanuensis.fs.Substrate.add_provenance`.

This is the M5.2 PROV-O writer the dispatch driver (M6.5) calls when an
LLM-derived artefact lands in the substrate. It is the only place in the
codebase that writes a PROV-O record with ``kind="llm"`` attribution —
human-attributed PROV (clarification resolve, iteration issue / apply)
goes through the existing CLI commands directly.

INV-3 / INV-4 cross-reference link
----------------------------------
INV-4 requires that every LLM call carry, among other things, an input
content hash and an output content hash. The substrate-level
:class:`ProvenanceRecord` schema does NOT currently have a dedicated
``inputs_hash`` field — every field is identity content (no volatile
drops, see ``schemas/provenance.py``), and adding one would change every
existing PROV record's id.

The cross-reference link is instead carried by the replay-log entry:

- The PROV record is filed under
  ``distillations/<source-id>/provenance/<prov-id>.yaml`` and references
  the produced artefact via ``entity_id``.
- The replay-log entry (M5.2's :func:`append_replay_entry`) carries
  ``inputs_hash`` AND ``outputs_hash`` AND ``activity`` AND ``actor``
  (the same :class:`AgentAttribution`). The dispatch driver writes both
  artefacts within the same flocked section, so an auditor walking from
  the PROV record back to the replay-log entry by ``(activity, actor,
  timestamp)`` recovers the input hash.

M5.3's mutating-side gate test asserts both artefacts exist for any
LLM-call activity, closing the INV-4 loop.

Why no flock here
-----------------
:meth:`Substrate.add_provenance` uses :func:`atomic_write_text` (M1.6),
which is torn-write-free for readers. The CALLER (dispatch driver) holds
the workspace flock around the PROV write + cache write + replay-log
append triple — that's where the multi-file atomicity matters. M5.2's
writer is a leaf operation.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal, cast

from amanuensis.fs import Substrate
from amanuensis.schemas import AgentAttribution, ProvenanceRecord, compute_id

# Closed set of PROV entity types this writer accepts; mirrors the
# ``Literal[...]`` in ``ProvenanceRecord`` so a typo at the call site
# fails fast with a clear KeyError instead of leaking through to a
# Pydantic ValidationError at write time.
_LLM_ENTITY_TYPES: frozenset[str] = frozenset(
    {
        "atom",
        "relation",
        "clarification-raised",
    }
)
"""Entity types valid for LLM-attributed PROV records.

LLM-attributed PROV is written for: (a) atoms the extractor produced;
(b) relations the extractor produced; (c) clarifications the auditor
RAISED (resolution is human, not LLM, and routes through the CLI).
Iteration directives are workspace-level human input; source-mirror
artefacts are deterministic ingest output (not LLM). The frozen set
documents the policy.
"""

_LLM_ROLES: frozenset[str] = frozenset(
    {
        "extractor",
        "auditor",
        "contrarian",
        "constructive",
        "premortem",
    }
)
"""Roles that an LLM may legitimately act under.

``human_supervisor`` is excluded — the human supervisor never acts via an
LLM; LLM-attributed PROV with that role is a programming error.
"""


def write_llm_provenance(
    *,
    substrate: Substrate,
    source_id: str,
    entity_type: str,
    entity_id: str,
    activity: str,
    started_at: datetime,
    ended_at: datetime,
    used_entity_ids: list[str],
    model_id: str,
    role: str,
    inputs_hash: str,
) -> ProvenanceRecord:
    """Write a PROV-O record attributing an LLM-produced artefact.

    Args:
        substrate: Workspace substrate (writes via
            :meth:`Substrate.add_provenance`).
        source_id: Per-distillation routing key; the PROV file lands
            under ``distillations/<source_id>/provenance/``.
        entity_type: The PROV-O entity type. Must be one of
            :data:`_LLM_ENTITY_TYPES`.
        entity_id: Content-addressable id of the artefact this PROV
            record describes (the atom / relation / clarification id).
        activity: Short verb describing the LLM activity, e.g.
            ``"extractor-propose"`` or ``"auditor-audit"``.
        started_at: tz-aware UTC datetime when the activity began.
        ended_at: tz-aware UTC datetime when the activity ended.
        used_entity_ids: Substrate artefacts the LLM consumed as inputs
            (e.g. source-mirror paragraph ids that fed an extractor
            invocation).
        model_id: Model identifier (e.g. ``"claude-opus-4-7"``); becomes
            the ``identifier`` field on the :class:`AgentAttribution`.
        role: Role the LLM was acting under. Must be one of
            :data:`_LLM_ROLES`.
        inputs_hash: The cache key linking this PROV record to its
            replay-log entry. Not stored in the PROV record itself
            (the schema doesn't carry an inputs_hash field — see
            module docstring) but accepted here so the caller's
            interface matches the INV-4 contract: every LLM-call PROV
            write SHOULD be paired with a replay-log append that
            persists the hash.

    Returns:
        The persisted :class:`ProvenanceRecord` (with its computed id).

    Raises:
        ValueError: if ``entity_type`` is not in :data:`_LLM_ENTITY_TYPES`
            or ``role`` is not in :data:`_LLM_ROLES`.
    """
    if entity_type not in _LLM_ENTITY_TYPES:
        raise ValueError(
            f"entity_type {entity_type!r} is not valid for LLM-attributed PROV; "
            f"choose one of {sorted(_LLM_ENTITY_TYPES)}"
        )
    if role not in _LLM_ROLES:
        raise ValueError(
            f"role {role!r} is not valid for LLM attribution; choose one of {sorted(_LLM_ROLES)}"
        )

    # ``inputs_hash`` is accepted to document the cross-reference
    # contract at the API boundary; the field is not part of the PROV
    # record schema. Reference the parameter so static analysis (vulture)
    # sees it as used and the docstring's contract stays honest.
    _ = inputs_hash

    # ``entity_type`` and ``role`` are validated against the closed sets
    # above; cast them to the Literal-typed shapes Pydantic expects.
    entity_type_lit = cast("Literal['atom', 'relation', 'clarification-raised']", entity_type)
    role_lit = cast(
        "Literal['extractor', 'auditor', 'contrarian', 'constructive', 'premortem']",
        role,
    )

    agent = AgentAttribution(
        kind="llm",
        identifier=model_id,
        role=role_lit,
    )

    draft = ProvenanceRecord(
        id="p-" + "0" * 16,
        entity_type=entity_type_lit,
        entity_id=entity_id,
        activity=activity,
        activity_started_at=started_at,
        activity_ended_at=ended_at,
        used_entity_ids=list(used_entity_ids),
        was_attributed_to=agent,
        was_influenced_by=[],
        schema_version=1,
    )
    prov_id = compute_id(draft)
    prov = draft.model_copy(update={"id": prov_id})
    substrate.add_provenance(source_id, prov)
    return prov
