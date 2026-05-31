"""T8.7 — entity-hover.js and relations.css static file serving."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from amanuensis.web.app import create_app


def _build_client() -> TestClient:
    return TestClient(create_app())


def test_entity_hover_js_served(
    planted_atom_workspace: tuple[Path, object, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """entity-hover.js is served and contains the entity-shared class reference."""
    workspace, _atom, _prov = planted_atom_workspace
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(workspace))
    res = _build_client().get("/static/js/entity-hover.js")
    assert res.status_code == 200
    assert "entity-shared" in res.text


def test_relations_css_served(
    planted_atom_workspace: tuple[Path, object, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """relations.css is served and contains the .entity-shared rule."""
    workspace, _atom, _prov = planted_atom_workspace
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(workspace))
    res = _build_client().get("/static/css/relations.css")
    assert res.status_code == 200
    assert ".entity-shared" in res.text


def test_relation_graph_page_loads_entity_hover_js(
    planted_atom_workspace: tuple[Path, object, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The relation-graph HTML page includes a script tag for entity-hover.js."""
    workspace, _atom, _prov = planted_atom_workspace
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(workspace))
    from .conftest import SOURCE_ID

    res = _build_client().get(f"/distillations/{SOURCE_ID}/relations")
    assert res.status_code == 200
    assert "entity-hover.js" in res.text


def test_relation_graph_page_loads_relations_css(
    planted_atom_workspace: tuple[Path, object, object],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The relation-graph HTML page links relations.css."""
    workspace, _atom, _prov = planted_atom_workspace
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(workspace))
    from .conftest import SOURCE_ID

    res = _build_client().get(f"/distillations/{SOURCE_ID}/relations")
    assert res.status_code == 200
    assert "relations.css" in res.text
