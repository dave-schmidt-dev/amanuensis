"""FastAPI application factory for the amanuensis local web app.

M8.1 wires the skeleton:

- :func:`create_app` builds the FastAPI instance, mounts ``/static``,
  registers Jinja2 templating, and exposes ``GET /healthz``.
- A lifespan async context manager is plumbed in even though M8.1 has
  no startup work — M8.2+ will open a Substrate handle here.

Run manually with::

    uvicorn amanuensis.web.app:app --host 127.0.0.1 --port 8723

The module-level ``app = create_app()`` export is what uvicorn imports.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

# ``_WEB_ROOT`` is the directory containing this file. Templates and
# static assets live alongside it; resolving them relatively keeps the
# wheel layout portable (no reliance on the editable-install src/ path).
_WEB_ROOT = Path(__file__).resolve().parent
_TEMPLATES_DIR = _WEB_ROOT / "templates"
_STATIC_DIR = _WEB_ROOT / "static"


def _package_version() -> str:
    """Return the installed amanuensis distribution version, or ``"unknown"``.

    Mirrors the CLI's helper (``amanuensis.cli._package_version``) — kept
    duplicated rather than imported because the web package should not
    depend on the CLI package import path.
    """
    try:
        return version("amanuensis")
    except PackageNotFoundError:  # pragma: no cover - dev-env glitch
        return "unknown"


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """App lifespan — startup before ``yield``, shutdown after.

    M8.1 has nothing to open or close. M8.2 will attach a Substrate
    handle to ``app.state`` here and close it on shutdown. The shape is
    plumbed now so later milestones don't have to refactor the factory.
    """
    # Startup: nothing yet.
    _ = app  # silence unused-arg in strict mode without an underscore-arg.
    yield
    # Shutdown: nothing yet.


def create_app() -> FastAPI:
    """Build and return the FastAPI app.

    Idempotent: each call constructs a fresh app (used by tests). The
    module-level ``app`` export below calls this once at import time.
    """
    pkg_version = _package_version()
    app = FastAPI(
        title="amanuensis",
        version=pkg_version,
        lifespan=_lifespan,
    )

    # Templates: render via FastAPI's Jinja2 helper. Stored on
    # ``app.state`` so routes (and future blueprints) can grab it
    # without re-instantiating.
    templates = Jinja2Templates(directory=str(_TEMPLATES_DIR))
    app.state.templates = templates
    app.state.package_version = pkg_version

    # Static files (Tailwind output + vendored HTMX). Mount path
    # matches what ``base.html`` references.
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.get("/healthz")
    async def healthz(request: Request) -> JSONResponse:  # pyright: ignore[reportUnusedFunction]
        """Liveness probe.

        Returns JSON (not HTML) — the dashboard at ``/`` (M8.2+) is the
        HTML entry point. ``/healthz`` is deliberately content-typed
        ``application/json`` so monitoring tooling can scrape it
        without parsing markup.
        """
        # ``request`` is unused but accepting it keeps the route
        # signature consistent with the Jinja2 routes M8.2+ will add.
        _ = request
        payload: dict[str, Any] = {"status": "ok", "version": pkg_version}
        return JSONResponse(payload)

    return app


# Module-level export so ``uvicorn amanuensis.web.app:app`` resolves.
# Tests construct their own app via ``create_app()`` for isolation.
app = create_app()
