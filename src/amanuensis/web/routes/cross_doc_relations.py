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

from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse

from amanuensis.fs import Substrate, SubstrateNotFound
from amanuensis.schemas import CrossDocRelationSupersede

from ..dependencies import get_substrate

router = APIRouter()


@dataclass
class _SupersedeChainEntry:
    """One line in the supersede-chain section on the detail page.

    ``direction='forward'`` means *this* relation has been superseded by
    ``other_id`` (rendered as "Superseded by <other>"). ``'backward'``
    means *this* relation supersedes ``other_id`` (rendered as
    "Supersedes <other>"). ``reason`` is the supervisor's free-text
    explanation from the ``CrossDocRelationSupersede`` record.
    """

    direction: Literal["forward", "backward"]
    other_id: str
    reason: str


def _walk_supersede_chain(
    substrate: Substrate,
    relation_id: str,
) -> list[_SupersedeChainEntry]:
    """Return both forward and backward supersede neighbours for ``relation_id``.

    Mirrors the CLI ``map relation show`` logic (see
    ``amanuensis/cli/map.py``). The supersedes directory is shared with
    Phase 2a's ``s-*`` and ``t-*`` records; cross-doc relation
    supersedes are namespaced ``v-*.yaml``. Phase 2b cleanup-1 swapped
    the bespoke directory walk for the unified
    ``Substrate.list_supersedes(kind="cross-doc-relation")`` dispatch.
    """
    entries: list[_SupersedeChainEntry] = []
    for record in substrate.list_supersedes(kind="cross-doc-relation"):
        if not isinstance(record, CrossDocRelationSupersede):
            continue  # type-narrowing for Pyright; runtime is already filtered
        if record.supersedes_id == relation_id:
            entries.append(
                _SupersedeChainEntry(
                    direction="forward",
                    other_id=record.superseded_by_id,
                    reason=record.reason,
                )
            )
        if record.superseded_by_id == relation_id:
            entries.append(
                _SupersedeChainEntry(
                    direction="backward",
                    other_id=record.supersedes_id,
                    reason=record.reason,
                )
            )
    return entries


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
    # Public accessor landed in Phase 2b cleanup-1 — no more reaching
    # into the private loader from the route layer.
    try:
        relation = substrate.get_cross_doc_relation(relation_id)
    except SubstrateNotFound as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"cross-doc relation {relation_id!r} not found",
        ) from exc

    chain_entries = _walk_supersede_chain(substrate, relation_id)

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
