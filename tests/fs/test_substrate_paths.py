"""Path conventions for the Substrate filesystem layout.

These tests pin the plan §5 layout. Path resolvers are pure (no FS
access beyond marker discovery at constructor time), so a constructed
``Substrate`` always knows exactly where each id lives.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from amanuensis.fs import Substrate, SubstrateInvalidId


def _new(workspace: Path) -> Substrate:
    return Substrate(workspace)


def test_atom_path(tmp_workspace: Path) -> None:
    sub = _new(tmp_workspace)
    expected = (
        tmp_workspace.resolve()
        / "distillations"
        / "src-fixture-001"
        / "atoms"
        / "a-deadbeef00000000.md"
    )
    assert sub.atom_path("src-fixture-001", "a-deadbeef00000000") == expected


def test_relation_path(tmp_workspace: Path) -> None:
    sub = _new(tmp_workspace)
    expected = (
        tmp_workspace.resolve()
        / "distillations"
        / "src-fixture-001"
        / "relations"
        / "r-cafef00d00000000.yaml"
    )
    assert sub.relation_path("src-fixture-001", "r-cafef00d00000000") == expected


def test_provenance_path_uses_prov_id_not_entity_id(tmp_workspace: Path) -> None:
    # M1.6 names provenance files by the provenance record's own id, not
    # the entity_id, to avoid raised+resolved Clarification collisions.
    # The resolver enforces that the prov id is the path component.
    sub = _new(tmp_workspace)
    expected = (
        tmp_workspace.resolve()
        / "distillations"
        / "src-fixture-001"
        / "provenance"
        / "p-0123456789abcdef.yaml"
    )
    assert sub.provenance_path("src-fixture-001", "p-0123456789abcdef") == expected


def test_clarification_path_open_default(tmp_workspace: Path) -> None:
    sub = _new(tmp_workspace)
    expected = (
        tmp_workspace.resolve()
        / "distillations"
        / "src-fixture-001"
        / "clarifications"
        / "open"
        / "c-aaaabbbbccccdddd.md"
    )
    assert sub.clarification_path("src-fixture-001", "c-aaaabbbbccccdddd") == expected


def test_clarification_path_resolved(tmp_workspace: Path) -> None:
    sub = _new(tmp_workspace)
    expected = (
        tmp_workspace.resolve()
        / "distillations"
        / "src-fixture-001"
        / "clarifications"
        / "resolved"
        / "c-aaaabbbbccccdddd.md"
    )
    assert (
        sub.clarification_path(
            "src-fixture-001",
            "c-aaaabbbbccccdddd",
            resolved=True,
        )
        == expected
    )


def test_iteration_path_is_workspace_level(tmp_workspace: Path) -> None:
    # IterationDirective files live at workspace root, not per-distillation.
    sub = _new(tmp_workspace)
    expected = tmp_workspace.resolve() / "iterations" / "i-eeeefffff0001234.md"
    assert sub.iteration_path("i-eeeefffff0001234") == expected


def test_path_resolvers_do_not_touch_filesystem(tmp_workspace: Path) -> None:
    # Computing a path must not create any directories — pure resolution.
    sub = _new(tmp_workspace)
    sub.atom_path("src-x", "a-1234567890abcdef")
    sub.relation_path("src-x", "r-1234567890abcdef")
    sub.provenance_path("src-x", "p-1234567890abcdef")
    sub.clarification_path("src-x", "c-1234567890abcdef")
    sub.iteration_path("i-1234567890abcdef")
    # Nothing under ``distillations/`` or ``iterations/`` should exist.
    assert not (tmp_workspace / "distillations").exists()
    assert not (tmp_workspace / "iterations").exists()


@pytest.mark.parametrize(
    "bad_source_id",
    [
        "",  # empty
        ".",  # current
        "..",  # parent
        "foo/bar",  # contains slash
        "foo\\bar",  # contains backslash
        "src with spaces",  # whitespace not allowed
        "src\x00null",  # NUL
    ],
)
def test_invalid_source_id_rejected(tmp_workspace: Path, bad_source_id: str) -> None:
    sub = _new(tmp_workspace)
    with pytest.raises(SubstrateInvalidId):
        sub.atom_path(bad_source_id, "a-1234567890abcdef")


@pytest.mark.parametrize(
    "bad_id",
    ["", ".", "..", "a/b", "a\\b", "with space"],
)
def test_invalid_atom_id_rejected(tmp_workspace: Path, bad_id: str) -> None:
    sub = _new(tmp_workspace)
    with pytest.raises(SubstrateInvalidId):
        sub.atom_path("src-x", bad_id)
