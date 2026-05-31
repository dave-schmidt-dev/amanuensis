"""T8.4 — /clarifications renders Phase 2a kinds with linked context_refs."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from amanuensis.fs import Substrate
from amanuensis.schemas import (
    AgentAttribution,
    Clarification,
    Entity,
    ProvenanceRecord,
    compute_id,
)
from amanuensis.web.app import create_app
from amanuensis.web.routes import forms as forms_routes

from .conftest import SOURCE_ID, _plant_atom, _plant_entity, _plant_resolution


def _build_client() -> TestClient:
    app = create_app()
    app.include_router(forms_routes.router)
    return TestClient(app)


def _plant_phase2a_clarification(
    substrate: Substrate,
    *,
    source_id: str,
    entity: Entity,
    kind: str = "resolution-disputed",
) -> Clarification:
    """Plant an open Phase 2a clarification referencing an entity."""
    raising_agent = AgentAttribution(kind="llm", identifier="auditor-test", role="auditor")
    prov_draft = ProvenanceRecord(
        id="p-" + "a" * 16,
        entity_type="clarification-raised",
        entity_id="c-" + "0" * 16,
        activity="audit_v1",
        activity_started_at=datetime(2026, 5, 30, 12, 5, 0, tzinfo=UTC),
        activity_ended_at=datetime(2026, 5, 30, 12, 5, 1, tzinfo=UTC),
        used_entity_ids=[],
        was_attributed_to=raising_agent,
        was_influenced_by=[],
        schema_version=1,
    )
    prov_id = compute_id(prov_draft)
    prov_path = substrate.provenance_path(source_id, prov_id)
    prov_path.parent.mkdir(parents=True, exist_ok=True)
    prov_path.write_text(
        prov_draft.model_copy(update={"id": prov_id}).model_dump_json(indent=2),
        encoding="utf-8",
    )

    payload: dict[str, Any] = {
        "id": "c-" + "0" * 16,
        "status": "open",
        "kind": kind,
        "raised_at": datetime(2026, 5, 30, 12, 5, 0, tzinfo=UTC),
        "raised_by": raising_agent,
        "raised_by_activity": "audit_v1",
        "context_refs": [entity.id],
        "question": "Which entity is the correct counterparty?",
        "options": None,
        "resolved_at": None,
        "resolved_by": None,
        "resolution": None,
        "raised_provenance_id": prov_id,
        "resolved_provenance_id": None,
        "schema_version": 2,
    }
    draft = Clarification(**payload)
    payload["id"] = compute_id(draft)
    clar = Clarification(**payload)
    substrate.add_clarification(source_id, clar)
    return clar


@pytest.fixture
def planted_phase2a_clarification_workspace(
    web_workspace: Path, web_substrate: Substrate
) -> tuple[Path, Clarification, Entity]:
    """Workspace with one Phase 2a open clarification referencing an entity."""
    _atom, _atom_prov = _plant_atom(web_substrate, SOURCE_ID)
    entity, _entity_prov = _plant_entity(
        web_substrate,
        kind="organization",
        canonical_name="Beta Corp",
        aliases=["Beta"],
    )
    clar = _plant_phase2a_clarification(
        web_substrate,
        source_id=SOURCE_ID,
        entity=entity,
        kind="resolution-disputed",
    )
    return web_workspace, clar, entity


@pytest.fixture
def planted_ambiguous_clarification_workspace(
    web_workspace: Path, web_substrate: Substrate
) -> tuple[Path, Clarification, Entity]:
    """Workspace with one resolution-ambiguous open clarification."""
    _atom, _atom_prov = _plant_atom(web_substrate, SOURCE_ID)
    entity, _entity_prov = _plant_entity(
        web_substrate,
        kind="person",
        canonical_name="Jane Doe",
    )
    clar = _plant_phase2a_clarification(
        web_substrate,
        source_id=SOURCE_ID,
        entity=entity,
        kind="resolution-ambiguous",
    )
    return web_workspace, clar, entity


def test_clarifications_list_renders_resolution_disputed_kind(
    planted_phase2a_clarification_workspace: tuple[Path, Clarification, Entity],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The list page shows the resolution-disputed kind badge."""
    workspace, _clar, _entity = planted_phase2a_clarification_workspace
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(workspace))
    res = _build_client().get("/clarifications")
    assert res.status_code == 200
    assert "resolution-disputed" in res.text


def test_clarifications_list_renders_resolution_ambiguous_kind(
    planted_ambiguous_clarification_workspace: tuple[Path, Clarification, Entity],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The list page shows the resolution-ambiguous kind badge."""
    workspace, _clar, _entity = planted_ambiguous_clarification_workspace
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(workspace))
    res = _build_client().get("/clarifications")
    assert res.status_code == 200
    assert "resolution-ambiguous" in res.text


def test_clarifications_list_links_entity_context_ref(
    planted_phase2a_clarification_workspace: tuple[Path, Clarification, Entity],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The context_refs panel renders an <a href=/entities/...> link."""
    workspace, _clar, entity = planted_phase2a_clarification_workspace
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(workspace))
    res = _build_client().get("/clarifications")
    assert res.status_code == 200
    assert f"/entities/{entity.id}" in res.text


def test_clarifications_list_shows_resolution_context_ref(
    web_workspace: Path,
    web_substrate: Substrate,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A context_ref pointing to a j-* resolution id renders a /resolutions/ link."""
    atom, _atom_prov = _plant_atom(web_substrate, SOURCE_ID)
    entity, _entity_prov = _plant_entity(
        web_substrate,
        kind="organization",
        canonical_name="Gamma Ltd",
    )
    resolution, _res_prov = _plant_resolution(
        web_substrate, entity=entity, atom=atom, source_id=SOURCE_ID
    )

    # Plant a clarification that references the resolution id directly.
    raising_agent = AgentAttribution(kind="llm", identifier="auditor-test", role="auditor")
    prov_draft = ProvenanceRecord(
        id="p-" + "b" * 16,
        entity_type="clarification-raised",
        entity_id="c-" + "1" * 16,
        activity="audit_v1",
        activity_started_at=datetime(2026, 5, 30, 12, 6, 0, tzinfo=UTC),
        activity_ended_at=datetime(2026, 5, 30, 12, 6, 1, tzinfo=UTC),
        used_entity_ids=[],
        was_attributed_to=raising_agent,
        was_influenced_by=[],
        schema_version=1,
    )
    prov_id = compute_id(prov_draft)
    prov_path = web_substrate.provenance_path(SOURCE_ID, prov_id)
    prov_path.parent.mkdir(parents=True, exist_ok=True)
    prov_path.write_text(
        prov_draft.model_copy(update={"id": prov_id}).model_dump_json(indent=2),
        encoding="utf-8",
    )

    payload: dict[str, Any] = {
        "id": "c-" + "1" * 16,
        "status": "open",
        "kind": "resolution-disputed",
        "raised_at": datetime(2026, 5, 30, 12, 6, 0, tzinfo=UTC),
        "raised_by": raising_agent,
        "raised_by_activity": "audit_v1",
        "context_refs": [resolution.id],
        "question": "Is this resolution correct?",
        "options": None,
        "resolved_at": None,
        "resolved_by": None,
        "resolution": None,
        "raised_provenance_id": prov_id,
        "resolved_provenance_id": None,
        "schema_version": 2,
    }
    draft = Clarification(**payload)
    payload["id"] = compute_id(draft)
    clar = Clarification(**payload)
    web_substrate.add_clarification(SOURCE_ID, clar)

    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(web_workspace))
    res = _build_client().get("/clarifications")
    assert res.status_code == 200
    assert f"/resolutions/{resolution.id}" in res.text
