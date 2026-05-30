"""Source-overview route: ``GET /distillations/<source-id>``.

Renders a per-distillation summary page. Shows the source-mirror
manifest summary (filename, source SHA, ingest engine + version,
paragraph count, vocabulary snapshot SHA) when a manifest exists, and a
"manifest not yet ingested" notice otherwise.

A missing distillation (no ``distillations/<source-id>/`` directory)
returns 404. A malformed ``source_id`` (one that ``Substrate``'s path
validator rejects) also returns 404 — the route deliberately does not
leak the raw exception message; M8.3+ will add typed error rendering
when more failure modes appear.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import HTMLResponse

from amanuensis.fs import Substrate, SubstrateInvalidId

from ..dependencies import get_substrate
from ._substrate_counts import collect_counts, load_manifest

router = APIRouter()


@router.get("/distillations/{source_id}", response_class=HTMLResponse)
async def source_overview(
    request: Request,
    source_id: str,
    substrate: Annotated[Substrate, Depends(get_substrate)],
) -> HTMLResponse:
    """Render the source-overview page for a single distillation."""
    # Reject path-unsafe ids early; we surface the same 404 as a missing
    # directory so the route is uniform from a client's perspective.
    try:
        manifest_path = substrate.manifest_path(source_id)
    except SubstrateInvalidId as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"distillation {source_id!r} not found",
        ) from exc

    distillation_root = substrate.root / "distillations" / source_id
    if not distillation_root.is_dir():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"distillation {source_id!r} not found",
        )

    counts = collect_counts(substrate, source_id)
    manifest = load_manifest(manifest_path) if manifest_path.is_file() else None

    templates = request.app.state.templates
    return templates.TemplateResponse(  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType,reportReturnType]
        request,
        "source_overview.html",
        {
            "source_id": source_id,
            "counts": counts,
            "manifest": manifest,
            "workspace_path": str(substrate.root),
        },
    )
