"""T8.8 — CV-9: web consumers walk the entity supersede chain.

Surface contract: every non-audit web consumer that displays entity-ids
must call latest_entity_for to canonicalize, so superseded ids never
leak to the supervisor's view of the resolved-entity registry.
"""

# pyright: reportPrivateUsage=false

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from amanuensis.web.app import create_app

# The ``merged_entity_workspace`` fixture is defined in conftest.py and plants:
#   - entity_A (superseded by entity_B)
#   - entity_B (canonical)
#   - resolution_R targeting entity_A's id (on-disk entity_id == A)
#   - EntitySupersede(A → B)
# Returns a 4-tuple (workspace, entity_A_id, entity_B_id, resolution_R_id).

_MERGE_SOURCE_ID = "src-merge"


def test_entities_list_skips_superseded(
    merged_entity_workspace: tuple[Path, str, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /entities must not show superseded entity_A; entity_B must appear."""
    workspace, ent_a_id, ent_b_id, _ = merged_entity_workspace
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(workspace))
    res = TestClient(create_app()).get("/entities")
    assert res.status_code == 200
    assert ent_b_id in res.text
    assert ent_a_id not in res.text, "superseded entity should not appear in /entities list"


def test_atom_entity_index_uses_canonical(
    merged_entity_workspace: tuple[Path, str, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """atom-entity-index must return canonical entity_B, not superseded entity_A."""
    workspace, ent_a_id, ent_b_id, _ = merged_entity_workspace
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(workspace))
    payload = (
        TestClient(create_app())
        .get(f"/distillations/{_MERGE_SOURCE_ID}/relations/atom-entity-index")
        .json()
    )
    for entity_ids in payload.values():
        assert ent_a_id not in entity_ids, (
            "superseded entity_A must not appear in atom-entity-index"
        )
        assert ent_b_id in entity_ids or entity_ids == []


def test_resolution_detail_links_canonical(
    merged_entity_workspace: tuple[Path, str, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """GET /resolutions/<R.id> must link to entity_B (canonical), not entity_A (raw on-disk id)."""
    workspace, ent_a_id, ent_b_id, res_r_id = merged_entity_workspace
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(workspace))
    res = TestClient(create_app()).get(f"/resolutions/{res_r_id}")
    assert res.status_code == 200
    assert f"/entities/{ent_b_id}" in res.text
    assert f"/entities/{ent_a_id}" not in res.text


def test_entity_detail_resolutions_pointing_here_filters_by_canonical(
    merged_entity_workspace: tuple[Path, str, str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """entity_B's detail page must list resolution_R even though R.entity_id == entity_A.id."""
    workspace, _ent_a_id, ent_b_id, res_r_id = merged_entity_workspace
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(workspace))
    res = TestClient(create_app()).get(f"/entities/{ent_b_id}")
    assert res.status_code == 200
    # resolution_R link must appear in entity_B's "Resolutions pointing here" section.
    assert res_r_id in res.text, (
        "resolution_R (entity_id==entity_A) must appear in entity_B's resolutions list "
        "after canonical chain-walking"
    )
