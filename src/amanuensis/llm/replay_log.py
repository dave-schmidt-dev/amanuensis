"""Replay-log entry appender for the LLM-call boundary (M5.2).

The workspace replay log is the append-only stream of every substrate-
affecting activity. M1.7 (``amanuensis.fs.replay_log.ReplayLog``)
implements the per-distillation, flock-guarded, monotonically-sequenced
writer. M5.2's :func:`append_replay_entry` is a thin facade on top: it
takes a fully-built :class:`ReplayLogEntry` (the caller is the dispatch
driver, which has all the relevant fields available at completion time),
extracts the per-distillation routing key from the entry's
``substrate_changes`` or — if the activity is workspace-level — uses a
caller-supplied ``source_id``, and appends.

Why a facade rather than reusing :class:`ReplayLog` directly
------------------------------------------------------------
The LLM-call boundary's contract is:

  Given a *pre-built* :class:`ReplayLogEntry` (the caller knows the
  ``inputs_hash`` from :func:`cached_call`, the ``outputs_hash`` from
  the dispatch result, the timing, etc.), append it to the log under
  the workspace flock and return the on-disk path.

:class:`ReplayLog.append` builds the entry itself from kwargs because
M1.7's caller is the FS layer, not a structured driver. M5.2's caller
already has the entry. The facade keeps the M1.7 machinery (flock,
counter, cross-day orphan recovery) untouched while presenting the
LLM-boundary's actual contract.

Idempotency contract
--------------------
The facade does NOT silently de-duplicate. Each call yields a NEW entry
with a fresh ``seq``. Per the M1.7 docstring, the seq counter is
monotonically increasing per workspace; the caller's discipline is "call
once per activity completion" and that discipline is what gives
:func:`append_replay_entry` its append-only semantics.
"""

from __future__ import annotations

from pathlib import Path

from amanuensis.fs import ReplayLog
from amanuensis.fs.lock import DEFAULT_TIMEOUT_SECONDS
from amanuensis.schemas import ReplayLogEntry


def append_replay_entry(
    workspace_root: Path,
    entry: ReplayLogEntry,
    *,
    source_id: str,
    lock_timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> Path:
    """Append a pre-built :class:`ReplayLogEntry` under the workspace flock.

    Args:
        workspace_root: Path to the workspace (must contain the INV-1
            marker; the underlying :class:`ReplayLog` re-validates).
        entry: The entry to write. Its ``seq`` field is REPLACED with
            the value assigned by the per-distillation counter — the
            caller's ``seq`` is ignored. Every other field is preserved
            verbatim.
        source_id: Per-distillation routing key. The entry lands under
            ``distillations/<source_id>/replay-log/<yyyy-mm-dd>/<seq>.yaml``.
        lock_timeout: Seconds to wait for the workspace flock; forwarded
            to :meth:`amanuensis.fs.ReplayLog.append`.

    Returns:
        The on-disk path of the written entry.

    Raises:
        amanuensis.fs.WorkspaceLockTimeout: if the flock cannot be
            acquired within ``lock_timeout`` seconds.
        amanuensis.fs.SubstrateMarkerMissing: if ``workspace_root`` has
            no marker file (defended by :class:`ReplayLog`'s constructor).
    """
    log = ReplayLog(workspace_root, source_id)
    written = log.append(
        actor=entry.actor,
        activity=entry.activity,
        inputs_hash=entry.inputs_hash,
        outputs_hash=entry.outputs_hash,
        cache_hit=entry.cache_hit,
        substrate_changes=list(entry.substrate_changes),
        duration_seconds=entry.duration_seconds,
        timestamp=entry.timestamp,
        tokens_input=entry.tokens_input,
        tokens_output=entry.tokens_output,
        cost_estimate_cents=entry.cost_estimate_cents,
        lock_timeout=lock_timeout,
    )
    # Reconstruct the canonical entry-file path: M1.7 writes
    # <workspace>/distillations/<source-id>/replay-log/<day>/<seq:012d>.yaml
    # The ReplayLog method computes the same path internally; we
    # re-derive it here so callers don't need to know about ReplayLog's
    # private path resolver.
    day = written.timestamp.strftime("%Y-%m-%d")
    return (
        workspace_root.resolve()
        / "distillations"
        / source_id
        / "replay-log"
        / day
        / f"{written.seq:012d}.yaml"
    )
