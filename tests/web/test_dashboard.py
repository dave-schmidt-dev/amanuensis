"""M8.2 dashboard route tests.

Covers:

- empty workspace renders 200 + "no distillations" UI.
- planted-atom workspace renders 200 + lists source_id + counts.
- missing-marker workspace renders 503 + workspace_not_configured page.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from amanuensis.schemas import Atom, ProvenanceRecord
from amanuensis.web.app import create_app

from .conftest import SOURCE_ID


def test_dashboard_empty_workspace(web_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fresh workspace (marker only) renders an explicit "no distillations" panel."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(web_workspace))
    client = TestClient(create_app())
    response = client.get("/")
    assert response.status_code == 200
    body = response.text
    assert "no distillations" in body.lower()
    # The dashboard surfaces the workspace path so the supervisor can
    # confirm they're looking at the right tmpdir.
    assert str(web_workspace) in body


def test_dashboard_lists_planted_distillation(
    planted_atom_workspace: tuple[Path, Atom, ProvenanceRecord],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A planted atom appears on the dashboard with its source_id + atom count of 1."""
    workspace, _atom, _prov = planted_atom_workspace
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(workspace))
    client = TestClient(create_app())
    response = client.get("/")
    assert response.status_code == 200
    body = response.text
    # source_id is the link text + the URL path
    assert SOURCE_ID in body
    assert f"/distillations/{SOURCE_ID}" in body
    # Atom count column shows 1 (the planted atom).
    # Search for the exact source_id row context to avoid false positives
    # if the template renders "1" elsewhere (e.g. tailwind class).
    assert ">1<" in body  # atom count cell
    # Manifest column says "no" for this workspace.
    assert ">no<" in body


def test_dashboard_workspace_not_configured_returns_503(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Pointing the env var at a marker-less dir returns 503 + the explanation page."""
    # tmp_path has no amanuensis.yaml marker — get_substrate should 503.
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(tmp_path))
    client = TestClient(create_app())
    response = client.get("/")
    assert response.status_code == 503
    body = response.text
    # The HTML page mentions the missing marker, the env var, and the path.
    assert "amanuensis.yaml" in body
    assert "AMANUENSIS_WORKSPACE" in body
    assert str(tmp_path) in body
    # Make sure we got HTML, not raw JSON.
    assert "text/html" in response.headers["content-type"]
