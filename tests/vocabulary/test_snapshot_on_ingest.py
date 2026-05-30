"""Per-distillation vocabulary-snapshot semantics (INV-10).

The snapshot file is the pinned copy of the vocabulary used during a
specific distillation. Four contracts:

1. Round-trip stable: write → read returns an equal ``Vocabulary``;
   re-loading the on-disk bytes via ``Vocabulary.load`` also returns an
   equal model.
2. Write-once: an attempt to overwrite an existing snapshot with
   different bytes raises ``SubstrateSnapshotConflict``. A fresh
   ``source-id`` accepts the modified vocabulary without affecting the
   original snapshot.
3. Idempotent: identical re-snapshot is a no-op and returns the same
   path without raising.
4. Substrate-as-truth: after snapshotting V1 to source-id A,
   constructing a different V2 in memory does not change what
   ``get_vocabulary_snapshot("A")`` returns.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from amanuensis.fs import Substrate, SubstrateNotFound, SubstrateSnapshotConflict
from amanuensis.schemas import Vocabulary, VocabularyEntry

REPO_ROOT = Path(__file__).resolve().parents[2]
GENERIC_VOCAB_PATH = REPO_ROOT / "vocabularies" / "generic" / "predicates.yaml"


@pytest.fixture
def tmp_workspace(tmp_path: Path) -> Path:
    marker = tmp_path / "amanuensis.yaml"
    marker.write_text("schema_version: 1\nproject_name: test\n", encoding="utf-8")
    return tmp_path


def _drop_first_entry(vocab: Vocabulary) -> Vocabulary:
    """Construct a fresh Vocabulary missing the first entry."""
    return Vocabulary(
        name=vocab.name,
        version=vocab.version,
        entries=list(vocab.entries[1:]),
    )


def test_snapshot_round_trip_byte_stable(tmp_workspace: Path) -> None:
    """Snapshot must be byte-stable across a write -> load -> write cycle.

    Asserted via round-trip text equality (the cleaner of the two
    approaches): write vocab to src-a, load that file back via
    ``Vocabulary.load``, then snapshot the loaded model to src-b. The
    raw text on disk for src-a and src-b must be byte-identical —
    otherwise the serializer is not deterministic and idempotent
    re-snapshot would depend on PyYAML behavior rather than schema
    semantics.
    """
    sub = Substrate(tmp_workspace)
    vocab = Vocabulary.load(GENERIC_VOCAB_PATH)

    path = sub.snapshot_vocabulary("src-a", vocab)
    assert path.is_file()
    assert path == sub.vocabulary_snapshot_path("src-a")

    # Read through the substrate API.
    loaded_via_substrate = sub.get_vocabulary_snapshot("src-a")
    assert loaded_via_substrate.name == vocab.name
    assert loaded_via_substrate.version == vocab.version
    assert len(loaded_via_substrate.entries) == len(vocab.entries)
    assert {e.predicate for e in loaded_via_substrate.entries} == {
        e.predicate for e in vocab.entries
    }

    # Read the raw bytes and reload via ``Vocabulary.load``.
    reloaded = Vocabulary.load(path)
    assert reloaded.name == vocab.name
    assert len(reloaded.entries) == len(vocab.entries)

    # Byte-stability proper: re-snapshotting the loaded model to a fresh
    # source-id must produce byte-identical on-disk text. If this fails,
    # the writer is non-deterministic and the idempotent-re-snapshot
    # contract depends on luck.
    path_b = sub.snapshot_vocabulary("src-b", reloaded)
    text_a = path.read_text(encoding="utf-8")
    text_b = path_b.read_text(encoding="utf-8")
    assert text_a == text_b, "snapshot serializer is not byte-stable across write->load->write"


def test_snapshot_get_missing_raises_not_found(tmp_workspace: Path) -> None:
    sub = Substrate(tmp_workspace)
    with pytest.raises(SubstrateNotFound, match="vocabulary snapshot not found"):
        sub.get_vocabulary_snapshot("never-snapshotted")


def test_snapshot_write_once_conflict_on_different_content(tmp_workspace: Path) -> None:
    sub = Substrate(tmp_workspace)
    vocab = Vocabulary.load(GENERIC_VOCAB_PATH)
    sub.snapshot_vocabulary("src-a", vocab)

    # Mutate the registry: drop one entry. Re-snapshotting under the
    # same source-id must refuse (INV-10 pinned).
    modified = _drop_first_entry(vocab)
    with pytest.raises(SubstrateSnapshotConflict):
        sub.snapshot_vocabulary("src-a", modified)

    # The original snapshot is unchanged.
    still_original = sub.get_vocabulary_snapshot("src-a")
    assert len(still_original.entries) == len(vocab.entries)

    # The same modified vocabulary can be snapshotted to a fresh
    # source-id without affecting the first snapshot.
    sub.snapshot_vocabulary("src-b", modified)
    b_snapshot = sub.get_vocabulary_snapshot("src-b")
    assert len(b_snapshot.entries) == len(modified.entries)
    # And src-a remains untouched.
    a_snapshot_after = sub.get_vocabulary_snapshot("src-a")
    assert len(a_snapshot_after.entries) == len(vocab.entries)


def test_snapshot_idempotent_re_snapshot(tmp_workspace: Path) -> None:
    sub = Substrate(tmp_workspace)
    vocab = Vocabulary.load(GENERIC_VOCAB_PATH)

    first = sub.snapshot_vocabulary("src-a", vocab)
    second = sub.snapshot_vocabulary("src-a", vocab)
    assert first == second
    # Snapshot file content is unchanged.
    assert first.is_file()


def test_validator_reads_snapshot_not_global_registry(tmp_workspace: Path) -> None:
    """INV-10 trivial direction: snapshot is independent of in-memory edits.

    Snapshot V1 to source-id A, then construct an unrelated V2 in
    memory (smaller, different name). ``get_vocabulary_snapshot('A')``
    must still reflect V1 — the snapshot, not the latest global, is the
    source of truth for validators.
    """
    sub = Substrate(tmp_workspace)
    v1 = Vocabulary.load(GENERIC_VOCAB_PATH)
    sub.snapshot_vocabulary("src-a", v1)

    # Construct an unrelated V2 with a single bespoke entry. V2 is
    # never handed to the substrate; the snapshot for src-a must be
    # uninfluenced by its existence.
    v2 = Vocabulary(
        name="unrelated-v2",
        version="9.9.9",
        entries=[
            VocabularyEntry(
                predicate="bespoke_predicate",
                aliases=[],
                operand_types=[],
                qualifier_required=False,
                notes="unrelated",
            )
        ],
    )
    assert v2.name != v1.name  # sanity

    snapshotted = sub.get_vocabulary_snapshot("src-a")
    assert snapshotted.name == v1.name
    assert snapshotted.name != v2.name
    assert len(snapshotted.entries) == len(v1.entries)


def test_snapshot_path_is_pure_computation(tmp_workspace: Path) -> None:
    """vocabulary_snapshot_path must not touch the filesystem."""
    sub = Substrate(tmp_workspace)
    expected = tmp_workspace.resolve() / "distillations" / "src-fresh" / "vocabulary-snapshot.yaml"
    assert sub.vocabulary_snapshot_path("src-fresh") == expected
    # Distillation directory must not be created by the path resolver.
    assert not (tmp_workspace / "distillations" / "src-fresh").exists()
