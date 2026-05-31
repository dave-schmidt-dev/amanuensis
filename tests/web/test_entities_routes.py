"""Tests for GET /entities and GET /entities/<id> routes (Phase 2a M8, T8.1+T8.2)."""

from __future__ import annotations

# pyright: reportPrivateUsage=false
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from amanuensis.fs import Substrate
from amanuensis.web.app import create_app

from .conftest import _plant_entity

# ---------------------------------------------------------------------------
# T8.1 — GET /entities list
# ---------------------------------------------------------------------------


def test_entities_list_renders(
    planted_entities_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """List page returns 200, shows ACME Corp, sets Cache-Control: no-store."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(planted_entities_workspace))
    app = create_app()
    client = TestClient(app)
    res = client.get("/entities")
    assert res.status_code == 200
    assert "ACME Corp" in res.text
    assert res.headers["cache-control"] == "no-store"


def test_entities_list_kind_filter(
    planted_entities_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """?kind=organization returns ACME Corp and omits Alice Smith."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(planted_entities_workspace))
    app = create_app()
    client = TestClient(app)
    res = client.get("/entities?kind=organization")
    assert res.status_code == 200
    assert "ACME Corp" in res.text
    assert "Alice Smith" not in res.text


def test_entities_list_kind_filter_person(
    planted_entities_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """?kind=person returns Alice Smith and omits ACME Corp."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(planted_entities_workspace))
    app = create_app()
    client = TestClient(app)
    res = client.get("/entities?kind=person")
    assert res.status_code == 200
    assert "Alice Smith" in res.text
    assert "ACME Corp" not in res.text


def test_entities_list_q_filter(
    planted_entities_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """?q=acme is case-insensitive and finds ACME Corp."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(planted_entities_workspace))
    app = create_app()
    client = TestClient(app)
    res = client.get("/entities?q=acme")
    assert res.status_code == 200
    assert "ACME" in res.text


def test_entities_list_q_filter_alias(
    planted_entities_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """?q= substring matches aliases too (Acme is an alias of ACME Corp)."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(planted_entities_workspace))
    app = create_app()
    client = TestClient(app)
    res = client.get("/entities?q=Acme")
    assert res.status_code == 200
    assert "ACME Corp" in res.text


def test_entities_list_empty_workspace(
    web_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty workspace returns 200 with empty-state message, not an error."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(web_workspace))
    app = create_app()
    client = TestClient(app)
    res = client.get("/entities")
    assert res.status_code == 200
    assert "no entities found" in res.text


# ---------------------------------------------------------------------------
# T8.2 — GET /entities/<id> detail
# ---------------------------------------------------------------------------


def test_entity_detail_renders(
    planted_entities_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Detail page renders kind, canonical_name, aliases, and provenance section."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(planted_entities_workspace))
    substrate = Substrate(planted_entities_workspace)
    entities = list(substrate.list_entities())
    assert entities, "fixture must plant at least one entity"
    # Pick ACME Corp specifically.
    acme = next(e for e in entities if e.canonical_name == "ACME Corp")

    app = create_app()
    client = TestClient(app)
    res = client.get(f"/entities/{acme.id}")
    assert res.status_code == 200
    assert "ACME Corp" in res.text
    assert "organization" in res.text
    assert "Acme" in res.text  # alias
    assert "provenance" in res.text.lower()
    assert res.headers["cache-control"] == "no-store"


def test_entity_detail_404_unknown(
    planted_entities_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unknown entity id returns 404."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(planted_entities_workspace))
    app = create_app()
    client = TestClient(app)
    res = client.get("/entities/e-" + "9" * 16)
    assert res.status_code == 404


def test_entity_detail_shows_resolutions(
    planted_resolutions_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Detail page lists resolutions that point to the entity."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(planted_resolutions_workspace))
    substrate = Substrate(planted_resolutions_workspace)
    entities = list(substrate.list_entities())
    acme = next(e for e in entities if e.canonical_name == "ACME Corp")

    app = create_app()
    client = TestClient(app)
    res = client.get(f"/entities/{acme.id}")
    assert res.status_code == 200
    # The resolutions section heading should appear.
    assert "resolutions pointing here" in res.text.lower()


def test_entity_detail_notes_shown_when_present(
    web_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Notes field is rendered when non-None."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(web_workspace))
    substrate = Substrate(web_workspace)
    entity, _ = _plant_entity(
        substrate,
        kind="organization",
        canonical_name="NotesCorp",
        notes="This entity needs disambiguation.",
    )

    app = create_app()
    client = TestClient(app)
    res = client.get(f"/entities/{entity.id}")
    assert res.status_code == 200
    assert "This entity needs disambiguation." in res.text
