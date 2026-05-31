# tests/fs/test_entity_vocabulary_snapshot.py
from __future__ import annotations

from pathlib import Path

import pytest

from amanuensis.fs._errors import MappingVocabularyAlreadyPinned
from amanuensis.fs.substrate import Substrate
from amanuensis.vocabulary.entity_registry import EntityKind, EntityVocabulary


def _ws(tmp_path: Path) -> Substrate:
    (tmp_path / "amanuensis.yaml").write_text("workspace: test\n")
    return Substrate(tmp_path)


def _vocab(name: str = "party") -> EntityVocabulary:
    return EntityVocabulary(
        version=1,
        kinds=[EntityKind(id=name, description=f"desc {name}", resolution_rules=["rule-a"])],
    )


def test_snapshot_writes_file(tmp_path: Path) -> None:
    s = _ws(tmp_path)
    s.snapshot_entity_vocabulary(_vocab())
    assert s.entity_vocabulary_snapshot_path().is_file()


def test_snapshot_idempotent_on_byte_equal(tmp_path: Path) -> None:
    s = _ws(tmp_path)
    v = _vocab()
    s.snapshot_entity_vocabulary(v)
    first_bytes = s.entity_vocabulary_snapshot_path().read_bytes()
    s.snapshot_entity_vocabulary(v)  # second call, same content
    assert s.entity_vocabulary_snapshot_path().read_bytes() == first_bytes


def test_snapshot_rejects_different_content(tmp_path: Path) -> None:
    s = _ws(tmp_path)
    s.snapshot_entity_vocabulary(_vocab("party"))
    with pytest.raises(MappingVocabularyAlreadyPinned):
        s.snapshot_entity_vocabulary(_vocab("person"))


def test_get_returns_what_was_written(tmp_path: Path) -> None:
    s = _ws(tmp_path)
    v = _vocab("party")
    s.snapshot_entity_vocabulary(v)
    loaded = s.get_entity_vocabulary_snapshot()
    assert {k.id for k in loaded.kinds} == {"party"}


def test_extend_archives_then_writes_new(tmp_path: Path) -> None:
    s = _ws(tmp_path)
    v1 = _vocab("party")
    v2 = EntityVocabulary(
        version=1,
        kinds=[
            EntityKind(id="party", description="d", resolution_rules=["r"]),
            EntityKind(id="person", description="d", resolution_rules=["r"]),
        ],
    )
    s.snapshot_entity_vocabulary(v1)
    archived_id = s.extend_entity_vocabulary_snapshot(v2)
    assert s.archived_entity_vocabulary_path(archived_id).is_file()
    # Active snapshot should now contain v2's kinds
    loaded = s.get_entity_vocabulary_snapshot()
    assert {k.id for k in loaded.kinds} == {"party", "person"}
