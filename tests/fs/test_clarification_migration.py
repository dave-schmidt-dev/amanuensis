from __future__ import annotations

from pathlib import Path

import pytest

from scripts.migrate_clarifications_to_schema_v2 import (
    MigrationFailed,
    migrate_workspace,
)


def test_v1_migration_sets_kind_and_bumps_version(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    (ws / "distillations" / "src1" / "clarifications" / "open").mkdir(parents=True)
    (ws / "amanuensis.yaml").write_text("workspace: test\n")
    c_path = ws / "distillations" / "src1" / "clarifications" / "open" / "c-0.md"
    c_path.write_text("---\nid: c-0\nstatus: open\nschema_version: 1\nquestion: q\n---\n")
    migrate_workspace(ws)
    text = c_path.read_text()
    assert "kind: warrant-defensibility-contested" in text
    assert "schema_version: 2" in text


def test_already_v2_is_noop(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    (ws / "distillations" / "src1" / "clarifications" / "open").mkdir(parents=True)
    (ws / "amanuensis.yaml").write_text("workspace: test\n")
    c_path = ws / "distillations" / "src1" / "clarifications" / "open" / "c-0.md"
    body = (
        "---\nid: c-0\nstatus: open\nschema_version: 2\n"
        "kind: warrant-defensibility-contested\nquestion: q\n---\n"
    )
    c_path.write_text(body)
    migrate_workspace(ws)
    assert c_path.read_text() == body  # exact byte equality


def test_malformed_raises(tmp_path: Path) -> None:
    ws = tmp_path / "ws"
    (ws / "distillations" / "src1" / "clarifications" / "open").mkdir(parents=True)
    (ws / "amanuensis.yaml").write_text("workspace: test\n")
    c_path = ws / "distillations" / "src1" / "clarifications" / "open" / "c-0.md"
    c_path.write_text("not even a yaml frontmatter")
    with pytest.raises(MigrationFailed):
        migrate_workspace(ws)


def test_substrate_init_triggers_migration(tmp_path: Path) -> None:
    """A Substrate over a workspace with a v1 clarification auto-migrates it."""
    ws = tmp_path / "ws"
    (ws / "distillations" / "src1" / "clarifications" / "open").mkdir(parents=True)
    (ws / "amanuensis.yaml").write_text("workspace: test\n")
    c_path = ws / "distillations" / "src1" / "clarifications" / "open" / "c-0.md"
    c_path.write_text("---\nid: c-0\nstatus: open\nschema_version: 1\nquestion: q\n---\n")

    from amanuensis.fs.substrate import Substrate

    Substrate(ws)

    text = c_path.read_text()
    assert "schema_version: 2" in text
    assert "kind: warrant-defensibility-contested" in text


def test_substrate_init_no_v1_files_skips_migration(tmp_path: Path) -> None:
    """If no v1 clarifications exist, Substrate.__init__ does not touch any files."""
    ws = tmp_path / "ws"
    (ws / "distillations" / "src1" / "clarifications" / "open").mkdir(parents=True)
    (ws / "amanuensis.yaml").write_text("workspace: test\n")
    # No clarifications written at all — the glob should match nothing.
    from amanuensis.fs.substrate import Substrate

    Substrate(ws)
    # Just verify no crash; the workspace should remain untouched.
    assert (ws / "amanuensis.yaml").exists()
