"""Shared fixtures for ``tests/dispatch/`` — workspace marker + queue builders."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from amanuensis.llm import DispatchQueueEntry


@pytest.fixture
def dispatch_workspace(tmp_path: Path) -> Path:
    """An empty tmpdir with the INV-1 marker, ready for dispatch tests."""
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: dispatch-test\n",
        encoding="utf-8",
    )
    return tmp_path


def make_entry(
    *,
    role: str = "extractor",
    prompt: str = "Extract atoms.",
    inputs: dict[str, object] | None = None,
    model_id: str = "claude-opus-4-7",
    inputs_hash: str | None = None,
) -> DispatchQueueEntry:
    """Build a syntactically-valid DispatchQueueEntry for protocol tests.

    ``inputs_hash`` is the cache key; tests usually pin a fake one so
    they can assert on canonical paths without having to recompute the
    SHA-256 of canonicalised inputs.
    """
    return DispatchQueueEntry(
        role=role,
        prompt=prompt,
        inputs=inputs or {"source_id": "fixture-src"},
        model_id=model_id,
        inputs_hash=inputs_hash or ("a" * 64),
        enqueued_at=datetime.now(UTC),
    )
