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

from amanuensis.fs import Substrate

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


# ---------------------------------------------------------------------------
# T10.2 — GET /probanda/<id> detail route
# ---------------------------------------------------------------------------


def test_detail_route_renders_probandum(
    tmp_workspace_with_probandum_tree: dict[str, str],
    web_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detail page renders the statement, scheme, and confidence."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", tmp_workspace_with_probandum_tree["workspace"])
    sub = Substrate(Path(tmp_workspace_with_probandum_tree["workspace"]))
    ultimate = sub.get_probandum(tmp_workspace_with_probandum_tree["ultimate"])
    client = TestClient(web_app)
    response = client.get(f"/probanda/{ultimate.id}")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert ultimate.statement in response.text
    assert ultimate.scheme in response.text
    assert ultimate.confidence in response.text


def test_detail_route_renders_lineage_to_ultimate(
    tmp_workspace_with_probandum_tree: dict[str, str],
    web_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Interim's detail page lineage walks up through penultimate to ultimate."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", tmp_workspace_with_probandum_tree["workspace"])
    client = TestClient(web_app)
    interim_id = tmp_workspace_with_probandum_tree["interim"]
    response = client.get(f"/probanda/{interim_id}")
    assert response.status_code == 200
    # The lineage chain links to both ancestors.
    assert f'href="/probanda/{tmp_workspace_with_probandum_tree["penultimate"]}"' in response.text
    assert f'href="/probanda/{tmp_workspace_with_probandum_tree["ultimate"]}"' in response.text


def test_detail_route_renders_outgoing_edges(
    tmp_workspace_with_probandum_tree: dict[str, str],
    web_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Penultimate's detail page lists its outgoing edge to the interim child."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", tmp_workspace_with_probandum_tree["workspace"])
    client = TestClient(web_app)
    penultimate_id = tmp_workspace_with_probandum_tree["penultimate"]
    response = client.get(f"/probanda/{penultimate_id}")
    assert response.status_code == 200
    # The interim child must appear as a /probanda/<id> link.
    assert f'href="/probanda/{tmp_workspace_with_probandum_tree["interim"]}"' in response.text


def test_detail_route_renders_alternatives(
    tmp_workspace_with_probandum_tree: dict[str, str],
    web_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detail page renders ``alternatives_considered`` as a bulleted list."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", tmp_workspace_with_probandum_tree["workspace"])
    sub = Substrate(Path(tmp_workspace_with_probandum_tree["workspace"]))
    pen = sub.get_probandum(tmp_workspace_with_probandum_tree["penultimate"])
    assert pen.alternatives_considered, "fixture must plant at least one alternative"
    client = TestClient(web_app)
    response = client.get(f"/probanda/{pen.id}")
    assert response.status_code == 200
    for alt in pen.alternatives_considered:
        assert alt in response.text


def test_detail_route_404(
    web_app: FastAPI,
    tmp_workspace_with_probandum_tree: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown probandum id returns 404."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", tmp_workspace_with_probandum_tree["workspace"])
    client = TestClient(web_app)
    response = client.get("/probanda/p-nonexistent00000")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# T10.3 — GET /probandum-edges/<id> detail route
# ---------------------------------------------------------------------------


def test_edge_detail_route_renders_edge(
    tmp_workspace_with_probandum_tree: dict[str, str],
    web_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Edge detail page renders the warrant, defensibility, basis, confidence."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", tmp_workspace_with_probandum_tree["workspace"])
    sub = Substrate(Path(tmp_workspace_with_probandum_tree["workspace"]))
    edge = sub.get_probandum_edge(tmp_workspace_with_probandum_tree["edge_ult_pen"])
    client = TestClient(web_app)
    response = client.get(f"/probandum-edges/{edge.id}")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert edge.warrant in response.text
    assert edge.warrant_defensibility in response.text
    assert edge.warrant_basis in response.text
    assert edge.confidence in response.text
    assert edge.kind in response.text


def test_edge_detail_route_links_parent_and_child(
    tmp_workspace_with_probandum_tree: dict[str, str],
    web_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Edge detail page links parent → /probanda/<id> and child → /probanda/<id>."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", tmp_workspace_with_probandum_tree["workspace"])
    client = TestClient(web_app)
    edge_id = tmp_workspace_with_probandum_tree["edge_ult_pen"]
    response = client.get(f"/probandum-edges/{edge_id}")
    assert response.status_code == 200
    # Parent link (ultimate).
    assert f'href="/probanda/{tmp_workspace_with_probandum_tree["ultimate"]}"' in response.text
    # Child link (penultimate, probandum kind).
    assert f'href="/probanda/{tmp_workspace_with_probandum_tree["penultimate"]}"' in response.text


def test_edge_detail_route_404(
    web_app: FastAPI,
    tmp_workspace_with_probandum_tree: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown probandum-edge id returns 404."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", tmp_workspace_with_probandum_tree["workspace"])
    client = TestClient(web_app)
    response = client.get("/probandum-edges/q-nonexistent00000")
    assert response.status_code == 404


# ---------------------------------------------------------------------------
# T10.4 — GET /probanda/<id>/tree + /tree.json (Cytoscape view)
# ---------------------------------------------------------------------------


def test_tree_json_endpoint_returns_subtree(
    tmp_workspace_with_probandum_tree: dict[str, str],
    web_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """tree.json returns nodes + edges in Cytoscape shape, untruncated."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", tmp_workspace_with_probandum_tree["workspace"])
    client = TestClient(web_app)
    ultimate_id = tmp_workspace_with_probandum_tree["ultimate"]
    response = client.get(f"/probanda/{ultimate_id}/tree.json")
    assert response.status_code == 200
    data = response.json()
    assert "nodes" in data and isinstance(data["nodes"], list)
    assert "edges" in data and isinstance(data["edges"], list)
    assert data.get("truncated") is False
    # All three probanda must appear as nodes.
    node_ids = {n["data"]["id"] for n in data["nodes"]}
    for role in ("ultimate", "penultimate", "interim"):
        assert tmp_workspace_with_probandum_tree[role] in node_ids
    # Both edges must appear.
    edge_ids = {e["data"]["id"] for e in data["edges"]}
    assert tmp_workspace_with_probandum_tree["edge_ult_pen"] in edge_ids
    assert tmp_workspace_with_probandum_tree["edge_pen_int"] in edge_ids


def test_tree_json_node_carries_kind_and_label(
    tmp_workspace_with_probandum_tree: dict[str, str],
    web_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each node carries data.id + data.kind + data.label."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", tmp_workspace_with_probandum_tree["workspace"])
    client = TestClient(web_app)
    ultimate_id = tmp_workspace_with_probandum_tree["ultimate"]
    response = client.get(f"/probanda/{ultimate_id}/tree.json")
    assert response.status_code == 200
    data = response.json()
    for n in data["nodes"]:
        nd = n["data"]
        assert "id" in nd
        assert "kind" in nd
        assert "label" in nd
    for e in data["edges"]:
        ed = e["data"]
        assert {"id", "source", "target", "kind"}.issubset(ed.keys())


def test_tree_json_truncates_at_cap(
    tmp_workspace_with_probandum_tree: dict[str, str],
    web_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Soft-cap fallback: monkeypatched cap of 1 forces truncation."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", tmp_workspace_with_probandum_tree["workspace"])
    # Drop the soft-cap to 1 so any tree with at least one edge will
    # trigger the truncation branch.
    monkeypatch.setattr(
        "amanuensis.web.routes.probanda.TREE_SOFT_CAP_NODES",
        1,
    )
    client = TestClient(web_app)
    ultimate_id = tmp_workspace_with_probandum_tree["ultimate"]
    response = client.get(f"/probanda/{ultimate_id}/tree.json")
    assert response.status_code == 200
    data = response.json()
    assert data.get("truncated") is True
    # Truncated payload must still include the root + its immediate
    # children, but NOT the interim (which is the grandchild).
    node_ids = {n["data"]["id"] for n in data["nodes"]}
    assert tmp_workspace_with_probandum_tree["ultimate"] in node_ids
    assert tmp_workspace_with_probandum_tree["penultimate"] in node_ids
    assert tmp_workspace_with_probandum_tree["interim"] not in node_ids


def test_tree_html_page_includes_cytoscape_script(
    tmp_workspace_with_probandum_tree: dict[str, str],
    web_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The HTML page references the cytoscape + dagre vendor bundles."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", tmp_workspace_with_probandum_tree["workspace"])
    client = TestClient(web_app)
    ultimate_id = tmp_workspace_with_probandum_tree["ultimate"]
    response = client.get(f"/probanda/{ultimate_id}/tree")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "/static/vendor/cytoscape.min.js" in response.text
    assert "/static/vendor/dagre.min.js" in response.text
    assert "/static/vendor/cytoscape-dagre.js" in response.text
    assert "/static/js/probandum_tree.js" in response.text


def test_tree_html_404_for_unknown_probandum(
    web_app: FastAPI,
    tmp_workspace_with_probandum_tree: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown probandum id on the tree HTML returns 404."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", tmp_workspace_with_probandum_tree["workspace"])
    client = TestClient(web_app)
    response = client.get("/probanda/p-nonexistent00000/tree")
    assert response.status_code == 404


def test_tree_json_404_for_unknown_probandum(
    web_app: FastAPI,
    tmp_workspace_with_probandum_tree: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown probandum id on the tree.json endpoint returns 404."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", tmp_workspace_with_probandum_tree["workspace"])
    client = TestClient(web_app)
    response = client.get("/probanda/p-nonexistent00000/tree.json")
    assert response.status_code == 404
