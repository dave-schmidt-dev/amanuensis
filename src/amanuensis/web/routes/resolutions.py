"""Resolution routes — detail page.

One route:

- ``GET /resolutions/<resolution-id>`` — single-resolution detail page.
  Shows source_id, atom_id, operand_index, entity_id (linked to
  ``/entities/<id>``), confidence, basis, provenance, and supersede chain
  (via ``latest_resolution_for``). Returns 404 on unknown id.
  Headers: ``Cache-Control: no-store``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse

from amanuensis.fs import Substrate, SubstrateNotFound

from ..dependencies import get_substrate

router = APIRouter()


@router.get("/resolutions/{resolution_id}", response_class=HTMLResponse)
async def resolution_detail(
    request: Request,
    resolution_id: str,
    substrate: Annotated[Substrate, Depends(get_substrate)],
) -> HTMLResponse:
    """Render the per-resolution detail page.

    Shows source_id, atom_id, operand_index, entity_id (linked to
    ``/entities/<id>``), confidence, basis, provenance id, and the
    supersede chain (latest non-superseded resolution for this triple).
    Returns 404 on unknown id.
    """
    try:
        resolution = substrate.get_resolution(resolution_id)
    except SubstrateNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"resolution {resolution_id!r} not found",
        ) from exc

    # Walk the supersede chain to find the latest resolution for this triple.
    try:
        latest = substrate.latest_resolution_for(
            resolution.source_id,
            resolution.atom_id,
            resolution.operand_index,
        )
    except SubstrateNotFound:
        latest = None

    is_superseded = latest is not None and latest.id != resolution_id

    templates = request.app.state.templates
    response = templates.TemplateResponse(  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType,reportReturnType]
        request,
        "resolution_detail.html",
        {
            "resolution": resolution,
            "latest": latest,
            "is_superseded": is_superseded,
        },
    )
    response.headers["cache-control"] = "no-store"
    return response  # pyright: ignore[reportReturnType]
