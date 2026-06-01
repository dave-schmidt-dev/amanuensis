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


# ---------------------------------------------------------------------------
# T9.2: amanuensis map probandum list
# ---------------------------------------------------------------------------


def _add_probandum(
    workspace: Path,
    statement: str,
    kind: str,
    scheme: str = "argument-from-sign",
    alternatives: list[str] | None = None,
) -> str:
    """CLI-driven helper: write a probandum and return its id."""
    argv = [
        "probandum",
        "add",
        statement,
        "--kind",
        kind,
        "--scheme",
        scheme,
        "--workspace",
        str(workspace),
    ]
    for alt in alternatives or []:
        argv.extend(["--alternative", alt])
    result = runner.invoke(map_app, argv)
    assert result.exit_code == 0, result.output
    return result.stdout.strip().splitlines()[-1]


def test_list_empty_workspace_prints_nothing(
    tmp_workspace_with_walton_snapshot: Path,
) -> None:
    """A workspace with no probanda produces no list output."""
    result = runner.invoke(
        map_app,
        ["probandum", "list", "--workspace", str(tmp_workspace_with_walton_snapshot)],
    )
    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == ""


def test_list_lists_all_probanda(
    tmp_workspace_with_walton_snapshot: Path,
) -> None:
    """All planted probanda appear in the unfiltered listing."""
    workspace = tmp_workspace_with_walton_snapshot
    ult_id = _add_probandum(workspace, "Root claim.", "ultimate")
    pen_id = _add_probandum(
        workspace,
        "Sub-claim.",
        "penultimate",
        alternatives=["Alternative A"],
    )
    result = runner.invoke(
        map_app,
        ["probandum", "list", "--workspace", str(workspace)],
    )
    assert result.exit_code == 0, result.output
    out = result.stdout
    assert ult_id in out
    assert pen_id in out


def test_list_filters_by_kind(
    tmp_workspace_with_walton_snapshot: Path,
) -> None:
    """``--kind ultimate`` filters out the penultimate row."""
    workspace = tmp_workspace_with_walton_snapshot
    ult_id = _add_probandum(workspace, "Root claim.", "ultimate")
    pen_id = _add_probandum(
        workspace,
        "Sub-claim.",
        "penultimate",
        alternatives=["Alternative A"],
    )
    result = runner.invoke(
        map_app,
        ["probandum", "list", "--kind", "ultimate", "--workspace", str(workspace)],
    )
    assert result.exit_code == 0, result.output
    assert ult_id in result.stdout
    assert pen_id not in result.stdout


def test_list_filters_by_scheme(
    tmp_workspace_with_walton_snapshot: Path,
) -> None:
    """``--scheme S`` filters to probanda whose scheme matches exactly."""
    workspace = tmp_workspace_with_walton_snapshot
    sign_id = _add_probandum(workspace, "Sign-based root.", "ultimate", scheme="argument-from-sign")
    expert_id = _add_probandum(
        workspace, "Expert-based root.", "ultimate", scheme="argument-from-expert-opinion"
    )
    result = runner.invoke(
        map_app,
        [
            "probandum",
            "list",
            "--scheme",
            "argument-from-expert-opinion",
            "--workspace",
            str(workspace),
        ],
    )
    assert result.exit_code == 0, result.output
    assert expert_id in result.stdout
    assert sign_id not in result.stdout


# ---------------------------------------------------------------------------
# T9.3: amanuensis map probandum show <id>
# ---------------------------------------------------------------------------


def test_show_renders_all_fields(
    tmp_workspace_with_walton_snapshot: Path,
) -> None:
    """``probandum show <id>`` renders statement, kind, scheme, alternatives, confidence."""
    workspace = tmp_workspace_with_walton_snapshot
    pen_id = _add_probandum(
        workspace,
        "ACME failed to pay on the due date.",
        "penultimate",
        scheme="argument-from-sign",
        alternatives=["ACME paid on time", "Payment was waived"],
    )
    result = runner.invoke(
        map_app,
        ["probandum", "show", pen_id, "--workspace", str(workspace)],
    )
    assert result.exit_code == 0, result.output
    out = result.stdout
    # Statement body appears.
    assert "ACME failed to pay on the due date." in out
    # Frontmatter fields rendered (markdown body + section headers).
    assert "argument-from-sign" in out
    assert "ACME paid on time" in out
    assert "Payment was waived" in out
    # Section headers.
    assert "Alternatives considered" in out
    assert "Confidence" in out
    assert "Lineage (incoming)" in out
    assert "Lineage (outgoing)" in out
    assert "Provenance" in out
    assert "Supersede chain" in out
    # No incoming / outgoing edges yet.
    assert "(none)" in out


def test_show_returns_error_for_unknown_id(
    tmp_workspace_with_walton_snapshot: Path,
) -> None:
    """``probandum show`` on an unknown id exits non-zero with a 'not found' message."""
    result = runner.invoke(
        map_app,
        [
            "probandum",
            "show",
            "p-doesnotexist01",
            "--workspace",
            str(tmp_workspace_with_walton_snapshot),
        ],
    )
    assert result.exit_code != 0
    haystack = (result.stdout or "") + (result.stderr or "")
    assert "not found" in haystack.lower()
