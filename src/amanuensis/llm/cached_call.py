"""Cached LLM-call wrapper (M5.1).

The :func:`cached_call` function is the only sanctioned entry point for
an LLM invocation in amanuensis. It does NOT itself talk to a model — it
hashes the call's inputs into a deterministic cache key and then either:

1. **Cache hit** — the cache already holds an entry for this input hash.
   We copy the cached output's bytes into
   ``<workspace>/dispatch/outputs/<role>-<inputs_hash>/output.yaml`` and
   return ``cache_hit=True`` with the destination path. No PROV-O is
   written here: a cache hit is the boundary's null outcome; the
   dispatch driver decides whether to record a PROV record for it
   (M6.5's concern, not M5.1's).

2. **Cache miss** — we write a :class:`DispatchQueueEntry` to
   ``<workspace>/dispatch/queue/<role>-<inputs_hash>.yaml`` and return
   ``cache_hit=False`` with the queue path. The dispatch driver (M6)
   reads the queue entry, runs the model, validates the output, and
   populates the cache. M5.1 stops at "queued"; the actual subprocess
   invocation is M6.2.

Why the wrapper exists structurally
-----------------------------------
INV-4 forbids non-deterministic computation outside named boundaries.
``cached_call`` is the structural boundary: every code path that wants
to consult an LLM goes through it, and the wrapper's design makes the
boundary observable (a cache key written, a queue entry written, a
replay-log entry written by the caller around the wrapper).

Filesystem layout (workspace-relative)
--------------------------------------
::

    <workspace>/
      cache/<inputs_hash>.yaml                  (mode 0600 — CV-15)
      dispatch/
        queue/<role>-<inputs_hash>.yaml         (mode 0644 — coordination msg)
        outputs/<role>-<inputs_hash>/output.yaml (mode 0600 — CV-15)
        failures/                               (created lazily by M6)

The ``cache/`` directory lives at the workspace root (not under any
single distillation): caching IS cross-distillation by design — the same
``(role, prompt, inputs, model_id)`` should not be re-invoked because it
happens to be referenced from two source documents.

CV-15 (Phase-1-plan): cache files may contain sensitive prompt / output
material. We chmod every cache write to 0600 immediately after the
atomic-rename so a concurrent reader sees either no file or a
0600-mode file — never a wider-mode intermediate.

Idempotency
-----------
- A cache-hit copy that finds the destination already exists with
  byte-identical content is a no-op.
- A cache-hit copy that finds the destination with DIFFERENT content
  overwrites it (the cache is authoritative; a stale prior dispatch
  output for this hash should not persist).
- A cache-miss with an existing queue entry overwrites the queue entry
  with the freshly-computed payload. The ``enqueued_at`` field will
  advance, which is the right behaviour: the caller has just re-stated
  the request, and the driver should consume the latest snapshot.

Concurrency
-----------
M5.1 does NOT acquire the workspace flock. Cache and queue writes are
per-input-hash files; two concurrent ``cached_call`` invocations
targeting the same hash will both end up writing the same canonical
content (the cache copy) or the same queue payload modulo
``enqueued_at`` (the queue write). ``atomic_write_text`` (M1.6) makes
each write torn-free, so a concurrent reader sees one whole file or
the other.

The dispatch driver (M6.2) takes the workspace flock when it pulls a
queue entry and writes a cache + PROV + replay-log triple — that's
where the multi-file atomicity matters.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import stat
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from amanuensis.fs._atomic import atomic_write_text
from amanuensis.fs._serialize import _safe_dump, _safe_load  # pyright: ignore[reportPrivateUsage]

from .queue import DispatchQueueEntry

CACHE_FILE_MODE: int = 0o600
"""File mode for cache + dispatch-output files (CV-15: sensitive material)."""

QUEUE_FILE_MODE: int = 0o644
"""File mode for queue entries (coordination message; no sensitive payload here)."""


@dataclass(frozen=True)
class CachedCallResult:
    """Outcome of one :func:`cached_call` invocation.

    Fields:
        cache_hit: ``True`` iff the cache held a matching entry and we
            populated the dispatch-outputs directory from it.
        output_path: Path to the populated dispatch-output file on a
            cache hit. ``None`` on a cache miss (no output exists yet).
        prov_record_id: Always ``None`` from :func:`cached_call`. The
            field exists so the dispatch driver can adopt the same
            result shape downstream (it will fill the field after writing
            a PROV record). M5.1 itself does not write PROV — the cache
            hit is the boundary's null outcome and the dispatch driver
            owns PROV bookkeeping.
        queue_entry_path: Path to the queue entry on a cache miss.
            ``None`` on a cache hit.
        inputs_hash: The cache key (SHA-256 hex of canonical-form
            ``{role, prompt, inputs, model_id}``). Returned on every
            call (hit OR miss) so the caller can cross-reference the
            PROV-O record / replay-log entry by hash.
    """

    cache_hit: bool
    output_path: Path | None
    prov_record_id: str | None
    queue_entry_path: Path | None
    inputs_hash: str


def cached_call(
    *,
    workspace_root: Path,
    role: str,
    prompt: str,
    inputs: dict[str, Any],
    model_id: str,
) -> CachedCallResult:
    """Check the LLM-call cache; on miss, enqueue a dispatch request.

    Args:
        workspace_root: Path to the workspace (must contain the INV-1
            marker — not re-validated here; callers that need the marker
            check go through :class:`amanuensis.fs.Substrate` first).
        role: Substrate role originating the call (e.g. ``"extractor"``,
            ``"auditor"``). Used in the cache / queue filenames so a
            human can see at a glance which role queued the call.
        prompt: The role's expanded prompt text.
        inputs: Structured inputs. Any JSON-friendly Python value tree;
            the canonical-form encoder accepts dicts, lists, strings,
            ints, bools, ``None``, and floats (rejecting NaN/Inf).
        model_id: Model identifier the dispatch driver will route to.

    Returns:
        A :class:`CachedCallResult` describing whether the call hit the
        cache and where the resulting artefact lives on disk.

    Side effects:
        - On cache hit: writes
          ``<workspace>/dispatch/outputs/<role>-<inputs_hash>/output.yaml``
          with mode 0600.
        - On cache miss: writes
          ``<workspace>/dispatch/queue/<role>-<inputs_hash>.yaml`` with
          mode 0644.
        - Creates ``cache/``, ``dispatch/queue/``, and
          ``dispatch/outputs/<role>-<inputs_hash>/`` as needed.
    """
    inputs_hash = _compute_inputs_hash(
        role=role,
        prompt=prompt,
        inputs=inputs,
        model_id=model_id,
    )

    cache_path = _cache_path(workspace_root, inputs_hash)
    if cache_path.is_file():
        output_path = _materialise_cache_hit(
            workspace_root=workspace_root,
            role=role,
            inputs_hash=inputs_hash,
            cache_path=cache_path,
        )
        return CachedCallResult(
            cache_hit=True,
            output_path=output_path,
            prov_record_id=None,
            queue_entry_path=None,
            inputs_hash=inputs_hash,
        )

    queue_path = _enqueue_dispatch_request(
        workspace_root=workspace_root,
        role=role,
        prompt=prompt,
        inputs=inputs,
        model_id=model_id,
        inputs_hash=inputs_hash,
    )
    return CachedCallResult(
        cache_hit=False,
        output_path=None,
        prov_record_id=None,
        queue_entry_path=queue_path,
        inputs_hash=inputs_hash,
    )


# --- Internal helpers -------------------------------------------------


def _compute_inputs_hash(
    *,
    role: str,
    prompt: str,
    inputs: dict[str, Any],
    model_id: str,
) -> str:
    """Compute the deterministic SHA-256 cache key for the call.

    Mirrors the canonical-form discipline of
    :mod:`amanuensis.schemas._hashing`: sort dict keys recursively,
    reject NaN / Inf floats, encode datetimes as ISO-8601 UTC with
    microsecond + ``Z`` suffix, render floats via ``repr()`` (shortest
    round-trip), then JSON-encode with sorted keys, ``ensure_ascii=True``,
    no whitespace, and ``allow_nan=False``.

    The encoded blob is
    ``{"role": ..., "prompt": ..., "inputs": ..., "model_id": ...}``.
    Returns the full 64-hex-char SHA-256 digest (not truncated — the
    cache key has its own namespace and birthday-collision risk doesn't
    benefit from truncation here; the substrate-id 8-byte truncation
    only makes sense for filename-friendliness, and these filenames are
    already long).
    """
    canonical_obj = _to_canonical(
        {
            "role": role,
            "prompt": prompt,
            "inputs": inputs,
            "model_id": model_id,
        }
    )
    encoded = json.dumps(
        canonical_obj,
        sort_keys=True,
        ensure_ascii=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _to_canonical(value: Any) -> Any:
    """Recursive canonical-form normalisation for the cache-key payload.

    Pared-down counterpart of
    :func:`amanuensis.schemas._hashing._to_canonical` — no per-class
    volatile drops (the payload is a plain dict, not a Pydantic model),
    but the same rules for sort order, datetimes, floats, and tuples.
    """
    if isinstance(value, dict):
        mapping: dict[str, Any] = value  # pyright: ignore[reportUnknownVariableType]
        out: dict[str, Any] = {}
        for k in sorted(mapping.keys()):
            out[k] = _to_canonical(mapping[k])
        return out
    if isinstance(value, list):
        items: list[Any] = value  # pyright: ignore[reportUnknownVariableType]
        return [_to_canonical(item) for item in items]
    if isinstance(value, tuple):
        items_tup: tuple[Any, ...] = value  # pyright: ignore[reportUnknownVariableType]
        return [_to_canonical(item) for item in items_tup]
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError(
                "naive datetime cannot appear in LLM-call inputs; "
                "use a tz-aware datetime (UTC convention)"
            )
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"
    if isinstance(value, bool):
        # bool is a subclass of int; pass through as-is BEFORE the float
        # branch so True/False stay JSON true/false (not "1.0" strings).
        return value
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            raise ValueError(f"non-finite float cannot be canonicalised: {value!r}")
        return repr(value)
    return value


def _cache_path(workspace_root: Path, inputs_hash: str) -> Path:
    """Canonical path for a cache entry."""
    return workspace_root / "cache" / f"{inputs_hash}.yaml"


def _queue_path(workspace_root: Path, role: str, inputs_hash: str) -> Path:
    """Canonical path for a queue entry."""
    return workspace_root / "dispatch" / "queue" / f"{role}-{inputs_hash}.yaml"


def _output_dir(workspace_root: Path, role: str, inputs_hash: str) -> Path:
    """Canonical directory for a dispatch output (one file per call)."""
    return workspace_root / "dispatch" / "outputs" / f"{role}-{inputs_hash}"


def _materialise_cache_hit(
    *,
    workspace_root: Path,
    role: str,
    inputs_hash: str,
    cache_path: Path,
) -> Path:
    """Copy the cached payload into the dispatch-outputs directory.

    Idempotent: if the destination already exists with byte-identical
    content, no write happens (and the caller still gets the canonical
    path back). If the destination exists with DIFFERENT content, the
    cache is authoritative and we overwrite — a stale prior dispatch
    output for this hash should not survive.

    The destination keeps the cache file's bytes verbatim. Validation /
    re-parsing is the consumer's job (the dispatch driver re-validates
    via the role's output schema before any downstream substrate write).
    """
    cache_bytes = cache_path.read_bytes()
    out_dir = _output_dir(workspace_root, role, inputs_hash)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "output.yaml"

    if out_path.is_file() and out_path.read_bytes() == cache_bytes:
        # Idempotent fast path; still chmod to make file mode self-healing.
        _chmod_safe(out_path, CACHE_FILE_MODE)
        return out_path

    # Validate the cache file parses and carries the required fields so
    # a corrupt cache entry surfaces as a clear error, not as a downstream
    # parsing surprise at the dispatch-output consumer's site.
    _validate_cache_payload(cache_path, cache_bytes)

    atomic_write_text(out_path, cache_bytes.decode("utf-8"))
    _chmod_safe(out_path, CACHE_FILE_MODE)
    return out_path


def _validate_cache_payload(cache_path: Path, cache_bytes: bytes) -> None:
    """Sanity-check the cache file's shape (CV-15 + fail-loud).

    A cache file must parse as YAML, be a top-level mapping, and carry
    ``output_payload`` and ``model_id`` (the two fields the dispatch
    driver needs to thread back into PROV-O + the role's validator).
    Anything else is a cache corruption and we raise loudly so the
    caller does not propagate garbage downstream.
    """
    try:
        payload = _safe_load(cache_bytes.decode("utf-8"))
    except (yaml.YAMLError, UnicodeDecodeError, ValueError) as exc:
        raise ValueError(
            f"cache file at {cache_path} could not be parsed as a YAML mapping: {exc}"
        ) from exc
    if "output_payload" not in payload:
        raise ValueError(f"cache file at {cache_path} missing required field 'output_payload'")
    if "model_id" not in payload:
        raise ValueError(f"cache file at {cache_path} missing required field 'model_id'")


def _enqueue_dispatch_request(
    *,
    workspace_root: Path,
    role: str,
    prompt: str,
    inputs: dict[str, Any],
    model_id: str,
    inputs_hash: str,
) -> Path:
    """Write a queue entry for the dispatch driver to consume."""
    entry = DispatchQueueEntry(
        role=role,
        prompt=prompt,
        inputs=inputs,
        model_id=model_id,
        inputs_hash=inputs_hash,
        enqueued_at=datetime.now(UTC),
    )
    queue_path = _queue_path(workspace_root, role, inputs_hash)
    payload: dict[str, Any] = entry.model_dump(mode="python")
    atomic_write_text(queue_path, _safe_dump(payload))
    _chmod_safe(queue_path, QUEUE_FILE_MODE)
    return queue_path


def _chmod_safe(path: Path, mode: int) -> None:
    """Apply ``mode`` to ``path``, masking out everything but the perm bits.

    Wrapper around :func:`os.chmod` so callers don't bake the bitmask in.
    No-op if the file vanishes between the rename and the chmod (extremely
    unlikely; defensive against a concurrent cleanup that we'd rather not
    crash on).
    """
    try:
        os.chmod(path, stat.S_IMODE(mode))
    except FileNotFoundError:  # pragma: no cover - racy cleanup; defensive
        pass
