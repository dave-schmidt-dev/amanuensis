"""T3.5 — Substrate supersede add / get / list.

Covers:
- ResolutionSupersede round-trip
- EntitySupersede round-trip
- Mixed-dir layout (s- and t- live in the same supersedes/ dir)
- list_supersedes unfiltered yields both kinds
- list_supersedes kind="resolution" yields only ResolutionSupersede
- list_supersedes kind="entity" yields only EntitySupersede
- get_resolution_supersede / get_entity_supersede raise on missing
"""

from __future__ import annotations

from pathlib import Path

import pytest

from amanuensis.fs import Substrate, SubstrateNotFound
from amanuensis.schemas import EntitySupersede, ResolutionSupersede, RoleAttribution
from tests.fs.conftest import (
    make_entity,
    make_entity_supersede,
    make_resolution,
    make_resolution_supersede,
)


def _new(workspace: Path) -> Substrate:
    return Substrate(workspace)


# --- ResolutionSupersede round-trip ----------------------------------


def test_add_then_get_resolution_supersede(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    sub = _new(tmp_workspace)
    ent = make_entity(role_attribution)
    sub.add_entity(ent)

    res_old = make_resolution(role_attribution, ent, operand_index=0)
    sub.add_resolution(res_old)

    # Build a replacement resolution for a different operand_index so
    # it doesn't trip the duplicate-triple guard.
    res_new = make_resolution(role_attribution, ent, operand_index=1)
    sub.add_resolution(res_new)

    rs = make_resolution_supersede(role_attribution, res_old, res_new)
    sub.add_resolution_supersede(rs)

    got = sub.get_resolution_supersede(rs.id)
    assert got == rs
    assert isinstance(got, ResolutionSupersede)


def test_resolution_supersede_file_lands_at_supersedes_dir(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    sub = _new(tmp_workspace)
    ent = make_entity(role_attribution)
    sub.add_entity(ent)
    res_old = make_resolution(role_attribution, ent, operand_index=0)
    sub.add_resolution(res_old)
    res_new = make_resolution(role_attribution, ent, operand_index=1)
    sub.add_resolution(res_new)
    rs = make_resolution_supersede(role_attribution, res_old, res_new)
    sub.add_resolution_supersede(rs)

    path = sub.supersede_path(rs.id)
    assert path.is_file()
    assert path.parent.name == "supersedes"
    assert rs.id.startswith("s-")


# --- EntitySupersede round-trip --------------------------------------


def test_add_then_get_entity_supersede(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    sub = _new(tmp_workspace)
    ent_old = make_entity(role_attribution, canonical_name="Old Corp.")
    ent_new = make_entity(role_attribution, canonical_name="New Corp.", aliases=["New"])
    sub.add_entity(ent_old)
    sub.add_entity(ent_new)

    es = make_entity_supersede(role_attribution, ent_old, ent_new)
    sub.add_entity_supersede(es)

    got = sub.get_entity_supersede(es.id)
    assert got == es
    assert isinstance(got, EntitySupersede)


def test_entity_supersede_file_lands_at_supersedes_dir(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    sub = _new(tmp_workspace)
    ent_old = make_entity(role_attribution, canonical_name="Old Corp.")
    ent_new = make_entity(role_attribution, canonical_name="New Corp.", aliases=["New"])
    sub.add_entity(ent_old)
    sub.add_entity(ent_new)
    es = make_entity_supersede(role_attribution, ent_old, ent_new)
    sub.add_entity_supersede(es)

    path = sub.supersede_path(es.id)
    assert path.is_file()
    assert path.parent.name == "supersedes"
    assert es.id.startswith("t-")


# --- mixed-dir layout ------------------------------------------------


def test_mixed_dir_both_kinds_in_same_directory(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    """s- and t- files coexist in the same supersedes/ directory."""
    sub = _new(tmp_workspace)

    ent_old = make_entity(role_attribution, canonical_name="Old Corp.")
    ent_new = make_entity(role_attribution, canonical_name="New Corp.", aliases=["New"])
    sub.add_entity(ent_old)
    sub.add_entity(ent_new)

    res_old = make_resolution(role_attribution, ent_old, operand_index=0)
    sub.add_resolution(res_old)
    res_new = make_resolution(role_attribution, ent_new, operand_index=1)
    sub.add_resolution(res_new)

    rs = make_resolution_supersede(role_attribution, res_old, res_new)
    es = make_entity_supersede(role_attribution, ent_old, ent_new)
    sub.add_resolution_supersede(rs)
    sub.add_entity_supersede(es)

    supersedes_dir = sub.mappings_root / "supersedes"
    files = {f.name for f in supersedes_dir.iterdir() if f.is_file()}
    assert any(f.startswith("s-") for f in files)
    assert any(f.startswith("t-") for f in files)


# --- list_supersedes -------------------------------------------------


def _setup_mixed(
    sub: Substrate, role_attribution: RoleAttribution
) -> tuple[ResolutionSupersede, EntitySupersede]:
    ent_old = make_entity(role_attribution, canonical_name="Old Corp.")
    ent_new = make_entity(role_attribution, canonical_name="New Corp.", aliases=["New"])
    sub.add_entity(ent_old)
    sub.add_entity(ent_new)

    res_old = make_resolution(role_attribution, ent_old, operand_index=0)
    sub.add_resolution(res_old)
    res_new = make_resolution(role_attribution, ent_new, operand_index=1)
    sub.add_resolution(res_new)

    rs = make_resolution_supersede(role_attribution, res_old, res_new)
    es = make_entity_supersede(role_attribution, ent_old, ent_new)
    sub.add_resolution_supersede(rs)
    sub.add_entity_supersede(es)
    return rs, es


def test_list_supersedes_unfiltered(tmp_workspace: Path, role_attribution: RoleAttribution) -> None:
    sub = _new(tmp_workspace)
    rs, es = _setup_mixed(sub, role_attribution)
    listed = list(sub.list_supersedes())
    assert len(listed) == 2
    ids = {r.id for r in listed}
    assert ids == {rs.id, es.id}


def test_list_supersedes_resolution_only(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    sub = _new(tmp_workspace)
    rs, _es = _setup_mixed(sub, role_attribution)
    listed = list(sub.list_supersedes(kind="resolution"))
    assert len(listed) == 1
    assert listed[0].id == rs.id
    assert isinstance(listed[0], ResolutionSupersede)


def test_list_supersedes_entity_only(
    tmp_workspace: Path, role_attribution: RoleAttribution
) -> None:
    sub = _new(tmp_workspace)
    _rs, es = _setup_mixed(sub, role_attribution)
    listed = list(sub.list_supersedes(kind="entity"))
    assert len(listed) == 1
    assert listed[0].id == es.id
    assert isinstance(listed[0], EntitySupersede)


def test_list_supersedes_empty_when_no_dir(tmp_workspace: Path) -> None:
    sub = _new(tmp_workspace)
    assert list(sub.list_supersedes()) == []


# --- missing-record errors -------------------------------------------


def test_get_resolution_supersede_raises_on_missing(tmp_workspace: Path) -> None:
    sub = _new(tmp_workspace)
    with pytest.raises(SubstrateNotFound):
        sub.get_resolution_supersede("s-notexistent00000")


def test_get_entity_supersede_raises_on_missing(tmp_workspace: Path) -> None:
    sub = _new(tmp_workspace)
    with pytest.raises(SubstrateNotFound):
        sub.get_entity_supersede("t-notexistent00000")
