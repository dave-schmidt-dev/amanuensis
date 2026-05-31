"""T3.8 — ensure_mappings_readme (CV-4).

Covers:
- Calling ensure_mappings_readme creates mappings/README.md
- All five subdirectory READMEs are created
- Every README contains the amanuensis-generated marker
- Calling it twice is idempotent (byte-identical output)
- Content is deterministic across calls
"""

from __future__ import annotations

from pathlib import Path

from amanuensis.fs import Substrate

_MARKER = "<!-- amanuensis-generated: do not edit -->"
_SUBDIRS = ["entities", "resolutions", "supersedes", "provenance", "vocabulary-history"]


def _new(workspace: Path) -> Substrate:
    return Substrate(workspace)


def test_ensure_mappings_readme_creates_parent_readme(
    tmp_workspace: Path,
) -> None:
    sub = _new(tmp_workspace)
    sub.ensure_mappings_readme()
    readme = tmp_workspace / "mappings" / "README.md"
    assert readme.is_file()


def test_ensure_mappings_readme_creates_all_subdir_readmes(
    tmp_workspace: Path,
) -> None:
    sub = _new(tmp_workspace)
    sub.ensure_mappings_readme()
    for subdir in _SUBDIRS:
        readme = tmp_workspace / "mappings" / subdir / "README.md"
        assert readme.is_file(), f"README.md missing in mappings/{subdir}/"


def test_parent_readme_contains_marker(tmp_workspace: Path) -> None:
    sub = _new(tmp_workspace)
    sub.ensure_mappings_readme()
    content = (tmp_workspace / "mappings" / "README.md").read_text(encoding="utf-8")
    assert _MARKER in content


def test_subdir_readmes_contain_marker(tmp_workspace: Path) -> None:
    sub = _new(tmp_workspace)
    sub.ensure_mappings_readme()
    for subdir in _SUBDIRS:
        content = (tmp_workspace / "mappings" / subdir / "README.md").read_text(encoding="utf-8")
        assert _MARKER in content, f"Marker missing in mappings/{subdir}/README.md"


def test_parent_readme_mentions_all_subdirs(tmp_workspace: Path) -> None:
    sub = _new(tmp_workspace)
    sub.ensure_mappings_readme()
    content = (tmp_workspace / "mappings" / "README.md").read_text(encoding="utf-8")
    for subdir in _SUBDIRS:
        assert subdir in content, f"Parent README does not mention {subdir}"


def test_ensure_mappings_readme_idempotent(tmp_workspace: Path) -> None:
    """Calling twice produces byte-identical files."""
    sub = _new(tmp_workspace)
    sub.ensure_mappings_readme()

    # Capture all file contents after first call.
    first_snapshots: dict[str, bytes] = {}
    parent = tmp_workspace / "mappings" / "README.md"
    first_snapshots["README.md"] = parent.read_bytes()
    for subdir in _SUBDIRS:
        key = f"{subdir}/README.md"
        first_snapshots[key] = (tmp_workspace / "mappings" / subdir / "README.md").read_bytes()

    # Second call.
    sub.ensure_mappings_readme()

    # Compare.
    assert (tmp_workspace / "mappings" / "README.md").read_bytes() == first_snapshots["README.md"]
    for subdir in _SUBDIRS:
        key = f"{subdir}/README.md"
        assert (tmp_workspace / "mappings" / subdir / "README.md").read_bytes() == first_snapshots[
            key
        ], f"Content changed on second call for mappings/{subdir}/README.md"


def test_ensure_mappings_readme_subdir_readme_mentions_subdir(
    tmp_workspace: Path,
) -> None:
    """Each subdir README references its own directory name."""
    sub = _new(tmp_workspace)
    sub.ensure_mappings_readme()
    for subdir in _SUBDIRS:
        content = (tmp_workspace / "mappings" / subdir / "README.md").read_text(encoding="utf-8")
        assert subdir in content, (
            f"mappings/{subdir}/README.md does not mention its own directory name"
        )
