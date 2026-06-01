"""T3.2 — Substrate.snapshot_walton_schemes + load_walton_scheme_snapshot.

Mirrors the Phase 2a entity-vocabulary-snapshot suite. The Walton-scheme
registry is pinned per engagement at
``mappings/walton-scheme-snapshot.yaml``. INV-18 (T3.3) consults this
snapshot at probandum write-time.
"""

from __future__ import annotations

from pathlib import Path

from amanuensis.fs.substrate import Substrate
from amanuensis.vocabulary.walton_schemes import WaltonSchemeRegistry


def _ws(tmp_path: Path) -> Substrate:
    (tmp_path / "amanuensis.yaml").write_text("workspace: test\n")
    return Substrate(tmp_path)


def test_snapshot_creates_file(tmp_path: Path) -> None:
    """Calling snapshot_walton_schemes writes the active snapshot file."""
    sub = _ws(tmp_path)
    snapshot_path = sub.snapshot_walton_schemes()
    assert snapshot_path.is_file()
    assert snapshot_path == tmp_path / "mappings" / "walton-scheme-snapshot.yaml"


def test_snapshot_idempotent(tmp_path: Path) -> None:
    """Re-snapshotting identical content is a byte-stable no-op."""
    sub = _ws(tmp_path)
    sub.snapshot_walton_schemes()
    snapshot_path = tmp_path / "mappings" / "walton-scheme-snapshot.yaml"
    first_bytes = snapshot_path.read_bytes()
    sub.snapshot_walton_schemes()  # second call
    assert snapshot_path.read_bytes() == first_bytes


def test_snapshot_extend_archives_prior(tmp_path: Path) -> None:
    """``extend=True`` archives the existing snapshot before writing a new one.

    To simulate a content drift, the test overwrites the on-disk snapshot
    with a smaller hand-built registry, then calls snapshot with
    ``extend=True`` to land the (different) generic catalogue.
    """
    sub = _ws(tmp_path)
    sub.snapshot_walton_schemes()
    snapshot_path = sub.walton_scheme_snapshot_path()

    # Replace the on-disk snapshot with a smaller hand-built variant so
    # the next extend has something different to archive.
    smaller = (
        "version: 1\n"
        "schemes:\n"
        "  - name: argument-from-expert-opinion\n"
        "    description: only one scheme.\n"
    )
    snapshot_path.write_text(smaller, encoding="utf-8")

    archive_dir = tmp_path / "mappings" / "walton-scheme-archive"
    assert not archive_dir.exists() or not any(archive_dir.iterdir())

    sub.snapshot_walton_schemes(extend=True)

    # An archive entry must now exist.
    assert archive_dir.is_dir()
    archived = [p for p in archive_dir.iterdir() if p.is_file() and p.suffix == ".yaml"]
    assert len(archived) == 1
    # The archived file is the OLD bytes.
    assert archived[0].read_text(encoding="utf-8") == smaller
    # The new active snapshot loads as the generic catalogue (7 schemes).
    loaded = sub.load_walton_scheme_snapshot()
    assert loaded is not None
    assert len(loaded.schemes) == 7


def test_load_returns_none_when_missing(tmp_path: Path) -> None:
    """``load_walton_scheme_snapshot`` returns None when no snapshot is on disk."""
    sub = _ws(tmp_path)
    assert sub.load_walton_scheme_snapshot() is None


def test_load_returns_registry_when_present(tmp_path: Path) -> None:
    """After snapshotting, load returns the parsed registry."""
    sub = _ws(tmp_path)
    sub.snapshot_walton_schemes()
    loaded = sub.load_walton_scheme_snapshot()
    assert isinstance(loaded, WaltonSchemeRegistry)
    assert loaded.has_scheme("argument-from-expert-opinion") is True
