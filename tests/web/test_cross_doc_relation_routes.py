"""Web route tests for cross-doc relations (Phase 2b M8 T8.1)."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from amanuensis.fs import Substrate

# ---------------------------------------------------------------------------
# T8.1 — GET /cross-doc-relations list route
# ---------------------------------------------------------------------------


def test_list_route_renders_html(
    tmp_workspace_with_two_cross_doc_relations: Path,
    web_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """List route returns HTML with both planted cross-doc relations."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(tmp_workspace_with_two_cross_doc_relations))
    client = TestClient(web_app)
    response = client.get("/cross-doc-relations")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    # Both relations (each id starts with x-) appear in the rendered table.
    assert response.text.count("x-") >= 2


def test_list_route_sets_no_store(
    tmp_workspace_with_two_cross_doc_relations: Path,
    web_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """List response carries Cache-Control: no-store (INV-8 substrate-derived)."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(tmp_workspace_with_two_cross_doc_relations))
    client = TestClient(web_app)
    response = client.get("/cross-doc-relations")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"


def test_list_route_filters_by_kind(
    tmp_workspace_with_two_cross_doc_relations: Path,
    web_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """?kind=supports yields only the supports relation."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(tmp_workspace_with_two_cross_doc_relations))
    sub = Substrate(tmp_workspace_with_two_cross_doc_relations)
    supports_ids = [r.id for r in sub.list_cross_doc_relations(kind="supports")]
    attacks_ids = [r.id for r in sub.list_cross_doc_relations(kind="attacks")]
    assert supports_ids and attacks_ids, "fixture must plant both kinds"

    client = TestClient(web_app)
    response = client.get("/cross-doc-relations?kind=supports")
    assert response.status_code == 200
    for sid in supports_ids:
        assert sid in response.text
    for aid in attacks_ids:
        assert aid not in response.text


def test_list_route_filters_by_from_source(
    tmp_workspace_with_two_cross_doc_relations: Path,
    web_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """?from_source=src-A matches both relations (both originate at src-A)."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(tmp_workspace_with_two_cross_doc_relations))
    client = TestClient(web_app)
    response = client.get("/cross-doc-relations?from_source=src-A")
    assert response.status_code == 200
    # Both relations originate at src-A.
    assert response.text.count("x-") >= 2

    response_miss = client.get("/cross-doc-relations?from_source=nope")
    assert response_miss.status_code == 200
    # Empty-state shown; no relation ids in rendered rows.
    assert "no cross-doc relations" in response_miss.text.lower()


def test_list_route_filters_by_shared_entity(
    tmp_workspace_with_two_cross_doc_relations: Path,
    web_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """?shared_entity=e-smith matches both relations; unrelated id matches none."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(tmp_workspace_with_two_cross_doc_relations))
    client = TestClient(web_app)
    response = client.get("/cross-doc-relations?shared_entity=e-smith")
    assert response.status_code == 200
    assert response.text.count("x-") >= 2

    response_miss = client.get("/cross-doc-relations?shared_entity=e-other")
    assert response_miss.status_code == 200
    assert "no cross-doc relations" in response_miss.text.lower()


def test_list_route_empty_workspace(
    web_workspace: Path,
    web_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty workspace returns the empty-state, not an error."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(web_workspace))
    client = TestClient(web_app)
    response = client.get("/cross-doc-relations")
    assert response.status_code == 200
    assert "no cross-doc relations" in response.text.lower()
