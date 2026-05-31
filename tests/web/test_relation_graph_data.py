"""M8.4 relation-graph route tests.

Covers:

- Empty distillation (workspace marker only) renders 200 + emits the
  ``id="cy-data"`` script block with a valid empty payload.
- Planted atom appears in the payload as a node.
- Planted relation appears in the payload as an edge with both
  endpoints referenced.
- Vendored Cytoscape / cose-bilkent / cose-base / Alpine assets are
  served by the static mount.

Test plumbing note
------------------
Until the orchestrator wires the M8.4 router into
``amanuensis.web.app.create_app``, the route is not reachable on the
default app. Each test constructs a fresh app via ``create_app()`` and
manually mounts ``relations.router`` so the TestClient can hit it
in isolation. Once the orchestrator runs ``app.include_router(...)``,
the manual mounts become redundant but stay harmless (FastAPI tolerates
re-includes that resolve to the same path operation).
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from amanuensis.fs import Substrate
from amanuensis.schemas import (
    AgentAttribution,
    Atom,
    OperandRef,
    ProvenanceRecord,
    Relation,
    RoleAttribution,
    compute_id,
)
from amanuensis.web.app import create_app
from amanuensis.web.routes import relations as relation_routes

from .conftest import SOURCE_ID

# Regex that pulls the JSON body out of the cy-data <script> block.
# Non-greedy on the body so it stops at the first </script>.
_CY_DATA_RE = re.compile(
    r'<script\s+type="application/json"\s+id="cy-data">(.*?)</script>',
    re.DOTALL,
)


def _make_app_with_relations_router() -> FastAPI:
    """Build a fresh app + manually include the M8.4 router.

    The orchestrator will eventually wire this in ``create_app`` itself;
    this helper keeps M8.4's tests self-contained until then.
    """
    app = create_app()
    app.include_router(relation_routes.router)
    return app


def _extract_cy_payload(body: str) -> dict[str, Any]:
    """Pull + parse the JSON payload from the ``#cy-data`` script block."""
    match = _CY_DATA_RE.search(body)
    assert match is not None, "expected a <script id='cy-data'> block in the response"
    return json.loads(match.group(1))


def _plant_second_atom(
    substrate: Substrate, source_id: str, first_atom: Atom, first_prov: ProvenanceRecord
) -> Atom:
    """Plant a second atom under ``source_id``, distinct from the first.

    The two atoms become the endpoints of the planted relation in the
    third test. Reuses the first atom's provenance record so we do not
    have to plant a second one (provenance integrity is M2's concern, not
    M8.4's).
    """
    agent = AgentAttribution(kind="llm", identifier="test-model", role="extractor")
    role_attribution = RoleAttribution(
        agent=agent,
        activity="proposed",
        at=datetime(2026, 5, 30, 12, 0, 1, tzinfo=UTC),
    )
    operand = OperandRef(role="subject", kind="entity", value="ent-buyer", type_hint=None)

    payload: dict[str, Any] = {
        "source_id": source_id,
        "section_path": ["Part I", "§2"],
        "paragraph_index": 1,
        "sentence_index": None,
        "char_span": (0, 25),
        "scale_anchor": "paragraph",
        "kind": "claim",
        "predicate": "asserts_obligation",
        "operands": [operand],
        "narrative": "Buyer shall provide notice.",
        "qualifier_level": None,
        "qualifier_basis": None,
        "provenance_id": first_prov.id,
        "role_attributions": [role_attribution],
        "schema_version": 1,
    }
    payload["id"] = "a-" + "1" * 16
    draft = Atom(**payload)
    payload["id"] = compute_id(draft)
    atom = Atom(**payload)
    # Distinct id confirms we did not just rebuild the first atom.
    assert atom.id != first_atom.id
    substrate.add_atom(source_id, atom)
    return atom


def _plant_relation(
    substrate: Substrate,
    source_id: str,
    from_atom: Atom,
    to_atom: Atom,
    prov: ProvenanceRecord,
) -> Relation:
    """Plant a single ``supports`` relation between two atoms."""
    agent = AgentAttribution(kind="llm", identifier="test-model", role="extractor")
    role_attribution = RoleAttribution(
        agent=agent,
        activity="proposed",
        at=datetime(2026, 5, 30, 12, 0, 2, tzinfo=UTC),
    )
    payload: dict[str, Any] = {
        "source_id": source_id,
        "from_atom_id": from_atom.id,
        "to_atom_id": to_atom.id,
        "kind": "supports",
        "warrant": "Notice obligation derives from the payment obligation.",
        "warrant_defensibility": "conventional",
        "warrant_basis": "test fixture",
        "confidence": "high",
        "provenance_id": prov.id,
        "role_attributions": [role_attribution],
        "schema_version": 1,
    }
    payload["id"] = "r-" + "0" * 16
    draft = Relation(**payload)
    payload["id"] = compute_id(draft)
    relation = Relation(**payload)
    substrate.add_relation(source_id, relation)
    return relation


def test_relation_graph_renders_with_no_data(
    web_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Empty distillation dir renders 200 + an empty ``cy-data`` payload."""
    # The route requires the distillation dir to exist (404 otherwise),
    # so create it explicitly. No atoms, no relations on disk.
    (web_workspace / "distillations" / SOURCE_ID).mkdir(parents=True)
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(web_workspace))
    client = TestClient(_make_app_with_relations_router())
    response = client.get(f"/distillations/{SOURCE_ID}/relations")
    assert response.status_code == 200
    body = response.text
    # Structural assertions: the canvas div + the JSON block both
    # present, regardless of whether the payload is empty.
    assert 'id="cy"' in body
    assert 'id="cy-data"' in body
    payload = _extract_cy_payload(body)
    assert payload == {"elements": []}


def test_relation_graph_includes_planted_atom_node(
    planted_atom_workspace: tuple[Path, Atom, ProvenanceRecord],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A planted atom appears in the Cytoscape payload as a node."""
    workspace, atom, _prov = planted_atom_workspace
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(workspace))
    client = TestClient(_make_app_with_relations_router())
    response = client.get(f"/distillations/{SOURCE_ID}/relations")
    assert response.status_code == 200
    payload = _extract_cy_payload(response.text)
    node_ids = [el["data"]["id"] for el in payload["elements"] if el["data"].get("kind") == "atom"]
    assert atom.id in node_ids


def test_relation_graph_includes_planted_relation_edge(
    planted_atom_workspace: tuple[Path, Atom, ProvenanceRecord],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A planted relation appears as an edge with both endpoints set."""
    workspace, first_atom, first_prov = planted_atom_workspace
    substrate = Substrate(workspace)
    second_atom = _plant_second_atom(substrate, SOURCE_ID, first_atom, first_prov)
    relation = _plant_relation(substrate, SOURCE_ID, first_atom, second_atom, first_prov)

    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(workspace))
    client = TestClient(_make_app_with_relations_router())
    response = client.get(f"/distillations/{SOURCE_ID}/relations")
    assert response.status_code == 200
    payload = _extract_cy_payload(response.text)

    edges = [
        el["data"]
        for el in payload["elements"]
        if "source" in el["data"] and "target" in el["data"]
    ]
    matching = [e for e in edges if e["id"] == relation.id]
    assert len(matching) == 1, f"expected exactly one edge for {relation.id}, got {edges}"
    edge = matching[0]
    assert edge["source"] == first_atom.id
    assert edge["target"] == second_atom.id
    # Both endpoints must also appear as nodes (Cytoscape will silently
    # render dangling edges; tests assert the substrate is consistent).
    node_ids = {el["data"]["id"] for el in payload["elements"] if el["data"].get("kind") == "atom"}
    assert first_atom.id in node_ids
    assert second_atom.id in node_ids


@pytest.mark.parametrize(
    "vendor_filename",
    [
        "cytoscape.min.js",
        "cytoscape-cose-bilkent.js",
        "cose-base.js",
        "alpine.min.js",
    ],
)
def test_cytoscape_vendor_files_served(
    web_workspace: Path, monkeypatch: pytest.MonkeyPatch, vendor_filename: str
) -> None:
    """Each vendored JS asset is served by the ``/static`` mount."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(web_workspace))
    client = TestClient(_make_app_with_relations_router())
    response = client.get(f"/static/vendor/{vendor_filename}")
    assert response.status_code == 200
    # Starlette's ``StaticFiles`` infers the mime from the suffix;
    # ``.js`` resolves to a JS content-type ("application/javascript"
    # or "text/javascript" depending on the platform mimetypes db, both
    # contain "javascript").
    content_type = response.headers.get("content-type", "")
    assert "javascript" in content_type, (
        f"expected JS content-type for {vendor_filename}, got {content_type!r}"
    )
    # Body has actual bytes (not a zero-byte stub).
    assert len(response.content) > 0
