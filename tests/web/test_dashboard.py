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


def test_dashboard_skips_non_path_safe_distillation_dirs(
    planted_atom_workspace: tuple[Path, Atom, ProvenanceRecord],
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Phase 2b cleanup-5: a sync-daemon ``" 2"`` duplicate dir must not 500 the route.

    Regression for the iCloud / Dropbox " 2" duplicate-naming corner:
    those daemons create sibling directories like ``phase1-smoke 2``
    (with an embedded space) alongside the original. The bare
    ``distillations/``-iterdir walk returns every subdirectory name
    verbatim, so the count walker pipes a space-containing string into
    Substrate path helpers — which raise ``SubstrateInvalidId``.

    Post-cleanup-5 the listing helper filters out names that fail
    ``_validate_id_component`` AND emits a warning log line naming
    each skipped directory so a supervisor can detect the orphan.
    """
    import logging

    workspace, _atom, _prov = planted_atom_workspace
    # Plant a sibling distillation dir with an invalid id (embedded space).
    invalid_dir = workspace / "distillations" / "phase1-smoke 2"
    invalid_dir.mkdir(parents=True, exist_ok=True)
    # Add a child file so the dir is non-empty (mimics a real sync clone).
    (invalid_dir / "atoms").mkdir(exist_ok=True)
    (invalid_dir / "atoms" / "a-clone.md").write_text("# duplicate", encoding="utf-8")

    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(workspace))
    client = TestClient(create_app())

    with caplog.at_level(logging.WARNING, logger="amanuensis.web"):
        response = client.get("/")

    # Route must NOT 500. The valid distillation still renders.
    assert response.status_code == 200, response.text
    body = response.text
    assert SOURCE_ID in body
    # The non-path-safe directory is silently absent from the listing.
    assert "phase1-smoke 2" not in body

    # A warning naming the skipped directory was emitted.
    warning_messages = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
    assert any("phase1-smoke 2" in m for m in warning_messages), (
        f"expected a warning naming the skipped directory; got {warning_messages!r}"
    )


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
