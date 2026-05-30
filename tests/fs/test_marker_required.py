"""INV-1 marker enforcement at ``Substrate.__init__``.

A directory only counts as an amanuensis workspace when an
``amanuensis.yaml`` regular file lives at its root. The substrate
refuses to construct anywhere else: no implicit init, no auto-create,
no silent fallback.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from amanuensis.fs import Substrate, SubstrateMarkerMissing


def test_marker_present_constructs_ok(tmp_workspace: Path) -> None:
    sub = Substrate(tmp_workspace)
    # ``root`` resolves to a canonical absolute path.
    assert sub.root == tmp_workspace.resolve()


def test_marker_missing_raises(tmp_path: Path) -> None:
    # tmp_path has no marker — explicitly verify.
    assert not (tmp_path / "amanuensis.yaml").exists()
    with pytest.raises(SubstrateMarkerMissing):
        Substrate(tmp_path)


def test_marker_is_directory_raises(tmp_path: Path) -> None:
    # A directory at the marker path is not a regular file.
    (tmp_path / "amanuensis.yaml").mkdir()
    with pytest.raises(SubstrateMarkerMissing):
        Substrate(tmp_path)


def test_workspace_root_nonexistent_raises(tmp_path: Path) -> None:
    nonexistent = tmp_path / "does-not-exist"
    with pytest.raises(SubstrateMarkerMissing):
        Substrate(nonexistent)


def test_workspace_root_is_a_file_raises(tmp_path: Path) -> None:
    # Passing a file instead of a directory: also rejected.
    f = tmp_path / "regular-file"
    f.write_text("hello", encoding="utf-8")
    with pytest.raises(SubstrateMarkerMissing):
        Substrate(f)


def test_accepts_string_path(tmp_workspace: Path) -> None:
    # The signature accepts ``Path | str``; string paths must work too.
    sub = Substrate(str(tmp_workspace))
    assert sub.root == tmp_workspace.resolve()
