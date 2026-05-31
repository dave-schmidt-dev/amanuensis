"""Tests for GET /resolutions/<id> route (Phase 2a M8, T8.3)."""

from __future__ import annotations

# pyright: reportPrivateUsage=false
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from amanuensis.fs import Substrate
from amanuensis.web.app import create_app

# ---------------------------------------------------------------------------
# T8.3 — GET /resolutions/<id> detail
# ---------------------------------------------------------------------------


def test_resolution_detail_renders(
    planted_resolutions_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Detail page returns 200 and renders all key fields."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(planted_resolutions_workspace))
    substrate = Substrate(planted_resolutions_workspace)
    resolutions = list(substrate.list_resolutions())
    assert resolutions, "fixture must plant at least one resolution"
    r = resolutions[0]

    app = create_app()
    client = TestClient(app)
    res = client.get(f"/resolutions/{r.id}")
    assert res.status_code == 200
    # Core fields present in the page.
    assert r.source_id in res.text
    assert r.atom_id in res.text
    assert r.entity_id in res.text
    assert r.confidence in res.text
    assert "exact-name-match in fixture" in res.text
    assert res.headers["cache-control"] == "no-store"


def test_resolution_detail_links_to_entity(
    planted_resolutions_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Detail page contains a link to /entities/<entity-id>."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(planted_resolutions_workspace))
    substrate = Substrate(planted_resolutions_workspace)
    r = next(iter(substrate.list_resolutions()))

    app = create_app()
    client = TestClient(app)
    res = client.get(f"/resolutions/{r.id}")
    assert res.status_code == 200
    assert f"/entities/{r.entity_id}" in res.text


def test_resolution_detail_404_unknown(
    planted_resolutions_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unknown resolution id returns 404."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(planted_resolutions_workspace))
    app = create_app()
    client = TestClient(app)
    res = client.get("/resolutions/j-" + "9" * 16)
    assert res.status_code == 404
