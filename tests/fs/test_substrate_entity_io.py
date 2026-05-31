"""T3.3 — Substrate.add_entity / get_entity / list_entities.

Covers:
- Round-trip write + read
- Idempotent on canonical-equal (same non-volatile content)
- Raises MutationOfImmutableRecord on differing non-volatile content
- list_entities returns all written entities
- notes=None round-trips correctly (body is empty)
- notes with text round-trips correctly
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from amanuensis.fs import MutationOfImmutableRecord, Substrate, SubstrateNotFound
from amanuensis.schemas import RoleAttribution
from tests.fs.conftest import make_entity


def _new(workspace: Path) -> Substrate:
    return Substrate(workspace)


# --- round-trip -------------------------------------------------------


def test_add_then_get_entity_round_trip(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    sub = _new(tmp_workspace)
    ent = make_entity(role_attribution, canonical_name="ACME Corp.")
    sub.add_entity(ent)
    got = sub.get_entity(ent.id)
    assert got == ent


def test_entity_with_notes_round_trips(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    sub = _new(tmp_workspace)
    ent = make_entity(role_attribution, notes="This is the **parent** entity.")
    sub.add_entity(ent)
    got = sub.get_entity(ent.id)
    assert got.notes == "This is the **parent** entity."


def test_entity_notes_none_round_trips(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    sub = _new(tmp_workspace)
    ent = make_entity(role_attribution, notes=None)
    sub.add_entity(ent)
    got = sub.get_entity(ent.id)
    assert got.notes is None


# --- idempotent write -------------------------------------------------


def test_add_entity_idempotent_on_canonical_equal(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    """Calling add_entity twice with the same content is a no-op."""
    sub = _new(tmp_workspace)
    ent = make_entity(role_attribution)
    sub.add_entity(ent)
    path = sub.entity_path(ent.id)
    first_mtime = path.stat().st_mtime_ns

    # Second write with same content: should be no-op (no file rewrite).
    sub.add_entity(ent)
    assert path.stat().st_mtime_ns == first_mtime


def test_add_entity_idempotent_different_volatile_only(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    """Different provenance_id (volatile) → still idempotent, no error."""
    sub = _new(tmp_workspace)
    ent = make_entity(role_attribution)
    sub.add_entity(ent)

    # Build a variant with different provenance_id (volatile field).
    payload: dict[str, Any] = ent.model_dump(mode="python")
    payload["provenance_id"] = "p-different0000001"
    payload["id"] = ent.id
    # id must still match canonical (non-volatile content unchanged)
    from amanuensis.schemas import Entity as _Entity

    variant = _Entity(**payload)
    # Should NOT raise — only volatile field differs.
    sub.add_entity(variant)


# --- raises on non-volatile mismatch ---------------------------------


def test_add_entity_raises_on_non_volatile_change(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    """Tampered on-disk content with matching id → MutationOfImmutableRecord.

    The id-hash guard ``SubstrateIdMismatch`` blocks tampered IN-MEMORY models
    (their id no longer matches their content hash). To exercise the
    on-disk immutability guard, we have to forge the file directly: write
    a model with different non-volatile content, then rename the file to
    use the ORIGINAL entity's id. A subsequent ``add_entity(original)``
    finds same-id-different-content on disk and trips
    ``MutationOfImmutableRecord``.
    """
    from amanuensis.fs._serialize import serialize_entity_md

    sub = _new(tmp_workspace)
    ent = make_entity(role_attribution, canonical_name="ACME Corp.")
    sub.add_entity(ent)

    # Forge on disk: build a different entity, serialize it, but overwrite
    # the file at ent's path with the divergent content (id field in the
    # frontmatter still says ent.id since we tamper post-serialization).
    divergent = make_entity(role_attribution, canonical_name="Other Corp.")
    forged_text = serialize_entity_md(divergent).replace(divergent.id, ent.id)
    sub.entity_path(ent.id).write_text(forged_text)

    # Now add_entity(ent) sees on-disk content that differs in canonical_name.
    with pytest.raises(MutationOfImmutableRecord):
        sub.add_entity(ent)


# --- get raises on missing -------------------------------------------


def test_get_entity_raises_on_missing(tmp_workspace: Path) -> None:
    sub = _new(tmp_workspace)
    with pytest.raises(SubstrateNotFound):
        sub.get_entity("e-notexistent00000")


# --- list_entities ---------------------------------------------------


def test_list_entities_returns_all(tmp_workspace: Path, role_attribution: RoleAttribution) -> None:
    sub = _new(tmp_workspace)
    e1 = make_entity(role_attribution, canonical_name="Alpha Ltd.", kind="party")
    e2 = make_entity(role_attribution, canonical_name="Beta Inc.", kind="party", aliases=["Beta"])
    sub.add_entity(e1)
    sub.add_entity(e2)
    listed = list(sub.list_entities())
    assert len(listed) == 2
    ids = {e.id for e in listed}
    assert ids == {e1.id, e2.id}


def test_list_entities_empty_when_no_dir(tmp_workspace: Path) -> None:
    sub = _new(tmp_workspace)
    assert list(sub.list_entities()) == []


def test_add_entity_file_lands_at_correct_path(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    sub = _new(tmp_workspace)
    ent = make_entity(role_attribution)
    sub.add_entity(ent)
    expected = sub.entity_path(ent.id)
    assert expected.is_file()


def test_entity_id_mismatch_raises(tmp_workspace: Path, role_attribution: RoleAttribution) -> None:
    """add_entity refuses a model whose id != compute_id(model)."""
    from amanuensis.fs import SubstrateIdMismatch
    from amanuensis.schemas import Entity

    sub = _new(tmp_workspace)
    ent = make_entity(role_attribution)
    payload = ent.model_dump(mode="python")
    payload["id"] = "e-wrongid000000000"
    bad = Entity(**payload)
    with pytest.raises(SubstrateIdMismatch):
        sub.add_entity(bad)
