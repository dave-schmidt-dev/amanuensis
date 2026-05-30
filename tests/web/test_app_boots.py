"""M8.1 smoke tests for the FastAPI skeleton.

Covers:

- ``create_app()`` returns a FastAPI instance (factory works).
- ``GET /healthz`` returns 200 + JSON ``{"status": "ok",
  "version": "<non-empty>"}``.
- ``GET /static/vendor/htmx.min.js`` serves the vendored HTMX file
  with a JS-shaped content-type (so the ``<script>`` tag in base.html
  resolves and the browser will execute it).

These are deliberately narrow — M8.2+ tests cover real routes and the
dashboard. We are only asserting the plumbing here.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from amanuensis.web.app import create_app


def test_create_app_returns_fastapi_instance() -> None:
    """Factory returns a fresh FastAPI app."""
    app = create_app()
    assert isinstance(app, FastAPI)
    assert app.title == "amanuensis"
    # Two distinct calls produce distinct apps — isolates tests from
    # each other when later milestones add app.state mutation.
    assert create_app() is not app


def test_healthz_returns_ok_with_version() -> None:
    """``GET /healthz`` returns JSON with status + non-empty version."""
    client = TestClient(create_app())
    response = client.get("/healthz")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert isinstance(payload["version"], str)
    assert payload["version"] != ""
    # Content-type must be JSON, not HTML — monitoring tools scrape it.
    assert "application/json" in response.headers["content-type"]


def test_vendored_htmx_is_served() -> None:
    """``/static/vendor/htmx.min.js`` is reachable and JS-typed.

    The base template references this path with ``<script src=...>``;
    if it 404s the whole UI breaks silently.
    """
    client = TestClient(create_app())
    response = client.get("/static/vendor/htmx.min.js")
    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"].lower()
    # The vendored file is ~48KB; anything tiny means we got a stub or
    # an error page rendered into 200.
    assert len(response.content) > 1000
