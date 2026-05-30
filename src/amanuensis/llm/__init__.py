"""LLM-call boundary mechanics (M5).

This package wraps the only place in amanuensis where non-deterministic
computation is permitted: an LLM call. INV-4 makes the boundary explicit,
gated, and audited. The package itself contains NO HTTP / SDK / process-
spawning code — actual model invocation is the dispatch driver's concern
(M6.2). What lives here is the structural envelope:

- :mod:`amanuensis.llm.queue` — :class:`DispatchQueueEntry` Pydantic
  model describing one queued LLM call. M6.1 will reuse it.
- :mod:`amanuensis.llm.cached_call` — :func:`cached_call` wrapper that
  hashes a call's inputs, checks the on-disk cache, and either copies
  the cached output into the dispatch-outputs directory (cache hit) or
  writes a queue entry for the dispatch driver to consume (cache miss).
- :mod:`amanuensis.llm.replay_log` — :func:`append_replay_entry` thin
  wrapper that takes a fully-built :class:`ReplayLogEntry` and appends
  it under the workspace flock, using the M1.7 :class:`ReplayLog`
  machinery underneath.
- :mod:`amanuensis.llm.provenance` — :func:`write_llm_provenance` PROV-O
  writer specialised to LLM-call attribution (``AgentAttribution`` with
  ``kind="llm"`` and the model id captured as ``identifier``).

Invariants enforced
-------------------
- **INV-3 (provenance by construction):** the dispatch driver pairs every
  LLM-call completion with both a PROV-O write (:func:`write_llm_provenance`)
  and a replay-log entry (:func:`append_replay_entry`). The
  ``inputs_hash`` field is the cross-reference key linking the cache
  entry, the PROV-O record, and the replay-log row.
- **INV-4 (determinism boundary):** non-deterministic LLM calls go through
  :func:`cached_call`, which assigns a deterministic ``inputs_hash`` and
  routes the call either to a cache hit (deterministic from prior output)
  or to the dispatch queue (where the boundary is named and observed).
- **INV-8 (substrate is source of truth):** every write uses
  :func:`amanuensis.fs._atomic.atomic_write_text` and the cache write is
  immediately chmod'd to 0600 to honour Phase-1-plan CV-15 (cache may
  hold sensitive prompt / output material).
"""

from .cached_call import CachedCallResult, cached_call
from .provenance import write_llm_provenance
from .queue import DispatchQueueEntry
from .replay_log import append_replay_entry

__all__ = [
    "CachedCallResult",
    "DispatchQueueEntry",
    "append_replay_entry",
    "cached_call",
    "write_llm_provenance",
]
