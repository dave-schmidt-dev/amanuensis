"""CLI tests for ``amanuensis map probandum`` sub-commands (Phase 2c M9).

The verbs exercised here cover Phase 2c's argument-tree CRUD surface:

- ``probandum add`` — write a new Probandum (T9.1).
- ``probandum list`` — read-only listing with filters (T9.2).
- ``probandum show`` — record detail view (T9.3).
- ``probandum lineage`` — INCOMING / OUTGOING tree walk (T9.4).
- ``probandum link`` — write a new ProbandumEdge (T9.5).
- ``probandum supersede`` — supervisor correction at the probandum level (T9.6).
- ``probandum-edge supersede`` — same at the edge level (T9.7).

The fixture ``tmp_workspace_with_walton_snapshot`` (see
``tests/cli/conftest.py``) pins the bundled generic Walton-scheme
catalogue so probandum writes clear INV-18.
"""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from amanuensis.cli.map import map_app
from amanuensis.fs import Substrate

runner = CliRunner()


# ---------------------------------------------------------------------------
# T9.1: amanuensis map probandum add
# ---------------------------------------------------------------------------


def test_add_ultimate_without_alternatives_passes(
    tmp_workspace_with_walton_snapshot: Path,
) -> None:
    """An ultimate probandum has no alternatives requirement (ACH exempt)."""
    result = runner.invoke(
        map_app,
        [
            "probandum",
            "add",
            "ACME breached the contract.",
            "--kind",
            "ultimate",
            "--scheme",
            "argument-from-sign",
            "--workspace",
            str(tmp_workspace_with_walton_snapshot),
        ],
    )
    assert result.exit_code == 0, result.output
    # Output is the resulting p-<hash> id.
    line = result.stdout.strip().splitlines()[-1]
    assert line.startswith("p-")
    # Persisted on disk.
    sub = Substrate(tmp_workspace_with_walton_snapshot)
    persisted = sub.get_probandum(line)
    assert persisted.kind == "ultimate"
    assert persisted.scheme == "argument-from-sign"
    assert persisted.alternatives_considered == []


def test_add_penultimate_with_alternatives_passes(
    tmp_workspace_with_walton_snapshot: Path,
) -> None:
    """A penultimate probandum with at least one alternative clears ACH (INV-19)."""
    result = runner.invoke(
        map_app,
        [
            "probandum",
            "add",
            "ACME failed to pay on the due date.",
            "--kind",
            "penultimate",
            "--scheme",
            "argument-from-sign",
            "--alternative",
            "ACME paid on time",
            "--alternative",
            "Payment was waived",
            "--workspace",
            str(tmp_workspace_with_walton_snapshot),
        ],
    )
    assert result.exit_code == 0, result.output
    line = result.stdout.strip().splitlines()[-1]
    assert line.startswith("p-")
    sub = Substrate(tmp_workspace_with_walton_snapshot)
    persisted = sub.get_probandum(line)
    assert persisted.kind == "penultimate"
    assert len(persisted.alternatives_considered) == 2


def test_add_interim_without_alternatives_rejected(
    tmp_workspace_with_walton_snapshot: Path,
) -> None:
    """An interim probandum with no alternatives trips the ACH gate (INV-19)."""
    result = runner.invoke(
        map_app,
        [
            "probandum",
            "add",
            "ACME's intent was malicious.",
            "--kind",
            "interim",
            "--scheme",
            "argument-from-sign",
            "--workspace",
            str(tmp_workspace_with_walton_snapshot),
        ],
    )
    assert result.exit_code != 0
    haystack = (result.stdout or "") + (result.stderr or "")
    assert "alternatives" in haystack.lower() or "ach" in haystack.lower()


def test_add_with_unknown_scheme_rejected(
    tmp_workspace_with_walton_snapshot: Path,
) -> None:
    """A scheme not in the pinned Walton-scheme snapshot trips INV-18."""
    result = runner.invoke(
        map_app,
        [
            "probandum",
            "add",
            "ACME breached the contract.",
            "--kind",
            "ultimate",
            "--scheme",
            "not-a-real-walton-scheme",
            "--workspace",
            str(tmp_workspace_with_walton_snapshot),
        ],
    )
    assert result.exit_code != 0
    haystack = (result.stdout or "") + (result.stderr or "")
    assert "walton" in haystack.lower() or "scheme" in haystack.lower()
