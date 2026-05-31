"""M8.5 iteration add route tests.

Covers:

- ``GET /iterations`` empty workspace renders 200 + "no iterations".
- ``POST /iterations/add`` with valid form data writes a new directive
  + its issued PROV record and returns 303.
- ``POST /iterations/add`` with an unknown ``target_phase`` returns 4xx
  without writing anything to the substrate.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from amanuensis.fs import Substrate
from amanuensis.fs._serialize import parse_iteration_md
from amanuensis.schemas import Atom, ProvenanceRecord
from amanuensis.web.app import create_app
from amanuensis.web.routes import forms as forms_routes

from .conftest import SOURCE_ID


def _build_client() -> TestClient:
    """Build a TestClient with the M8.5 router mounted manually."""
    app = create_app()
    app.include_router(forms_routes.router)
    return TestClient(app)


def test_iterations_list_empty(web_workspace: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty workspace renders the no-iterations empty state."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(web_workspace))
    response = _build_client().get("/iterations")
    assert response.status_code == 200
    assert "no iterations" in response.text.lower()


def test_iteration_add_form_post_writes_directive(
    planted_atom_workspace: tuple[Path, Atom, ProvenanceRecord],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """POSTing the add form writes one directive + its issued PROV record."""
    workspace, _atom, _prov = planted_atom_workspace
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(workspace))
    substrate = Substrate(workspace)

    response = _build_client().post(
        "/iterations/add",
        data={
            "directive": "Re-extract atoms with stricter qualifier discipline.",
            "target_source": SOURCE_ID,
            "target_phase": "distill",
            "rationale": "Auditor flagged loose qualifier_level pins.",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303, response.text
    assert response.headers["location"] == "/iterations"

    iters_dir = substrate.root / "iterations"
    assert iters_dir.is_dir()
    # Exactly one written directive (skipping .tmp.* writer leftovers).
    written = [p for p in iters_dir.iterdir() if p.suffix == ".md" and ".tmp." not in p.name]
    assert len(written) == 1, [p.name for p in iters_dir.iterdir()]
    iter_obj = parse_iteration_md(written[0].read_text(encoding="utf-8"))
    assert iter_obj.target_phase == "distill"
    assert iter_obj.target_artifacts == [SOURCE_ID]
    assert "Re-extract atoms" in iter_obj.directive
    # Default issuer identity for web POSTs is "web-supervisor".
    assert iter_obj.issued_by.identifier == "web-supervisor"
    # The paired issued PROV record exists at the canonical path.
    assert substrate.provenance_path(SOURCE_ID, iter_obj.issued_provenance_id).is_file()


def test_iteration_add_with_unknown_target_phase_rejected(
    planted_atom_workspace: tuple[Path, Atom, ProvenanceRecord],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unknown ``target_phase`` returns 4xx and does not write anything."""
    workspace, _atom, _prov = planted_atom_workspace
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(workspace))
    substrate = Substrate(workspace)

    response = _build_client().post(
        "/iterations/add",
        data={
            "directive": "Try to write a directive with a bogus phase.",
            "target_source": SOURCE_ID,
            "target_phase": "bogus",
        },
        follow_redirects=False,
    )
    assert 400 <= response.status_code < 500, response.text

    # The substrate's iterations/ directory must not have been created
    # (no fall-through write happened before the validation error).
    iters_dir = substrate.root / "iterations"
    if iters_dir.is_dir():
        written = [p for p in iters_dir.iterdir() if p.suffix == ".md" and ".tmp." not in p.name]
        assert written == [], [p.name for p in written]
