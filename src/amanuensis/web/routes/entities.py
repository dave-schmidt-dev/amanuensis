"""Entity routes — list browser + detail page.

Two routes:

- ``GET /entities`` — table of all entities with optional ``?kind=`` and
  ``?q=`` filters. Sort order: (kind, canonical_name). Headers:
  ``Cache-Control: no-store``.

- ``GET /entities/<entity-id>`` — single-entity detail page showing kind,
  canonical_name, aliases, notes, provenance summary, resolutions that
  point here, and the supersede chain. Returns 404 on unknown id.
  Headers: ``Cache-Control: no-store``.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse

from amanuensis.fs import Substrate, SubstrateNotFound

from ..dependencies import get_substrate

router = APIRouter()


@router.get("/entities", response_class=HTMLResponse)
async def entities_list(
    request: Request,
    substrate: Annotated[Substrate, Depends(get_substrate)],
    kind: Annotated[
        str | None,
        Query(description="Filter entities by kind (exact match)"),
    ] = None,
    q: Annotated[
        str | None,
        Query(description="Substring filter on canonical_name and aliases (case-insensitive)"),
    ] = None,
) -> HTMLResponse:
    """Render the entity browser with optional kind and substring filters."""
    all_entities = list(substrate.list_entities())

    filtered = all_entities
    if kind is not None:
        filtered = [e for e in filtered if e.kind == kind]
    if q:
        q_lower = q.lower()
        filtered = [
            e
            for e in filtered
            if q_lower in e.canonical_name.lower()
            or any(q_lower in alias.lower() for alias in e.aliases)
        ]

    # Sort by (kind, canonical_name) — stable, deterministic.
    filtered.sort(key=lambda e: (e.kind, e.canonical_name))

    # Collect distinct kind values for the filter UI (from the full list,
    # not the filtered subset so the dropdown always shows all options).
    kinds = sorted({e.kind for e in all_entities})

    templates = request.app.state.templates
    response = templates.TemplateResponse(  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType,reportReturnType]
        request,
        "entities_list.html",
        {
            "entities": filtered,
            "total": len(all_entities),
            "filtered_count": len(filtered),
            "kinds": kinds,
            "kind": kind or "",
            "q": q or "",
        },
    )
    response.headers["cache-control"] = "no-store"
    return response  # pyright: ignore[reportReturnType]


@router.get("/entities/{entity_id}", response_class=HTMLResponse)
async def entity_detail(
    request: Request,
    entity_id: str,
    substrate: Annotated[Substrate, Depends(get_substrate)],
) -> HTMLResponse:
    """Render the per-entity detail page.

    Shows kind, canonical_name, aliases, notes, provenance summary,
    resolutions pointing to this entity, and the supersede chain.
    Returns 404 on unknown id.
    """
    try:
        entity = substrate.get_entity(entity_id)
    except SubstrateNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"entity {entity_id!r} not found",
        ) from exc

    # Resolutions that resolve to this entity.
    resolutions = list(substrate.list_resolutions(where_entity_id=entity_id))

    # Supersede chain: walk from this entity to the terminal one.
    # If this entity IS the terminal one, the chain has length 1.
    try:
        latest = substrate.latest_entity_for(entity_id)
    except SubstrateNotFound:
        # Damaged chain — fall back gracefully.
        latest = entity

    is_superseded = latest.id != entity_id

    templates = request.app.state.templates
    response = templates.TemplateResponse(  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType,reportReturnType]
        request,
        "entity_detail.html",
        {
            "entity": entity,
            "resolutions": resolutions,
            "latest": latest,
            "is_superseded": is_superseded,
        },
    )
    response.headers["cache-control"] = "no-store"
    return response  # pyright: ignore[reportReturnType]
