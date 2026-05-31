"""Tests for _append_replay replay-log routing (T6.6).

Verifies that ``_append_replay`` in ``amanuensis.cli.dispatch`` routes
entries to the correct log scope based on the queue entry's role:

- ``map-resolve`` and ``map-audit`` → ``mappings/replay-log/``
  (``ReplayLog.for_mappings``).
- ``extractor`` and ``auditor`` → ``distillations/<source_id>/replay-log/``
  (``append_replay_entry`` / ``ReplayLog.for_source``).

The test creates a minimal workspace (INV-1 marker only), calls the
private ``_append_replay`` directly, then inspects the on-disk tree to
confirm the entry landed in the right subtree.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest

from amanuensis.cli.dispatch import _append_replay  # pyright: ignore[reportPrivateUsage]
from amanuensis.fs import ReplayLog
from amanuensis.llm import DispatchQueueEntry

# --- Local fixtures --------------------------------------------------------


def _make_workspace(tmp_path: Path) -> Path:
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text(
        "schema_version: 1\nproject_name: routing-test\n",
        encoding="utf-8",
    )
    return tmp_path


def _make_entry(
    role: str,
    source_id: str | None = None,
) -> DispatchQueueEntry:
    inputs: dict[str, object] = {}
    if source_id is not None:
        inputs["source_id"] = source_id
    return DispatchQueueEntry(
        role=role,
        prompt="test prompt",
        inputs=inputs,
        model_id="claude-opus-4-7",
        inputs_hash="a" * 64,
        enqueued_at=datetime.now(UTC),
    )


# --- map-role entries land in mappings/replay-log/ ------------------------


@pytest.mark.parametrize("role", ["map-resolve", "map-audit"])
def test_map_role_routes_to_mappings_replay_log(tmp_path: Path, role: str) -> None:
    """map-resolve and map-audit entries land in mappings/replay-log/."""
    workspace = _make_workspace(tmp_path)
    entry = _make_entry(role)

    _append_replay(
        workspace_path=workspace,
        entry=entry,
        cache_hit=False,
        outputs_hash="b" * 64,
        duration_seconds=1.0,
        substrate_changes=[],
    )

    # Entry is in the mappings scope.
    log = ReplayLog.for_mappings(workspace)
    entries = list(log.list_entries())
    assert len(entries) == 1, f"expected 1 entry in mappings log, got {entries!r}"
    assert entries[0].activity == f"{role}-dispatch"

    # distillations/ subtree has no replay-log entries.
    dist_root = workspace / "distillations"
    assert not dist_root.is_dir() or not any(dist_root.rglob("*.yaml")), (
        "unexpected replay entry in distillations/"
    )


# --- distillation-role entries land in distillations/<src>/replay-log/ ---


@pytest.mark.parametrize("role", ["extractor", "auditor"])
def test_distillation_role_routes_to_distillation_replay_log(tmp_path: Path, role: str) -> None:
    """extractor and auditor entries land in distillations/<source_id>/replay-log/."""
    workspace = _make_workspace(tmp_path)
    source_id = "test-source"
    entry = _make_entry(role, source_id=source_id)

    _append_replay(
        workspace_path=workspace,
        entry=entry,
        cache_hit=False,
        outputs_hash="c" * 64,
        duration_seconds=0.5,
        substrate_changes=[],
    )

    # Entry is in the per-distillation scope.
    log = ReplayLog.for_source(workspace, source_id)
    entries = list(log.list_entries())
    assert len(entries) == 1, f"expected 1 entry in distillation log, got {entries!r}"
    assert entries[0].activity == f"{role}-dispatch"

    # mappings/ replay-log is absent.
    mappings_log_dir = workspace / "mappings" / "replay-log"
    assert not mappings_log_dir.is_dir(), f"unexpected mappings replay-log dir for role {role!r}"


# --- map-role entries do NOT bleed into distillation scope ----------------


def test_map_resolve_does_not_write_to_distillation_scope(tmp_path: Path) -> None:
    """A map-resolve dispatch entry writes ONLY to the mappings scope."""
    workspace = _make_workspace(tmp_path)
    # Plant a source_id in the entry's inputs — the routing must ignore it
    # for map roles and still go to the mappings scope.
    entry = _make_entry("map-resolve", source_id="should-be-ignored")

    _append_replay(
        workspace_path=workspace,
        entry=entry,
        cache_hit=True,
        outputs_hash="d" * 64,
        duration_seconds=0.1,
        substrate_changes=["mappings/entities/e-abc.md"],
    )

    mappings_entries = list(ReplayLog.for_mappings(workspace).list_entries())
    assert len(mappings_entries) == 1

    dist_root = workspace / "distillations"
    assert not dist_root.is_dir() or not any(dist_root.rglob("*.yaml"))
