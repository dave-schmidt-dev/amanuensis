"""T3.4 — Substrate.add_resolution / get_resolution / list_resolutions.

Covers:
- Round-trip write + read
- Duplicate-triple guard raises ResolutionDuplicateTriple
- list_resolutions filtered by source_id
- list_resolutions filtered by where_entity_id
- list_resolutions unfiltered returns all
- get_resolution raises SubstrateNotFound on missing
"""

from __future__ import annotations

from pathlib import Path

import pytest

from amanuensis.fs import ResolutionDuplicateTriple, Substrate, SubstrateNotFound
from amanuensis.schemas import RoleAttribution
from tests.fs.conftest import make_entity, make_resolution


def _new(workspace: Path) -> Substrate:
    return Substrate(workspace)


# --- round-trip -------------------------------------------------------


def test_add_then_get_resolution_round_trip(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    sub = _new(tmp_workspace)
    ent = make_entity(role_attribution)
    sub.add_entity(ent)
    res = make_resolution(role_attribution, ent)
    sub.add_resolution(res)
    got = sub.get_resolution(res.id)
    assert got == res


def test_resolution_file_lands_at_correct_path(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    sub = _new(tmp_workspace)
    ent = make_entity(role_attribution)
    sub.add_entity(ent)
    res = make_resolution(role_attribution, ent)
    sub.add_resolution(res)
    assert sub.resolution_path(res.id).is_file()


# --- duplicate-triple guard ------------------------------------------


def test_add_resolution_duplicate_triple_raises(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    """Two non-superseded resolutions for the same triple → ResolutionDuplicateTriple."""
    sub = _new(tmp_workspace)
    ent1 = make_entity(role_attribution, canonical_name="Alpha Ltd.")
    ent2 = make_entity(role_attribution, canonical_name="Beta Inc.", aliases=["Beta"])
    sub.add_entity(ent1)
    sub.add_entity(ent2)

    # First resolution for (source_id, atom_id, operand_index=0)
    res1 = make_resolution(role_attribution, ent1, operand_index=0)
    sub.add_resolution(res1)

    # Second resolution for same triple → should raise
    res2 = make_resolution(role_attribution, ent2, operand_index=0)
    with pytest.raises(ResolutionDuplicateTriple):
        sub.add_resolution(res2)


def test_add_resolution_different_operand_index_ok(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    """Same source+atom but different operand_index → no conflict."""
    sub = _new(tmp_workspace)
    ent = make_entity(role_attribution)
    sub.add_entity(ent)

    res0 = make_resolution(role_attribution, ent, operand_index=0)
    res1 = make_resolution(role_attribution, ent, operand_index=1)
    sub.add_resolution(res0)
    sub.add_resolution(res1)  # should not raise


def test_add_resolution_idempotent_same_record(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    """Writing the identical resolution twice is idempotent (same id = same triple)."""
    sub = _new(tmp_workspace)
    ent = make_entity(role_attribution)
    sub.add_entity(ent)
    res = make_resolution(role_attribution, ent)
    sub.add_resolution(res)
    # Same record again — latest_resolution_for returns the same id, no raise.
    sub.add_resolution(res)


# --- get raises on missing -------------------------------------------


def test_get_resolution_raises_on_missing(tmp_workspace: Path) -> None:
    sub = _new(tmp_workspace)
    with pytest.raises(SubstrateNotFound):
        sub.get_resolution("j-notexistent00000")


# --- list_resolutions ------------------------------------------------


def test_list_resolutions_unfiltered(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    sub = _new(tmp_workspace)
    ent = make_entity(role_attribution)
    sub.add_entity(ent)
    r0 = make_resolution(role_attribution, ent, operand_index=0)
    r1 = make_resolution(role_attribution, ent, operand_index=1)
    sub.add_resolution(r0)
    sub.add_resolution(r1)
    listed = list(sub.list_resolutions())
    assert {r.id for r in listed} == {r0.id, r1.id}


def test_list_resolutions_by_source_id(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    sub = _new(tmp_workspace)
    ent = make_entity(role_attribution)
    sub.add_entity(ent)

    r_src1 = make_resolution(role_attribution, ent, source_id="src-fixture-001", operand_index=0)
    r_src2 = make_resolution(role_attribution, ent, source_id="src-fixture-002", operand_index=0)
    sub.add_resolution(r_src1)
    sub.add_resolution(r_src2)

    result = list(sub.list_resolutions(source_id="src-fixture-001"))
    assert len(result) == 1
    assert result[0].id == r_src1.id


def test_list_resolutions_by_entity_id(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    sub = _new(tmp_workspace)
    ent1 = make_entity(role_attribution, canonical_name="Alpha Ltd.")
    ent2 = make_entity(role_attribution, canonical_name="Beta Inc.", aliases=["Beta"])
    sub.add_entity(ent1)
    sub.add_entity(ent2)

    r1 = make_resolution(role_attribution, ent1, operand_index=0)
    r2 = make_resolution(role_attribution, ent2, operand_index=1)
    sub.add_resolution(r1)
    sub.add_resolution(r2)

    result = list(sub.list_resolutions(where_entity_id=ent1.id))
    assert len(result) == 1
    assert result[0].id == r1.id


def test_list_resolutions_empty_when_no_dir(tmp_workspace: Path) -> None:
    sub = _new(tmp_workspace)
    assert list(sub.list_resolutions()) == []
