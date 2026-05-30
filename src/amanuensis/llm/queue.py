"""Dispatch queue entry schema (M5.1 / M6.1).

A :class:`DispatchQueueEntry` is what :func:`amanuensis.llm.cached_call.cached_call`
writes when the input hash misses the cache. The dispatch driver (M6)
reads queue entries off disk, invokes the configured LLM via a subprocess
into the host harness's CLI, validates the produced output, and on
success populates the cache.

Why a Pydantic model (not free-form YAML)
-----------------------------------------
The queue is a cross-process coordination channel: the writer is the
mutating CLI command that originated the role invocation, the reader is
the dispatch driver (a separate process). A schema gives the reader a
parse-time check that every field is present and well-typed, and gives
the writer the same parsing discipline for round-trip equality tests.

``model_config = strict + extra="forbid"`` matches the rest of the
schema layer: every queue entry must be exhaustively typed, and an
unexpected field is a bug (not a forward-compatibility opportunity).
"""

from __future__ import annotations

from typing import Any

from pydantic import AwareDatetime, BaseModel, ConfigDict


class DispatchQueueEntry(BaseModel):
    """One queued LLM call awaiting dispatch.

    Fields:
        role: Substrate role originating the call (``"extractor"``,
            ``"auditor"``, etc.). Recorded so the dispatch driver can
            route to the correct prompt and route the response to the
            correct validator.
        prompt: The role's full prompt text (already-expanded). The
            dispatch driver hands this to the model verbatim.
        inputs: Structured inputs (atoms, source-mirror references,
            vocabulary snapshot, etc.). The shape is role-specific;
            the cached-call wrapper only requires that it be JSON-
            serialisable through canonical-form encoding.
        model_id: Model identifier (e.g. ``"claude-opus-4-7"``). The
            driver routes the call to this model; the same id appears in
            the PROV-O record's ``was_attributed_to.identifier`` (the
            cross-reference INV-4 requires).
        inputs_hash: Deterministic SHA-256 hex digest of canonical
            ``{role, prompt, inputs, model_id}``. This is the cache key
            and the cross-reference field that links the queue entry to
            the eventual cache hit, the PROV-O record, and the replay-log
            entry.
        enqueued_at: tz-aware UTC timestamp at which the queue entry was
            written. The dispatch driver may use this for first-in-first-
            out ordering across queued entries; the writer does not
            depend on it for correctness.
        schema_version: Versioning hook. Bumped only when the queue
            schema changes in a breaking way; consumers that don't
            handle a new version refuse to process the entry.
    """

    model_config = ConfigDict(strict=True, extra="forbid")

    role: str
    prompt: str
    inputs: dict[str, Any]
    model_id: str
    inputs_hash: str
    enqueued_at: AwareDatetime
    schema_version: int = 1
