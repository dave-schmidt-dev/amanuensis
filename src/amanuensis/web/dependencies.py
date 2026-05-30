"""FastAPI dependency injection helpers for the amanuensis web app.

This module exposes the small set of request-scoped helpers the route
handlers reach for. The key one today is :func:`get_substrate`, which
constructs a :class:`amanuensis.fs.Substrate` bound to the workspace
named by the ``AMANUENSIS_WORKSPACE`` environment variable.

Design notes
------------
- Per-request construction. ``Substrate.__init__`` only checks the
  marker (cheap stat); we get a fresh validation every request without
  caching stale state.
- Marker / directory failures surface as ``HTTPException(503)`` with a
  template-rendered body. Route handlers receive a working ``Substrate``
  or never run — the 503 is rendered by an exception handler registered
  on the app (see :mod:`amanuensis.web.app`).
- Trivially swappable for tests via FastAPI's ``app.dependency_overrides``
  mechanism.
"""

from __future__ import annotations

import os
from pathlib import Path

from fastapi import HTTPException, status

from amanuensis.fs import Substrate, SubstrateMarkerMissing

WORKSPACE_ENV_VAR = "AMANUENSIS_WORKSPACE"


def get_substrate() -> Substrate:
    """Return a :class:`Substrate` for the configured workspace.

    Reads the workspace path from ``AMANUENSIS_WORKSPACE`` (falls back to
    the current working directory). Raises ``HTTPException(503)`` with a
    structured ``detail`` payload when the path is missing the
    ``amanuensis.yaml`` marker (INV-1) or does not exist; the exception
    handler in :mod:`amanuensis.web.app` renders that into an HTML page.
    """
    raw = os.environ.get(WORKSPACE_ENV_VAR) or os.getcwd()
    workspace_path = Path(raw)
    try:
        return Substrate(workspace_path)
    except SubstrateMarkerMissing as exc:
        # Surface enough context for the rendered 503 page to be useful
        # without leaking the full host filesystem to the browser. The
        # path is needed because the supervisor needs to know which
        # directory they should point AMANUENSIS_WORKSPACE at.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "reason": "workspace_not_configured",
                "workspace_path": str(workspace_path),
                "env_var": WORKSPACE_ENV_VAR,
                "message": str(exc),
            },
        ) from exc
