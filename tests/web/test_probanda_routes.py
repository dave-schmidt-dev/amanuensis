"""Web route tests for probanda (Phase 2c M10).

These tests exercise the /probanda routes + the entity-detail
"probanda referencing this entity" section. Each test mounts a fresh
FastAPI app via the ``web_app`` fixture and points it at the planted
workspace fixture ``tmp_workspace_with_probandum_tree`` via the
``AMANUENSIS_WORKSPACE`` env var.
"""

# pyright: reportPrivateUsage=false

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# T10.1 — GET /probanda list route
# ---------------------------------------------------------------------------


def test_list_route_renders_html(
    tmp_workspace_with_probandum_tree: dict[str, str],
    web_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """List route returns HTML with all planted probanda."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", tmp_workspace_with_probandum_tree["workspace"])
    client = TestClient(web_app)
    response = client.get("/probanda")
    assert response.status_code == 200
    assert "text/html" in response.headers["content-type"]
    # All three planted probanda (ultimate + penultimate + interim) appear.
    for role in ("ultimate", "penultimate", "interim"):
        assert tmp_workspace_with_probandum_tree[role] in response.text


def test_list_route_sets_no_store(
    tmp_workspace_with_probandum_tree: dict[str, str],
    web_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """List response carries Cache-Control: no-store."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", tmp_workspace_with_probandum_tree["workspace"])
    client = TestClient(web_app)
    response = client.get("/probanda")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"


def test_list_route_filters_by_kind(
    tmp_workspace_with_probandum_tree: dict[str, str],
    web_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """?kind=ultimate yields only the ultimate probandum."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", tmp_workspace_with_probandum_tree["workspace"])
    client = TestClient(web_app)
    response = client.get("/probanda?kind=ultimate")
    assert response.status_code == 200
    # The ultimate must appear; penultimate + interim must not.
    assert tmp_workspace_with_probandum_tree["ultimate"] in response.text
    assert tmp_workspace_with_probandum_tree["penultimate"] not in response.text
    assert tmp_workspace_with_probandum_tree["interim"] not in response.text


def test_list_route_filters_by_scheme(
    tmp_workspace_with_probandum_tree: dict[str, str],
    web_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """?scheme=argument-from-expert-opinion matches only the ultimate."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", tmp_workspace_with_probandum_tree["workspace"])
    client = TestClient(web_app)
    response = client.get("/probanda?scheme=argument-from-expert-opinion")
    assert response.status_code == 200
    # The ultimate uses argument-from-expert-opinion; the penultimate +
    # interim use argument-from-sign, so they should be filtered out.
    assert tmp_workspace_with_probandum_tree["ultimate"] in response.text
    assert tmp_workspace_with_probandum_tree["penultimate"] not in response.text
    assert tmp_workspace_with_probandum_tree["interim"] not in response.text


def test_list_route_empty_workspace(
    web_workspace: Path,
    web_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty workspace returns the empty-state, not an error."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(web_workspace))
    client = TestClient(web_app)
    response = client.get("/probanda")
    assert response.status_code == 200
    assert "no probanda" in response.text.lower()


def test_list_route_unknown_kind_returns_empty(
    tmp_workspace_with_probandum_tree: dict[str, str],
    web_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unrecognized ?kind= short-circuits to the empty state."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", tmp_workspace_with_probandum_tree["workspace"])
    client = TestClient(web_app)
    response = client.get("/probanda?kind=nonsense")
    assert response.status_code == 200
    # No probandum ids should leak into the rendered output.
    assert tmp_workspace_with_probandum_tree["ultimate"] not in response.text
