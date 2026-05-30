"""``amanuensis ingest`` — CLI wrapper around the docling / pdfplumber ingesters.

Uses the M3.1 CUAD fixture (the same one ``tests/ingest/test_simple_pdf.py``
exercises) to verify end-to-end CLI invocation. The library-level
ingester is already covered by the M3 suite; this test confirms the
CLI wiring (argument parsing, default engine, flock acquisition,
summary output, manifest path).
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from amanuensis.cli import app
from amanuensis.fs import Substrate

runner = CliRunner()

FIXTURE_PDF = Path(__file__).parent.parent / "fixtures" / "ingest" / "simple-contract.pdf"


def test_ingest_default_engine_docling_succeeds(cli_workspace: Path) -> None:
    """Default engine is docling; manifest is written under the workspace."""
    assert FIXTURE_PDF.is_file(), f"fixture missing: {FIXTURE_PDF}"
    result = runner.invoke(
        app,
        [
            "ingest",
            "--workspace",
            str(cli_workspace),
            "--source-id",
            "cli-ingest-test",
            str(FIXTURE_PDF),
        ],
    )
    assert result.exit_code == 0, (
        f"ingest failed (exit={result.exit_code})\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    # Output mentions the engine and the manifest path.
    assert "docling" in result.stdout
    assert "manifest" in result.stdout.lower()
    # The manifest exists on disk.
    substrate = Substrate(cli_workspace)
    manifest_path = substrate.manifest_path("cli-ingest-test")
    assert manifest_path.is_file()
    # The vocabulary snapshot was written too (INV-10 pin).
    assert substrate.vocabulary_snapshot_path("cli-ingest-test").is_file()


def test_ingest_pdfplumber_engine_succeeds(cli_workspace: Path) -> None:
    """Explicit ``--engine pdfplumber`` invokes the fallback ingester."""
    result = runner.invoke(
        app,
        [
            "ingest",
            "--engine",
            "pdfplumber",
            "--workspace",
            str(cli_workspace),
            "--source-id",
            "cli-ingest-plumber",
            str(FIXTURE_PDF),
        ],
    )
    assert result.exit_code == 0, (
        f"ingest failed (exit={result.exit_code})\nstdout: {result.stdout}\nstderr: {result.stderr}"
    )
    assert "pdfplumber" in result.stdout
    substrate = Substrate(cli_workspace)
    assert substrate.manifest_path("cli-ingest-plumber").is_file()


def test_ingest_default_source_id_is_pdf_stem(cli_workspace: Path) -> None:
    """Omitting ``--source-id`` derives it from the PDF stem."""
    result = runner.invoke(
        app,
        [
            "ingest",
            "--workspace",
            str(cli_workspace),
            str(FIXTURE_PDF),
        ],
    )
    assert result.exit_code == 0
    substrate = Substrate(cli_workspace)
    # Stem of "simple-contract.pdf" is "simple-contract".
    assert substrate.manifest_path("simple-contract").is_file()


def test_ingest_refuses_missing_pdf(cli_workspace: Path) -> None:
    """Typer's path validation rejects a non-existent PDF (exit 2)."""
    result = runner.invoke(
        app,
        [
            "ingest",
            "--workspace",
            str(cli_workspace),
            "/no/such/file.pdf",
        ],
    )
    assert result.exit_code != 0
