"""T3.2 — Path resolvers for mappings/ substrate.

Pins the plan §5 layout for the mappings layer. All resolvers are pure
(no FS access beyond marker discovery at construction time).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from amanuensis.fs import Substrate, SubstrateInvalidId


def _new(workspace: Path) -> Substrate:
    return Substrate(workspace)


# --- _mappings_root --------------------------------------------------


def test_mappings_root_is_under_workspace(tmp_workspace: Path) -> None:
    sub = _new(tmp_workspace)
    assert sub.mappings_root == tmp_workspace.resolve() / "mappings"


# --- entity_path -----------------------------------------------------


def test_entity_path(tmp_workspace: Path) -> None:
    sub = _new(tmp_workspace)
    expected = tmp_workspace.resolve() / "mappings" / "entities" / "e-deadbeef00000000.md"
    assert sub.entity_path("e-deadbeef00000000") == expected


def test_entity_path_no_fs_access(tmp_workspace: Path) -> None:
    sub = _new(tmp_workspace)
    sub.entity_path("e-1234567890abcdef")
    assert not (tmp_workspace / "mappings").exists()


@pytest.mark.parametrize(
    "bad_id",
    ["", ".", "..", "e/bad", "e\\bad", "with space", "e\x00nul"],
)
def test_entity_path_rejects_invalid_id(tmp_workspace: Path, bad_id: str) -> None:
    sub = _new(tmp_workspace)
    with pytest.raises(SubstrateInvalidId):
        sub.entity_path(bad_id)


# --- resolution_path -------------------------------------------------


def test_resolution_path(tmp_workspace: Path) -> None:
    sub = _new(tmp_workspace)
    expected = tmp_workspace.resolve() / "mappings" / "resolutions" / "j-cafef00d00000000.yaml"
    assert sub.resolution_path("j-cafef00d00000000") == expected


def test_resolution_path_no_fs_access(tmp_workspace: Path) -> None:
    sub = _new(tmp_workspace)
    sub.resolution_path("j-1234567890abcdef")
    assert not (tmp_workspace / "mappings").exists()


@pytest.mark.parametrize(
    "bad_id",
    ["", ".", "..", "j/bad", "j\\bad", "with space"],
)
def test_resolution_path_rejects_invalid_id(tmp_workspace: Path, bad_id: str) -> None:
    sub = _new(tmp_workspace)
    with pytest.raises(SubstrateInvalidId):
        sub.resolution_path(bad_id)


# --- supersede_path --------------------------------------------------


def test_supersede_path_s_prefix(tmp_workspace: Path) -> None:
    sub = _new(tmp_workspace)
    expected = tmp_workspace.resolve() / "mappings" / "supersedes" / "s-aaaa000000000000.yaml"
    assert sub.supersede_path("s-aaaa000000000000") == expected


def test_supersede_path_t_prefix(tmp_workspace: Path) -> None:
    sub = _new(tmp_workspace)
    expected = tmp_workspace.resolve() / "mappings" / "supersedes" / "t-bbbb111111111111.yaml"
    assert sub.supersede_path("t-bbbb111111111111") == expected


def test_supersede_path_no_fs_access(tmp_workspace: Path) -> None:
    sub = _new(tmp_workspace)
    sub.supersede_path("s-1234567890abcdef")
    assert not (tmp_workspace / "mappings").exists()


@pytest.mark.parametrize(
    "bad_id",
    ["", ".", "..", "s/bad", "t\\bad", "with space"],
)
def test_supersede_path_rejects_invalid_id(tmp_workspace: Path, bad_id: str) -> None:
    sub = _new(tmp_workspace)
    with pytest.raises(SubstrateInvalidId):
        sub.supersede_path(bad_id)


# --- mappings_provenance_path ----------------------------------------


def test_mappings_provenance_path(tmp_workspace: Path) -> None:
    sub = _new(tmp_workspace)
    expected = tmp_workspace.resolve() / "mappings" / "provenance" / "p-0123456789abcdef.yaml"
    assert sub.mappings_provenance_path("p-0123456789abcdef") == expected


def test_mappings_provenance_path_no_fs_access(tmp_workspace: Path) -> None:
    sub = _new(tmp_workspace)
    sub.mappings_provenance_path("p-1234567890abcdef")
    assert not (tmp_workspace / "mappings").exists()


@pytest.mark.parametrize(
    "bad_id",
    ["", ".", "..", "p/bad", "p\\bad", "with space"],
)
def test_mappings_provenance_path_rejects_invalid_id(tmp_workspace: Path, bad_id: str) -> None:
    sub = _new(tmp_workspace)
    with pytest.raises(SubstrateInvalidId):
        sub.mappings_provenance_path(bad_id)
