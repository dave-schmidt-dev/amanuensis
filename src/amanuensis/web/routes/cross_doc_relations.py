"""Cross-doc relation routes — list browser + detail page (Phase 2b M8).

Two routes:

- ``GET /cross-doc-relations`` — table of all CrossDocRelation records
  with optional ``?kind=``, ``?from_source=``, ``?to_source=``,
  ``?touching_source=``, and ``?shared_entity=`` filters. Each filter
  composes with AND semantics; ``touching_source`` matches a source on
  either endpoint. Sort order is lex-id (mirrors
  ``Substrate.list_cross_doc_relations``). Headers:
  ``Cache-Control: no-store``.

- ``GET /cross-doc-relations/<id>`` — single-relation detail page.
  Renders endpoints (source + atom), warrant block (warrant text +
  defensibility + basis + confidence), shared entities (each linked to
  ``/entities/<id>``), and provenance id. The supersede-chain section
  is plumbed but populated by T8.3. Returns 404 on unknown id.
  Headers: ``Cache-Control: no-store``.

Read-only per Phase 2b spec: supersedes are CLI-only (no POST endpoint).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
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


@router.get("/cross-doc-relations/{relation_id}", response_class=HTMLResponse)
async def cross_doc_relation_detail(
    request: Request,
    relation_id: str,
    substrate: Annotated[Substrate, Depends(get_substrate)],
) -> HTMLResponse:
    """Render the per-relation detail page.

    Sections: header (id + kind), endpoints (source + atom), warrant
    block (warrant text, defensibility, basis, confidence), shared
    entities (linked list), provenance id, and a supersede-chain
    placeholder (T8.3 fills it in).
    """
    # ``Substrate`` does not currently expose ``get_cross_doc_relation``
    # — mirror the CLI's access pattern (see
    # ``amanuensis/cli/map.py::relation_show_command``) by going through
    # the public path helper + the private loader.
    path = substrate.cross_doc_relation_path(relation_id)
    if not path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"cross-doc relation {relation_id!r} not found",
        )
    relation = substrate._load_cross_doc_relation(path)  # pyright: ignore[reportPrivateUsage]

    # Supersede-chain entries land in T8.3; pass an empty list now so the
    # template's chain section renders the "(no supersede chain)" branch.
    chain_entries: list[object] = []

    templates = request.app.state.templates
    response = templates.TemplateResponse(  # pyright: ignore[reportUnknownMemberType,reportUnknownVariableType,reportReturnType]
        request,
        "cross_doc_relation_detail.html",
        {
            "relation": relation,
            "chain_entries": chain_entries,
        },
    )
    response.headers["cache-control"] = "no-store"
    return response  # pyright: ignore[reportReturnType]
