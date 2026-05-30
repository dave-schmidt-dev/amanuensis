"""Dashboard route: ``GET /`` lists every distillation in the workspace.

For each distillation the dashboard surfaces:

- ``source_id`` (linked to the source overview page)
- source-mirror manifest presence + paragraph count
- atom count
- relation count
- open / resolved clarification counts

The route is read-only (no flock acquisition); it constructs a
``Substrate`` per request via the :func:`get_substrate` dependency. M8.3
will add the atom-browser link from each row.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse

from amanuensis.fs import Substrate

from ..dependencies import get_substrate
from ._substrate_counts import collect_counts, list_distillation_source_ids

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    substrate: Annotated[Substrate, Depends(get_substrate)],
) -> HTMLResponse:
    """Render the dashboard listing every distillation in the workspace."""
    source_ids = list_distillation_source_ids(substrate)
    rows = [collect_counts(substrate, sid) for sid in source_ids]
    templates = request.app.state.templates
    return templates.TemplateResponse(  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType,reportReturnType]
        request,
        "dashboard.html",
        {
            "workspace_path": str(substrate.root),
            "rows": rows,
        },
    )
