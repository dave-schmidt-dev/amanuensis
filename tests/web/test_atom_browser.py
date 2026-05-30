"""M8.3 atom-browser route tests.

Covers:

- planted-atom workspace renders 200 + lists the atom id.
- ``?scale=paragraph`` filter returns the matching atom; ``?scale=sentence``
  returns none.
- HTMX requests (``HX-Request: true``) return just the fragment HTML
  (no ``<html>`` / ``<body>`` tags).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from amanuensis.schemas import Atom, ProvenanceRecord
from amanuensis.web.app import create_app

from .conftest import SOURCE_ID


def test_atom_browser_lists_atoms(
    planted_atom_workspace: tuple[Path, Atom, ProvenanceRecord],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The browser renders 200 and surfaces the planted atom id."""
    workspace, atom, _prov = planted_atom_workspace
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(workspace))
    client = TestClient(create_app())
    response = client.get(f"/distillations/{SOURCE_ID}/atoms")
    assert response.status_code == 200
    body = response.text
    # Atom id appears (linked in the first column).
    assert atom.id in body
    # Detail-link target also appears so the table is navigable.
    assert f"/distillations/{SOURCE_ID}/atoms/{atom.id}" in body
    # Predicate from the planted fixture is rendered.
    assert atom.predicate in body


def test_atom_browser_filter_by_scale(
    planted_atom_workspace: tuple[Path, Atom, ProvenanceRecord],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``?scale=paragraph`` matches the planted atom; ``?scale=sentence`` does not."""
    workspace, atom, _prov = planted_atom_workspace
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(workspace))
    client = TestClient(create_app())

    # The conftest plants the atom with scale_anchor="paragraph"; assert
    # the test fixture truly is paragraph-scale before asserting filter
    # behaviour (catches a fixture drift before it looks like a route bug).
    assert atom.scale_anchor == "paragraph"

    matching = client.get(f"/distillations/{SOURCE_ID}/atoms?scale=paragraph")
    assert matching.status_code == 200
    assert atom.id in matching.text

    non_matching = client.get(f"/distillations/{SOURCE_ID}/atoms?scale=sentence")
    assert non_matching.status_code == 200
    # The atom should not appear when filtered out.
    assert atom.id not in non_matching.text
    # ... but the empty-state copy should.
    assert "no atoms match" in non_matching.text.lower()


def test_atom_browser_htmx_request_returns_fragment(
    planted_atom_workspace: tuple[Path, Atom, ProvenanceRecord],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``HX-Request: true`` returns the partial: no ``<html>`` / ``<body>``."""
    workspace, atom, _prov = planted_atom_workspace
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(workspace))
    client = TestClient(create_app())
    response = client.get(
        f"/distillations/{SOURCE_ID}/atoms",
        headers={"HX-Request": "true"},
    )
    assert response.status_code == 200
    body = response.text
    # Atom id is still rendered (data path identical to full-page).
    assert atom.id in body
    # Fragment must not include the full document scaffold.
    lower = body.lower()
    assert "<html" not in lower
    assert "<body" not in lower
    assert "<!doctype" not in lower
    # The fragment's target wrapper IS present so HTMX can swap it in.
    assert 'id="atom-list"' in body


def test_atom_browser_missing_distillation_returns_404(
    web_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A source_id with no distillation directory returns 404."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(web_workspace))
    client = TestClient(create_app())
    response = client.get("/distillations/does-not-exist/atoms")
    assert response.status_code == 404
