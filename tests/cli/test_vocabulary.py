"""``amanuensis vocabulary`` CLI tests — list / show / snapshot."""

from __future__ import annotations

from pathlib import Path

import yaml
from typer.testing import CliRunner

from amanuensis.cli import app

from .conftest import SOURCE_ID

runner = CliRunner()


def test_vocabulary_list_emits_predicates(cli_workspace: Path) -> None:
    """`vocabulary list` prints the bundled fallback vocabulary entries."""
    result = runner.invoke(app, ["vocabulary", "list", "--workspace", str(cli_workspace)])
    assert result.exit_code == 0, result.stdout
    # The fallback resolver returns either the bundled generic registry
    # (~58 predicates) or the in-memory placeholder (1+ predicates). Either
    # way at least one canonical predicate line should appear.
    non_comment_lines = [line for line in result.stdout.splitlines() if not line.startswith("#")]
    assert any(line.strip() for line in non_comment_lines), (
        f"expected at least one predicate line; got:\n{result.stdout}"
    )


def test_vocabulary_show_unknown_predicate_fails(cli_workspace: Path) -> None:
    """Unknown predicate exits non-zero with a clear error."""
    result = runner.invoke(
        app,
        ["vocabulary", "show", "definitely_not_a_predicate", "--workspace", str(cli_workspace)],
    )
    assert result.exit_code != 0


def test_vocabulary_snapshot_emits_pinned_yaml(cli_workspace: Path, planted_atom: object) -> None:
    """`vocabulary snapshot <source-id>` prints the per-distillation pinned YAML.

    The planted_atom fixture writes a vocabulary snapshot under SOURCE_ID
    as part of substrate setup; `vocabulary snapshot` should echo that
    file's bytes back.
    """
    _ = planted_atom
    result = runner.invoke(
        app,
        ["vocabulary", "snapshot", SOURCE_ID, "--workspace", str(cli_workspace)],
    )
    assert result.exit_code == 0, result.stdout
    payload = yaml.safe_load(result.stdout)
    # The snapshot has the canonical vocabulary shape.
    assert "name" in payload
    assert "version" in payload
    assert "entries" in payload
    assert isinstance(payload["entries"], list)


def test_vocabulary_snapshot_missing_source_fails(cli_workspace: Path) -> None:
    """Snapshot for an unknown source-id exits non-zero with a clear error."""
    result = runner.invoke(
        app,
        ["vocabulary", "snapshot", "nonexistent-source", "--workspace", str(cli_workspace)],
    )
    assert result.exit_code != 0
