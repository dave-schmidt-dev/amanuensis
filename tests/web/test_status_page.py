"""M8.7 status-page tests.

Covers:

- fresh workspace renders 200 + surfaces the workspace path.
- a workspace with a planted atom surfaces the atom count.

The HTML ``/status`` page is the supervisor-facing companion to the
JSON ``/healthz`` route (which already lives on ``app.py`` and is
unmodified by M8.7).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from amanuensis.schemas import Atom, ProvenanceRecord
from amanuensis.web.app import create_app
from amanuensis.web.routes import status as status_routes


def _build_client(workspace: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """TestClient with the M8.7 router mounted (see test_replay_log.py)."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(workspace))
    app = create_app()
    app.include_router(status_routes.router)
    return TestClient(app)


def test_status_page_returns_200(web_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Fresh workspace returns 200 and renders the workspace path."""
    client = _build_client(web_workspace, monkeypatch)
    response = client.get("/status")
    assert response.status_code == 200
    body = response.text
    assert str(web_workspace) in body
    # The marker version (schema_version: 1 from conftest) is surfaced.
    assert "marker version" in body.lower()
    # JSON liveness link is referenced so the supervisor can find it.
    assert "/healthz" in body


def test_status_page_includes_counts(
    planted_atom_workspace: tuple[Path, Atom, ProvenanceRecord],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A planted atom is reflected in the workspace-wide atom total."""
    workspace, _atom, _prov = planted_atom_workspace
    client = _build_client(workspace, monkeypatch)
    response = client.get("/status")
    assert response.status_code == 200
    body = response.text
    # The "atoms" totals card on status.html should render "1".
    # Cross-check via the surrounding label text to avoid false positives.
    assert "atoms" in body.lower()
    # Atom count of 1 is rendered as a standalone "1" cell with a
    # neighbouring "atoms" label; we assert both presences.
    # The dashboard test uses ">1<" for the same purpose — mirror that.
    assert ">1<" in body
    # Distillation count of 1 should also appear.
    assert "distillations" in body.lower()
