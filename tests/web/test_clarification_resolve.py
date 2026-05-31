"""M8.5 clarification resolve route tests.

Covers:

- ``GET /clarifications`` empty workspace renders 200 + "no clarifications".
- ``GET /clarifications`` with a planted open clarification renders the
  question + the resolve form action.
- ``POST /clarifications/<id>/resolve`` flips the clarification from
  ``open/`` to ``resolved/`` on disk and returns 303.
- ``POST /clarifications/<id>/resolve`` against an unknown id returns 404.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from amanuensis.fs import Substrate
from amanuensis.fs._serialize import parse_clarification_md
from amanuensis.schemas import Atom, Clarification, ProvenanceRecord
from amanuensis.web.app import create_app
from amanuensis.web.routes import forms as forms_routes

from .conftest import SOURCE_ID


def _build_client() -> TestClient:
    """Build a TestClient with the M8.5 router mounted manually.

    The orchestrator wires ``app.include_router(forms.router)`` after
    every wave-3 subagent lands; until then, tests mount it themselves
    so the routes are exercisable in isolation.
    """
    app = create_app()
    app.include_router(forms_routes.router)
    return TestClient(app)


def test_clarifications_list_empty(web_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty workspace renders the no-clarifications empty state."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(web_workspace))
    response = _build_client().get("/clarifications")
    assert response.status_code == 200
    assert "no clarifications" in response.text.lower()


def test_clarifications_list_with_open(
    planted_clarification_workspace: tuple[Path, Clarification, Atom, ProvenanceRecord],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An open clarification appears with its question + a resolve-form action."""
    workspace, clar, _atom, _prov = planted_clarification_workspace
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(workspace))
    response = _build_client().get("/clarifications")
    assert response.status_code == 200
    body = response.text
    assert clar.id in body
    assert clar.question in body
    # The resolve-form action must point at the per-id endpoint.
    assert f'action="/clarifications/{clar.id}/resolve"' in body


def test_clarification_resolve_form_post_succeeds(
    planted_clarification_workspace: tuple[Path, Clarification, Atom, ProvenanceRecord],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Posting the resolve form flips the on-disk file open/ -> resolved/.

    Mirrors the M4.3 ``clarification resolve`` CLI semantics: a paired
    PROV record is written, the resolved variant lives in the resolved/
    bucket, and the open variant is gone.
    """
    workspace, clar, _atom, _prov = planted_clarification_workspace
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(workspace))
    substrate = Substrate(workspace)

    open_path = substrate.clarification_path(SOURCE_ID, clar.id, resolved=False)
    assert open_path.is_file(), "fixture should have planted an open clarification"

    client = _build_client()
    # follow_redirects=False so the test asserts the 303 status code
    # before the redirect target is GET'd.
    response = client.post(
        f"/clarifications/{clar.id}/resolve",
        data={
            "source_id": SOURCE_ID,
            "resolution": "ACME is the parent entity.",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    assert response.headers["location"] == "/clarifications"

    # The on-disk state matches the M4.3 CLI behaviour exactly.
    assert not open_path.is_file()
    resolved_path = substrate.clarification_path(SOURCE_ID, clar.id, resolved=True)
    assert resolved_path.is_file()
    resolved_clar = parse_clarification_md(resolved_path.read_text(encoding="utf-8"))
    assert resolved_clar.status == "resolved"
    assert resolved_clar.resolution == "ACME is the parent entity."
    assert resolved_clar.resolved_provenance_id is not None
    assert resolved_clar.resolved_by is not None
    # Default resolver identity for web POSTs is "web-supervisor"
    # (per the task spec) — verify that propagates through.
    assert resolved_clar.resolved_by.identifier == "web-supervisor"

    # The paired PROV record exists at the canonical path.
    prov_path = substrate.provenance_path(SOURCE_ID, resolved_clar.resolved_provenance_id)
    assert prov_path.is_file()


def test_clarification_resolve_with_unknown_id_returns_404(
    planted_clarification_workspace: tuple[Path, Clarification, Atom, ProvenanceRecord],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POSTing against a bogus id returns 404 without mutating the substrate."""
    workspace, clar, _atom, _prov = planted_clarification_workspace
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(workspace))
    substrate = Substrate(workspace)
    # Use a syntactically-valid but non-existent id to avoid tripping the
    # path-validator (which would yield 422 / 500 instead of the 404 the
    # supervisor expects).
    bogus_id = "c-" + "f" * 16
    response = _build_client().post(
        f"/clarifications/{bogus_id}/resolve",
        data={
            "source_id": SOURCE_ID,
            "resolution": "anything",
        },
        follow_redirects=False,
    )
    assert response.status_code == 404
    # The planted open clarification is untouched.
    open_path = substrate.clarification_path(SOURCE_ID, clar.id, resolved=False)
    assert open_path.is_file()
