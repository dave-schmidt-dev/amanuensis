"""Dual-path routing tests for ``ReplayLog`` + ``_resolve_replay_log_root`` (T3.9/T3.10).

Validates that:
- ``ReplayLog.for_source`` routes to ``distillations/<source_id>/replay-log/``.
- ``ReplayLog.for_mappings`` routes to ``mappings/replay-log/``.
- ``_resolve_replay_log_root`` produces the correct directory for both role families.
"""

# pyright: reportPrivateUsage=false

from __future__ import annotations

from pathlib import Path

import pytest

from amanuensis.fs.replay_log import ReplayLog, _resolve_replay_log_root


def _ws(tmp_path: Path) -> Path:
    (tmp_path / "amanuensis.yaml").write_text("workspace: test\n")
    return tmp_path


@pytest.mark.parametrize(
    "role,expect_dir_segment",
    [
        ("extractor", "distillations/src1/replay-log"),
        ("auditor", "distillations/src1/replay-log"),
        ("map-resolve", "mappings/replay-log"),
        ("map-audit", "mappings/replay-log"),
    ],
)
def test_role_routing(tmp_path: Path, role: str, expect_dir_segment: str) -> None:
    root = _ws(tmp_path)
    if role.startswith("map-"):
        rl = ReplayLog.for_mappings(root)
    else:
        rl = ReplayLog.for_source(root, "src1")
    assert expect_dir_segment in str(rl._replay_log_dir)  # type: ignore[attr-defined]


def test_resolve_replay_log_root_map_role(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    assert _resolve_replay_log_root(root, "map-resolve", None) == root / "mappings" / "replay-log"


def test_resolve_replay_log_root_distill_role(tmp_path: Path) -> None:
    root = _ws(tmp_path)
    assert (
        _resolve_replay_log_root(root, "extractor", "src1")
        == root / "distillations" / "src1" / "replay-log"
    )


def test_resolve_replay_log_root_map_audit_ignores_source_id(tmp_path: Path) -> None:
    """map-audit routes to mappings/replay-log regardless of source_id."""
    root = _ws(tmp_path)
    assert (
        _resolve_replay_log_root(root, "map-audit", "some-source")
        == root / "mappings" / "replay-log"
    )


def test_resolve_replay_log_root_distill_requires_source_id(tmp_path: Path) -> None:
    """Distillation role without source_id raises ValueError."""
    root = _ws(tmp_path)
    with pytest.raises(ValueError, match="source_id"):
        _resolve_replay_log_root(root, "extractor", None)


def test_for_mappings_replay_log_dir(tmp_path: Path) -> None:
    """for_mappings() _replay_log_dir is <workspace>/mappings/replay-log."""
    root = _ws(tmp_path)
    rl = ReplayLog.for_mappings(root)
    assert rl._replay_log_dir == root / "mappings" / "replay-log"  # type: ignore[attr-defined]


def test_for_source_replay_log_dir(tmp_path: Path) -> None:
    """for_source() _replay_log_dir is <workspace>/distillations/<source_id>/replay-log."""
    root = _ws(tmp_path)
    rl = ReplayLog.for_source(root, "my-source")
    assert rl._replay_log_dir == root / "distillations" / "my-source" / "replay-log"  # type: ignore[attr-defined]
