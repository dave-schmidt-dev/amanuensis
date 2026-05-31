"""T8.6 — atom-entity-index JSON fragment endpoint."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from amanuensis.web.app import create_app

from .conftest import SOURCE_ID


def _build_client() -> TestClient:
    return TestClient(create_app())


def test_atom_entity_index_shape(
    planted_resolutions_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Endpoint returns dict[atom_id, list[entity_id]]; both sides well-shaped."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(planted_resolutions_workspace))
    res = _build_client().get(f"/distillations/{SOURCE_ID}/relations/atom-entity-index")
    assert res.status_code == 200
    payload = res.json()
    assert isinstance(payload, dict)
    for atom_id, entity_ids in payload.items():
        assert atom_id.startswith("a-"), f"unexpected atom key: {atom_id!r}"
        assert isinstance(entity_ids, list)
        for eid in entity_ids:
            assert isinstance(eid, str) and eid.startswith("e-")


def test_atom_entity_index_cache_control(
    planted_resolutions_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Response carries Cache-Control: no-store."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(planted_resolutions_workspace))
    res = _build_client().get(f"/distillations/{SOURCE_ID}/relations/atom-entity-index")
    assert res.status_code == 200
    assert res.headers.get("cache-control") == "no-store"


def test_atom_entity_index_empty_when_no_resolutions(
    planted_atom_workspace: tuple[Path, object, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No resolutions → empty dict."""
    workspace, _atom, _prov = planted_atom_workspace
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(workspace))
    res = _build_client().get(f"/distillations/{SOURCE_ID}/relations/atom-entity-index")
    assert res.status_code == 200
    assert res.json() == {}


def test_atom_entity_index_404_unknown_source(
    planted_atom_workspace: tuple[Path, object, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown source_id returns 404."""
    workspace, _atom, _prov = planted_atom_workspace
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(workspace))
    res = _build_client().get("/distillations/no-such-source/relations/atom-entity-index")
    assert res.status_code == 404


def test_atom_entity_index_embedded_in_relation_graph_page(
    planted_resolutions_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The relation-graph HTML page embeds the atom-entity-index JSON block."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(planted_resolutions_workspace))
    res = _build_client().get(f"/distillations/{SOURCE_ID}/relations")
    assert res.status_code == 200
    assert 'id="atom-entity-index"' in res.text
