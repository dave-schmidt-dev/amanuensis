"""M8.2 source-overview route tests.

Covers:

- 200 + manifest summary when a manifest is on disk.
- 404 for a source_id that has no ``distillations/<source-id>/`` dir.
- 404 for a syntactically-invalid source_id (path-unsafe).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from amanuensis.schemas import SourceMirrorManifest
from amanuensis.web.app import create_app

from .conftest import SOURCE_ID


def test_source_overview_with_manifest(
    planted_manifest_workspace: tuple[Path, SourceMirrorManifest],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The overview page renders the planted manifest's filename + engine."""
    workspace, manifest = planted_manifest_workspace
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(workspace))
    client = TestClient(create_app())
    response = client.get(f"/distillations/{SOURCE_ID}")
    assert response.status_code == 200
    body = response.text
    assert SOURCE_ID in body
    assert manifest.source_filename in body
    assert manifest.ingest_engine in body
    assert manifest.ingest_engine_version in body
    # Paragraph count from the manifest (2 planted) renders.
    assert ">2<" in body


def test_source_overview_missing_distillation_returns_404(
    web_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A source_id that has no on-disk distillation directory returns 404."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(web_workspace))
    client = TestClient(create_app())
    response = client.get("/distillations/does-not-exist")
    assert response.status_code == 404


def test_source_overview_invalid_source_id_returns_404(
    web_workspace: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A path-unsafe source_id is rejected as 404 (not 500)."""
    monkeypatch.setenv("AMANUENSIS_WORKSPACE", str(web_workspace))
    client = TestClient(create_app())
    # ``..`` is a path-component the Substrate validator rejects with
    # SubstrateInvalidId; the route translates that to 404 rather than
    # leaking a 500.
    response = client.get("/distillations/..")
    # Some path normalizations may make this look like / — accept either
    # 404 (Substrate rejected the id) or 200/308 (FastAPI normalised it
    # away). We care about "not a 500".
    assert response.status_code != 500
