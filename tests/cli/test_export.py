"""CLI tests for ``amanuensis export`` (Phase 2b M10 — T10.0 wiring).

Phase 1 shipped ``amanuensis export <source-id> --output FILE.html`` as a
per-source single-file emitter. Phase 2b M9 added the workspace-level
appendix exporter as a Python API (``export_workspace_appendix``). T10.0
wires the new mode into the CLI:

    amanuensis export --workspace-appendix --out-dir DIR

The new mode is mutually exclusive with the positional ``source-id``
argument — passing both is a usage error. The fixture
``tmp_workspace_with_two_cross_doc_relations`` (see ``tests/cli/conftest.py``)
plants the substrate state needed for the appendix exporter to have
content to emit.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from amanuensis.cli import app

runner = CliRunner()


def test_export_workspace_appendix_writes_bundle(
    tmp_workspace_with_two_cross_doc_relations: Path, tmp_path: Path
) -> None:
    """``--workspace-appendix --out-dir DIR`` writes the bundle layout."""
    out_dir = tmp_path / "bundle"
    result = runner.invoke(
        app,
        [
            "export",
            "--workspace-appendix",
            "--out-dir",
            str(out_dir),
            "--workspace",
            str(tmp_workspace_with_two_cross_doc_relations),
        ],
    )
    assert result.exit_code == 0, result.output
    assert (out_dir / "cross-doc-relations.html").exists()
    assert (out_dir / "entities").is_dir()
    # Summary line in stdout names the bundle layout for the supervisor.
    assert "bundle" in result.stdout.lower() or "cross-doc" in result.stdout.lower()


def test_export_workspace_appendix_rejects_with_source_id(
    tmp_workspace_with_two_cross_doc_relations: Path, tmp_path: Path
) -> None:
    """Passing both ``source-id`` and ``--workspace-appendix`` is a usage error."""
    result = runner.invoke(
        app,
        [
            "export",
            "some-source-id",
            "--workspace-appendix",
            "--out-dir",
            str(tmp_path / "out"),
            "--workspace",
            str(tmp_workspace_with_two_cross_doc_relations),
        ],
    )
    assert result.exit_code != 0
    # The error message should make the mutual-exclusion explicit so a
    # supervisor running --help on the failed invocation knows why.
    assert (
        "mutually exclusive" in result.output.lower()
        or "workspace-appendix" in result.output.lower()
    )


def test_export_workspace_appendix_requires_out_dir(
    tmp_workspace_with_two_cross_doc_relations: Path,
) -> None:
    """``--workspace-appendix`` without ``--out-dir`` is rejected."""
    result = runner.invoke(
        app,
        [
            "export",
            "--workspace-appendix",
            "--workspace",
            str(tmp_workspace_with_two_cross_doc_relations),
        ],
    )
    assert result.exit_code != 0
    assert "out-dir" in result.output.lower() or "out_dir" in result.output.lower()


def test_export_workspace_appendix_help_lists_flag() -> None:
    """``amanuensis export --help`` advertises the new flag."""
    result = runner.invoke(app, ["export", "--help"])
    assert result.exit_code == 0
    assert "--workspace-appendix" in result.output
    assert "--out-dir" in result.output


def test_export_positional_still_requires_output_when_no_appendix(
    tmp_workspace_with_two_cross_doc_relations: Path,
) -> None:
    """The Phase 1 ``--output`` mode is still required when no appendix flag.

    Regression guard: invoking ``export <source-id>`` without either
    ``--output`` or ``--workspace-appendix`` must fail with a clear usage
    error, not silently succeed.
    """
    result = runner.invoke(
        app,
        [
            "export",
            "some-source-id",
            "--workspace",
            str(tmp_workspace_with_two_cross_doc_relations),
        ],
    )
    assert result.exit_code != 0
