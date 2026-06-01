"""Cross-doc relation routes — list browser (Phase 2b M8).

T8.1 ships the list route only; ``GET /cross-doc-relations/<id>`` lands
in T8.2 and the supersede-chain rendering in T8.3. Mirrors the
structural template style of Phase 2a's ``entities.py`` /
``resolutions.py``.

Route surface (T8.1):

- ``GET /cross-doc-relations`` — table of all CrossDocRelation records
  with optional ``?kind=``, ``?from_source=``, ``?to_source=``,
  ``?touching_source=``, and ``?shared_entity=`` filters. Each filter
  composes with AND semantics; ``touching_source`` matches a source on
  either endpoint. Sort order is lex-id (mirrors
  ``Substrate.list_cross_doc_relations``). Headers:
  ``Cache-Control: no-store``.

Read-only per Phase 2b spec: supersedes are CLI-only (no POST endpoint).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse

from amanuensis.fs import Substrate

from ..dependencies import get_substrate

router = APIRouter()


@router.get("/cross-doc-relations", response_class=HTMLResponse)
async def cross_doc_relations_list(
    request: Request,
    substrate: Annotated[Substrate, Depends(get_substrate)],
    kind: Annotated[
        str | None,
        Query(description="Filter by relation kind (supports / attacks / undercuts)."),
    ] = None,
    from_source: Annotated[
        str | None,
        Query(description="Filter by from_source_id (exact match)."),
    ] = None,
    to_source: Annotated[
        str | None,
        Query(description="Filter by to_source_id (exact match)."),
    ] = None,
    touching_source: Annotated[
        str | None,
        Query(description="Match relations where either endpoint is this source id."),
    ] = None,
    shared_entity: Annotated[
        str | None,
        Query(description="Match relations whose shared_entities list contains this id."),
    ] = None,
) -> HTMLResponse:
    """Render the cross-doc-relation browser with optional filters.

    Filter ``kind`` is validated against the allowed values; anything
    else short-circuits to an empty list so the substrate's
    ``Literal``-typed filter does not raise.
    """
    # ``Substrate.list_cross_doc_relations`` accepts a Literal-typed
    # ``kind`` arg, so a freeform query string that isn't a known value
    # must be coerced to None (and the filter result manually emptied) to
    # avoid a runtime mismatch. Other filters are plain str | None.
    allowed_kinds = {"supports", "attacks", "undercuts"}
    if kind is not None and kind not in allowed_kinds:
        relations: list[object] = []
    else:
        relations = list(
            substrate.list_cross_doc_relations(
                kind=kind,  # type: ignore[arg-type]
                from_source=from_source,
                to_source=to_source,
                touching_source=touching_source,
                shared_entity=shared_entity,
            )
        )

    # Distinct kinds for the filter dropdown (always the full set; we
    # cannot enumerate on-disk kinds when the list is empty post-filter).
    kinds = ["supports", "attacks", "undercuts"]

    templates = request.app.state.templates
    response = templates.TemplateResponse(  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType,reportReturnType]
        request,
        "cross_doc_relations_list.html",
        {
            "relations": relations,
            "filtered_count": len(relations),
            "kinds": kinds,
            "kind": kind or "",
            "from_source": from_source or "",
            "to_source": to_source or "",
            "touching_source": touching_source or "",
            "shared_entity": shared_entity or "",
        },
    )
    response.headers["cache-control"] = "no-store"
    return response  # pyright: ignore[reportReturnType]
