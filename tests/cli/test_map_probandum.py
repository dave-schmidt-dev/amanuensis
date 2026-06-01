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


# ---------------------------------------------------------------------------
# T9.4: amanuensis map probandum lineage <id>
# ---------------------------------------------------------------------------


def _build_three_node_tree(workspace: Path) -> tuple[str, str, str]:
    """Plant ultimate -> penultimate -> interim chain.

    Adds three probanda via the CLI and connects them with two
    probandum-edges via ``Substrate.add_probandum_edge`` directly (the
    ``map probandum link`` CLI verb is T9.5, not available yet).

    Returns ``(ultimate_id, penultimate_id, interim_id)``.
    """
    from datetime import UTC, datetime

    from amanuensis.fs import Substrate
    from amanuensis.schemas import (
        AgentAttribution,
        ProbandumEdge,
        RoleAttribution,
        compute_id,
    )

    ult_id = _add_probandum(workspace, "Root claim.", "ultimate")
    pen_id = _add_probandum(
        workspace,
        "Sub-claim under ultimate.",
        "penultimate",
        alternatives=["Alt A"],
    )
    int_id = _add_probandum(
        workspace,
        "Intermediate under penultimate.",
        "interim",
        alternatives=["Alt B"],
    )
    # Wait: per the schema rules: interim probanda live "below"
    # penultimate? Actually the kind ordering is ultimate > interim >
    # penultimate. But T9.4 only needs *some* tree shape. Use the
    # ordering: ultimate -> penultimate, and ultimate -> interim is also
    # acceptable. The schema doesn't enforce a kind ordering on edges.
    # We connect penultimate as child-of ultimate, and interim as
    # child-of penultimate. INV-16 (tree-shape) + INV-17 (lineage to
    # ultimate) both pass: each child has a single parent path back to
    # ultimate.
    sub = Substrate(workspace)
    now = datetime.now(UTC)
    role_attr = RoleAttribution(
        agent=AgentAttribution(kind="human", identifier="test", role="human_supervisor"),
        activity="proposed",
        at=now,
    )

    def _make_edge(parent: str, child: str) -> ProbandumEdge:
        draft = ProbandumEdge(
            id="q-" + "0" * 16,
            parent_probandum_id=parent,
            child_id=child,
            child_kind="probandum",
            child_source_id=None,
            kind="supports",
            warrant="warrant",
            warrant_defensibility="conventional",
            warrant_basis="basis",
            confidence="medium",
            provenance_id="p-fixture-edge",
            role_attributions=[role_attr],
            schema_version=1,
        )
        edge_id = compute_id(draft)
        return ProbandumEdge(
            id=edge_id,
            parent_probandum_id=parent,
            child_id=child,
            child_kind="probandum",
            child_source_id=None,
            kind="supports",
            warrant="warrant",
            warrant_defensibility="conventional",
            warrant_basis="basis",
            confidence="medium",
            provenance_id="p-fixture-edge",
            role_attributions=[role_attr],
            schema_version=1,
        )

    sub.add_probandum_edge(_make_edge(ult_id, pen_id))
    sub.add_probandum_edge(_make_edge(pen_id, int_id))
    return ult_id, pen_id, int_id


def test_lineage_renders_upward_and_downward(
    tmp_workspace_with_walton_snapshot: Path,
) -> None:
    """Lineage of the penultimate node visits ultimate above and interim below."""
    workspace = tmp_workspace_with_walton_snapshot
    ult_id, pen_id, int_id = _build_three_node_tree(workspace)
    result = runner.invoke(
        map_app,
        ["probandum", "lineage", pen_id, "--workspace", str(workspace)],
    )
    assert result.exit_code == 0, result.output
    out = result.stdout
    # All three nodes appear in the rendered tree.
    assert ult_id in out
    assert pen_id in out
    assert int_id in out
    # Section headers.
    assert "upward to ultimate" in out
    assert "downward to leaves" in out
    # Focal marker (`*`) is on the penultimate node.
    assert f"* {pen_id}" in out


def test_lineage_unknown_id_rejected(
    tmp_workspace_with_walton_snapshot: Path,
) -> None:
    """An unknown probandum id exits non-zero."""
    result = runner.invoke(
        map_app,
        [
            "probandum",
            "lineage",
            "p-nonexistent01",
            "--workspace",
            str(tmp_workspace_with_walton_snapshot),
        ],
    )
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# T9.5: amanuensis map probandum link <parent-id> <child-id>
# ---------------------------------------------------------------------------


def test_link_probandum_to_probandum(
    tmp_workspace_with_walton_snapshot: Path,
) -> None:
    """Linking a penultimate child under an ultimate parent succeeds."""
    workspace = tmp_workspace_with_walton_snapshot
    ult_id = _add_probandum(workspace, "Ultimate.", "ultimate")
    pen_id = _add_probandum(
        workspace,
        "Penultimate.",
        "penultimate",
        alternatives=["Alt"],
    )
    result = runner.invoke(
        map_app,
        [
            "probandum",
            "link",
            ult_id,
            pen_id,
            "--kind",
            "supports",
            "--warrant",
            "Supports the ultimate.",
            "--warrant-basis",
            "fixture",
            "--workspace",
            str(workspace),
        ],
    )
    assert result.exit_code == 0, result.output
    line = result.stdout.strip().splitlines()[-1]
    assert line.startswith("q-")
    # The edge is persisted.
    sub = Substrate(workspace)
    edge = sub.get_probandum_edge(line)
    assert edge.parent_probandum_id == ult_id
    assert edge.child_id == pen_id
    assert edge.child_kind == "probandum"


def test_link_probandum_to_atom_requires_source_id(
    tmp_workspace_with_walton_snapshot: Path,
) -> None:
    """Linking to an atom child without --child-source-id is rejected."""
    workspace = tmp_workspace_with_walton_snapshot
    ult_id = _add_probandum(workspace, "Ultimate.", "ultimate")
    result = runner.invoke(
        map_app,
        [
            "probandum",
            "link",
            ult_id,
            "a-someatomid",
            "--kind",
            "supports",
            "--warrant",
            "Atom supports the ultimate.",
            "--warrant-basis",
            "fixture",
            "--workspace",
            str(workspace),
        ],
    )
    assert result.exit_code != 0
    haystack = (result.stdout or "") + (result.stderr or "")
    assert "child-source-id" in haystack.lower()


def test_link_probandum_to_cross_doc_relation(
    tmp_workspace_with_walton_snapshot: Path,
) -> None:
    """Linking to a cross-doc-relation child dispatches the x- prefix."""
    workspace = tmp_workspace_with_walton_snapshot
    ult_id = _add_probandum(workspace, "Ultimate.", "ultimate")
    # No real cross-doc relation on disk -> the EdgeChildMissing gate
    # should fire (exit 1), but the prefix dispatch (a child_kind of
    # cross-doc-relation) is exercised — that's what this test verifies.
    result = runner.invoke(
        map_app,
        [
            "probandum",
            "link",
            ult_id,
            "x-nonexistent00",
            "--kind",
            "supports",
            "--warrant",
            "x.",
            "--warrant-basis",
            "fixture",
            "--workspace",
            str(workspace),
        ],
    )
    # exits 1: child does not exist on disk (EdgeChildMissing). The
    # prefix dispatch succeeded — we didn't get the "unknown prefix"
    # exit-2 from the CLI's own guard.
    assert result.exit_code == 1
    haystack = (result.stdout or "") + (result.stderr or "")
    assert "cross-doc-relation" in haystack.lower() or "not found" in haystack.lower()


def test_link_rejects_unknown_child_prefix(
    tmp_workspace_with_walton_snapshot: Path,
) -> None:
    """A child id with an unknown prefix is rejected at exit 2 (parse-time)."""
    workspace = tmp_workspace_with_walton_snapshot
    ult_id = _add_probandum(workspace, "Ultimate.", "ultimate")
    result = runner.invoke(
        map_app,
        [
            "probandum",
            "link",
            ult_id,
            "z-bogusprefix",
            "--kind",
            "supports",
            "--warrant",
            "z.",
            "--warrant-basis",
            "fixture",
            "--workspace",
            str(workspace),
        ],
    )
    assert result.exit_code == 2
    haystack = (result.stdout or "") + (result.stderr or "")
    assert "prefix" in haystack.lower() or "p-" in haystack


# ---------------------------------------------------------------------------
# T9.6: amanuensis map probandum supersede <old-id> <new-id> --reason "..."
# ---------------------------------------------------------------------------


def test_supersede_writes_supersede_record(
    tmp_workspace_with_walton_snapshot: Path,
) -> None:
    """The supersede verb writes a ProbandumSupersede and re-routes the chain."""
    workspace = tmp_workspace_with_walton_snapshot
    old_id = _add_probandum(workspace, "Original ultimate.", "ultimate")
    new_id = _add_probandum(workspace, "Refined ultimate.", "ultimate")
    result = runner.invoke(
        map_app,
        [
            "probandum",
            "supersede",
            old_id,
            new_id,
            "--reason",
            "supervisor refined statement",
            "--workspace",
            str(workspace),
        ],
    )
    assert result.exit_code == 0, result.output
    sub = Substrate(workspace)
    terminus = sub.latest_probandum_for(old_id)
    assert terminus is not None
    assert terminus.id == new_id


def test_supersede_requires_reason_flag(
    tmp_workspace_with_walton_snapshot: Path,
) -> None:
    """Omitting --reason exits non-zero (Typer required-option error)."""
    workspace = tmp_workspace_with_walton_snapshot
    old_id = _add_probandum(workspace, "Original.", "ultimate")
    new_id = _add_probandum(workspace, "Refined.", "ultimate")
    result = runner.invoke(
        map_app,
        [
            "probandum",
            "supersede",
            old_id,
            new_id,
            "--workspace",
            str(workspace),
        ],
    )
    assert result.exit_code != 0


def test_supersede_rejects_unknown_old_id(
    tmp_workspace_with_walton_snapshot: Path,
) -> None:
    """An unknown old-id is rejected before any write."""
    workspace = tmp_workspace_with_walton_snapshot
    new_id = _add_probandum(workspace, "Replacement.", "ultimate")
    result = runner.invoke(
        map_app,
        [
            "probandum",
            "supersede",
            "p-doesnotexist01",
            new_id,
            "--reason",
            "r",
            "--workspace",
            str(workspace),
        ],
    )
    assert result.exit_code != 0


def test_supersede_already_superseded_rejected(
    tmp_workspace_with_walton_snapshot: Path,
) -> None:
    """Once a probandum is superseded, a second supersede on the old id is refused."""
    workspace = tmp_workspace_with_walton_snapshot
    a_id = _add_probandum(workspace, "A.", "ultimate")
    b_id = _add_probandum(workspace, "B.", "ultimate")
    c_id = _add_probandum(workspace, "C.", "ultimate")
    first = runner.invoke(
        map_app,
        [
            "probandum",
            "supersede",
            a_id,
            b_id,
            "--reason",
            "first",
            "--workspace",
            str(workspace),
        ],
    )
    assert first.exit_code == 0, first.output
    second = runner.invoke(
        map_app,
        [
            "probandum",
            "supersede",
            a_id,
            c_id,
            "--reason",
            "second",
            "--workspace",
            str(workspace),
        ],
    )
    assert second.exit_code != 0
