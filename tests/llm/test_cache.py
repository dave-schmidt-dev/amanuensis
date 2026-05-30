"""Cached LLM-call wrapper tests (M5.1).

Covers the five contracts the wrapper makes:

1. **Cache miss writes queue entry** — fresh workspace, one call,
   queue file exists at the canonical path with all fields populated.
2. **Cache hit copies output to dispatch outputs** — plant a cache file,
   call with matching inputs, dispatch-outputs file appears with the
   cached bytes verbatim.
3. **inputs_hash stable across dict key insertion order** — canonical
   form sorts keys; two dicts with identical content but different
   insertion order yield the same hash.
4. **inputs_hash differs across model_ids** — same prompt + inputs +
   role, different model_id ⇒ different cache key.
5. **Cache write uses mode 0600** — CV-15 (sensitive material). The
   M5.1 wrapper itself doesn't write to ``cache/`` (that's the dispatch
   driver's job in M6) but it DOES write the dispatch-output file on a
   cache hit and chmods it to 0600; we assert on the destination's mode.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

import yaml

from amanuensis.llm import DispatchQueueEntry, cached_call


def _plant_cache_entry(
    workspace: Path,
    inputs_hash: str,
    *,
    output_payload: dict[str, Any] | None = None,
    model_id: str = "claude-opus-4-7",
) -> Path:
    """Write a synthetic cache entry at the canonical path.

    Returns the path. The dispatch driver (M6) will be the real writer;
    here we hand-craft entries to exercise the cache-hit branch.
    """
    cache_dir = workspace / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    path = cache_dir / f"{inputs_hash}.yaml"
    payload: dict[str, Any] = {
        "model_id": model_id,
        "output_payload": output_payload or {"atoms": []},
        "completed_at": "2026-05-30T00:00:00.000000Z",
    }
    text = yaml.safe_dump(payload, sort_keys=True, default_flow_style=False, allow_unicode=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_cache_miss_writes_queue_entry(llm_workspace: Path) -> None:
    """Fresh workspace: one call lands a queue entry with every field set."""
    inputs = {"paragraph_id": "p-0001", "section": "I.A"}

    result = cached_call(
        workspace_root=llm_workspace,
        role="extractor",
        prompt="Extract atoms from the paragraph.",
        inputs=inputs,
        model_id="claude-opus-4-7",
    )

    assert result.cache_hit is False
    assert result.output_path is None
    assert result.prov_record_id is None
    assert result.queue_entry_path is not None
    assert result.queue_entry_path.is_file()

    # Canonical layout: dispatch/queue/<role>-<inputs_hash>.yaml
    expected = llm_workspace / "dispatch" / "queue" / f"extractor-{result.inputs_hash}.yaml"
    assert result.queue_entry_path == expected

    # The on-disk payload round-trips through the queue schema.
    raw = yaml.safe_load(result.queue_entry_path.read_text(encoding="utf-8"))
    entry = DispatchQueueEntry(**raw)
    assert entry.role == "extractor"
    assert entry.prompt == "Extract atoms from the paragraph."
    assert entry.inputs == inputs
    assert entry.model_id == "claude-opus-4-7"
    assert entry.inputs_hash == result.inputs_hash
    assert entry.enqueued_at.tzinfo is not None  # tz-aware (AwareDatetime)
    assert entry.schema_version == 1


def test_cache_hit_copies_output_to_dispatch_outputs(llm_workspace: Path) -> None:
    """Plant a cache entry; matching call yields cache_hit + dispatch-output write."""
    inputs = {"paragraph_id": "p-0042"}
    # Compute the same hash the wrapper will compute; we do it indirectly
    # by issuing a miss first (which gives us the hash) then planting the
    # cache. The miss writes a queue entry which we don't care about for
    # this test — we just need the inputs_hash for the cache filename.
    miss = cached_call(
        workspace_root=llm_workspace,
        role="auditor",
        prompt="Audit the proposed atom.",
        inputs=inputs,
        model_id="claude-opus-4-7",
    )
    inputs_hash = miss.inputs_hash

    cache_bytes_planted = _plant_cache_entry(
        llm_workspace,
        inputs_hash,
        output_payload={"audited": True, "findings": []},
    )
    expected_bytes = cache_bytes_planted.read_bytes()

    hit = cached_call(
        workspace_root=llm_workspace,
        role="auditor",
        prompt="Audit the proposed atom.",
        inputs=inputs,
        model_id="claude-opus-4-7",
    )

    assert hit.cache_hit is True
    assert hit.queue_entry_path is None
    assert hit.prov_record_id is None
    assert hit.inputs_hash == inputs_hash
    assert hit.output_path is not None
    assert hit.output_path.is_file()

    # Canonical layout: dispatch/outputs/<role>-<inputs_hash>/output.yaml
    expected_path = (
        llm_workspace / "dispatch" / "outputs" / f"auditor-{inputs_hash}" / "output.yaml"
    )
    assert hit.output_path == expected_path

    # The dispatch-output file's bytes match the cache file's bytes verbatim.
    assert hit.output_path.read_bytes() == expected_bytes


def test_inputs_hash_stable_across_dict_key_order(llm_workspace: Path) -> None:
    """Two calls with identical inputs in different key order ⇒ same hash."""
    inputs_a: dict[str, Any] = {"alpha": 1, "beta": 2, "gamma": {"nested_a": 10, "nested_b": 20}}
    inputs_b: dict[str, Any] = {"gamma": {"nested_b": 20, "nested_a": 10}, "beta": 2, "alpha": 1}

    result_a = cached_call(
        workspace_root=llm_workspace,
        role="extractor",
        prompt="P",
        inputs=inputs_a,
        model_id="m",
    )
    # Second call uses a separate workspace so the queue write from the
    # first doesn't influence anything; actually a non-issue (queue writes
    # are content-addressable too) but tidier.
    result_b = cached_call(
        workspace_root=llm_workspace,
        role="extractor",
        prompt="P",
        inputs=inputs_b,
        model_id="m",
    )

    assert result_a.inputs_hash == result_b.inputs_hash


def test_inputs_hash_differs_across_model_ids(llm_workspace: Path) -> None:
    """Same prompt + inputs + role, different model_id ⇒ different cache key."""
    inputs: dict[str, Any] = {"x": 1}
    a = cached_call(
        workspace_root=llm_workspace,
        role="extractor",
        prompt="P",
        inputs=inputs,
        model_id="claude-opus-4-7",
    )
    b = cached_call(
        workspace_root=llm_workspace,
        role="extractor",
        prompt="P",
        inputs=inputs,
        model_id="claude-haiku-4-5",
    )
    assert a.inputs_hash != b.inputs_hash


def test_cache_write_uses_mode_0600(llm_workspace: Path) -> None:
    """Cache-hit branch writes the dispatch-output file at mode 0600 (CV-15)."""
    inputs: dict[str, Any] = {"k": "v"}
    miss = cached_call(
        workspace_root=llm_workspace,
        role="extractor",
        prompt="P",
        inputs=inputs,
        model_id="m",
    )
    _plant_cache_entry(llm_workspace, miss.inputs_hash)

    hit = cached_call(
        workspace_root=llm_workspace,
        role="extractor",
        prompt="P",
        inputs=inputs,
        model_id="m",
    )
    assert hit.output_path is not None
    # CV-15: sensitive payload material lives behind 0600 perms.
    mode = stat.S_IMODE(os.stat(hit.output_path).st_mode)
    assert mode == 0o600, f"expected 0o600 cache-hit output mode, got {oct(mode)}"


def test_cache_hit_idempotent_on_byte_identical_destination(llm_workspace: Path) -> None:
    """Second cache-hit on the same input ⇒ no-op write, same bytes, mode stays 0600."""
    inputs: dict[str, Any] = {"k": "v"}
    miss = cached_call(
        workspace_root=llm_workspace,
        role="extractor",
        prompt="P",
        inputs=inputs,
        model_id="m",
    )
    _plant_cache_entry(llm_workspace, miss.inputs_hash)

    first = cached_call(
        workspace_root=llm_workspace,
        role="extractor",
        prompt="P",
        inputs=inputs,
        model_id="m",
    )
    assert first.output_path is not None
    first_bytes = first.output_path.read_bytes()

    second = cached_call(
        workspace_root=llm_workspace,
        role="extractor",
        prompt="P",
        inputs=inputs,
        model_id="m",
    )
    assert second.output_path is not None
    assert second.output_path.read_bytes() == first_bytes
    assert stat.S_IMODE(os.stat(second.output_path).st_mode) == 0o600
