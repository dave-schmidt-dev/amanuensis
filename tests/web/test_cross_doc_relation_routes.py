"""Web route tests for cross-doc relations (Phase 2b M8 T8.1 - T8.5)."""

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


# ---------------------------------------------------------------------------
# T8.2 — GET /cross-doc-relations/<id> detail route
# ---------------------------------------------------------------------------


def test_detail_route_renders_relation(
    tmp_workspace_with_two_cross_doc_relations: Path,
    web_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detail page renders the warrant and each shared entity as a /entities/<id> link."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(tmp_workspace_with_two_cross_doc_relations))
    sub = Substrate(tmp_workspace_with_two_cross_doc_relations)
    rel = next(iter(sub.list_cross_doc_relations()))
    client = TestClient(web_app)
    response = client.get(f"/cross-doc-relations/{rel.id}")
    assert response.status_code == 200
    assert rel.warrant in response.text
    for entity_id in rel.shared_entities:
        assert f'href="/entities/{entity_id}"' in response.text


def test_detail_route_renders_warrant_metadata(
    tmp_workspace_with_two_cross_doc_relations: Path,
    web_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detail page shows kind, basis, defensibility, confidence."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(tmp_workspace_with_two_cross_doc_relations))
    sub = Substrate(tmp_workspace_with_two_cross_doc_relations)
    rel = next(iter(sub.list_cross_doc_relations()))
    client = TestClient(web_app)
    response = client.get(f"/cross-doc-relations/{rel.id}")
    assert response.status_code == 200
    assert rel.kind in response.text
    assert rel.warrant_basis in response.text
    assert rel.warrant_defensibility in response.text
    assert rel.confidence in response.text


def test_detail_route_sets_no_store(
    tmp_workspace_with_two_cross_doc_relations: Path,
    web_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Detail response carries Cache-Control: no-store."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(tmp_workspace_with_two_cross_doc_relations))
    sub = Substrate(tmp_workspace_with_two_cross_doc_relations)
    rel = next(iter(sub.list_cross_doc_relations()))
    client = TestClient(web_app)
    response = client.get(f"/cross-doc-relations/{rel.id}")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"


def test_detail_route_404(
    web_app: FastAPI,
    tmp_workspace_with_two_cross_doc_relations: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown cross-doc relation id returns 404."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(tmp_workspace_with_two_cross_doc_relations))
    client = TestClient(web_app)
    response = client.get("/cross-doc-relations/x-nonexistent00000")
    assert response.status_code == 404


def test_detail_route_no_supersede_chain(
    tmp_workspace_with_two_cross_doc_relations: Path,
    web_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A relation with no supersede record renders the empty-chain branch."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(tmp_workspace_with_two_cross_doc_relations))
    sub = Substrate(tmp_workspace_with_two_cross_doc_relations)
    rel = next(iter(sub.list_cross_doc_relations()))
    client = TestClient(web_app)
    response = client.get(f"/cross-doc-relations/{rel.id}")
    assert response.status_code == 200
    assert "(no supersede chain)" in response.text


# ---------------------------------------------------------------------------
# T8.3 — Supersede chain rendering on detail page
# ---------------------------------------------------------------------------


def test_detail_shows_supersede_chain(
    tmp_workspace_with_cross_doc_supersede_chain: tuple[Path, str, str],
    web_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Old → New chain renders 'superseded' on old and 'supersedes' on new."""
    workspace, old_id, new_id = tmp_workspace_with_cross_doc_supersede_chain
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(workspace))
    client = TestClient(web_app)

    response_old = client.get(f"/cross-doc-relations/{old_id}")
    assert response_old.status_code == 200
    assert "superseded" in response_old.text.lower()
    # old must link to new in the supersede section.
    assert f"/cross-doc-relations/{new_id}" in response_old.text

    response_new = client.get(f"/cross-doc-relations/{new_id}")
    assert response_new.status_code == 200
    assert "supersedes" in response_new.text.lower()
    # new must link back to old.
    assert f"/cross-doc-relations/{old_id}" in response_new.text


def test_detail_supersede_chain_renders_reason(
    tmp_workspace_with_cross_doc_supersede_chain: tuple[Path, str, str],
    web_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The supervisor's reason text is rendered inline with the chain entry."""
    workspace, old_id, _new_id = tmp_workspace_with_cross_doc_supersede_chain
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(workspace))
    client = TestClient(web_app)
    response = client.get(f"/cross-doc-relations/{old_id}")
    assert response.status_code == 200
    assert "fixture supersede for M8 T8.3" in response.text


# ---------------------------------------------------------------------------
# T8.4 — Entity-detail page extension
# ---------------------------------------------------------------------------


def test_entity_detail_shows_cross_doc_edges(
    tmp_workspace_with_two_cross_doc_relations: Path,
    web_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Entity detail lists every CrossDocRelation whose shared_entities contains it."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(tmp_workspace_with_two_cross_doc_relations))
    sub = Substrate(tmp_workspace_with_two_cross_doc_relations)
    all_rels = list(sub.list_cross_doc_relations(shared_entity="e-smith"))
    assert len(all_rels) >= 2, "fixture must plant two relations on e-smith"

    client = TestClient(web_app)
    response = client.get("/entities/e-smith")
    assert response.status_code == 200
    assert "Cross-doc edges touching this entity" in response.text
    # Each fixture-planted relation must appear with a link to its detail.
    for rel in all_rels:
        assert f"/cross-doc-relations/{rel.id}" in response.text
    # The kinds are grouped: both kinds appear (supports + attacks).
    assert "supports" in response.text
    assert "attacks" in response.text


def test_entity_detail_empty_cross_doc_section(
    planted_entities_workspace: Path,
    web_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An entity with no cross-doc edges still renders the section (empty state)."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(planted_entities_workspace))
    sub = Substrate(planted_entities_workspace)
    entity = next(iter(sub.list_entities()))
    client = TestClient(web_app)
    response = client.get(f"/entities/{entity.id}")
    assert response.status_code == 200
    assert "Cross-doc edges touching this entity" in response.text
    assert "no cross-doc edges cite this entity" in response.text


# ---------------------------------------------------------------------------
# T8.5 — atom-entity-index fragment with cross-doc overlay
# ---------------------------------------------------------------------------


def test_atom_entity_index_fragment_with_cross_doc(
    tmp_workspace_with_two_cross_doc_relations: Path,
    web_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """?include_cross_doc=1 envelopes the index and adds cross_doc_edges."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(tmp_workspace_with_two_cross_doc_relations))
    client = TestClient(web_app)
    response = client.get("/distillations/src-A/relations/atom-entity-index?include_cross_doc=1")
    assert response.status_code == 200
    data = response.json()
    assert "cross_doc_edges" in data
    assert isinstance(data["cross_doc_edges"], list)
    # Both fixture relations touch src-A.
    assert len(data["cross_doc_edges"]) >= 2
    required_keys = {
        "id",
        "from_source_id",
        "from_atom_id",
        "to_source_id",
        "to_atom_id",
        "kind",
        "shared_entities",
    }
    for edge in data["cross_doc_edges"]:
        assert required_keys.issubset(edge.keys())
        assert edge["from_source_id"] == "src-A" or edge["to_source_id"] == "src-A"


def test_atom_entity_index_without_flag_omits_cross_doc(
    tmp_workspace_with_two_cross_doc_relations: Path,
    web_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No ?include_cross_doc flag → response is the legacy shape (dict only)."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(tmp_workspace_with_two_cross_doc_relations))
    client = TestClient(web_app)
    response = client.get("/distillations/src-A/relations/atom-entity-index")
    assert response.status_code == 200
    data = response.json()
    # Legacy contract: dict[atom_id, list[entity_id]] — no envelope.
    assert "cross_doc_edges" not in data
    # Each value, if any, must remain a list-of-strings (canonical entity ids).
    for entity_ids in data.values():
        assert isinstance(entity_ids, list)


def test_atom_entity_index_cross_doc_filtered_by_source(
    tmp_workspace_with_two_cross_doc_relations: Path,
    web_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Edges returned only include ones where either endpoint matches the requested source."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(tmp_workspace_with_two_cross_doc_relations))
    client = TestClient(web_app)
    res_a = client.get("/distillations/src-A/relations/atom-entity-index?include_cross_doc=1")
    assert res_a.status_code == 200
    edges_a = res_a.json()["cross_doc_edges"]
    for edge in edges_a:
        assert "src-A" in (edge["from_source_id"], edge["to_source_id"])

    res_b = client.get("/distillations/src-B/relations/atom-entity-index?include_cross_doc=1")
    assert res_b.status_code == 200
    edges_b = res_b.json()["cross_doc_edges"]
    for edge in edges_b:
        assert "src-B" in (edge["from_source_id"], edge["to_source_id"])
