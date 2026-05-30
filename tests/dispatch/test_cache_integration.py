"""Cache integration tests (M6.5).

Two contracts:

1. Cache hit: a queue entry whose ``inputs_hash`` already has a cache
   entry resolves WITHOUT subprocess invocation; output lands under
   ``dispatch/outputs/``; queue entry is consumed.
2. Cache miss: a queue entry without a cache entry triggers the echo
   script exactly once; the cache file is populated (mode 0600); the
   second drive uses the cache.
"""

from __future__ import annotations

import os
import stat
from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from amanuensis.cli import app
from amanuensis.cli.dispatch import TEST_HARNESS_OVERRIDES
from amanuensis.dispatch.queue import enqueue, list_queue
from amanuensis.llm.cached_call import _compute_inputs_hash  # pyright: ignore[reportPrivateUsage]

from .conftest import make_entry

runner = CliRunner()


def _plant_cache_entry(
    workspace: Path,
    inputs_hash: str,
    *,
    output_payload: dict[str, Any] | None = None,
    model_id: str = "claude-opus-4-7",
) -> Path:
    """Plant a synthetic cache entry at the canonical path."""
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


def _write_counting_script(tmp_path: Path, counter: Path) -> Path:
    """Plant a script that bumps a counter file then echoes JSON."""
    script = tmp_path / "counter.sh"
    body = (
        "#!/bin/sh\n"
        f'printf "x" >> "{counter}"\n'
        "cat <<'__EOF__'\n"
        '{"atoms": [], "findings": []}\n'
        "__EOF__\n"
        "exit 0\n"
    )
    script.write_text(body, encoding="utf-8")
    script.chmod(0o700)
    return script


def test_cache_hit_consumes_queue_without_subprocess(
    dispatch_workspace: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """A pre-populated cache satisfies the queue without invoking the harness."""
    # NOTE: counter / script live OUTSIDE the workspace so the write-isolation
    # checker doesn't flag the counter-bump as a CV-5 violation.
    aux = tmp_path_factory.mktemp("aux-cache-hit")
    counter = aux / "invocations.txt"
    script = _write_counting_script(aux, counter)

    # Build an entry whose inputs_hash matches what cached_call would compute.
    inputs: dict[str, Any] = {"source_id": "fixture-src", "key": "value"}
    role = "extractor"
    prompt = "Extract."
    model_id = "claude-opus-4-7"
    real_hash = _compute_inputs_hash(role=role, prompt=prompt, inputs=inputs, model_id=model_id)

    # Plant the cache BEFORE the dispatch run.
    _plant_cache_entry(
        dispatch_workspace,
        real_hash,
        output_payload={"atoms": [{"id": "a-1"}]},
    )

    entry = make_entry(
        role=role, prompt=prompt, inputs=inputs, model_id=model_id, inputs_hash=real_hash
    )
    enqueue(dispatch_workspace, entry)

    TEST_HARNESS_OVERRIDES["claude"] = script
    try:
        result = runner.invoke(app, ["dispatch", "--once", "--workspace", str(dispatch_workspace)])
        assert result.exit_code == 0, (
            f"dispatch failed: stdout={result.stdout!r} stderr={result.stderr!r}"
        )

        # Subprocess NOT invoked (cache hit).
        assert not counter.is_file() or counter.read_text(encoding="utf-8") == "", (
            "cache-hit branch must not invoke the harness subprocess"
        )

        # Queue is empty (entry consumed).
        assert list_queue(dispatch_workspace) == []

        # Output written.
        out_path = (
            dispatch_workspace / "dispatch" / "outputs" / f"{role}-{real_hash}" / "output.yaml"
        )
        assert out_path.is_file()
    finally:
        TEST_HARNESS_OVERRIDES.pop("claude", None)


def test_cache_miss_populates_cache_at_mode_0600(
    dispatch_workspace: Path, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Cache miss: subprocess runs once, cache file written at 0600."""
    aux = tmp_path_factory.mktemp("aux-cache-miss")
    counter = aux / "invocations.txt"
    script = _write_counting_script(aux, counter)

    inputs: dict[str, Any] = {"source_id": "fixture-src", "k": "v"}
    role = "extractor"
    prompt = "Extract."
    model_id = "claude-opus-4-7"
    real_hash = _compute_inputs_hash(role=role, prompt=prompt, inputs=inputs, model_id=model_id)

    entry = make_entry(
        role=role, prompt=prompt, inputs=inputs, model_id=model_id, inputs_hash=real_hash
    )
    enqueue(dispatch_workspace, entry)

    TEST_HARNESS_OVERRIDES["claude"] = script
    try:
        result = runner.invoke(app, ["dispatch", "--once", "--workspace", str(dispatch_workspace)])
        assert result.exit_code == 0, (
            f"dispatch failed: stdout={result.stdout!r} stderr={result.stderr!r}"
        )

        # Subprocess invoked exactly once.
        assert counter.is_file()
        assert counter.read_text(encoding="utf-8") == "x"

        # Queue is empty.
        assert list_queue(dispatch_workspace) == []

        # Output written.
        out_path = (
            dispatch_workspace / "dispatch" / "outputs" / f"{role}-{real_hash}" / "output.yaml"
        )
        assert out_path.is_file()

        # Cache file written at mode 0600 (CV-15).
        cache_path = dispatch_workspace / "cache" / f"{real_hash}.yaml"
        assert cache_path.is_file()
        mode = stat.S_IMODE(os.stat(cache_path).st_mode)
        assert mode == 0o600, f"expected cache file mode 0600, got {oct(mode)}"

        # Cache payload round-trips.
        cache_loaded: Any = yaml.safe_load(cache_path.read_text(encoding="utf-8"))
        assert cache_loaded["model_id"] == model_id
        assert cache_loaded["output_payload"] == {"atoms": [], "findings": []}
    finally:
        TEST_HARNESS_OVERRIDES.pop("claude", None)


def test_unmapped_role_routes_to_failures(dispatch_workspace: Path) -> None:
    """A role with no harness mapping ⇒ failures with ``role-unmapped``."""
    entry = make_entry(role="contrarian", inputs_hash="u" * 64)
    enqueue(dispatch_workspace, entry)

    result = runner.invoke(app, ["dispatch", "--once", "--workspace", str(dispatch_workspace)])
    assert result.exit_code == 0
    assert list_queue(dispatch_workspace) == []

    failures_dir = dispatch_workspace / "dispatch" / "failures"
    sidecars = [p for p in failures_dir.iterdir() if p.name.endswith(".failure.yaml")]
    assert len(sidecars) == 1
    sidecar_payload: Any = yaml.safe_load(sidecars[0].read_text(encoding="utf-8"))
    assert sidecar_payload["reason"] == "role-unmapped"
